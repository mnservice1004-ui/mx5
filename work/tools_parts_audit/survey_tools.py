import json, pathlib, re, collections

p = pathlib.Path('work/ocr_text')
fs = list(p.glob('*.json'))
keys = ['렌치','드라이버','리무버','플라이어','해머','망치','스패너','테스터','측정기','진단기','KDS','GDS','테이프','비눗','윤활','그리스','실런트','접착','육각','소켓','SST','공구',r'[0-9]{5}[- ][A-Z0-9]{5}']
result = {'source_pages_surveyed': len(fs), 'matches': {}}
for k in keys:
    hits = []
    for f in fs:
        j = json.loads(f.read_text(encoding='utf-8-sig'))
        ll = [x for x in j['text'].splitlines() if re.search(k, x, re.I)]
        if ll:
            hits.append({'source_ocr': f.name, 'matched_lines': ll})
    result['matches'][k] = hits
pathlib.Path('work/tools_parts_audit/tools_ocr_survey.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
for k, hits in result['matches'].items():
    print('KEY',k, 'PAGES',len(hits))
    for x in hits[:20]:
        print(x['source_ocr'], ' | '.join(x['matched_lines']))
