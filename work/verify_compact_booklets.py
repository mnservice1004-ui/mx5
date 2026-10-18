"""Independent, read-only QA for the compact two-page-frontmatter edition.

The authoring code is deliberately not imported. Technical source objects,
actual placement operators, navigation destinations and ZIP bytes are inspected
from the delivered PDF documents against the prior verified edition.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path
import re
import sys
import traceback
import zipfile

from pypdf import PdfReader
from pypdf.generic import ArrayObject, ContentStream, DictionaryObject, IndirectObject

from verify_photo_intro import Canonical, annotations, count_outlines, filehash, normalized_text, outlines, xobjects
from verify_nested_final import actual_placement, close, frame_check, image_placements

ROOT = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def local(item, global_page):
    return int(global_page) - int(item['original_start']) + 3


def contexts(item, p):
    rows = [e for e in item['reference_events']
            if local(item, e['first_inserted_page']) <= p < local(item, e['return_page'])]
    return sorted(rows, key=lambda e: e['return_page'] - e['first_inserted_page'], reverse=True)


def short_title(item, title):
    for prefix in (item['chapter_title']+' ', '프런트 도어 ', '리어 도어 '):
        if title.startswith(prefix):
            return title[len(prefix):]
    return title


def section_label(item, section):
    if section['component'] in (section['procedure_display'], item['title']):
        return section['procedure_display']
    return short_title(item, section['component']) + ' / ' + section['procedure_display']


def internal_targets(reader, page):
    result = []
    for raw in page.get('/Annots', []):
        ann = raw.get_object()
        if ann.get('/Subtype') != '/Link':
            continue
        action = ann.get('/A')
        if action:
            action = action.get_object()
        dest = ann.get('/Dest', action.get('/D') if action and action.get('/S') == '/GoTo' else None)
        if dest is not None:
            dest = dest.get_object() if isinstance(dest, IndirectObject) else dest
            assert isinstance(dest, (list, ArrayObject)) and len(dest), ('Unsupported internal destination', dest)
            target = reader._get_page_number_by_indirect(dest[0]) if isinstance(dest[0], IndirectObject) else int(dest[0])
            assert target is not None and 0 <= target < len(reader.pages), ('Invalid internal target', target)
            result.append(target)
    return result


def text_fragments(page):
    result = []
    def visit(text, cm, tm, font, size):
        if text.strip():
            result.append({'text': text.strip(), 'x': float(tm[4]), 'y': float(tm[5]), 'size': float(size)})
    page.extract_text(visitor_text=visit)
    return result


def validate_annotations(reader):
    count, internal, remote = 0, 0, []
    for pn, page in enumerate(reader.pages, 1):
        internal += len(internal_targets(reader, page))
        for raw in page.get('/Annots', []):
            a = raw.get_object()
            count += 1
            rect = list(map(float, a['/Rect']))
            assert (0 <= rect[0] < rect[2] <= float(page.mediabox.width) + .02
                    and 0 <= rect[1] < rect[3] <= float(page.mediabox.height) + .02), ('Annotation outside page', pn, rect)
            action = a.get('/A')
            if action:
                action = action.get_object()
                if action.get('/S') == '/GoToR':
                    f = action['/F']
                    if isinstance(f, DictionaryObject):
                        f = f.get('/UF', f.get('/F'))
                    d = action['/D']
                    assert isinstance(d, (list, ArrayObject)) and isinstance(d[0], int), ('Remote destination is not numeric', pn, d)
                    remote.append({'page': pn, 'filename': str(f).replace('\\', '/'), 'target': int(d[0]), 'rect': rect})
    return count, internal, remote


def cover_check(old_reader, reader, item, old_item, ca, cb):
    before, after = old_reader.pages[0], reader.pages[0]
    assert image_placements(before, old_reader, ca) == image_placements(after, reader, cb), 'Cover image placement or image bytes changed'
    old_imgs = collections.Counter(ca.hash(o) for _, o in xobjects(before['/Resources']) if o.get('/Subtype') == '/Image')
    new_imgs = collections.Counter(cb.hash(o) for _, o in xobjects(after['/Resources']) if o.get('/Subtype') == '/Image')
    assert old_imgs == new_imgs and sum(old_imgs.values()) == 1, 'Cover image resources changed'
    text = normalized_text(after.extract_text())
    old_text = normalized_text(before.extract_text())
    old_text = re.sub(r'색인3쪽부터/본문\d+쪽부터/이파일총\d+쪽', '', old_text)
    new_text = re.sub(r'작업길잡이2쪽/본문3쪽부터/이파일총\d+쪽', '', text)
    assert old_text == new_text, 'Cover text outside navigation/page count changed'
    asset = old_item['asset']
    protect = [item['title'], asset['intro'], asset['caption'], asset['image_kind']]
    protect += [v for s in asset['workflow'] for v in [s['title'], s.get('description', '')] if v]
    for value in protect:
        assert normalized_text(value) in text, ('Cover introduction or workflow changed', value)
    assert '본문3쪽' in text and f'총{item["total_pages"]}쪽' in text, 'Cover body page range or total not recalculated'
    assert 2 in internal_targets(reader, after), 'Cover has no link to body first page 3'
    return sum(old_imgs.values())


def outline_destinations(reader):
    flat = []
    def walk(items):
        for entry in items:
            if isinstance(entry, list):
                walk(entry)
            else:
                target = reader.get_destination_page_number(entry)
                assert target is not None and 0 <= target < len(reader.pages), ('Invalid bookmark target', entry.title, target)
                flat.append((entry.title, target))
    walk(reader.outline)
    return flat


def validate_item(item, old_item):
    old_path, new_path = Path(old_item['path']), Path(item['path'])
    assert filehash(old_path) == old_item['sha256'], 'Previous edition file changed'
    assert Path(item['source_path']) == old_path, 'Wrong baseline edition'
    assert item['source_sha256'] == old_item['sha256'], 'Baseline hash mismatch'
    assert filehash(new_path) == item['sha256'], 'Output hash mismatch'
    before, reader = PdfReader(old_path), PdfReader(new_path)
    assert item['front_pages'] == 2, 'Booklet must have exactly two frontmatter pages'
    body_count = int(old_item['body_pages'])
    expected_pages = 2 + body_count + (body_count % 2)
    assert len(reader.pages) == item['total_pages'] == expected_pages, ('Unexpected page count', len(reader.pages), expected_pages)
    assert len(reader.pages) % 2 == 0, 'Booklet duplex page count must be even'
    ca, cb = Canonical(), Canonical()
    totals = collections.Counter()
    totals['covers_preserved'] = cover_check(before, reader, item, old_item, ca, cb)
    assert item['sections'] == old_item['sections'], 'Main procedure entries changed'
    assert item['reference_events'] == old_item['reference_events'], 'Reference insertion or return sequence changed'
    expected_events = []
    for event in item['reference_events']:
        depth = len(contexts(item, local(item, event['first_inserted_page'])))
        expected_events.append({**event,
                                **{key: local(item, event[key]) for key in ('origin_page', 'first_inserted_page', 'return_page')},
                                'nesting_depth': depth})
    assert item['local_reference_events'] == expected_events, 'Local event page numbers or nesting depth stale'
    old_meta = old_item['page_meta']
    new_meta = item['page_meta']
    assert len(new_meta) == len(old_meta) == body_count, 'Source body coverage mismatch'
    assert [p['old_page'] for p in new_meta] == [p['old_page'] for p in old_meta], 'Source page order changed'
    assert [p['local_page'] for p in new_meta] == list(range(3, 3 + body_count)), 'Body pages must start at 3 and be consecutive'
    guide_text = normalized_text(reader.pages[1].extract_text())
    assert '작업길잡이' in guide_text, 'Guide page missing'
    assert '참조' in guide_text and '복귀' in guide_text, 'Reference-return reading rule missing'
    guide_targets = internal_targets(reader, reader.pages[1])
    for s in item['sections']:
        assert normalized_text(s['procedure_display']) in guide_text, ('Main procedure missing from guide', s['procedure_display'])
        assert local(item, s['original_start']) - 1 in guide_targets, ('Guide main procedure target wrong', s['procedure_display'])
        totals['guide_main_procedure_links'] += 1
    technical_checks = []
    for old_pm, pm in zip(old_meta, new_meta):
        p = pm['local_page']
        left, right = before.pages[old_pm['local_page']-1], reader.pages[p-1]
        assert p == local(item, pm['old_page']), ('Global-local mapping wrong', p)
        for key in ('kind', 'old_page', 'source_file', 'source_page', 'source_top', 'source_bottom', 'root_copy', 'active_reference_ids'):
            assert pm.get(key) == old_pm.get(key), ('Source fragment metadata changed', p, key)
        ctx = contexts(item, p)
        assert [e['reference_id'] for e in ctx] == pm.get('active_reference_ids', []), ('Reference context wrong', p)
        depth = len(ctx)
        actual_targets = internal_targets(reader, right)
        text = normalized_text(right.extract_text())
        fragments = text_fragments(right)
        assert any(t['text'] == str(p) and abs(t['y']-26) < .01 and abs(t['size']-11) < .01
                   for t in fragments), ('Printed local footer page number stale', p)
        assert ('길잡이2쪽' in text or '작업길잡이2쪽' in text), ('Stale frontmatter link label', p)
        assert 1 in actual_targets, ('Body lacks guide target page 2', p)
        if pm['kind'] == 'source':
            a_form = left['/Resources']['/XObject']['/Original']
            b_form = right['/Resources']['/XObject']['/Original']
            assert ca.hash(a_form) == cb.hash(b_form), ('Original technical text/diagram/font/image resources changed', p)
            op = actual_placement(left, before)
            np = actual_placement(right, reader)
            assert op and np, ('Original form placement missing', p)
            assert close(op['clip'][1:], np['clip'][1:]), ('Original source clip height/width/y changed', p)
            assert close(op['matrix'][:4] + op['matrix'][5:], np['matrix'][:4] + np['matrix'][5:]), ('Original source scale or y changed', p)
            x = 44 if p % 2 else 21
            assert abs(np['clip'][0] - x) < .002 and abs(np['matrix'][4] - x) < .002, ('Duplex source x incorrect', p, np)
            assert close(np['clip'], pm['clip_rect']) and close(np['matrix'], pm['transform']), ('Declared source placement differs from actual stream', p)
            rectangles = [list(map(float, args)) for args, op in ContentStream(right.get_contents(), reader).operations if op == b're']
            tab_x = float(right.mediabox.width) - 39 if p % 2 else 27
            assert any(close(rect, [tab_x, 715, 12, 69]) for rect in rectangles), ('Duplex outer-margin item tab incorrect', p, tab_x)
            shown = frame_check(right, reader, pm, depth)
            if depth:
                assert f'참조{depth}단계' in text and f'표시선{len(shown)}개' in text, ('Depth or visible line count missing', p, depth)
                parent = ctx[-1]
                return_page = local(item, parent['return_page'])
                assert return_page - 1 in actual_targets, ('Immediate parent return target wrong', p, return_page)
                assert f'{return_page}쪽' in text and parent['reference_id'] in text, ('Immediate parent guidance/page number stale', p)
                for ancestor in ctx:
                    assert local(item, ancestor['return_page']) - 1 in actual_targets, ('Ancestor return link missing', p, ancestor)
                totals['reference_pages'] += 1
                totals['parent_return_targets_valid'] += 1
            calls = [e for e in item['reference_events'] if e['origin_page'] == pm['old_page']]
            for child in calls:
                entry, ret = local(item, child['first_inserted_page']), local(item, child['return_page'])
                assert entry - 1 in actual_targets, ('Child reference entry link stale', p, child)
                assert f'{entry}쪽' in text and f'{ret}쪽' in text, ('Printed child entry or return page stale', p, child)
                totals['child_entry_return_pairs'] += 1
            # Original editorial source provenance may mention old global pages;
            # that is intentional and not a current navigation destination.
            totals['technical_forms_preserved'] += 1
            totals[f'depth_{depth}_pages'] += 1
            technical_checks.append({'page': p, 'global_page': pm['old_page'], 'depth': depth,
                                     'source_form_unchanged': True, 'source_crop_scale_unchanged': True,
                                     'duplex_x': x, 'shown_reference_lines': shown,
                                     'parent_return_page': local(item, ctx[-1]['return_page']) if ctx else None})
        else:
            old_text = normalized_text(left.extract_text())
            for warning in ('참조 원문 미수록', '실제 참조절차가 제공 자료에 없습니다.'):
                if normalized_text(warning) in old_text:
                    assert normalized_text(warning) in text, ('Missing-source technical warning removed', p)
            old_warning = ''.join(t['text'] for t in text_fragments(left) if 250 < t['y'] < 785 and 59 <= t['x'] <= 61)
            new_warning = ''.join(t['text'] for t in fragments if 250 < t['y'] < 785 and 59 <= t['x'] <= 61)
            assert normalized_text(old_warning) == normalized_text(new_warning), ('Missing reference component or explanation changed', p)
            assert p in actual_targets and f'다음{p+1}쪽에서계속' in text, ('Missing-source next-page link or number stale', p)
            totals['notices_preserved'] += 1
    bookmarks = outline_destinations(reader)
    for s in item['sections']:
        assert any(target == local(item, s['original_start'])-1 and
                   normalized_text(s['procedure_display']) in normalized_text(title)
                   for title, target in bookmarks), ('Main procedure bookmark missing or stale', s['procedure_display'])
    for e in item['reference_events']:
        assert any(target == local(item, e['first_inserted_page'])-1 and e['reference_id'] in title
                   and f'복귀 {local(item, e["return_page"])}쪽' in title
                   for title, target in bookmarks), ('Reference bookmark missing or printed return page stale', e['reference_id'], e['first_inserted_page'])
    totals['bookmarks_valid'] += len(bookmarks)
    totals['booklet_pages'] += len(reader.pages)
    totals['guide_pages'] += 1
    totals['binding_blank_pages'] += expected_pages - 2 - body_count
    annotations_count, internals, remotes = validate_annotations(reader)
    totals['booklet_annotations_valid'] += annotations_count
    totals['booklet_internal_links_valid'] += internals
    return {'id': item['id'], 'pages': len(reader.pages), 'totals': dict(totals),
            'remote_links': remotes, 'technical_page_checks': technical_checks}, totals


def validate_remote_files(path, reader, items_by_path, readers):
    count, internal, rows = validate_annotations(reader)
    checked = []
    for row in rows:
        target = (Path(path).parent / row['filename']).resolve()
        assert target.is_file(), ('Missing external PDF', str(path), row['filename'])
        assert target in items_by_path, ('Remote target not in final edition', target)
        if target not in readers:
            readers[target] = PdfReader(target)
        assert 0 <= row['target'] < len(readers[target].pages), ('Remote target page invalid', row)
        checked.append({**row, 'target_id': items_by_path[target].get('id', 'master')})
    return count, internal, checked


def validate_transferred_details(index, reader, subset, old_by_id, remote):
    """Compare moved detailed rows to the prior edition, then inspect the PDF."""
    descriptors = index['descriptors']
    assert len(descriptors) == len(reader.pages), 'Master descriptor coverage incomplete'
    page_text = {p: normalized_text(page.extract_text()) for p, page in enumerate(reader.pages, 1)}
    counts = collections.Counter()
    actual_remote = collections.defaultdict(set)
    for row in remote:
        actual_remote[(row['page'], row['target_id'])].add(row['target'])
    for item in subset:
        rows = [(p, row) for p, descriptor in enumerate(descriptors, 1)
                if descriptor.get('item_id') == item['id']
                for row in descriptor.get('rows', [])]
        assert rows, ('Detailed item rows missing', item['id'])
        main = [(p, r) for p, r in rows if r['kind'] == 'main']
        expected_sections = sorted(item['sections'], key=lambda s: (s['component'], s['procedure_display']))
        assert len(main) == len(expected_sections), ('Detailed main row count wrong', item['id'])
        for (p, row), sec in zip(main, expected_sections):
            label = section_label(item, sec)
            start, end = local(item, sec['original_start']), local(item, sec['original_end'])
            assert (row['file'], row['label'], row['start'], row['end']) == (sec['file'], label, start, end), ('Detailed main row data/order wrong', item['id'], row)
            assert normalized_text(label) in page_text[p] and f'{start}-{end}쪽' in page_text[p], ('Detailed main printed content stale', item['id'], p, row)
            assert start-1 in actual_remote[(p, item['id'])], ('Detailed main actual link stale', item['id'], p)
            counts['transferred_main_rows'] += 1
        refs = [(p, r) for p, r in rows if r['kind'] == 'reference']
        expected_refs = collections.defaultdict(list)
        for event in item['reference_events']:
            expected_refs[event['title']].append(event)
        assert len(refs) == len(expected_refs), ('Detailed reference row count wrong', item['id'])
        for (p, row), (title, events) in zip(refs, sorted(expected_refs.items())):
            events = sorted(events, key=lambda e: e['first_inserted_page'])
            starts = [local(item, e['first_inserted_page']) for e in events]
            assert row['title'] == title and row['starts'] == starts and row['event_ids'] == [e['reference_id'] for e in events], ('Detailed reference data/order wrong', item['id'], row)
            assert normalized_text(short_title(item, title)) in page_text[p], ('Detailed reference printed title missing', item['id'], p)
            number_line = normalized_text('참조 시작: ' + ', '.join(str(n) for n in starts) + '쪽')
            assert number_line in page_text[p], ('Detailed reference printed start list stale', item['id'], p, number_line)
            assert all(start-1 in actual_remote[(p, item['id'])] for start in starts), ('Detailed reference occurrence actual links stale', item['id'], p)
            counts['transferred_reference_titles'] += 1
            counts['transferred_reference_occurrences'] += len(events)
        flows = [(p, r) for p, r in rows if r['kind'] == 'flow']
        expected_flows = sorted(item['reference_events'], key=lambda e: e['origin_page'])
        assert len(flows) == len(expected_flows), ('Detailed flow row count wrong', item['id'])
        for (p, row), event in zip(flows, expected_flows):
            origin, start, ret = [local(item, event[k]) for k in ('origin_page', 'first_inserted_page', 'return_page')]
            depth = 1 + len(contexts(item, origin))
            assert (row['event_id'], row['event_title'], row['origin'], row['start'], row['return_page'], row['depth']) == (event['reference_id'], event['title'], origin, start, ret, depth), ('Detailed flow data/order wrong', item['id'], row)
            printed = f'{depth}차 / 호출 {origin}쪽 → 참조 {start}-{ret-1}쪽 → 복귀 {ret}쪽'
            assert normalized_text(printed) in page_text[p], ('Detailed flow printed page numbers stale', item['id'], p, printed)
            assert all(n-1 in actual_remote[(p, item['id'])] for n in (origin, start, ret)), ('Detailed flow actual destinations stale', item['id'], p, event)
            counts['transferred_flow_rows'] += 1
        missing = [(p, r) for p, r in rows if r['kind'] == 'missing']
        expected_missing = collections.defaultdict(set)
        for descriptor in old_by_id[item['id']]['front_descriptors']:
            if descriptor['kind'] == 'missing_index':
                for title, locations in descriptor['rows']:
                    for rid, g in locations:
                        expected_missing[title].add((rid, local(item, g)))
        assert len(missing) == len(expected_missing), ('Detailed missing-source title count wrong', item['id'])
        for (p, row), (title, locations) in zip(missing, sorted(expected_missing.items())):
            locations = sorted(locations, key=lambda v: (v[1], v[0]))
            expected = [{'reference_id': rid, 'page': n} for rid, n in locations]
            assert row['label'] == title and row['locations'] == expected, ('Detailed missing-source data/order wrong', item['id'], row)
            assert normalized_text(title) in page_text[p], ('Missing-source title not printed', item['id'], p)
            for rid, n in locations:
                assert normalized_text(f'{rid}: {n}쪽') in page_text[p], ('Missing-source location not printed or stale', item['id'], p, rid, n)
            assert all(n-1 in actual_remote[(p, item['id'])] for _, n in locations), ('Missing-source occurrence link stale', item['id'], p)
            counts['transferred_missing_titles'] += 1
            counts['transferred_missing_locations'] += len(locations)
    return counts


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT/'compact_booklets_manifest.json'
    manifest, old = read(path), read(ROOT/'nested_final_manifest.json')
    old_by_id = {i['id']: i for i in old['items']}
    assert len(manifest['items']) == 30 and {i['id'] for i in manifest['items']} == set(old_by_id), 'Incomplete set of 30 booklets'
    report = {'status': 'passed', 'items': [], 'indexes': [], 'bundles': [], 'failures': []}
    totals = collections.Counter()
    paths = {Path(i['path']).resolve(): i for i in manifest['items'] + manifest['indexes']}
    readers = {}
    for item in manifest['items']:
        try:
            row, counts = validate_item(item, old_by_id[item['id']])
            report['items'].append(row)
            totals.update(counts)
            p = Path(item['path']).resolve()
            readers[p] = PdfReader(p)
            _, _, remote = validate_remote_files(p, readers[p], paths, readers)
            row['remote_links'] = remote
            totals['booklet_remote_links_valid'] += len(remote)
            print(f"{item['id']}: PASS, {row['pages']} pages", flush=True)
        except Exception as error:
            report['failures'].append({'id': item['id'], 'error': str(error), 'traceback': traceback.format_exc()})
            print(f"{item['id']}: FAIL, {error}", flush=True)
    assert len(manifest['indexes']) == 3, 'Three master indexes required'
    for index in manifest['indexes']:
        try:
            p = Path(index['path']).resolve()
            assert filehash(p) == index['sha256'], 'Master index hash mismatch'
            reader = PdfReader(p)
            assert len(reader.pages) == index['total_pages'], 'Master index page count mismatch'
            count, internals, remote = validate_remote_files(p, reader, paths, readers)
            bookmarks = outline_destinations(reader)
            text = normalized_text(''.join(page.extract_text() for page in reader.pages))
            subset = [i for i in manifest['items'] if ('07_' not in p.name and '08_' not in p.name)
                      or ('07_' in p.name and i['part'] == 7) or ('08_' in p.name and i['part'] == 8)]
            remote_targets = {(r['target_id'], r['target']) for r in remote}
            for item in subset:
                assert normalized_text(item['title']) in text, ('Booklet missing in master index', item['id'])
                for section in item['sections']:
                    assert normalized_text(section['procedure_display']) in text, ('Main procedure missing from detailed index', item['id'], section['procedure_display'])
                    assert (item['id'], local(item, section['original_start'])-1) in remote_targets, ('Detailed main procedure link stale', item['id'], section['original_start'])
                    totals['master_main_procedures_present'] += 1
                for event in item['reference_events']:
                    assert normalized_text(short_title(item, event['title'])) in text and event['reference_id'] in text, ('Reference procedure missing from master index', item['id'], event)
                    for field in ('origin_page', 'first_inserted_page', 'return_page'):
                        assert (item['id'], local(item, event[field])-1) in remote_targets, ('Master reference/flow link stale', item['id'], field, event[field])
                    totals['master_reference_flow_rows_present'] += 1
            counts = validate_transferred_details(index, reader, subset, old_by_id, remote)
            totals.update(counts)
            totals['master_pages'] += len(reader.pages)
            totals['master_remote_links_valid'] += len(remote)
            report['indexes'].append({'path': str(p), 'pages': len(reader.pages), 'annotations': count,
                                      'internal_links': internals, 'external_links': len(remote), 'bookmarks': len(bookmarks),
                                      'transferred_row_counts': dict(counts)})
            print(f"Master: PASS, {len(reader.pages)} pages, {len(remote)} external links", flush=True)
        except Exception as error:
            report['failures'].append({'index': index['path'], 'error': str(error), 'traceback': traceback.format_exc()})
            print(f'Master: FAIL, {error}', flush=True)
    for item in manifest['items']:
        try:
            index = manifest['indexes'][1 if item['part'] == 7 else 2 if item['part'] == 8 else 0]
            detail_pages = [p for p, d in enumerate(index['descriptors'], 1) if d.get('item_id') == item['id']]
            missing_pages = [p for p, d in enumerate(index['descriptors'], 1) if d.get('item_id') == item['id']
                             and any(r['kind'] == 'missing' for r in d.get('rows', []))]
            assert detail_pages, ('No master detail pages for guide', item['id'])
            reader = readers.get(Path(item['path']).resolve()) or PdfReader(item['path'])
            _, _, remote = validate_annotations(reader)
            index_path = Path(index['path']).resolve()
            on_guide = [(Path(item['path']).parent / r['filename']).resolve() == index_path
                        and r['target'] == detail_pages[0]-1 and r['page'] == 2 for r in remote]
            assert any(on_guide), ('Work guide detailed-index link missing or stale', item['id'], detail_pages[0])
            printed = normalized_text(reader.pages[1].extract_text())
            assert f'이항목상세{detail_pages[0]}쪽' in printed, ('Work guide printed master detail page stale', item['id'])
            totals['guide_master_detail_links_valid'] += 1
            if missing_pages:
                assert any((Path(item['path']).parent / r['filename']).resolve() == index_path
                           and r['target'] == missing_pages[0]-1 and r['page'] == 2 for r in remote), ('Work guide missing-source master link stale', item['id'])
                totals['guide_master_missing_links_valid'] += 1
        except Exception as error:
            report['failures'].append({'guide_master_link': item['id'], 'error': str(error), 'traceback': traceback.format_exc()})
    assert len(manifest['bundles']) == 3, 'Three ZIP bundles required'
    for bundle in manifest['bundles']:
        try:
            p = Path(bundle['path'])
            assert filehash(p) == bundle['sha256'] and p.stat().st_size == bundle['bytes'], 'ZIP hash or size mismatch'
            if '프런트' in p.name:
                expected = [i for i in manifest['items'] if i['part'] == 7] + [manifest['indexes'][1]]
            elif '리어' in p.name:
                expected = [i for i in manifest['items'] if i['part'] == 8] + [manifest['indexes'][2]]
            else:
                expected = manifest['items'] + manifest['indexes']
            with zipfile.ZipFile(p) as archive:
                assert archive.testzip() is None, 'ZIP CRC failed'
                names = archive.namelist()
                assert len(names) == len(set(names)) == len(expected) == bundle['files'], 'ZIP file count mismatch'
                assert set(names) == {i['relative_path'] for i in expected}, 'ZIP names/paths incomplete'
                for item in expected:
                    assert archive.read(item['relative_path']) == Path(item['path']).read_bytes(), ('ZIP file bytes differ', item['relative_path'])
            report['bundles'].append({'path': str(p), 'files': len(expected), 'crc_passed': True, 'member_bytes_identical': True})
            print(f"ZIP: PASS, {len(expected)} PDFs", flush=True)
        except Exception as error:
            report['failures'].append({'bundle': bundle['path'], 'error': str(error), 'traceback': traceback.format_exc()})
    if len(report['items']) == 30:
        for field, expected in [('technical_forms_preserved', 921), ('notices_preserved', 9), ('covers_preserved', 30),
                                ('reference_pages', 484), ('parent_return_targets_valid', 484), ('guide_pages', 30),
                                ('guide_main_procedure_links', 149), ('child_entry_return_pairs', 150),
                                ('guide_master_detail_links_valid', 30), ('booklet_pages', 1006)]:
            if totals[field] != expected:
                report['failures'].append({'aggregate': field, 'expected': expected, 'actual': totals[field]})
    if len(report['indexes']) == 3:
        for field, expected in [('transferred_main_rows', 213), ('transferred_reference_titles', 119),
                                ('transferred_reference_occurrences', 264), ('transferred_flow_rows', 264),
                                ('transferred_missing_titles', 16), ('transferred_missing_locations', 46)]:
            if totals[field] != expected:
                report['failures'].append({'aggregate': field, 'expected': expected, 'actual': totals[field]})
    report['totals'] = dict(totals)
    report['status'] = 'failed' if report['failures'] else 'passed'
    (ROOT/'compact_qa_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': report['status'], 'totals': report['totals'], 'failures': report['failures']}, ensure_ascii=False), flush=True)
    return 1 if report['failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
