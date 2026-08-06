import time, json, os, uuid

t0 = time.time()
from astroquery_ai.main_graph import create_main_graph

initial = {
    'user_query': 'Betelgeuse 的 JHK 红外星等和视向速度',
    'query_id': str(uuid.uuid4()),
    'extra_pdfs': [], 'error_log': [],
    'target_entity': 'Betelgeuse',
    'requested_properties': ['JHK 红外星等', '视向速度'],
    'clarification_status': 'confirmed', 'query_type': 'astronomical',
    'user_confirmed': True, 'entity_type_hint': 'unknown',
}
print(f'[{time.strftime("%H:%M:%S")}] start Betelgeuse pipeline', flush=True)
app = create_main_graph()
final_state = app.invoke(initial, config={'recursion_limit': 50})
elapsed = time.time() - t0

final = final_state.get('final_output', {})
simbad = final_state.get('simbad_info', {})
ps = final_state.get('property_spec', []) or []
os.makedirs('output', exist_ok=True)
json.dump(final, open('output/betelgeuse_result.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=2)

print(f'[{time.strftime("%H:%M:%S")}] === DONE in {elapsed:.0f}s ===', flush=True)
print(f'simbad: main_id={simbad.get("main_id")} otype={simbad.get("otype")}', flush=True)
print(f'property_spec ({len(ps)}):', [p["property_id"] for p in ps], flush=True)
print(f'sources: {len(final.get("sources",[]))}  records: {len(final.get("records",[]))}', flush=True)
errs = final.get('error_log', []) or []
print(f'errors: {len(errs)}', flush=True)
for e in errs[:6]:
    print(f'  [{e.get("node")}] {str(e.get("error"))[:150]}', flush=True)
if final.get('records'):
    from collections import Counter
    names = Counter(r.get('field_name','?') for r in final['records'])
    print(f'field_names: {dict(names)}', flush=True)
    print(f'paper_records: {len([r for r in final["records"] if r.get("extraction_method","").startswith("vlm")])}', flush=True)
    db_recs = [r for r in final['records'] if r.get('extraction_method') == 'database_query']
    for r in db_recs[:5]:
        print(f'  DB: {r["field_name"]}={r["field_value"]} {r.get("field_unit","")} src={r.get("source_id","")}', flush=True)
print('saved output/betelgeuse_result.json', flush=True)
