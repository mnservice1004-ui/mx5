"""Map reviewed principle summaries to original top-origin PDF coordinates.

The reviewed source JSON remains unchanged. Only source pages appearing as
partial clips need OCR regions; full-page-only records can retain full bounds.
The resulting JSON is an evidence-location aid, not a new service instruction.
"""
from pathlib import Path
from difflib import SequenceMatcher
import argparse
import hashlib
import json
import re


ROOT = Path(__file__).resolve().parents[1]
CATEGORIES = ('principles', 'completion')


def norm(text):
    value = re.sub(r'[^0-9a-z가-힣]', '', text.lower())
    return value.replace('배리언트', '베리언트').replace('작용한다', '착용한다')


def boxes_for(source, page):
    stem = f'{Path(source).stem}__{page:02}'
    raw = json.loads((ROOT/'work'/'ocr_bounds'/f'{stem}.json').read_text(encoding='utf-8'))
    scale = 841 / raw['image_height']
    result = []
    for box in raw['boxes']:
        top = box['y']*scale
        bottom = (box['y']+box['height'])*scale
        if top < 60 or bottom > 800:
            continue
        result.append({'text': box['text'], 'source_top': top,
                       'source_bottom': bottom, 'norm': norm(box['text'])})
    return sorted(result, key=lambda b: b['source_top'])


def located(summary, boxes):
    wanted = norm(summary)
    # These paraphrases have unmistakable source anchors. Include continuation
    # lines where a single instruction wraps across more than one OCR box.
    anchors = []
    if '금속성물질' in wanted:
        indexes = [i for i,b in enumerate(boxes) if '금속성물질' in b['norm']]
        if indexes:
            i = indexes[0]
            anchors = [boxes[i]]
            if '제거' not in boxes[i]['norm'] and i+1 < len(boxes):
                anchors.append(boxes[i+1])
    elif '개인보호장비' in wanted:
        anchors = [b for b in boxes if '개인보호장비' in b['norm'] and '참조' not in b['norm']][:1]
    elif '고전압차단절차' in wanted:
        anchors = [b for b in boxes if '고전압차단절차' in b['norm'] and '반드시' in b['norm']][:1]
    elif '보호테이프' in wanted and '리무버' in wanted:
        anchors = [b for b in boxes if '보호테이프' in b['norm'] and '리무버' in b['norm']][:1]
    elif 'ota대상제어기' in wanted and '업데이트' in wanted:
        anchors = [b for b in boxes if 'ota대상제어기' in b['norm'] and '업데이트' in b['norm']][:1]
    elif all(word in wanted for word in ('고장코드', '베리언트', '초기화')):
        # One reviewed summary describes three linked PTG replacement actions.
        anchors = [b for b in boxes if
                   ('고장코드' in b['norm'] and '반드시' in b['norm']) or
                   ('베리언트코딩' in b['norm'] and '신품' in b['norm']) or
                   ('초기화과정' in b['norm'] and '신품' in b['norm'])]
        if len(anchors) != 3:
            anchors = []
    if anchors:
        return dict(source_top=round(min(b['source_top'] for b in anchors), 3),
                    source_bottom=round(max(b['source_bottom'] for b in anchors), 3),
                    method='unambiguous OCR instruction anchors',
                    matched_text=[b['text'] for b in anchors], score=1.0)

    candidates = []
    for start in range(len(boxes)):
        for count in (1,2,3):
            chunk = boxes[start:start+count]
            if len(chunk) != count or chunk[-1]['source_bottom']-chunk[0]['source_top'] > 100:
                continue
            actual = ''.join(b['norm'] for b in chunk)
            score = SequenceMatcher(None, wanted, actual, autojunk=False).ratio()
            candidates.append((score, chunk))
    candidates.sort(key=lambda value:value[0], reverse=True)
    if not candidates or candidates[0][0] < .64:
        return None
    score, chunk = candidates[0]
    # A close competing candidate at a different vertical position is ambiguous.
    alternate = next((other for other in candidates[1:]
                      if other[1][-1]['source_bottom'] < chunk[0]['source_top'] or
                      other[1][0]['source_top'] > chunk[-1]['source_bottom']), None)
    if alternate and alternate[0] > score-.06:
        return None
    return dict(source_top=round(chunk[0]['source_top'],3),
                source_bottom=round(chunk[-1]['source_bottom'],3),
                method='unique normalized OCR phrase match',
                matched_text=[b['text'] for b in chunk], score=round(score,4))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT/'work'/'service_principle_regions.json')
    args = parser.parse_args()
    source = ROOT/'work'/'service_principles.json'
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    reviewed = json.loads(source.read_text(encoding='utf-8'))
    baseline = json.loads((ROOT/'work'/'folio_booklets_manifest.json').read_text(encoding='utf-8'))
    partial = {f"{p['source_file']}#{p['source_page']}" for book in baseline['items']
               for p in book['page_meta'] if p['kind']=='source' and
               (p.get('source_top',0)>0 or p.get('source_bottom',841)<841)}
    result = dict(schema_version=1, principles_sha256=before, pages={}, unresolved=[],
                  coordinate_system='original PDF points, top origin, source height 841',
                  partial_source_pages=len(partial))
    totals = dict(partial_rows=0, located_partial_rows=0, fullpage_rows=0)
    for key, page in reviewed['pages'].items():
        target = {category:[] for category in CATEGORIES}
        boxes = boxes_for(page['file'], page['page']) if key in partial else []
        for category in CATEGORIES:
            for entry in page.get(category,[]):
                if key in partial:
                    totals['partial_rows'] += 1
                    location = located(entry['text'], boxes)
                    if location is None:
                        result['unresolved'].append(dict(source_key=key,category=category,text=entry['text']))
                        continue
                    totals['located_partial_rows'] += 1
                else:
                    location = dict(source_top=0.0,source_bottom=841.0,
                                    method='full-page-only source; no partial evidence destination')
                    totals['fullpage_rows'] += 1
                target[category].append(dict(text=entry['text'],**location))
        result['pages'][key] = target
    result['totals'] = totals
    assert before == hashlib.sha256(source.read_bytes()).hexdigest(), 'Reviewed source changed'
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(**totals,unresolved=len(result['unresolved'])),ensure_ascii=False))
    for entry in result['unresolved']:
        print(json.dumps(entry,ensure_ascii=False))
    if result['unresolved']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
