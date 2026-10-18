"""Independent QA for the normal left-spine, 25 mm binding edition.

No authoring module is imported.  The actual PDF graph, graphics operators,
destinations and archive members are compared with the verified compact edition.
The separate visual QA additionally measures every rendered binding strip.
"""
from __future__ import annotations

from collections import Counter
import copy
import json
from pathlib import Path
import sys
import traceback
import zipfile

from pypdf import PdfReader
from pypdf.generic import ContentStream

from verify_compact_booklets import (contexts, internal_targets, local,
                                    outline_destinations, validate_annotations)
from verify_nested_final import STYLE, close, multiply, rgb
from verify_photo_intro import Canonical, filehash, normalized_text, xobjects

ROOT = Path(__file__).resolve().parent
MM = 72 / 25.4
IDENTITY = [1., 0., 0., 1., 0., 0.]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def xy(matrix, x, y):
    a, b, c, d, e, f = matrix
    return [a*x+c*y+e, b*x+d*y+f]


def rectangle(matrix, rect, widths=False):
    x, y, a, b = rect
    if widths:
        a, b = x+a, y+b
    points = [xy(matrix, xx, yy) for xx, yy in ((x, y), (a, y), (a, b), (x, b))]
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]


def rect_wh(rect):
    return [rect[0], rect[1], rect[2]-rect[0], rect[3]-rect[1]]


def drawings(page, reader):
    """Resolve actual composed placement and stroked paths outside source forms."""
    matrix, color, width, dash, clip = IDENTITY[:], [0., 0., 0.], 1., [], None
    stack, paths, stroked, original = [], [], [], []
    pen = None
    pending_clip = False
    for args, op in ContentStream(page.get_contents(), reader).operations:
        if op == b'q':
            stack.append((matrix[:], color[:], width, dash[:], copy.deepcopy(clip)))
        elif op == b'Q':
            assert stack, 'Unbalanced graphics-state restore'
            matrix, color, width, dash, clip = stack.pop()
        elif op == b'cm':
            matrix = multiply(matrix, list(map(float, args)))
        elif op == b'RG':
            color = list(map(float, args))
        elif op == b'G':
            color = [float(args[0])]*3
        elif op == b'w':
            width = float(args[0])
        elif op == b'd':
            dash = list(map(float, args[0]))
        elif op == b're':
            paths.append(('rect', rectangle(matrix, list(map(float, args)), widths=True)))
        elif op == b'm':
            pen = xy(matrix, *map(float, args))
        elif op == b'l':
            end = xy(matrix, *map(float, args))
            if pen is not None:
                paths.append(('line', pen+end))
            pen = end
        elif op in (b'W', b'W*'):
            pending_clip = True
        elif op == b'n':
            if pending_clip:
                rectangles = [coords for kind, coords in paths if kind == 'rect']
                assert rectangles, 'Unsupported non-rectangular source clipping'
                value = rectangles[-1]
                clip = value if clip is None else [max(clip[0], value[0]), max(clip[1], value[1]),
                                                  min(clip[2], value[2]), min(clip[3], value[3])]
            paths, pen, pending_clip = [], None, False
        elif op in (b'S', b's', b'B', b'B*', b'b', b'b*'):
            scale = (matrix[0]**2+matrix[1]**2)**.5
            for kind, coords in paths:
                stroked.append({'shape': kind, 'coordinates': coords, 'color': color[:],
                                'width': width*scale, 'dash': [v*scale for v in dash]})
            paths, pen = [], None
        elif op in (b'f', b'f*'):
            paths, pen = [], None
        elif op == b'Do' and str(args[0]) == '/Original':
            assert clip is not None, 'Technical source form drawn without clipping'
            original.append({'matrix': matrix[:], 'clip': clip[:]})
    assert not stack, 'Unbalanced graphics-state save'
    assert len(original) <= 1, 'Technical source form drawn repeatedly'
    return original[0] if original else None, stroked


def annotation_rows(reader, page):
    rows = []
    for raw in page.get('/Annots', []):
        a = raw.get_object()
        action = a.get('/A')
        action = action.get_object() if action else None
        target, filename = None, None
        dest = a.get('/Dest')
        if action and action.get('/S') in ('/GoTo', '/GoToR'):
            dest = action.get('/D')
        if dest is not None:
            dest = dest.get_object() if hasattr(dest, 'get_object') else dest
            if action and action.get('/S') == '/GoToR':
                target = int(dest[0])
                f = action['/F']
                if hasattr(f, 'get'):
                    f = f.get('/UF', f.get('/F'))
                filename = str(f).replace('\\', '/')
            else:
                target = reader._get_page_number_by_indirect(dest[0]) if hasattr(dest[0], 'idnum') else int(dest[0])
            view = [str(v) for v in dest[1:]]
        else:
            view = []
        rows.append({'subtype': str(a.get('/Subtype')), 'rect': list(map(float, a['/Rect'])),
                     'action': str(action.get('/S')) if action else None,
                     'target': target, 'file': filename, 'view': view,
                     'uri': str(action.get('/URI')) if action and action.get('/S') == '/URI' else None})
    return rows


def text_without_changes(text, changes, before):
    text = normalized_text(text)
    for change in changes:
        old = normalized_text(change.get('old', change.get('before', '')))
        new = normalized_text(change.get('new', change.get('after', '')))
        value = old if before else new
        if value:
            assert value in text, ('Declared guidance change absent', value)
            text = text.replace(value, '')
    return text


def allowed_changes(entry, binding_page):
    values = binding_page.get('text_changes', [])
    if not values:
        values = [r for r in entry.get('binding_text_changes', []) if r.get('page') == binding_page['page']]
    return values


def bind_geometry(page, binding_page):
    p = binding_page['page']
    matrix = list(map(float, binding_page['matrix']))
    scale = matrix[0]
    assert 0 < scale <= 1.00001 and abs(matrix[3]-scale) < .00001, ('Nonuniform or enlarged binding transform', p, matrix)
    assert abs(matrix[1]) < .00001 and abs(matrix[2]) < .00001, ('Skew/rotation in binding transform', p, matrix)
    assert abs(float(binding_page['scale'])-scale) < .00001, ('Declared binding scale differs', p)
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    inner = [0., 0., 25*MM, height] if p % 2 else [width-25*MM, 0., width, height]
    assert close(inner, binding_page['inner_strip'], .01), ('Wrong binding side or strip width', p, binding_page['inner_strip'])
    limits = [28*MM, width-10*MM] if p % 2 else [10*MM, width-28*MM]
    declared = binding_page['content_limits']
    if len(declared) == 4:
        declared = [declared[0], declared[2]]
    assert close(limits, list(map(float, declared)), .01), ('Wrong inner safety or outer margin limits', p, declared)
    before, after = binding_page.get('ink_bbox_before'), binding_page.get('ink_bbox_after')
    if before is not None and after is not None:
        expected = rectangle(matrix, list(map(float, before)))
        assert close(expected, list(map(float, after)), .02), ('Ink bbox transform stale', p, expected, after)
        assert after[0] >= limits[0]-.15 and after[2] <= limits[1]+.15, ('Declared ink exceeds safe content range', p, after, limits)
        assert after[1] >= -.1 and after[3] <= height+.1, ('Ink outside vertical page', p, after)
    return matrix, limits


def compare_annots(before, after, old_reader, new_reader, matrix, limits):
    a, b = annotation_rows(old_reader, before), annotation_rows(new_reader, after)
    assert len(a) == len(b), ('Annotation count changed', len(a), len(b))
    for old, new in zip(a, b):
        expected = rectangle(matrix, old['rect'])
        assert close(expected, new['rect'], .025), ('Annotation hit area not transformed with visible content', old, new, expected)
        for key in ('subtype', 'action', 'target', 'file', 'view', 'uri'):
            assert old[key] == new[key], ('Annotation navigation changed', key, old, new)
        # Hit areas contain invisible padding; permit that padding in the 3 mm
        # safety area, but never in the actual physical 25 mm binding strip.
        physical = [25*MM, float(after.mediabox.width)] if matrix and new_reader.get_page_number(after) % 2 == 0 else [0., float(after.mediabox.width)-25*MM]
        assert new['rect'][0] >= physical[0]-.02 and new['rect'][2] <= physical[1]+.02, ('Annotation enters binding strip', new, physical)
    return len(b)


def page_operator_check(before, after, old_reader, new_reader, meta, matrix):
    """Body operators remain identical except moved ancestor verticals."""
    old = ContentStream(before.get_contents(), old_reader).operations
    new = ContentStream(after.get_contents(), new_reader).operations
    # pypdf add_transformation encloses, rather than rewriting, each page.
    assert len(new) >= len(old)+3 and new[0][1] == b'q' and new[1][1] == b'cm' and new[-1][1] == b'Q', 'Missing full-page binding transform wrapper'
    assert close(list(map(float, new[1][0])), matrix, .000001), 'Actual outer transform differs from manifest'
    inner = new[2:-1]
    assert len(inner) == len(old), ('Body drawing operator count changed', len(old), len(inner))
    border = meta.get('border_rect')
    depth = len(meta.get('active_reference_ids', []))
    y_pair = border[1::2] if border else None
    allowed = list(range(1, depth)) if depth < 4 else list(range(4, depth))
    relocation_count = 0
    for index, ((a, op), (b, np)) in enumerate(zip(old, inner)):
        assert op == np, ('Body operator changed', index, op, np)
        if a == b:
            continue
        if op not in (b'm', b'l') or not border or not allowed:
            assert close(list(map(float, a)), list(map(float, b)), .00001), ('Body operand changed beyond permitted rail relocation', index, op, a, b)
            continue
        assert len(a) == len(b) == 2 and abs(float(a[1])-float(b[1])) < .00001, ('Rail y changed', index, a, b)
        assert any(abs(float(a[1])-y) < .002 for y in y_pair), ('Changed line is not full-height ancestor rail', index, a)
        assert float(a[0]) < border[0] or float(a[0]) > border[2], ('Changed line is inside current reference frame', index, a)
        relocation_count += 1
    assert relocation_count == 2*len(allowed), ('Ancestor rail relocation count differs', depth, relocation_count, allowed)
    return relocation_count//2


def frame_check_actual(before, after, old_reader, new_reader, meta, matrix):
    depth = len(meta.get('active_reference_ids', []))
    if not depth:
        return []
    _, old_shapes = drawings(before, old_reader)
    _, new_shapes = drawings(after, new_reader)
    border = meta['border_rect']
    full = [r for r in new_shapes if r['shape'] == 'rect' and close(r['coordinates'], rectangle(matrix, border), .01)]
    assert len(full) == 1, ('Current reference frame lost or duplicated', depth, full)
    s = matrix[0]
    color, dash = STYLE[depth]
    assert close(full[0]['color'], rgb(color)) and close(full[0]['dash'], [d*s for d in dash], .005), ('Current frame color/dash changed', depth, full)
    assert abs(full[0]['width']-1.6*s) < .005, ('Current frame width differs after scaling', full)
    ancestors = list(range(1, depth)) if depth < 4 else list(range(4, depth))
    verticals = []
    target_y = sorted([xy(matrix, border[0], border[1])[1], xy(matrix, border[0], border[3])[1]])
    for row in new_shapes:
        if row['shape'] != 'line':
            continue
        x, y, x2, y2 = row['coordinates']
        if abs(x-x2) < .01 and close(sorted([y, y2]), target_y, .01):
            verticals.append(row)
    assert len(verticals) == len(ancestors), ('Visible ancestor rail count changed', depth, verticals)
    for number, ancestor in enumerate(ancestors, 1):
        color, dash = STYLE[ancestor]
        offset = (len(ancestors)-number+1)*4
        expected_x = border[2]+offset if meta['local_page'] % 2 else border[0]-offset
        expected = xy(matrix, expected_x, border[1])[0]
        row = next((r for r in verticals if close(r['color'], rgb(color))), None)
        assert row is not None and abs(row['coordinates'][0]-expected) < .01, ('Ancestor rail not on outer margin', depth, ancestor, expected, row)
        assert close(row['dash'], [d*s for d in dash], .005), ('Ancestor rail dash changed', ancestor, row)
    return ancestors+[depth]


def source_check(before, after, old_reader, new_reader, old_meta, meta, matrix, ca, cb):
    a = before['/Resources']['/XObject']['/Original']
    b = after['/Resources']['/XObject']['/Original']
    assert ca.hash(a) == cb.hash(b), 'Original technical form bytes/images/fonts/resources changed'
    op, _ = drawings(before, old_reader)
    np, _ = drawings(after, new_reader)
    assert op is not None and np is not None, 'Original technical form placement missing'
    expected_matrix = multiply(matrix, op['matrix'])
    expected_clip = rectangle(matrix, op['clip'])
    assert close(expected_matrix, np['matrix'], .00005), ('Technical source not uniformly transformed with page', expected_matrix, np)
    assert close(expected_clip, np['clip'], .001), ('Source clipping changed relative to page transform', expected_clip, np)
    assert close(np['matrix'], meta['transform'], .00005), 'Declared source transform differs from actual composed CTM'
    assert close(rect_wh(np['clip']), meta['clip_rect'], .001), 'Declared source clipping differs from actual PDF'
    assert abs(np['matrix'][0]-np['matrix'][3]) < .000001 and abs(np['matrix'][1])+abs(np['matrix'][2]) < .000001, 'Source image aspect ratio distorted'
    for key in ('kind', 'old_page', 'local_page', 'source_file', 'source_page', 'source_top', 'source_bottom', 'root_copy', 'active_reference_ids'):
        assert meta.get(key) == old_meta.get(key), ('Original segment coverage/order changed', key)
    return frame_check_actual(before, after, old_reader, new_reader, old_meta, matrix)


def check_entry(entry, old, is_booklet):
    old_path, path = Path(old['path']), Path(entry['path'])
    assert old_path.resolve() != path.resolve(), 'Output overwrote previous approved PDF'
    assert filehash(old_path) == old['sha256'], 'Previous approved PDF changed'
    assert filehash(path) == entry['sha256'], 'New PDF differs from final manifest hash'
    assert Path(entry['source_path']).resolve() == old_path.resolve() and entry['source_sha256'] == old['sha256'], 'Wrong baseline PDF or baseline hash'
    before, after = PdfReader(old_path), PdfReader(path)
    assert len(before.pages) == len(after.pages) == entry['total_pages'], 'Page count changed during binding revision'
    assert len(after.pages) % 2 == 0, 'Booklet or index has odd duplex page count'
    assert all(abs(float(p.mediabox.width)-595.2755905511812) < .1 and abs(float(p.mediabox.height)-841.8897637795277) < .1 for p in after.pages), 'Page size no longer A4'
    preferences = after.trailer['/Root']['/ViewerPreferences']
    assert preferences.get('/PrintScaling') == '/None', 'PDF print defaults no longer preserve actual size'
    assert preferences.get('/Duplex') == '/DuplexFlipLongEdge', 'PDF duplex default does not use the long edge'
    assert preferences.get('/Direction') == '/L2R', 'PDF reading direction no longer matches normal left-spine books'
    assert after.trailer['/Root'].get('/PageLayout') == '/TwoPageRight', 'Odd-page right-hand spread layout lost'
    old_outline, new_outline = outline_destinations(before), outline_destinations(after)
    assert old_outline == new_outline, 'Bookmark titles/order/destinations changed'
    bpages = entry['binding_pages']
    assert [p['page'] for p in bpages] == list(range(1, len(after.pages)+1)), 'Binding metadata does not cover every page exactly once'
    ca, cb, counts = Canonical(), Canonical(), Counter()
    old_meta = {p['local_page']: p for p in old.get('page_meta', [])}
    new_meta = {p['local_page']: p for p in entry.get('page_meta', [])}
    assert set(old_meta) == set(new_meta), 'Technical body page coverage changed'
    checks = []
    for binding in bpages:
        p = binding['page']
        left, right = before.pages[p-1], after.pages[p-1]
        matrix, limits = bind_geometry(right, binding)
        changes = allowed_changes(entry, binding)
        assert text_without_changes(left.extract_text(), changes, True) == text_without_changes(right.extract_text(), changes, False), ('Visible text changed outside approved binding guidance', p)
        counts['annotation_hit_areas_transformed'] += compare_annots(left, right, before, after, matrix, limits)
        # Every original cover/component bitmap and its font resources survive.
        old_images = Counter(ca.hash(obj) for _, obj in xobjects(left['/Resources']) if obj.get('/Subtype') == '/Image')
        new_images = Counter(cb.hash(obj) for _, obj in xobjects(right['/Resources']) if obj.get('/Subtype') == '/Image')
        assert old_images == new_images, ('Source images or bitmap resources changed', p)
        old_fonts = {ca.hash(v) for v in left['/Resources'].get('/Font', {}).values()}
        new_fonts = {cb.hash(v) for v in right['/Resources'].get('/Font', {}).values()}
        assert old_fonts <= new_fonts, ('Original page fonts removed', p)
        shown = None
        if p in old_meta:
            om, nm = old_meta[p], new_meta[p]
            relocated = page_operator_check(left, right, before, after, om, matrix)
            counts['ancestor_rails_moved_outward'] += relocated
            if om['kind'] == 'source':
                shown = source_check(left, right, before, after, om, nm, matrix, ca, cb)
                counts['technical_forms_preserved'] += 1
                depth = len(contexts(entry, p))
                counts[f'depth_{depth}_pages'] += 1
                if depth:
                    counts['reference_pages'] += 1
                    parent = contexts(entry, p)[-1]
                    target = local(entry, parent['return_page'])-1
                    assert target in internal_targets(after, right), ('Immediate parent return destination changed', p, target)
                    counts['parent_return_targets_valid'] += 1
            else:
                counts['notices_preserved'] += 1
        counts['pages_uniformly_reflowed'] += 1
        checks.append({'page': p, 'scale': matrix[0], 'matrix': matrix, 'side': 'left' if p % 2 else 'right',
                       'source_form_unchanged': True if p in old_meta and old_meta[p]['kind'] == 'source' else None,
                       'shown_reference_lines': shown})
    if is_booklet:
        for key in ('sections', 'reference_events', 'local_reference_events', 'front_pages', 'body_pages', 'page_map'):
            assert entry.get(key) == old.get(key), ('Procedure/reference/navigation metadata changed', key)
        assert entry['front_pages'] == 2 and 2 in internal_targets(after, after.pages[0]), 'Cover/body start links changed'
        guide_targets = internal_targets(after, after.pages[1])
        guide_text = normalized_text(after.pages[1].extract_text())
        for section in entry['sections']:
            assert local(entry, section['original_start'])-1 in guide_targets, 'Main guide destination changed'
            assert normalized_text(section['procedure_display']) in guide_text, 'Main guide label removed'
            counts['guide_main_procedure_links'] += 1
        for event in entry['reference_events']:
            origin, start, ret = [local(entry, event[k]) for k in ('origin_page', 'first_inserted_page', 'return_page')]
            assert start-1 in internal_targets(after, after.pages[origin-1]), ('Reference entry target changed', event)
            counts['child_entry_return_pairs'] += 1
        counts['covers_preserved'] += 1
        counts['guide_pages'] += 1
        counts['booklet_pages'] += len(after.pages)
        counts['booklet_bookmarks_valid'] += len(new_outline)
    else:
        for key in ('descriptors', 'item_details', 'transfer_counts', 'item_ids'):
            assert entry.get(key) == old.get(key), ('Detailed master-index rows changed', key)
        counts['master_pages'] += len(after.pages)
        counts['master_bookmarks_valid'] += len(new_outline)
    total, internal, remotes = validate_annotations(after)
    counts['annotations_valid'] += total
    counts['internal_links_valid'] += internal
    counts['remote_links_valid'] += len(remotes)
    return {'id': entry.get('id', entry.get('filename', path.name)), 'path': str(path), 'pages': len(after.pages),
            'checks': checks, 'totals': dict(counts), 'remote_links': remotes}, counts, after


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT/'binding_booklets_manifest.json'
    manifest, prior = read(path), read(ROOT/'compact_booklets_manifest.json')
    old_items = {i['id']: i for i in prior['items']}
    old_indexes = {i['relative_path']: i for i in prior['indexes']}
    assert len(manifest['items']) == 30 and {i['id'] for i in manifest['items']} == set(old_items), 'Complete set of 30 booklets missing'
    assert len(manifest['indexes']) == 3, 'Complete set of three master indexes missing'
    assert len(manifest['bundles']) == 3, 'Complete set of three ZIP deliverables missing'
    config = manifest['binding']
    assert config['spine'] == 'left' and config['turn_direction'] == 'right-to-left' and config['duplex'] == 'long-edge', 'Binding direction or duplex configuration wrong'
    assert [config[k] for k in ('inner_strip_mm', 'inner_buffer_mm', 'outer_margin_mm')] == [25, 3, 10], 'Binding width or safety spacing configuration wrong'
    report = {'status': 'passed', 'items': [], 'indexes': [], 'bundles': [], 'failures': []}
    totals, readers = Counter(), {}
    all_entries = manifest['items']+manifest['indexes']
    final_paths = {Path(e['path']).resolve(): e for e in all_entries}
    for kind, entries in [('items', manifest['items']), ('indexes', manifest['indexes'])]:
        for entry in entries:
            key = entry.get('id', entry['relative_path'])
            old = old_items[key] if kind == 'items' else old_indexes[entry['relative_path']]
            try:
                row, counts, reader = check_entry(entry, old, kind == 'items')
                report[kind].append(row)
                totals.update(counts)
                readers[Path(entry['path']).resolve()] = reader
                print(f"{key}: PASS, {row['pages']} pages", flush=True)
            except Exception as error:
                report['failures'].append({'id': key, 'error': str(error), 'traceback': traceback.format_exc()})
                print(f'{key}: FAIL, {error}', flush=True)
    for entry in all_entries:
        path = Path(entry['path']).resolve()
        if path not in readers:
            continue
        try:
            _, _, remotes = validate_annotations(readers[path])
            for remote in remotes:
                target = (path.parent/remote['filename']).resolve()
                assert target in final_paths and target.is_file(), ('Cross-PDF destination missing', entry.get('id'), remote)
                target_reader = readers.get(target) or PdfReader(target)
                assert 0 <= remote['target'] < len(target_reader.pages), ('Cross-PDF page invalid', remote)
        except Exception as error:
            report['failures'].append({'remote': str(path), 'error': str(error), 'traceback': traceback.format_exc()})
    for bundle in manifest['bundles']:
        try:
            path = Path(bundle['path'])
            assert filehash(path) == bundle['sha256'] and path.stat().st_size == bundle['bytes'], 'ZIP hash/size differs from final manifest'
            if '프런트' in path.name:
                subset = [i for i in manifest['items'] if i['part'] == 7]+[manifest['indexes'][1]]
            elif '리어' in path.name:
                subset = [i for i in manifest['items'] if i['part'] == 8]+[manifest['indexes'][2]]
            else:
                subset = all_entries
            with zipfile.ZipFile(path) as archive:
                assert archive.testzip() is None, 'ZIP CRC error'
                names = archive.namelist()
                assert len(names) == len(set(names)) == len(subset) == bundle['files'], 'ZIP member count mismatch'
                assert set(names) == {i['relative_path'] for i in subset}, 'ZIP paths or PDF set mismatch'
                for entry in subset:
                    assert archive.read(entry['relative_path']) == Path(entry['path']).read_bytes(), ('ZIP member differs from final PDF', entry['relative_path'])
            report['bundles'].append({'path': str(path), 'files': len(subset), 'crc_passed': True, 'member_bytes_identical': True})
            print(f'ZIP: PASS, {len(subset)} PDFs', flush=True)
        except Exception as error:
            report['failures'].append({'bundle': bundle['path'], 'error': str(error), 'traceback': traceback.format_exc()})
    if len(report['items']) == 30 and len(report['indexes']) == 3:
        for field, expected in [('technical_forms_preserved', 921), ('notices_preserved', 9), ('covers_preserved', 30),
                                ('reference_pages', 484), ('parent_return_targets_valid', 484), ('guide_pages', 30),
                                ('guide_main_procedure_links', 149), ('child_entry_return_pairs', 150),
                                ('booklet_pages', 1006), ('master_pages', 86), ('booklet_bookmarks_valid', 417),
                                ('master_bookmarks_valid', 221), ('ancestor_rails_moved_outward', 212),
                                ('annotations_valid', 4255), ('annotation_hit_areas_transformed', 4255),
                                ('internal_links_valid', 2634), ('remote_links_valid', 1621),
                                ('pages_uniformly_reflowed', 1092)]:
            if totals[field] != expected:
                report['failures'].append({'aggregate': field, 'expected': expected, 'actual': totals[field]})
    report['totals'] = dict(totals)
    report['status'] = 'failed' if report['failures'] else 'passed'
    (ROOT/'binding_qa_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'status': report['status'], 'totals': report['totals'], 'failures': report['failures']}, ensure_ascii=False), flush=True)
    return 1 if report['failures'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
