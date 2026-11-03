"""Optional search preferences cannot masquerade as missing credentials."""
from astroquery_ai.runtime.configuration import Configuration,REQUIRED_CONNECTION_FIELDS

def test_research_delivery_release_is_persisted_and_selects_ordinary_frozen_policy(tmp_path,monkeypatch):
 from astroquery_ai.runtime.run_policy import request_policy
 monkeypatch.setattr(Configuration,'effective',staticmethod(lambda saved:dict(saved)))
 cfg=Configuration(tmp_path)
 cfg.save({'research_delivery_version':'research-delivery/1','retrieval_policy_version':'retrieval-feedback/1'},cfg.saved['revision'])
 restarted=Configuration(tmp_path)
 policy=request_policy(restarted)
 assert policy['version']=='research-delivery/1'
 assert policy['insights']['version']=='research-property-short-2'
 assert policy['delivery']['export_schema_version']==2
 assert policy['literature']['release']=='retrieval-feedback/1'

def test_default_ads_order_does_not_block_four_loaded_connections(tmp_path,monkeypatch):
 monkeypatch.setattr(Configuration,'effective',staticmethod(lambda saved:dict(saved)))
 cfg=Configuration(tmp_path)
 values={'dashscope_api_key':'SYNTHETIC-KEY','dashscope_base_url':'https://example.org/compatible-mode/v1','ads_api_token':'SYNTHETIC-TOKEN','unpaywall_email':'synthetic@example.org'}
 cfg.saved={'revision':1,'values':values};cfg.runtime=dict(values)
 public=cfg.public()
 assert public['setup_complete'] and not public['restart_required']
 assert set(public['configured'])==set(public['runtime_configured'])==REQUIRED_CONNECTION_FIELDS
 assert 'ads_sort' in public['editable_values']
 assert 'SYNTHETIC-KEY' not in str(public) and 'SYNTHETIC-TOKEN' not in str(public)
 cfg.runtime.pop('ads_api_token');assert not cfg.public()['setup_complete']

def test_an_explicit_valid_sort_remains_editable_and_does_not_change_connection_count(tmp_path,monkeypatch):
 monkeypatch.setattr(Configuration,'effective',staticmethod(lambda saved:dict(saved)))
 cfg=Configuration(tmp_path);cfg.runtime={k:'SYNTHETIC' for k in REQUIRED_CONNECTION_FIELDS};cfg.runtime['ads_sort']='date desc';cfg.saved={'revision':1,'values':dict(cfg.runtime)}
 public=cfg.public();assert public['setup_complete'] and len(public['runtime_configured'])==4
 assert public['editable_values']['ads_sort']=='date desc'
