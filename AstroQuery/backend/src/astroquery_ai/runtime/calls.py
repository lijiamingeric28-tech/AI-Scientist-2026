"""Single budgeted OpenAI-compatible streaming transport for text AND vision."""

from __future__ import annotations

import asyncio
import base64
import time
import json
import re
from dataclasses import dataclass, asdict

import httpx

from .codec import loads, digest
from .errors import DomainError


def complete_array_items(text, array_key):
    """Recover only complete JSON candidate objects from a truncated root.

    Items still require the normal contracts, owned locations and independent
    scientific review. No unfinished numeric/string fragment is accepted.
    """
    if not text.lstrip().startswith('{'):
        return None
    marker = re.search(r'"' + re.escape(array_key) + r'"\s*:\s*\[', text)
    if not marker:
        return None
    decoder, items, position = json.JSONDecoder(), [], marker.end()
    while len(items) < 24:
        while position < len(text) and text[position] in ' \t\r\n,':
            position += 1
        try:
            value, end = decoder.raw_decode(text, position)
        except ValueError:
            break
        if not isinstance(value, dict):
            break
        items.append(value)
        position = end
    if not items:
        return None
    result={array_key:items,'coverage':'partial','limitations':['provider_output_truncated_complete_items_only']}
    if array_key=='results':result.update(context_requests=[],figures=[],figure_requests=[])
    return result


def complete_extraction_items(text):
    return complete_array_items(text, 'results')


@dataclass(frozen=True)
class ModelProfile:
    model: str
    version: str = "trial-1"
    state: str = "trial"
    thinking: bool = True
    max_output_tokens: int = 8192
    wall_seconds: int = 180
    inactivity_seconds: int = 60
    max_input_tokens: int = 24000
    max_images: int = 4
    high_resolution_images: bool = False
    operation: str = "unspecified"
    source_format: str = "unspecified"


def input_upper_bound(messages: list[dict]) -> int:
    # Every UTF-8 byte is a conservative bound for text tokens, plus protocol overhead.
    # Verified provider family: one visual token per 32x32 pixels plus markers.
    # Ceiling both dimensions bounds provider rounding; no downsampling discount
    # is assumed. See https://help.aliyun.com/en/model-studio/vision .
    total = 512
    for message in messages:
        total += 64
        content = message.get("content", "")
        if isinstance(content, str):
            total += len(content.encode("utf-8"))
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    total += len(part["text"].encode("utf-8"))
                elif part.get("type") == "image_url":
                    url = part["image_url"]["url"]
                    if not url.startswith("data:image/"):
                        raise DomainError("UNBOUNDED_IMAGE", "模型图像必须来自本地已受控页图", 422)
                    import pymupdf as fitz

                    data = base64.b64decode(url.split(",", 1)[1], validate=True)
                    image = fitz.Pixmap(data)
                    if max(image.width, image.height) > 2048:
                        raise DomainError(
                            "IMAGE_PROFILE_EXCEEDED", "页图超出已登记的费用上界配置", 422
                        )
                    if len(data) > 14 * 1024**2:
                        raise DomainError("IMAGE_BYTE_LIMIT", "页图超过已登记文件大小上限", 422)
                    total += max(4, ((image.width + 31) // 32) * ((image.height + 31) // 32)) + 2
                else:
                    raise DomainError("UNSUPPORTED_MODEL_INPUT", "未登记的模型输入类型", 422)
        else:
            raise DomainError("INVALID_MODEL_INPUT", "模型消息结构无效", 422)
    return total


def json_messages(messages):
    """The exact JSON-mode envelope used both by planners and dispatch."""
    texts = [m['content'] for m in messages if isinstance(m.get('content'), str)]
    texts.extend(p['text'] for m in messages if isinstance(m.get('content'), list)
                 for p in m['content'] if p.get('type') == 'text')
    if not any('json' in text.casefold() for text in texts):
        return [{'role': 'system', 'content': 'Return one complete JSON object matching the requested schema.'}, *messages]
    return messages


def json_input_capacity(messages, profile):
    messages = json_messages(messages)
    bound = input_upper_bound(messages)
    images = sum(p.get('type') == 'image_url' for m in messages
                 if isinstance(m.get('content'), list) for p in m['content'])
    return dict(input_bound=bound, maximum=profile.max_input_tokens, images=images,
                maximum_images=profile.max_images,
                fits=bound <= profile.max_input_tokens and images <= profile.max_images)


class ModelGateway:
    def __init__(self, configuration, budget, *, transport=None, profile_authorizer=None):
        self.config, self.budget, self.transport = configuration, budget, transport
        self.profile_authorizer = profile_authorizer
        # The selected workspace endpoint is explicit. Ambient system proxies
        # caused verified pre-request TLS failures; do not inherit them silently.
        self.trust_env = False
        self.pilot_authorizer = None
        self.verification_authorizer = None
        from .stages import EXECUTION_POLICY
        self.semaphore = asyncio.Semaphore(EXECUTION_POLICY['models_total'])
        self.model_semaphores = {model: asyncio.Semaphore(limit)
                                 for model, limit in EXECUTION_POLICY['models'].items()}
        from .throughput import ModelTraffic
        self.traffic = ModelTraffic()

    async def json(
        self,
        *,
        task_id: str,
        owner: str,
        root_id: str,
        messages: list[dict],
        profile: ModelProfile,
        job=None,
        smoke=False,
        purpose="calibration",
        root_limit=3,
        dispatch_guard=None,
    ):
        values = self.config.runtime
        if not values.get("dashscope_api_key") or not values.get("dashscope_base_url"):
            raise DomainError("PROVIDER_NOT_CONFIGURED", "尚未配置模型服务")
        if profile.model == "qwen3.7-flash":
            raise DomainError("RETIRED_MODEL", "新任务必须使用qwen3.8-flash")
        # JSON-object mode requires an explicit JSON instruction at the provider.
        # Inspect text only: image base64 may coincidentally contain those letters.
        messages = json_messages(messages)
        if (
            purpose == "calibration"
            and self.budget.repository.get_task(task_id)["kind"] != "validation"
        ):
            raise DomainError("CALIBRATION_TASK_REQUIRED", "校准请求必须使用单独登记的验证任务")
        capacity = json_input_capacity(messages, profile)
        bound, images = capacity['input_bound'], capacity['images']
        if not capacity['fits']:
            raise DomainError(
                "MODEL_INPUT_LIMIT",
                "完整输入超出当前配置上限，应缩批或保留缺口",
                input_bound=bound,
                maximum=profile.max_input_tokens,
                images=images,
            )
        body = {
            "model": profile.model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "response_format": {"type": "json_object"},
            "enable_thinking": profile.thinking,
            "max_tokens": profile.max_output_tokens,
        }
        if images:
            body["vl_high_resolution_images"] = profile.high_resolution_images
        model_slot = self.model_semaphores.setdefault(profile.model, asyncio.Semaphore(1))
        from .throughput import DispatchDeferred, rate_token_estimate, shared_window_delay
        # Short business jobs yield their lease while rate-limited. An insight
        # coordinator owns multiple units, so only its waiting unit sleeps.
        can_defer = job is not None and profile.operation != 'insights'
        if can_defer and (model_slot.locked() or self.semaphore.locked()):
            raise DispatchDeferred('model-slot:' + profile.model, 0.5)
        rate_wait_started = time.monotonic()
        rate_estimate = rate_token_estimate(messages, bound, profile.max_output_tokens)
        rate_ticket = await self.traffic.acquire(profile.model, rate_estimate, defer=can_defer)
        while True:
            with self.budget.repository.read() as conn:
                shared_wait = shared_window_delay(conn, profile.model, rate_estimate)
            if not shared_wait:
                break
            if can_defer:
                self.traffic.cancel(profile.model, rate_ticket)
                raise DispatchDeferred('model-account-window:' + profile.model, shared_wait)
            await asyncio.sleep(min(shared_wait, 30))
        rate_wait_seconds = time.monotonic() - rate_wait_started
        async with model_slot, self.semaphore:
            from .run_policy import dispatch_remaining
            from dataclasses import replace
            catalog_left = dispatch_remaining(self.budget.repository, job)
            if catalog_left is not None:
                profile = replace(profile, wall_seconds=min(profile.wall_seconds, catalog_left),
                                  inactivity_seconds=min(profile.inactivity_seconds, catalog_left))
            qualification = None
            if purpose == "verification":
                if self.verification_authorizer is None:
                    raise DomainError("VERIFICATION_SCOPE", "固定输入验证尚未登记")
                qualification = self.verification_authorizer(task_id, owner, profile, bound)
            if purpose == 'production' and self.pilot_authorizer is not None:
                qualification = self.pilot_authorizer(task_id, owner, profile, bound)
                if qualification is not None:
                    purpose = 'pilot'
            if purpose == "production" and self.profile_authorizer is not None:
                qualification = self.profile_authorizer(task_id, owner, profile, bound)
                if qualification.get("synthetic"):
                    raise DomainError(
                        "SYNTHETIC_PROFILE_DISPATCH_FORBIDDEN", "合成校准资格不能授权真实模型调用"
                    )
            try:
                attempt = self.budget.reserve(
                    task_id=task_id,
                    owner=owner,
                    model=profile.model,
                    root_id=root_id,
                    request=body,
                    input_bound=bound,
                    output_bound=profile.max_output_tokens,
                    job=job,
                    smoke=smoke,
                    root_limit=root_limit,
                    profile_state=profile.state,
                    purpose=purpose,
                    wall_bound_seconds=profile.wall_seconds,
                )
            except BaseException:
                self.traffic.cancel(profile.model, rate_ticket)
                raise

            dispatch_context_ref = None

            def authorize_dispatch(conn, attempt):
                nonlocal dispatch_context_ref
                from .run_policy import guard, current_job
                guard(self.budget.repository, conn, job or current_job.get(), dispatch=True)
                if purpose == "verification" and self.verification_authorizer(task_id, owner, profile, bound) != qualification:
                    raise DomainError("VERIFICATION_SCOPE_CHANGED", "派发前固定输入验证范围变化")
                if purpose == "production" and self.profile_authorizer is not None:
                    if self.profile_authorizer(task_id, owner, profile, bound) != qualification:
                        raise DomainError(
                            "PROFILE_QUALIFICATION_CHANGED", "派发前科学运行资格发生变化"
                        )
                if purpose == 'pilot' and (self.pilot_authorizer is None or self.pilot_authorizer(task_id, owner, profile, bound) != qualification):
                    raise DomainError('PILOT_SCOPE_CHANGED', '隔离试运行范围发生变化')
                shared_wait = shared_window_delay(conn, profile.model, rate_estimate)
                if shared_wait:
                    raise DispatchDeferred('model-account-window:' + profile.model, shared_wait)
                if dispatch_guard:
                    dispatch_guard(conn, attempt)
                dispatch_context_ref = self.budget.repository.put_object(
                    conn,
                    task_id,
                    "model_dispatch",
                    attempt["attempt_id"],
                    1,
                    {
                        "schema_version": "ModelDispatchContext/1",
                        "attempt_id": attempt["attempt_id"],
                        "owner": owner,
                        "root_id": root_id,
                        "profile": asdict(profile),
                        "purpose": purpose,
                        "scientific_qualification": qualification,
                        "endpoint_sha256": digest(values["dashscope_base_url"].rstrip("/")),
                        "input_bound": bound,
                        "rate_token_estimate": rate_estimate,
                        "output_bound": profile.max_output_tokens,
                        "request_hash": attempt["request_hash"],
                    },
                )

            self.budget.dispatch(attempt["attempt_id"], authorize=authorize_dispatch)
            usage = None
            content, thinking_chars, finish, done = [], 0, None, False
            provider_id = None
            started = time.monotonic()
            error = None
            partial_result = None
            provider_status, provider_rejection = None, None
            transport_events = []

            async def trace(event_name, info):
                # Never retain trace info: it can contain Authorization headers.
                if len(transport_events) < 64:
                    transport_events.append(event_name)

            try:
                async with asyncio.timeout(profile.wall_seconds):
                    async with httpx.AsyncClient(
                        transport=self.transport,
                        trust_env=self.trust_env,
                        timeout=httpx.Timeout(profile.inactivity_seconds, connect=10),
                        follow_redirects=False,
                    ) as client:
                        async with client.stream(
                            "POST",
                            values["dashscope_base_url"].rstrip("/") + "/chat/completions",
                            headers={"Authorization": "Bearer " + values["dashscope_api_key"]},
                            json=body,
                            extensions={'trace': trace},
                        ) as response:
                            provider_status = response.status_code
                            if response.status_code != 200:
                                error_body = b''
                                async for piece in response.aiter_bytes():
                                    error_body += piece[:4096 - len(error_body)]
                                    if len(error_body) >= 4096:
                                        break
                                lowered = error_body.lower()
                                if b'json' in lowered and (b'messages' in lowered or b'response_format' in lowered):
                                    provider_rejection = 'json_mode_request_rejected'
                                # Do not include provider response text: it may contain credentials.
                                raise DomainError(
                                    "PROVIDER_HTTP_ERROR",
                                    "模型服务请求失败",
                                    502,
                                    provider_status=response.status_code,
                                    retry_after_seconds=_retry_after(response.headers.get('Retry-After')),
                                )
                            received = 0
                            iterator = response.aiter_lines()
                            first_event, last_progress = False, time.monotonic()
                            while True:
                                now = time.monotonic()
                                remaining = min(
                                    last_progress + profile.inactivity_seconds - now,
                                    started + 90 - now if not first_event else profile.wall_seconds,
                                )
                                if remaining <= 0:
                                    raise DomainError(
                                        "MODEL_PROGRESS_TIMEOUT", "模型未在期限内返回有效进展"
                                    )
                                try:
                                    line = await asyncio.wait_for(
                                        anext(iterator), timeout=remaining
                                    )
                                except StopAsyncIteration:
                                    break
                                received += len(line.encode("utf-8"))
                                if received > 8 * 1024**2:
                                    raise DomainError("PROVIDER_RESPONSE_LIMIT", "响应超过受控大小")
                                if not line.startswith("data:"):
                                    continue
                                data = line[5:].strip()
                                if data == "[DONE]":
                                    done = True
                                    break
                                chunk = loads(data)
                                first_event = True
                                provider_id = chunk.get("id", provider_id)
                                if chunk.get("usage"):
                                    usage = chunk["usage"]
                                for choice in chunk.get("choices", []):
                                    delta = choice.get("delta", {})
                                    if delta.get("content"):
                                        content.append(delta["content"])
                                        last_progress = time.monotonic()
                                    thinking_chars += len(delta.get("reasoning_content") or "")
                                    if choice.get("finish_reason"):
                                        finish = choice["finish_reason"]
                partial_result = None
                if (profile.operation == 'paper_batch' and profile.version.startswith(('bounded-extraction-', 'quality-local-reextraction-'))
                        and finish == 'length'):
                    partial_result = complete_extraction_items(''.join(content))
                elif (profile.operation=='paper_admission' and profile.version.startswith('unified-')
                        and finish=='length'):
                    partial_result = complete_array_items(''.join(content), 'items')
                if (not done or finish != "stop") and partial_result is None:
                    raise DomainError(
                        "INCOMPLETE_MODEL_RESPONSE",
                        "模型输出未完整结束，未提交残片",
                        502,
                        finish_reason=finish,
                    )
                try:
                    result = partial_result or loads("".join(content))
                except ValueError as exc:
                    raise DomainError('INVALID_MODEL_JSON', '模型返回的JSON格式无效，结果未采用', 502,
                        parse_error=str(exc)[:240]) from exc
                if not isinstance(result, dict):
                    raise DomainError("INVALID_MODEL_JSON", "模型输出必须为JSON对象", 502)
                if purpose == "verification" and self.verification_authorizer(task_id, owner, profile, bound) != qualification:
                    raise DomainError("VERIFICATION_SCOPE_CHANGED", "返回时固定输入验证范围变化")
                if purpose == 'pilot' and self.pilot_authorizer(task_id, owner, profile, bound) != qualification:
                    raise DomainError('PILOT_SCOPE_CHANGED', '响应返回时隔离试运行范围发生变化')
                if (
                    purpose == "production"
                    and self.profile_authorizer is not None
                    and self.profile_authorizer(task_id, owner, profile, bound) != qualification
                ):
                    raise DomainError(
                        "PROFILE_QUALIFICATION_CHANGED",
                        "响应返回时科学运行资格发生变化；调用费用保留，结果未放行",
                    )
            except BaseException as exc:
                error = exc
            finally:
                receipt = {
                    "endpoint_sha256": digest(values["dashscope_base_url"].rstrip("/")),
                    "provider_id": provider_id,
                    "model": profile.model,
                    "profile": profile.version,
                    "dispatch_context_ref": dispatch_context_ref,
                    "operation": profile.operation,
                    "source_format": profile.source_format,
                    "scientific_qualification": qualification,
                    "thinking_mode": profile.thinking,
                    "high_resolution_images": profile.high_resolution_images,
                    "input_bound": bound,
                    "estimator": "qwen32-ceil-1",
                    "rate_token_estimate": rate_estimate,
                    "rate_wait_seconds": rate_wait_seconds,
                    "rate_quota_basis": "public-floor-70pct-workspace-unconfirmed",
                    "max_output_tokens": profile.max_output_tokens,
                    "wall_seconds": profile.wall_seconds,
                    "inactivity_seconds": profile.inactivity_seconds,
                    "finish_reason": finish,
                    "done": done,
                    "thinking_characters": thinking_chars,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "error_type": type(error).__name__ if error else None,
                    "error_code": getattr(error, "code", None),
                    'provider_status': provider_status,
                    'provider_rejection': provider_rejection,
                    'transport_events': transport_events,
                    'environment_proxy_enabled': self.trust_env,
                }
                receipt['partial_complete_items'] = bool(partial_result)
                if (error or partial_result) and content:
                    try:
                        with self.budget.repository.transaction() as conn:
                            receipt['diagnostic_ref'] = self.budget.repository.put_object(conn, task_id,
                                'model_response_diagnostic', attempt['attempt_id'], 1,
                                {'attempt_id': attempt['attempt_id'], 'raw_response': ''.join(content),
                                 'finish_reason': finish, 'error_code': getattr(error, 'code', type(error).__name__) if error else 'OUTPUT_TRUNCATED_COMPLETE_ITEMS',
                                 'adopted_as_scientific_data': False})
                    except Exception as diagnostic_error:
                        # Accounting and the original failure still finish if
                        # cleanup/deletion has made diagnostic storage unavailable.
                        receipt['diagnostic_save_error'] = type(diagnostic_error).__name__
                known_unsent = (self.transport is None and isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout))
                    and provider_status is None
                    and any(name.endswith(('.connect_tcp.failed', '.start_tls.failed')) for name in transport_events)
                    and not any('send_request_headers' in name or 'send_request_body' in name for name in transport_events))
                if known_unsent:
                    # Proven pre-request failure, not a guessed refund of an
                    # ambiguous request. Root/work attempt counts still apply.
                    usage = {'prompt_tokens': 0, 'completion_tokens': 0}
                    receipt['usage_basis'] = 'native_transport_failed_before_request_headers'
                self.budget.settle(
                    attempt["attempt_id"],
                    input_tokens=usage.get("prompt_tokens") if usage else None,
                    output_tokens=usage.get("completion_tokens") if usage else None,
                    receipt=receipt,
                )
                self.traffic.settle(profile.model, rate_ticket, usage,
                    limited=provider_status == 429,
                    retry_after=error.details.get('retry_after_seconds') if isinstance(error, DomainError) else None)
            if error:
                raise error
            return result, {**receipt, "attempt_id": attempt["attempt_id"], "usage": usage}


def _retry_after(value):
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        from datetime import datetime, timezone
        from email.utils import parsedate_to_datetime
        try:
            return max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None
