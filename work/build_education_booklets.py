"""Source-preserving educational edition, normal duplex left-spine binding."""
from pathlib import Path
from collections import Counter
import argparse, copy, hashlib, io, json, zipfile
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from pypdf import PdfReader, PdfWriter
from pypdf.annotations import Link
from pypdf.generic import (NameObject, DictionaryObject, DecodedStreamObject,
                           ArrayObject, NumberObject, TextStringObject)
import education_frontmatter as front
import education_body_layout as body
import education_index_style as index_style

ROOT = Path(__file__).resolve().parent
PRIOR = ROOT/'folio_booklets_manifest.json'
OUT = ROOT.parent/'outputs'/'작업중_교육교재'
W,H = A4
MM = 72/25.4
GLOBAL = json.loads((ROOT/'booklet_manifest.json').read_text(encoding='utf-8'))
EDUCATION = json.loads((ROOT/'education_structure_recommendation.json').read_text(encoding='utf-8'))

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def local(item, number): return number-item['original_start']+3
def safe(p):
    left,right=(28*MM,W-10*MM) if p%2 else (10*MM,W-28*MM)
    # Include the 1.2pt notice stroke and its raster antialiasing inside the
    # physical binding limits. Source clips and existing frames stay intact.
    return left+1.5,right-1.5
def node(g): return GLOBAL['nodes'][g-GLOBAL['front_pages']-1]
def section(item,g): return next(s for s in reversed(item['sections']) if s['original_start']<=g)
def contexts(item,g):
    return sorted([e for e in item['reference_events'] if e['first_inserted_page']<=g<e['return_page']],
                  key=lambda e:e['return_page']-e['first_inserted_page'],reverse=True)

def folio(c,p):
    c.saveState();c.setFont('Helvetica-Bold',11);c.setFillColor('#18374D')
    if p%2:c.drawRightString(W-12*MM,8*MM,str(p))
    else:c.drawString(12*MM,8*MM,str(p))
    c.restoreState()

def original_command(pm):
    x,y,w,h=pm['clip_rect'];a,b,cc,d,e,f=pm['transform']
    return ('q '+' '.join(f'{v:.12f}' for v in [x,y,w,h])+' re W n '+
            ' '.join(f'{v:.12f}' for v in [a,b,cc,d,e,f])+' cm /Original Do Q')

def notice(c,item,pm):
    p=pm['local_page'];n=node(pm['old_page']);left,right=safe(p);width=right-left
    front.tx(c,left,805,f"UNIT {item['id']}  /  {item['title']}",8.1,True,front.BLUE)
    front.tx(c,left,772,'확인이 필요한 참조 원문',20,True,front.NAVY)
    front.tx(c,left,748,'제공 자료에 없는 절차를 임의로 채우지 않았습니다.',10.5,color=front.GRAY)
    c.setFillColor('#FFF8EE');c.setStrokeColor('#C28B41');c.setLineWidth(1.2)
    c.roundRect(left,190,width,520,6,fill=1,stroke=1)
    y=680
    for row in n['missing']:
        front.tx(c,left+16,y,row['reference_id'],10,True,front.AMBER);y-=25
        for text in front.wrap(row['target_title'],width-32,13,True):
            front.tx(c,left+16,y,text,13,True,front.AMBER);y-=20
        y-=9
        for text in front.wrap(row.get('note',''),width-32,10):
            front.tx(c,left+16,y,text,10,color=front.NAVY);y-=17
        y-=24
    assert y>=220,(item['id'],p,y)
    front.tx(c,left+16,214,'원문 확인 후 표시된 다음 쪽에서 원래 순서를 이어갑니다.',9.6,color=front.NAVY)
    c.setFillColor(front.LIGHT);c.roundRect(left,43,width,39,4,fill=1,stroke=0)
    front.tx(c,left+10,66,f'다음 {p+1}쪽에서 본절차 계속',11,True,front.BLUE)
    front.tx(c,left,34.5,f"원문 {n['file']} · {n['page']}쪽 / 참조 원문 미수록 안내",6.7,color=front.GRAY)
    front.tx(c,right-65,805,'작업 길잡이 2쪽',7.4,True,front.NAVY)
    return dict(links=[dict(kind='guide',origin=p-1,rect=[right-68,798,right,813],target=1),
                      dict(kind='notice_continue',origin=p-1,rect=[left,43,right,82],target=p)],
                missing=copy.deepcopy(n['missing']),kind='notice')

def memo(c,item,p):
    left,right=safe(p);width=right-left
    front.tx(c,left,805,f"UNIT {item['id']}  /  {item['title']}",8.1,True,front.BLUE)
    front.tx(c,left,763,'실습 메모',26,True,front.NAVY)
    front.tx(c,left,735,'관찰한 점, 질문, 다시 확인할 쪽을 기록하세요.',10.5,color=front.GRAY)
    for y,title in [(675,'관찰한 점'),(490,'질문과 확인할 내용'),(305,'다시 확인할 원문과 쪽')]:
        front.tx(c,left,y,title,11,True,front.BLUE)
        c.setStrokeColor('#DCE5E9');c.setLineWidth(.5)
        for offset in (23,49,75,101,127):c.line(left,y-offset,right,y-offset)
    front.tx(c,left,43,'양면 제본을 맞추는 마지막 쪽 / 이 쪽까지 포함해 인쇄하세요.',8.3,color=front.GRAY)
    return dict(kind='binding_memo',links=[],writing_fields=3)

def remote_annotation(writer,record):
    value=DictionaryObject({NameObject('/Type'):NameObject('/Annot'),NameObject('/Subtype'):NameObject('/Link'),
        NameObject('/Rect'):ArrayObject([__import__('pypdf').generic.FloatObject(v) for v in record['rect']]),
        NameObject('/Border'):ArrayObject([NumberObject(0),NumberObject(0),NumberObject(0)]),
        NameObject('/A'):DictionaryObject({NameObject('/S'):NameObject('/GoToR'),
            NameObject('/F'):TextStringObject(record['file']),
            NameObject('/D'):ArrayObject([NumberObject(record['target']),NameObject('/Fit')])})})
    writer.add_annotation(record['origin'],value)

def fix_remote_paths(item,links):
    for row in links:
        if 'file' in row or 'relative_path' in row:
            filename=Path(row.get('file',row.get('relative_path',''))).name
            row['file']='../'+filename
            row['relative_path']=row['file']
    return links

def build_book(original,out):
    item=copy.deepcopy(original);source=Path(original['path']);before=digest(source)
    reader=PdfReader(source);writer=PdfWriter();writer.clone_document_from_reader(reader)
    page_metas={m['local_page']:m for m in item['page_meta']}
    buffer=io.BytesIO();c=canvas.Canvas(buffer,pagesize=A4,pageCompression=1)
    c.setTitle(item['title']+' / 정비교육 교재')
    descriptions=[];links=[]
    for p in range(1,len(reader.pages)+1):
        if p==1:
            cover_links=front.draw_cover(c,item,EDUCATION)
            desc=dict(kind='cover',links=cover_links);links.extend(cover_links)
        elif p==2:
            desc=front.draw_guide(c,item,EDUCATION);desc['kind']='work_guide'
            links.extend(desc['links']);links.extend(desc['remote_links'])
        elif p in page_metas:
            pm=page_metas[p]
            if pm['kind']=='source':
                c._code.append(original_command(pm))
                g=pm['old_page'];ctx=contexts(item,g)
                desc=body.draw_body(c,item,pm,ctx,section(item,g),
                    [e for e in item['reference_events'] if e['origin_page']==g],
                    [e for e in item['reference_events'] if e['return_page']==g],node(g))
                desc['kind']='source';links.extend(desc['links'])
            else:
                desc=notice(c,item,pm);links.extend(desc['links'])
        else:desc=memo(c,item,p)
        folio(c,p);c.showPage();desc['page']=p;descriptions.append(desc)
    c.save();overlay=PdfReader(io.BytesIO(buffer.getvalue()))
    assert len(overlay.pages)==len(reader.pages)
    for p,(page,fresh) in enumerate(zip(writer.pages,overlay.pages),1):
        old_xobjects=page['/Resources'].get('/XObject',DictionaryObject()).get_object()
        original_form=old_xobjects.get('/Original')
        pm=page_metas.get(p)
        fresh_resources=fresh['/Resources'].clone(writer)
        if pm and pm['kind']=='source':
            assert original_form is not None
            if '/XObject' not in fresh_resources:fresh_resources[NameObject('/XObject')]=DictionaryObject()
            fresh_resources['/XObject'][NameObject('/Original')]=original_form
        stream=DecodedStreamObject();stream.set_data(fresh.get_contents().get_data())
        page[NameObject('/Contents')]=writer._add_object(stream)
        page[NameObject('/Resources')]=fresh_resources
        page.pop(NameObject('/Annots'),None)
    links=fix_remote_paths(item,links)
    for link in links:
        assert 0<=link['origin']<len(writer.pages)
        if 'file' in link:remote_annotation(writer,link)
        else:
            assert 0<=link['target']<len(writer.pages)
            writer.add_annotation(link['origin'],Link(rect=link['rect'],target_page_index=link['target']))
    destination=out/item['relative_path'];destination.parent.mkdir(parents=True,exist_ok=True)
    writer.add_metadata({'/Title':item['title']+' / 정비교육 교재 개선본',
        '/Subject':'부품·학습 범위·작업 길잡이 / 본문 큰 제목·현재 작업·참조 및 복귀 패널 / 원문 절차 보존 / 좌측 양면 제본·고정 바깥 쪽번호'})
    with destination.open('wb') as target:writer.write(target)
    assert digest(source)==before
    item.update(path=str(destination),source_path=str(source),source_sha256=before,
                sha256=digest(destination),education_pages=descriptions,
                navigation_links=links,prior_navigation_links=copy.deepcopy(original['navigation_links']))
    item['added_navigation_links']=[r for r in links if r['kind']=='parent_return']
    item['guide_descriptor']=descriptions[1]
    item['education_layout']=dict(source_clip_transform_unchanged=True,header=[760,813],
        footer=[43,82],body_source_forms=sum(m['kind']=='source' for m in item['page_meta']))
    print(f"{item['id']}: {len(writer.pages)} pages / {len(links)} links",flush=True)
    return item

def build_index(original,out):
    item=copy.deepcopy(original);source=Path(item['path']);before=digest(source)
    reader=PdfReader(source);writer=PdfWriter();writer.clone_document_from_reader(reader)
    audits=[index_style.restyle_index_page(page,p,item,writer) for p,page in enumerate(writer.pages,1)]
    destination=out/item['relative_path'];destination.parent.mkdir(parents=True,exist_ok=True)
    writer.add_metadata({'/Title':item['title']+' / 정비교육 교재 종합색인'})
    with destination.open('wb') as target:writer.write(target)
    assert digest(source)==before
    item.update(path=str(destination),source_path=str(source),source_sha256=before,
                sha256=digest(destination),education_index_pages=audits)
    print(f"{item['relative_path']}: {len(writer.pages)} pages unchanged index routes",flush=True)
    return item

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pilot',default=None)
    parser.add_argument('--output-dir',type=Path,help='Separate output folder for a working edition')
    parser.add_argument('--manifest',type=Path,help='Manifest for this working edition')
    args=parser.parse_args()
    prior=json.loads(PRIOR.read_text(encoding='utf-8'))
    is_pilot=args.pilot is not None
    out=args.output_dir or (ROOT/'education_pilot' if is_pilot else OUT)
    protected=[ROOT.parent/'outputs'/'정비매뉴얼_교육교재_개선본',
               ROOT.parent/'outputs'/'정비매뉴얼_좌측제본_쪽번호정렬본']
    if any(out.resolve().is_relative_to(folder.resolve()) for folder in protected):
        parser.error('The preserved edition and baseline folders cannot be used as output.')
    selected=None
    if is_pilot:
        requested=[v.strip() for v in args.pilot.split(',')]
        valid={v['id'] for v in prior['items']}
        if not requested or any(not v or v not in valid for v in requested):
            parser.error('Pilot IDs must be nonempty known booklet IDs, for example 07-02.')
        selected=set(requested)
    name='education_pilot_manifest.json' if is_pilot else 'draft_education_manifest.json'
    manifest_path=args.manifest or ROOT/name
    protected_manifests=[ROOT/'education_booklets_manifest.json',PRIOR,
                         ROOT/'booklet_manifest.json',ROOT/'education_structure_recommendation.json']
    if manifest_path.resolve() in [v.resolve() for v in protected_manifests]:
        parser.error('The source and preserved-edition manifests cannot be overwritten.')
    items=[build_book(item,out) for item in prior['items'] if selected is None or item['id'] in selected]
    indexes=[build_index(item,out) for item in prior['indexes']]
    bundles=[]
    if not is_pilot:
        for label,part in [('전체_30책자',None),('프런트_도어_12책자',7),('리어_도어_12책자',8)]:
            subset=[i for i in items if part is None or i['part']==part]
            index_subset=indexes if part is None else [indexes[1 if part==7 else 2]]
            path=out.parent/f'{out.name}_{label}.zip'
            with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
                for row in subset+index_subset:z.write(row['path'],row['relative_path'])
            bundles.append(dict(path=str(path),files=len(subset)+len(index_subset),bytes=path.stat().st_size,sha256=digest(path)))
    result=copy.deepcopy(prior)
    result.update(items=items,indexes=indexes,bundles=bundles,prior_manifest=str(PRIOR),
        design_reference=json.loads((ROOT.parent/'project.json').read_text(encoding='utf-8'))['design_reference'],
        design_reference_analysis=str(ROOT/'textbook_reference_design.json'),
        education_data=str(ROOT/'education_structure_recommendation.json'),
        edition='정비교육 교재 개선본',booklet_page_count=sum(i['total_pages'] for i in items),
        master_page_count=sum(i['total_pages'] for i in indexes))
    manifest_path.parent.mkdir(parents=True,exist_ok=True)
    manifest_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f"Completed {len(items)} booklets and {len(indexes)} master indexes.",flush=True)

if __name__=='__main__':main()
