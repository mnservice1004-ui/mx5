"""Independent read-only validation of final nested-reference booklets.

Checks the delivered PDF operators, resources, destinations and archives against
the prior photo/introduction edition.  Authoring modules are not imported.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path
import sys
import zipfile

from pypdf import PdfReader
from pypdf.generic import ContentStream

from verify_photo_intro import (
    Canonical, annotations, count_outlines, filehash, normalized_text,
    outlines, remote_links, xobjects,
)

ROOT = Path(__file__).resolve().parent
OLD_GUIDANCE = '참조는 빨간 테두리 안에서 읽고, 표시된 복귀 쪽에서 원래 순서를 이어갑니다.'
NEW_GUIDANCE = '참조는 단계별 테두리 안에서 읽고, 표시된 복귀 쪽에서 원래 순서를 이어갑니다.'
STYLE = {
    1: ('B52D32', []), 2: ('235F9A', []), 3: ('6B478F', []),
    4: ('00756C', [9, 3.5]), 5: ('3F4853', [2, 3]),
}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def close(left, right, tolerance=.002):
    return len(left) == len(right) and all(abs(a-b) <= tolerance for a, b in zip(left, right))


def rgb(hexcode):
    return [int(hexcode[n:n+2], 16)/255 for n in (0, 2, 4)]


def actual_placement(page, reader):
    """Extract technical source placement directly from the page stream."""
    operations = ContentStream(page.get_contents(), reader).operations
    matches = []
    for index, (args, op) in enumerate(operations):
        if op == b'Do' and args and str(args[0]) == '/Original':
            nearby = operations[max(0, index-12):index]
            matrices = [list(map(float, a)) for a, o in nearby if o == b'cm']
            clips = [list(map(float, a)) for a, o in nearby if o == b're']
            assert matrices and clips and any(o in (b'W', b'W*') for _, o in nearby), 'Unclipped Original form'
            matches.append({'matrix': matrices[-1], 'clip': clips[-1]})
    assert len(matches) <= 1, 'Repeated technical source draw'
    return matches[0] if matches else None


def stroke_paths(page, reader):
    """Read vector shapes and actual stroke/dash state outside the source form."""
    color, width, dash = [0., 0., 0.], 1., []
    stack, pending, result = [], [], []
    pen = None
    for args, op in ContentStream(page.get_contents(), reader).operations:
        if op == b'q':
            stack.append((color[:], width, dash[:]))
        elif op == b'Q' and stack:
            color, width, dash = stack.pop()
        elif op == b'RG':
            color = list(map(float, args))
        elif op == b'G':
            color = [float(args[0])]*3
        elif op == b'w':
            width = float(args[0])
        elif op == b'd':
            dash = list(map(float, args[0]))
        elif op == b're':
            pending.append(('rect', list(map(float, args))))
        elif op == b'm':
            pen = list(map(float, args))
        elif op == b'l':
            endpoint = list(map(float, args))
            if pen is not None:
                pending.append(('line', pen+endpoint))
            pen = endpoint
        elif op in (b'S', b's', b'B', b'B*', b'b', b'b*'):
            for shape, coords in pending:
                result.append(dict(shape=shape, coordinates=coords,
                                   color=color[:], width=width, dash=dash[:]))
            pending, pen = [], None
        elif op in (b'n', b'f', b'f*'):
            pending, pen = [], None
    return result


def frame_check(page, reader, meta, depth):
    """Count full-height reference lines, not declarations in the manifest."""
    clip = meta['clip_rect']
    border = meta.get('border_rect', [clip[0]-4, clip[1]-4,
                                    clip[0]+clip[2]+4, clip[1]+clip[3]+4])
    brect = [border[0], border[1], border[2]-border[0], border[3]-border[1]]
    actual = stroke_paths(page, reader)
    full_rect = [p for p in actual if p['shape']=='rect' and close(p['coordinates'], brect)]
    verticals = []
    for p in actual:
        if p['shape'] != 'line':
            continue
        x, y, x2, y2 = p['coordinates']
        if (abs(x-x2) < .002 and close(sorted([y,y2]), [border[1],border[3]])
                and (x < clip[0] or x > clip[0]+clip[2])):
            verticals.append(p)
    if depth == 0:
        assert not full_rect and not verticals, ('Unexpected reference border', full_rect, verticals)
        return []
    assert len(full_rect)==1, ('Current reference needs exactly one surrounding border', full_rect)
    expected_ancestors = list(range(1,depth)) if depth<4 else list(range(4,depth))
    assert len(verticals)==len(expected_ancestors), ('Wrong ancestor line count', depth, verticals)
    current = full_rect[0]
    hexcode, dash = STYLE[depth]
    assert close(current['color'], rgb(hexcode)) and close(current['dash'], dash), ('Wrong current border style', depth, current)
    assert abs(current['width']-1.6)<.002, ('Current border width', current)
    remaining = verticals[:]
    for ancestor in expected_ancestors:
        hexcode, dash = STYLE[ancestor]
        found = next((p for p in remaining if close(p['color'], rgb(hexcode)) and close(p['dash'], dash)), None)
        assert found is not None, ('Ancestor style not drawn', ancestor, verticals)
        remaining.remove(found)
    assert not remaining
    return expected_ancestors+[depth]


def multiply(left, right):
    a,b,c,d,e,f = left
    g,h,i,j,k,l = right
    return [a*g+c*h,b*g+d*h,a*i+c*j,b*i+d*j,a*k+c*l+e,b*k+d*l+f]


def image_placements(page, reader, canon):
    """Record image identity and composed CTM, ignoring renamed resource keys."""
    matrix = [1.,0.,0.,1.,0.,0.]
    stack, result = [], []
    objects = page['/Resources'].get('/XObject', {})
    for args, op in ContentStream(page.get_contents(), reader).operations:
        if op==b'q':
            stack.append(matrix[:])
        elif op==b'Q' and stack:
            matrix=stack.pop()
        elif op==b'cm':
            matrix=multiply(matrix,list(map(float,args)))
        elif op==b'Do' and str(args[0]) in objects:
            obj=objects[str(args[0])].get_object()
            if obj.get('/Subtype')=='/Image':
                result.append({'object':canon.hash(obj),'matrix':matrix[:]})
    return result


def cover_check(src, new, item, photo_item, canon_old, canon_new, manifest):
    left, right = src.pages[0], new.pages[0]
    old_text=normalized_text(left.extract_text())
    new_text=normalized_text(right.extract_text())
    old_g=normalized_text(manifest.get('old_cover_guidance', OLD_GUIDANCE))
    new_g=normalized_text(manifest.get('new_cover_guidance', NEW_GUIDANCE))
    assert old_text.count(old_g)==1 and new_text.count(new_g)==1, 'Cover guidance replacement missing or duplicated'
    assert old_text.replace(old_g,'')==new_text.replace(new_g,''), 'Other cover text changed'
    assert image_placements(left,src,canon_old)==image_placements(right,new,canon_new), 'Cover image or exact placement changed'
    old_images=collections.Counter(canon_old.hash(obj) for _,obj in xobjects(left['/Resources']) if obj.get('/Subtype')=='/Image')
    new_images=collections.Counter(canon_new.hash(obj) for _,obj in xobjects(right['/Resources']) if obj.get('/Subtype')=='/Image')
    assert old_images and old_images==new_images, 'Cover embedded image resources changed'
    old_fonts={canon_old.hash(v) for v in left['/Resources'].get('/Font',{}).values()}
    new_fonts={canon_new.hash(v) for v in right['/Resources'].get('/Font',{}).values()}
    assert old_fonts<=new_fonts, 'Original cover fonts lost'
    asset=photo_item['asset']
    for text in [item['title'],asset['intro'],asset['caption'],asset['image_kind']] + [v for s in asset['workflow'] for v in [s['title'],s.get('description','')]]:
        assert normalized_text(text) in new_text, ('Missing cover introduction',text)
    return sum(old_images.values())


def descriptor_candidates(desc):
    """Find source item labels within a rebuilt index, independent of layout."""
    result=[]
    def visit(value, key=''):
        if isinstance(value,dict):
            for k,v in value.items():
                if k in ('title','component','procedure','procedure_display','reference_id','label') and isinstance(v,str):
                    result.append(v)
                elif isinstance(v,(dict,list)):
                    visit(v,k)
        elif isinstance(value,list):
            for v in value:
                if isinstance(v,str) and key=='rows' and not v.endswith('.pdf'):
                    result.append(v)
                else:
                    visit(v,key)
    visit(desc)
    return [t for t in result if t]


def validate_item(item, photo_item, old_item, manifest):
    before, after=Path(item['source_path']),Path(item['path'])
    assert before==Path(photo_item['path']), 'Wrong prior edition selected'
    assert filehash(before)==photo_item['sha256']==item['source_sha256'], 'Original photo booklet changed'
    assert filehash(after)==item['sha256'], 'Delivered file hash differs from manifest'
    src,new=PdfReader(before),PdfReader(after)
    assert len(src.pages)==len(new.pages)==item['total_pages'] and len(new.pages)%2==0, 'Page count or duplex parity changed'
    assert item['front_pages']==photo_item['front_pages']==old_item['front_pages'], 'Index/body starts changed'
    old_canon,new_canon=Canonical(),Canonical()
    totals=collections.Counter()
    totals['cover_images_preserved']=cover_check(src,new,item,photo_item,old_canon,new_canon,manifest)
    old_meta={m['local_page']:m for m in old_item['page_meta']}
    declared={m['local_page']:m for m in item['page_meta']}
    assert set(declared)==set(old_meta), 'Technical page order or coverage changed'
    for p,meta in old_meta.items():
        for key in ('kind','old_page','local_page','source_file','source_page','source_top','source_bottom','root_copy','clip_rect','transform','active_reference_ids','call_strip_rect'):
            assert meta.get(key)==declared[p].get(key), ('Source fragment metadata changed',p,key)
    events=old_item['local_reference_events']
    if 'local_reference_events' in item:
        assert item['local_reference_events']==events, 'Reference insertion/return metadata changed'
    rows=[]
    descriptors=item.get('front_descriptors',old_item['front_descriptors'])
    assert descriptors==old_item['front_descriptors'], 'Source index rows changed'
    allowed=set(item.get('allowedchanged_front_kinds',[]))
    for index,(left,right) in enumerate(zip(src.pages,new.pages)):
        p=index+1
        for key in (set(left.keys())|set(right.keys()))-{'/Parent','/Resources','/Contents','/Annots'}:
            assert old_canon.hash(left.get(key))==new_canon.hash(right.get(key)), ('Page attributes changed',p,key)
        before_ann=annotations(src,left,old_canon)
        after_ann=annotations(new,right,new_canon)
        assert before_ann==after_ann[:len(before_ann)], ('Existing annotation/destination/click area changed',p)
        extra_ann=after_ann[len(before_ann):]
        expected_ctx=sorted([e for e in events if e['first_inserted_page']<=p<e['return_page']],key=lambda e:e['return_page']-e['first_inserted_page'],reverse=True)
        expected_extra=1 if expected_ctx and p in old_meta and old_meta[p]['kind']=='source' else 0
        assert len(extra_ann)==expected_extra, ('Unexpected new annotation count',p,len(extra_ann),expected_extra)
        if expected_extra:
            assert extra_ann[0].get('/Subtype')=='/Link' and extra_ann[0].get('/Dest',[None])[0]==expected_ctx[-1]['return_page']-1, ('New emphasized parent return link is incorrect',p,extra_ann)
            totals['emphasized_parent_return_links']+=1
        for annot in after_ann:
            if annot.get('/Subtype')!='/Link':
                continue
            if annot in before_ann:
                totals['links_preserved']+=1
            rect=annot.get('/Rect')
            assert rect and 0<=rect[0]<rect[2]<=float(right.mediabox.width)+.02 and 0<=rect[1]<rect[3]<=float(right.mediabox.height)+.02, ('Link outside page',p,rect)
            target=annot.get('/Dest',annot.get('/A',{}).get('/D'))
            if isinstance(target,list):
                assert isinstance(target[0],int) and 0<=target[0]<len(new.pages), ('Internal link invalid',p,target)
        totals['annotations_preserved']+=len(before_ann)
        if p==1:
            continue
        if p<=item['front_pages']:
            desc=descriptors[index]
            if desc['kind'] not in allowed:
                assert left.get_contents().get_data()==right.get_contents().get_data(), ('Unapproved front-matter content edit',p,desc['kind'])
                assert old_canon.hash(left['/Resources'])==new_canon.hash(right['/Resources']), ('Unapproved front-matter resources edit',p)
                totals['unchanged_front_pages']+=1
            else:
                extracted=normalized_text(right.extract_text())
                old_extracted=normalized_text(left.extract_text())
                for text in descriptor_candidates(desc):
                    if normalized_text(text) in old_extracted:
                        assert normalized_text(text) in extracted, ('Index label disappeared',p,text)
                if desc['kind']=='reference_index':
                    # The printed dictionary contains group headings and start
                    # page lists, while the row data also holds hidden events.
                    # Compare every genuinely printed data line exactly.
                    old_lines=left.extract_text().splitlines()
                    for text in old_lines[3:-2]:
                        assert normalized_text(text) in extracted, ('Printed reference-index row changed',p,text)
                totals['updated_front_pages']+=1
            continue
        if p in old_meta:
            meta=old_meta[p]
            if meta['kind']=='source':
                left_form=left['/Resources']['/XObject']['/Original']
                right_form=right['/Resources']['/XObject']['/Original']
                assert old_canon.hash(left_form)==new_canon.hash(right_form), ('Technical diagram/text/resources changed',p)
                old_place,new_place=actual_placement(left,src),actual_placement(right,new)
                assert old_place and new_place and close(old_place['clip'],new_place['clip']) and close(old_place['matrix'],new_place['matrix']), ('Technical clip or scale changed',p)
                assert close(meta['clip_rect'],new_place['clip']) and close(meta['transform'],new_place['matrix']), ('Technical placement disagrees with original',p)
                ctx=sorted([e for e in events if e['first_inserted_page']<=p<e['return_page']],key=lambda e:e['return_page']-e['first_inserted_page'],reverse=True)
                assert [e['reference_id'] for e in ctx]==meta['active_reference_ids'], ('Actual reference nesting mismatch',p)
                depth=len(ctx)
                shown=frame_check(right,new,meta,depth)
                text=normalized_text(right.extract_text())
                if depth:
                    assert f'참조{depth}단계' in text or f'{depth}차참조' in text, ('Current depth label missing',p,depth)
                    assert f'표시선{len(shown)}개' in text, ('Visible line count label missing',p,len(shown))
                    parent=ctx[-1]
                    assert f'{parent["return_page"]}쪽' in text and parent['reference_id'] in text, ('Immediate parent return guidance missing',p,parent)
                    # The original return link on this very page must still lead
                    # to the immediate parent, not merely to the outermost one.
                    assert any(a.get('/Dest',[None])[0]==parent['return_page']-1 for a in after_ann), ('Immediate parent return link missing',p)
                    totals['reference_pages']+=1
                totals[f'depth_{depth}_pages']+=1
                totals['technical_forms_preserved']+=1
                rows.append({'page':p,'depth':depth,'shown_lines':shown,'original_form_unchanged':True,'clip_scale_unchanged':True,'immediate_parent_return_page':ctx[-1]['return_page'] if ctx else None})
            else:
                # Missing-source notices carry no original maintenance content;
                # their supplied explanation must survive a wrapper redraw.
                for marker in ('참조 원문 미수록','실제 참조절차가 제공 자료에 없습니다.'):
                    if normalized_text(marker) in normalized_text(left.extract_text()):
                        assert normalized_text(marker) in normalized_text(right.extract_text()), ('Missing-source warning lost',p)
                totals['notices_preserved']+=1
        else:
            assert left.get_contents().get_data()==right.get_contents().get_data(), ('End binding blank changed',p)
            assert old_canon.hash(left['/Resources'])==new_canon.hash(right['/Resources']), ('End blank resources changed',p)
            totals['unchanged_binding_pages']+=1
    before_outline,after_outline=outlines(src),outlines(new)
    assert before_outline==after_outline, 'Bookmark hierarchy/sequence/destinations changed'
    totals['bookmarks_preserved']=count_outlines(before_outline)
    return {'id':item['id'],'pages':len(new.pages),'totals':dict(totals),'technical_page_checks':rows},totals


def main():
    path=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'nested_final_manifest.json'
    report_path=ROOT/'nested_final_qa_report.json'
    manifest=read(path)
    photo=read(ROOT/'photo_intro_manifest.json')
    old=read(ROOT/'door_booklets_manifest.json')
    photos={i['id']:i for i in photo['items']}
    originals={i['id']:i for i in old['items']}
    assert len(manifest['items'])==30 and {i['id'] for i in manifest['items']}==set(photos), 'Incomplete 30-booklet edition'
    report={'status':'passed','items':[],'indexes':[],'bundles':[],'failures':[]}
    totals=collections.Counter()
    for item in manifest['items']:
        try:
            record,counts=validate_item(item,photos[item['id']],originals[item['id']],manifest)
            report['items'].append(record)
            totals.update(counts)
            print(f"{item['id']}: PASS, {record['pages']} pages, {counts['technical_forms_preserved']} technical forms, {counts['links_preserved']} links",flush=True)
        except Exception as error:
            report['failures'].append({'id':item['id'],'error':str(error)})
            print(f"{item['id']}: FAIL, {error}",flush=True)
    assert len(manifest['indexes'])==3, 'Missing master index'
    for index in manifest['indexes']:
        try:
            src,dst=Path(index['source_path']),Path(index['path'])
            old_index=next(v for v in photo['indexes'] if Path(v['path'])==src)
            assert filehash(src)==old_index['sha256'], 'Original master index changed'
            assert filehash(dst)==index['sha256'], 'New master index hash mismatch'
            before,after=PdfReader(src),PdfReader(dst)
            assert len(before.pages)==len(after.pages)==index['total_pages'], 'Master index page count changed'
            ca,cb=Canonical(),Canonical()
            allowed=index.get('changed_pages',[])
            for p,(left,right) in enumerate(zip(before.pages,after.pages),1):
                assert annotations(before,left,ca)==annotations(after,right,cb), ('Master index links changed',p)
                if p not in allowed:
                    assert left.get_contents().get_data()==right.get_contents().get_data(), ('Master index rows changed',p)
                    assert ca.hash(left['/Resources'])==cb.hash(right['/Resources']), ('Master index resources changed',p)
            assert outlines(before)==outlines(after), 'Master index bookmarks changed'
            rows=remote_links(dst,after)
            totals['master_index_remote_links']+=len(rows)
            report['indexes'].append({'path':str(dst),'pages':len(after.pages),'remote_links_preserved':len(rows),'all_targets_exist':True})
        except Exception as error:
            report['failures'].append({'index':index['path'],'error':str(error)})
    assert len(manifest['bundles'])==3, 'Missing ZIP bundle'
    for bundle in manifest['bundles']:
        try:
            path=Path(bundle['path'])
            assert filehash(path)==bundle['sha256'] and path.stat().st_size==bundle['bytes'], 'Bundle hash/size mismatch'
            if '프런트' in path.name:
                expected=[r for r in manifest['items'] if r['part']==7]+[manifest['indexes'][1]]
            elif '리어' in path.name:
                expected=[r for r in manifest['items'] if r['part']==8]+[manifest['indexes'][2]]
            else:
                expected=manifest['items']+manifest['indexes']
            with zipfile.ZipFile(path) as archive:
                assert archive.testzip() is None, 'ZIP CRC failure'
                names=archive.namelist()
                assert len(names)==len(set(names))==len(expected)==bundle['files'], 'ZIP count/duplicates mismatch'
                assert set(names)=={r['relative_path'] for r in expected}, 'ZIP filenames incomplete'
                for record in expected:
                    assert archive.read(record['relative_path'])==Path(record['path']).read_bytes(), ('ZIP member differs',record['relative_path'])
            report['bundles'].append({'path':str(path),'files':len(expected),'crc_passed':True,'members_identical':True})
        except Exception as error:
            report['failures'].append({'bundle':bundle['path'],'error':str(error)})
    if not report['failures']:
        for field,expected in (('technical_forms_preserved',921),('reference_pages',484),
                               ('cover_images_preserved',30),('emphasized_parent_return_links',484)):
            if totals[field]!=expected:
                report['failures'].append({'aggregate':field,'expected':expected,'actual':totals[field]})
    report['totals']=dict(totals)
    report['status']='failed' if report['failures'] else 'passed'
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':report['status'],'totals':report['totals'],'failures':report['failures']},ensure_ascii=False),flush=True)
    return 1 if report['failures'] else 0


if __name__=='__main__':
    raise SystemExit(main())
