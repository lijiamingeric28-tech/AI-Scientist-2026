"""Bounded, recorded scientific HTTP transport. No hidden retries/redirects."""

from __future__ import annotations
import asyncio
import ipaddress
from urllib.parse import urlsplit, urljoin

import httpx

from .codec import digest, new_id, utcnow
from .errors import DomainError
from .models import TERMINAL
from .source_resources import local_source_bytes


class ScientificHTTP:
    def __init__(self, repository, *, transport=None):
        self.repository, self.transport = repository, transport
        from .stages import EXECUTION_POLICY
        self.total = asyncio.Semaphore(EXECUTION_POLICY['network_total'])
        self.services = {}
        self.endpoint_preferences = {}
        self.request_locks = {}
        self.service_backoffs = {}

    async def request(
        self,
        task_id: str,
        owner: str,
        service: str,
        method: str,
        url: str,
        *,
        params=None,
        data=None,
        headers=None,
        max_bytes=16 * 1024**2,
        timeout=45,
        max_redirects=0,
        connect_timeout=10,
        read_timeout=45,
        resource_scope="general",
        managed_routes=False,
    ) -> tuple[bytes, dict]:
        from .run_policy import dispatch_remaining, endpoint_cooling, cool_endpoint
        remaining_catalog = dispatch_remaining(self.repository)
        if remaining_catalog is not None:
            timeout = min(timeout, remaining_catalog)
        if endpoint_cooling(self.repository, task_id, service, url):
            raise DomainError('SOURCE_ENDPOINT_COOLDOWN', '本任务已确认该来源入口暂不可用，未重复探测')
        if type(max_redirects) is not int or not 0 <= max_redirects <= 5:
            raise DomainError("REDIRECT_POLICY", "重定向上限无效", 422)
        if (
            type(max_bytes) is not int
            or not 0 < max_bytes <= 100 * 1024**2
            or type(timeout) not in {int, float}
            or not 0 < timeout <= 180
            or resource_scope not in {"general", "body", "attachment"}
        ):
            raise DomainError("HTTP_RESOURCE_POLICY", "网络读取范围或有限上限无效", 422)
        import time

        if owner == "M05" and resource_scope == "general":
            resource_scope = "body"

        deadline, hops = time.monotonic() + timeout, []
        for index in range(max_redirects + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DomainError("SOURCE_HTTP_TIMEOUT", "来源请求总时限已到")
            try:
                raw, metadata = await self._request_once(
                    task_id,
                    owner,
                    service,
                    method,
                    url,
                    params=params,
                    data=data,
                    headers=headers,
                    max_bytes=max_bytes,
                    timeout=remaining,
                    connect_timeout=connect_timeout,
                    read_timeout=read_timeout,
                    resource_scope=resource_scope,
                    managed_routes=managed_routes,
                )
            except (TimeoutError, httpx.TimeoutException) as exc:
                cool_endpoint(self.repository, task_id, service, url, 'SOURCE_HTTP_TIMEOUT')
                raise DomainError("SOURCE_HTTP_TIMEOUT", "来源请求超时，失败尝试已保留") from exc
            except httpx.TransportError as exc:
                cool_endpoint(self.repository, task_id, service, url, 'SOURCE_TRANSPORT_ERROR')
                raise DomainError(
                    "SOURCE_TRANSPORT_ERROR", "来源连接未完成，失败尝试已保留"
                ) from exc
            except DomainError as exc:
                if exc.code == 'SOURCE_HTTP_ERROR' and (exc.details.get('provider_status') == 429 or (exc.details.get('provider_status') or 0) >= 500):
                    cool_endpoint(self.repository, task_id, service, url, exc.code)
                raise
            if metadata["status"] == 200:
                metadata["redirect_chain"] = hops
                return raw, metadata
            location = metadata.pop("redirect_location", None)
            if index == max_redirects or not location:
                raise DomainError("SOURCE_REDIRECT_LIMIT", "来源重定向未能在限定次数内取得正文")
            next_url = urljoin(url, location)
            # Each destination is validated and recorded by _request_once.
            # Secrets never travel to a different authority.
            if urlsplit(next_url).netloc != urlsplit(url).netloc:
                headers = {
                    k: v
                    for k, v in (headers or {}).items()
                    if k.lower() not in {"authorization", "cookie", "proxy-authorization"}
                }
            hops.append(
                {
                    "from": urlsplit(url)._replace(query="").geturl(),
                    "to": urlsplit(next_url)._replace(query="").geturl(),
                    "attempt_id": metadata["attempt_id"],
                    "status": metadata["status"],
                }
            )
            if metadata["status"] == 303:
                method, data = "GET", None
            url, params = next_url, None
        raise AssertionError("bounded redirect loop")

    async def _request_once(
        self,
        task_id: str,
        owner: str,
        service: str,
        method: str,
        url: str,
        *,
        params=None,
        data=None,
        headers=None,
        max_bytes=16 * 1024**2,
        timeout=45,
        connect_timeout=10,
        read_timeout=45,
        resource_scope="general",
        managed_routes=False,
    ) -> tuple[bytes, dict]:
        import time
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise DomainError("INVALID_SOURCE_URL", "来源必须使用有效HTTPS地址", 422)
        try:
            private = not ipaddress.ip_address(parsed.hostname).is_global
        except ValueError:
            private = parsed.hostname.lower() in {
                "localhost",
                "localhost.localdomain",
            } or parsed.hostname.lower().endswith(".local")
        if private:
            raise DomainError("PRIVATE_SOURCE_URL", "来源地址不能指向本地网络", 422)
        if owner in {"M07", "M08", "M09", "M10", "M11", "M12"}:
            raise DomainError("SOURCE_READ_FORBIDDEN", "该模块没有新增来源读取权限")
        service_key = ('publisher:' + parsed.hostname.lower().removeprefix('www.')
                       if service == 'publisher' else service)
        from .stages import EXECUTION_POLICY
        semaphore = self.services.setdefault(service_key,
            asyncio.Semaphore(EXECUTION_POLICY['services'].get(service, 2)))
        delay = self.service_backoffs.get(service_key, 0) - time.monotonic()
        if delay > 0:
            await asyncio.sleep(delay)
        # A queue for one service/domain must not reserve all global network slots.
        async with semaphore, self.total:
            with self.repository.transaction() as conn:
                task = self.repository.task(conn, task_id)
                self.repository.guard_definitions(conn, task)
                calibration = task["kind"] == "validation"
                calibration_scope = None
                if calibration:
                    calibration_scope = self.repository.object(
                        conn, task_id, "calibration_scope", task_id
                    )
                    if (
                        owner not in calibration_scope["allowed_owners"]
                        or service not in calibration_scope["allowed_services"]
                    ):
                        raise DomainError("CALIBRATION_SCOPE", "校准请求超出预登记范围")
                if task["kind"] not in {"live", "validation"} or task["lifecycle"] in TERMINAL | {
                    "paused",
                    "pausing",
                    "cancelling",
                    "interrupted",
                    "waiting_input",
                    "waiting_review",
                }:
                    raise DomainError("HTTP_DISPATCH_FORBIDDEN", "当前任务没有外部请求授权")
                if (
                    not calibration
                    and owner != "M01"
                    and (task["query_ref"] is None or task["science_state"] != "open")
                ):
                    raise DomainError("QUERY_NOT_CONFIRMED", "科学请求尚未冻结")
                accounting = "CASE WHEN status IN ('dispatched','unknown') THEN max(byte_bound,byte_count) ELSE byte_count END"
                total = conn.execute(
                    f"SELECT count(*),coalesce(sum({accounting}),0) FROM http_attempts WHERE task_id=?",
                    (task_id,),
                ).fetchone()
                local = conn.execute(
                    "SELECT count(*) FROM http_attempts WHERE task_id=? AND owner=?",
                    (task_id, owner),
                ).fetchone()[0]
                limit = {"M01": 32, "M03": 800, "M04": 320, "M05": 640}.get(owner, 2000)
                pilot_rows = self.repository.objects(conn, task_id, 'pilot_scope')
                if pilot_rows and total[0] >= pilot_rows[0]['maximum_http_requests']:
                    raise DomainError('PILOT_HTTP_LIMIT', '本次隔离试运行的网络请求上限已达')
                if calibration_scope:
                    limit = min(limit, calibration_scope["max_requests"])
                    if total[0] >= calibration_scope["max_requests"]:
                        raise DomainError("CALIBRATION_HTTP_LIMIT", "本次校准网络请求额度已满")
                expanded_bytes = local_source_bytes(self.repository, conn, task_id)
                if total[1] + expanded_bytes + max_bytes > 3 * 1024**3:
                    raise DomainError("TASK_HTTP_LIMIT", "该任务科学网络请求预算不足")
                if calibration_scope and local >= limit:
                    raise DomainError(
                        "MODULE_HTTP_LIMIT", "该模块科学网络请求预算不足", owner=owner
                    )
                if owner == "M05":
                    module_bytes = conn.execute(
                        f"SELECT coalesce(sum({accounting}),0) FROM http_attempts WHERE task_id=? AND owner='M05'",
                        (task_id,),
                    ).fetchone()[0]
                    if module_bytes + expanded_bytes + max_bytes > 2 * 1024**3:
                        raise DomainError(
                            "MODULE_HTTP_BYTE_LIMIT", "正文及附件获取累计字节预算不足"
                        )
                attempt_id = new_id()
                root_url = (
                    parsed._replace(netloc="vizier-official-mirrors", query="").geturl()
                    if service == "vizier"
                    and parsed.hostname in {"vizier.cds.unistra.fr", "vizier.cfa.harvard.edu"}
                    else parsed._replace(query="").geturl()
                )
                request_hash = digest(
                    {
                        "method": method,
                        "url": root_url,
                        "params_hash": digest(params),
                        "data_hash": digest(data),
                    }
                )
                if (
                    owner == "M03"
                    # ServiceRoutes already owns two finite rounds, task-wide
                    # cooldown and recovery. The legacy three-failure count
                    # combines mirrors and can abort a parallel successful
                    # sibling before its second round is committed.
                    and not managed_routes
                    and conn.execute(
                        "SELECT count(*) FROM http_attempts WHERE task_id=? AND owner=? AND request_hash=? AND status<>'completed'",
                        (task_id, owner, request_hash),
                    ).fetchone()[0]
                    >= 3
                ):
                    raise DomainError(
                        "SOURCE_REQUEST_LIMIT", "同一星表逻辑请求已达3次，镜像及重启不重置"
                    )
                # Never persist authorization headers or URL query credentials.
                conn.execute(
                    "INSERT INTO http_attempts(attempt_id,task_id,owner,service,request_hash,status,started_at,byte_bound,wall_bound_seconds,resource_scope) VALUES(?,?,?,?,?,'dispatched',?,?,?,?)",
                    (
                        attempt_id,
                        task_id,
                        owner,
                        service,
                        request_hash,
                        utcnow(),
                        max_bytes,
                        timeout,
                        resource_scope,
                    ),
                )
            received, status, error = 0, None, None
            import time

            started = time.monotonic()
            try:
                async with asyncio.timeout(timeout):
                    async with httpx.AsyncClient(
                        transport=self.transport,
                        timeout=httpx.Timeout(
                            min(timeout, read_timeout), connect=min(timeout, connect_timeout)
                        ),
                        follow_redirects=False,
                    ) as client:
                        async with client.stream(
                            method, url, params=params, data=data, headers=headers
                        ) as response:
                            status = response.status_code
                            declared = response.headers.get("content-length")
                            if declared and declared.isdecimal() and int(declared) > max_bytes:
                                raise DomainError(
                                    "SOURCE_BYTE_LIMIT", "来源声明大小超过本次读取上限"
                                )
                            if status in {301, 302, 303, 307, 308}:
                                return b"", {
                                    "attempt_id": attempt_id,
                                    "endpoint": parsed._replace(query="").geturl(),
                                    "status": status,
                                    "redirect_location": response.headers.get("location"),
                                    "retrieved_at": utcnow(),
                                }
                            if status != 200:
                                from .calls import _retry_after
                                retry_after = _retry_after(response.headers.get('Retry-After'))
                                provider_error = None
                                if service == 'ads' and status == 400:
                                    # The syntax repair needs the actual API diagnostic,
                                    # not credentials or an unbounded server document.
                                    error_bytes = bytearray()
                                    async for chunk in response.aiter_bytes(chunk_size=4096):
                                        received += len(chunk)
                                        error_bytes.extend(chunk[:4096-len(error_bytes)])
                                        if len(error_bytes) >= 4096:
                                            break
                                    provider_error = error_bytes.decode('utf-8',errors='replace')
                                    for key,value in (headers or {}).items():
                                        if key.lower() in {'authorization','cookie','proxy-authorization'}:
                                            provider_error = provider_error.replace(value,'[redacted]')
                                            if value.lower().startswith('bearer '):
                                                provider_error = provider_error.replace(value[7:],'[redacted]')
                                if status == 429:
                                    self.service_backoffs[service_key] = time.monotonic() + (retry_after if retry_after is not None else 2)
                                raise DomainError(
                                    "SOURCE_HTTP_ERROR",
                                    "来源服务请求失败",
                                    502,
                                    provider_status=status,
                                    retry_after_seconds=retry_after,
                                    **({'provider_error':provider_error} if provider_error is not None else {}),
                                )
                            chunks = []
                            async for chunk in response.aiter_bytes():
                                received += len(chunk)
                                if received > max_bytes:
                                    raise DomainError(
                                        "SOURCE_BYTE_LIMIT", "来源响应超过本次读取上限"
                                    )
                                chunks.append(chunk)
                            metadata = {
                                "attempt_id": attempt_id,
                                "endpoint": parsed._replace(query="").geturl(),
                                "status": status,
                                "etag": response.headers.get("etag"),
                                "last_modified": response.headers.get("last-modified"),
                                "media_type": response.headers.get("content-type"),
                                "byte_count": received,
                                "retrieved_at": utcnow(),
                                "elapsed_seconds": time.monotonic() - started,
                            }
                            return b"".join(chunks), metadata
            except BaseException as exc:
                error = exc.code if isinstance(exc, DomainError) else type(exc).__name__
                raise
            finally:
                with self.repository.transaction() as conn:
                    conn.execute(
                        "UPDATE http_attempts SET status=?,byte_count=?,completed_at=?,status_code=?,error_code=?,elapsed_seconds=? WHERE attempt_id=?",
                        (
                            "unknown" if error == "CancelledError" else "failed" if error else "completed",
                            received,
                            utcnow(),
                            status,
                            error,
                            time.monotonic() - started,
                            attempt_id,
                        ),
                    )
