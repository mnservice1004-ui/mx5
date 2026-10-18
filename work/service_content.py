"""Evidence-backed preparation and service-principle data for each booklet.

Only visually verified source records are displayed. Unknown part numbers and
tool sizes remain unknown. Repeated inline references retain all local pages.
"""
from collections import OrderedDict
from pathlib import Path
import copy
import hashlib
import json

ROOT = Path(__file__).resolve().parent
CATEGORIES = ('tools', 'parts', 'principles', 'completion')
TITLES = {'tools': '공구·보호 준비물', 'parts': '교환 부품·적용 조건',
          'principles': '주의·필수·권고', 'completion': '완료 확인'}


def read_evidence(name):
    path = ROOT / name
    if not path.is_file():
        raise FileNotFoundError(f'Missing reviewed service evidence: {path}')
    data = json.loads(path.read_text(encoding='utf-8'))
    for key, record in data['pages'].items():
        assert key == f"{record['file']}#{record['page']}", key
    return data


def load_catalog():
    tools = read_evidence('service_tools_parts.json')
    principles = read_evidence('service_principles.json')
    region_path=ROOT/'service_principle_regions.json'
    if not region_path.is_file():
        raise FileNotFoundError('Reviewed source-fragment geometry is required before building.')
    regions=json.loads(region_path.read_text(encoding='utf-8'))
    assert regions['principles_sha256']==hashlib.sha256((ROOT/'service_principles.json').read_bytes()).hexdigest(),'Principle geometry applies to another source-data version'
    assert not regions.get('unresolved'),('Unresolved source-fragment evidence',regions.get('unresolved'))
    for key,record in principles['pages'].items():
        if record.get('visual_verified') is not True:continue
        geometry=regions['pages'].get(key,{})
        for category in ('principles','completion'):
            for entry in record.get(category,[]):
                matches=[v for v in geometry.get(category,[]) if v['text']==entry['text']]
                assert len(matches)==1,('Missing or ambiguous principle geometry',key,entry['text'])
                entry.update(source_top=matches[0]['source_top'],source_bottom=matches[0]['source_bottom'])
    pages = {}
    for source in (tools, principles):
        for key, value in source['pages'].items():
            if value.get('visual_verified') is not True:
                continue
            record = pages.setdefault(key, {'file': value['file'], 'page': value['page'],
                                            **{c: [] for c in CATEGORIES}})
            for category in CATEGORIES:
                record[category].extend(copy.deepcopy(value.get(category, [])))
    return {'pages': pages, 'common': principles.get('common', []),
            'source_files': ['service_tools_parts.json', 'service_principles.json','service_principle_regions.json'],
            'source_sha256': {name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                              for name in ('service_tools_parts.json','service_principles.json','service_principle_regions.json')}}


def page_key(pm):
    return f"{pm['source_file']}#{pm['source_page']}"


def visible_records(pm,catalog):
    source=catalog['pages'].get(page_key(pm),{})
    top,bottom=pm.get('source_top',0),pm.get('source_bottom',842)
    return {category:[entry for entry in source.get(category,[])
            if entry.get('source_bottom',842)>top and entry.get('source_top',0)<bottom]
            for category in CATEGORIES}


def row_text(category, entry):
    text = entry['text']
    if category == 'parts' and entry.get('condition'):
        text += ' · ' + entry['condition']
    if category == 'tools' and (entry.get('number') or entry.get('tool_number')):
        number = entry.get('number', entry.get('tool_number'))
        if number not in text:
            text += ' (' + number + ')'
    return text


def compile_book(item, catalog):
    all_rows = {category: OrderedDict() for category in CATEGORIES}
    for pm in item['page_meta']:
        if pm['kind'] != 'source':
            continue
        source = visible_records(pm,catalog)
        for category in CATEGORIES:
            for entry in source.get(category, []):
                text = row_text(category, entry)
                label = entry.get('label', entry.get('kind', '원문 확인'))
                key = (label, text)
                rows = all_rows[category]
                if key not in rows:
                    rows[key] = {**copy.deepcopy(entry), 'text': text, 'label': label,
                                 'pages': [], 'source_refs': [], 'contexts': []}
                row = rows[key]
                if pm['local_page'] not in row['pages']:
                    row['pages'].append(pm['local_page'])
                ref = {'file': pm['source_file'], 'page': pm['source_page']}
                if ref not in row['source_refs']:
                    row['source_refs'].append(ref)
                context = '참조절차' if pm.get('active_reference_ids') else '본절차'
                if context not in row['contexts']:
                    row['contexts'].append(context)
    details = {c: list(rows.values()) for c, rows in all_rows.items()}
    # Prefer a required action or main-procedure item in the short opening guide.
    priority = {'위험': -2, '경고': -1, '필수': 0, '필수 교환': 0, '금지': 0, '주의': 1, '유의': 2,
                '조건부': 3, '권고': 4, '원문 원칙': 5}
    summary = {'counts': {c: len(v) for c, v in details.items()},
               'tool_status': '원문 확인 / 세부 규격은 해당 절차 확인',
               'part_number_status': '차량용 주문 품번 미확인 · 차대번호 대조 필요',
               'has_reference_preparation': any('참조절차' in r['contexts']
                   for category in CATEGORIES for r in details[category])}
    for category, values in details.items():
        ordered = sorted(values, key=lambda r: (priority.get(r['label'], 6),
                         '본절차' not in r['contexts'], r['pages'][0]))
        summary[category] = copy.deepcopy(ordered[:3])
        summary[category + '_overflow'] = max(0, len(ordered) - 3)
    if not summary['principles']:
        summary['principles'] = [{'label': '공통 원칙',
            'text': '지침서 순서 준수·탈거품 정리·교환품 구분', 'pages': [],
            'source_refs': [{'file': '13.pdf', 'page': 1}], 'contexts': ['공통 원칙']}]
    item['service_details'] = details
    item['service_summary'] = summary
    item['service_common_principles'] = copy.deepcopy(catalog['common'])
    return item


def signal_for_page(pm, catalog):
    source = visible_records(pm,catalog)
    groups = []
    for entry in source.get('principles', []):
        label = entry.get('label', '원문 확인')
        if label not in groups:
            groups.append(label)
    if source.get('parts') and any('반드시' in p.get('condition', '') or '필수' in p.get('condition', '')
                                   for p in source['parts']):
        if '필수 교환' not in groups and '필수' not in groups:
            groups.append('필수 교환')
    if source.get('completion'):
        groups.append('완료 확인')
    if source.get('tools'):
        groups.append('공구·보호 준비')
    if not groups:
        return {'text': '원문 적용 조건·작업 순서 확인 / 준비물·정비 원칙은 길잡이 2쪽',
                'labels': [], 'source_key': page_key(pm), 'specific': False}
    # A page-level signpost never replaces or changes a source instruction.
    text = ' · '.join(groups) + '  /  아래 원문 지시와 적용 조건을 확인하세요'
    return {'text': text, 'labels': groups, 'source_key': page_key(pm), 'specific': True}
