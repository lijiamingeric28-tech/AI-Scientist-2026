"""Connection rotation does not alter product science or leak a candidate key."""
import asyncio
from pathlib import Path
import httpx
import pytest
from astroquery_ai.runtime.application import Application
from astroquery_ai.runtime.configuration import MODELS
from astroquery_ai.runtime.connections import check, test_and_apply as apply_connection
from astroquery_ai.runtime.connections import inference_access
from astroquery_ai.runtime.provider import BEIJING,provider_identity,compatible
from astroquery_ai.runtime.errors import DomainError
from astroquery_ai.runtime.product_qualifications import install_release

URL='https://dashscope.aliyuncs.com/compatible-mode/v1'
SPACE='https://ws-example123.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/'

@pytest.mark.parametrize('url',[URL,SPACE])
def test_official_beijing_service_is_account_independent(url):
    assert provider_identity(url)==BEIJING
    assert compatible({'provider_identity':BEIJING},url)

@pytest.mark.parametrize('url',[
 'https://dashscope.aliyuncs.com.evil.example/compatible-mode/v1',
 'https://ws-example123.cn-shanghai.maas.aliyuncs.com/compatible-mode/v1',
 'http://dashscope.aliyuncs.com/compatible-mode/v1',
 URL+'?token=secret',URL.replace('/compatible-mode','/proxy/compatible-mode'),
 'https://user:secret@dashscope.aliyuncs.com/compatible-mode/v1',
 'https://dashscope.aliyuncs.com:8443/compatible-mode/v1'])
def test_other_services_cannot_reuse_a_proof(url):
    assert provider_identity(url) is None

def response(status=200,missing=False):
    def handler(req):
        assert req.headers['Authorization'].startswith('Bearer ')
        names=sorted(set(MODELS.values()))
        return httpx.Response(status,json={'data':[{'id':x} for x in (names[1:] if missing else names)]})
    return httpx.MockTransport(handler)

@pytest.mark.parametrize('status,code',[(401,'CONNECTION_AUTH'),(403,'CONNECTION_PERMISSION'),(429,'CONNECTION_RATE_LIMIT'),(503,'CONNECTION_UNAVAILABLE')])
def test_rejected_candidate_never_replaces_working_connection(tmp_path,status,code):
    a=Application(tmp_path,allow_synthetic=True);c=a.configuration
    c.save({'dashscope_api_key':'old','dashscope_base_url':URL},1);c.activate();before=dict(c.runtime)
    with pytest.raises(DomainError) as e:
        asyncio.run(apply_connection(a,{'dashscope_api_key':'candidate-secret'},2,transport=response(status)))
    assert e.value.code==code and 'candidate-secret' not in str(e.value)
    assert c.runtime==before and c.runtime_revision==2

def test_same_service_rotation_activates_next_call_and_preserves_old_snapshot(tmp_path):
    a=Application(tmp_path,allow_synthetic=True);c=a.configuration
    c.save({'dashscope_api_key':'old','dashscope_base_url':URL},1);c.activate();old=c.runtime
    result=asyncio.run(apply_connection(a,{'dashscope_api_key':'new','dashscope_base_url':SPACE},2,transport=response()))
    assert result['state']=='connected' and result['configuration_revision']==3
    assert old['dashscope_api_key']=='old' and c.runtime['dashscope_api_key']=='new'
    assert 'new' not in str(c.public())
    assert not c.public()['restart_required']
    from astroquery_ai.runtime.configuration import Configuration
    assert Configuration(tmp_path).public()['connection']['state']=='connected'
    c.save({'dashscope_api_key':'changed-outside-tested-path'},3)
    assert Configuration(tmp_path).public()['connection']['state']=='configured'

def test_missing_model_identifies_permission_gap():
    with pytest.raises(DomainError) as e:
        asyncio.run(check({'dashscope_api_key':'test','dashscope_base_url':URL},transport=response(missing=True)))
    assert e.value.code=='CONNECTION_MODELS_MISSING'

def test_parallel_settings_change_is_not_overwritten(tmp_path):
    a=Application(tmp_path,allow_synthetic=True);c=a.configuration
    c.save({'dashscope_api_key':'old','dashscope_base_url':URL},1);c.activate()
    def racing(req):
        c.save({'ads_sort':'date desc'},2);c.activate()
        return httpx.Response(200,json={'data':[{'id':x} for x in set(MODELS.values())]})
    with pytest.raises(DomainError) as e:
        asyncio.run(apply_connection(a,{'dashscope_api_key':'new'},2,transport=httpx.MockTransport(racing)))
    assert e.value.code=='CONFIG_CHANGED' and c.runtime['dashscope_api_key']=='old'

def test_clean_install_reuses_exact_product_proofs_without_personal_tasks(tmp_path):
    a=Application(tmp_path,allow_synthetic=True)
    assert install_release(a)
    a.configuration.runtime={'dashscope_base_url':SPACE,'dashscope_api_key':'own-key'}
    with a.repository.read() as c:
        assert c.execute("select count(*) from tasks where kind<>'validation'").fetchone()[0]==0
        assert c.execute('select count(*) from attempts').fetchone()[0]==0
        for owner in ('M01','M03','M04','M06','M08','M11'):
            assert a.profile_authority.load(c,owner)[0]['state']=='qualified'
    assert install_release(a) is None


def test_access_checks_use_three_small_requests_and_an_image_without_user_material(tmp_path):
    a=Application(tmp_path,allow_synthetic=True)
    calls=[]
    class Gateway:
        async def json(self,**kw):
            calls.append(kw);return {'connected':True},{'attempt_id':'synthetic-'+kw['profile'].model}
    checked=asyncio.run(inference_access(a,{},gateway=Gateway()))
    assert len(checked)==3 and len(calls)==3
    assert all(c['purpose']=='calibration' and c['root_limit']==1 for c in calls)
    visual=next(c for c in calls if c['profile'].model=='qwen3.7-plus')
    assert visual['messages'][0]['content'][1]['image_url']['url'].startswith('data:image/png;base64,')
    assert a.repository.list_tasks()==[]
    with a.repository.read() as c:assert c.execute('select lifecycle from tasks').fetchone()[0]=='completed'


def test_model_permission_failure_is_not_misreported_as_scientific_rejection(tmp_path):
    a=Application(tmp_path,allow_synthetic=True)
    class Gateway:
        async def json(self,**kw):raise DomainError('PROVIDER_HTTP_ERROR','provider detail with private data',502,provider_status=403)
    with pytest.raises(DomainError) as e:asyncio.run(inference_access(a,{},gateway=Gateway()))
    assert e.value.code=='CONNECTION_MODEL_PERMISSION'
    assert 'private data' not in str(e.value)
    with a.repository.read() as c:assert c.execute('select lifecycle from tasks').fetchone()[0]=='error'
