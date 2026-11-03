"""Credential access checks and atomic activation, separate from scientific qualification."""
import asyncio
import httpx
import base64
import struct
import zlib
from copy import copy
from uuid import uuid4
from .codec import utcnow
from .configuration import MODELS
from .errors import DomainError
from .provider import provider_identity


def access_image():
    """Public, synthetic 64px image; no query material is sent during setup."""
    def chunk(kind, data):
        return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    pixels=(b'\0'+b'\xff\xff\xff'*64)*64
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',64,64,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(pixels))+chunk(b'IEND',b'')
    return 'data:image/png;base64,'+base64.b64encode(png).decode()


async def inference_access(application, candidate, *, gateway=None):
    from .calls import ModelGateway,ModelProfile
    if gateway is None:
        isolated_config=copy(application.configuration)
        isolated_config.runtime=application.configuration.effective(candidate)
        gateway=ModelGateway(isolated_config,application.budget)
        # A candidate connection must not evade the running app's concurrency.
        gateway.semaphore=application.models.semaphore
        gateway.model_semaphores=application.models.model_semaphores
        gateway.traffic=application.models.traffic
    payer=application.repository.create_task('模型连接检查',kind='validation')['task_id']
    checked=[]
    try:
        for model in sorted(set(MODELS.values())):
            visual=model=='qwen3.7-plus'
            text='Return exactly this JSON object: {"connected":true}. This is a connection check.'
            content=[{'type':'text','text':text},{'type':'image_url','image_url':{'url':access_image()}}] if visual else text
            profile=ModelProfile(model=model,version='account-access-1',thinking=False,max_input_tokens=4096,
                max_output_tokens=64,max_images=1 if visual else 0,wall_seconds=60,inactivity_seconds=30,
                operation='account_access',source_format='synthetic_image' if visual else 'plain_text')
            try:
                response,receipt=await gateway.json(task_id=payer,owner='M01',root_id='connection:'+str(uuid4()),
                    profile=profile,messages=[{'role':'user','content':content}],purpose='calibration',root_limit=1)
            except DomainError as error:
                if not error.code.startswith(('PROVIDER_','MODEL_','JSON_')):
                    raise
                status=error.details.get('provider_status')
                if status in (401,403):
                    raise DomainError('CONNECTION_MODEL_PERMISSION',model+' 实际调用未通过授权，请检查当前空间的模型权限。',422,model=model) from None
                if status==429:
                    raise DomainError('CONNECTION_RATE_LIMIT',model+' 暂时限流，请稍后重试。',503,model=model) from None
                raise DomainError('CONNECTION_MODEL_UNAVAILABLE',model+' 未能完成连接检查，请稍后重试。',503,model=model) from None
            except (TimeoutError,httpx.HTTPError):
                raise DomainError('CONNECTION_MODEL_UNAVAILABLE',model+' 暂时无法连接，请稍后重试。',503,model=model) from None
            if not isinstance(response,dict) or response.get('connected') is not True:
                raise DomainError('CONNECTION_MODEL_RESPONSE',model+' 没有返回有效的连接检查结果，请重试。',503,model=model)
            checked.append({'model':model,'modalities':['text','image'] if visual else ['text'],'attempt_id':receipt['attempt_id']})
    finally:
        lifecycle='completed' if len(checked)==len(set(MODELS.values())) else 'error'
        with application.repository.transaction() as conn:
            application.repository.mutate_task(conn,payer,lifecycle=lifecycle)
            application.repository.event(conn,payer,'task_state_changed',{'lifecycle':lifecycle,'purpose':'connection_access'})
    return checked


async def check(values, *, transport=None):
    endpoint = values.get('dashscope_base_url', '').rstrip('/')
    if not provider_identity(endpoint):
        raise DomainError('PROVIDER_SERVICE_UNSUPPORTED', '当前版本支持百炼北京正式服务，请使用对应业务空间的兼容接口地址。', 422)
    key = values.get('dashscope_api_key')
    if not key:
        raise DomainError('PROVIDER_NOT_CONFIGURED', '请填写百炼 API Key。', 422)
    try:
        async with httpx.AsyncClient(transport=transport, timeout=15, follow_redirects=False) as client:
            response = await client.get(endpoint+'/models', headers={'Authorization': 'Bearer '+key})
    except httpx.TimeoutException:
        raise DomainError('CONNECTION_TIMEOUT', '百炼连接超时，请稍后重试。', 503) from None
    except httpx.HTTPError:
        raise DomainError('CONNECTION_UNAVAILABLE', '暂时无法连接百炼，请检查地址或网络后重试。', 503) from None
    messages = {
        401: ('CONNECTION_AUTH', 'API Key 未通过验证，请检查密钥及其所属业务空间。'),
        403: ('CONNECTION_PERMISSION', '当前密钥无权访问此业务空间，请检查空间权限。'),
        429: ('CONNECTION_RATE_LIMIT', '百炼暂时限流，请稍后重试。'),
    }
    if response.status_code in messages:
        code, message = messages[response.status_code]
        raise DomainError(code, message, 422 if response.status_code in (401,403) else 503)
    if response.status_code != 200:
        raise DomainError('CONNECTION_UNAVAILABLE', '模型服务未能完成连接检查，请检查地址后重试。', 503)
    try:
        data = response.json()['data']
        models = {m['id'] for m in data if isinstance(m, dict) and isinstance(m.get('id'), str)}
    except (ValueError, KeyError, TypeError):
        raise DomainError('CONNECTION_RESPONSE', '模型服务没有返回可读取的模型清单。', 503) from None
    needed = sorted(set(MODELS.values()))
    missing = [name for name in needed if name not in models]
    if missing:
        raise DomainError('CONNECTION_MODELS_MISSING', '当前空间未列出所需模型：'+'、'.join(missing)+'。请检查模型授权。', 422)
    return {'state': 'connected', 'checked_at': utcnow(), 'models': needed, 'checked': 'model_catalog',
            'provider': provider_identity(endpoint)}


async def test_and_apply(application, patch, expected_revision, *, transport=None):
    config = application.configuration
    candidate = config.candidate(patch, expected_revision)
    if any(config.effective(candidate).get(k) != candidate.get(k) for k in ('dashscope_api_key','dashscope_base_url')):
        raise DomainError('CONNECTION_ENV_OVERRIDE', '启动环境正在覆盖模型连接，请先修改对应的环境配置。', 409)
    changed = any(candidate.get(k) != config.runtime.get(k) for k in ('dashscope_api_key','dashscope_base_url'))
    if changed and provider_identity(candidate.get('dashscope_base_url','')) != provider_identity(config.runtime.get('dashscope_base_url','')):
        with application.repository.read() as conn:
            if conn.execute("SELECT 1 FROM jobs WHERE status='running' LIMIT 1").fetchone():
                raise DomainError('CONNECTION_BUSY', '有查询正在使用另一种服务，请在当前调用结束后应用新连接。', 409)
    result = await check(config.effective(candidate), transport=transport)
    if not application.registry.allow_synthetic:
        from .product_libraries import ensure_libraries
        from .product_qualifications import install_release
        ensure_libraries(application)
        install_release(application)
        result['capabilities']=await inference_access(application,candidate)
        result['checked']='model_inference'
    # The revision is rechecked after the network request, before any settings change.
    config.save(patch, expected_revision)
    config.activate()
    result['configuration_revision'] = config.runtime_revision
    config.record_connection(result)
    return result
