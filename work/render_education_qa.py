"""Independent actual-render QA for the education booklet edition."""
from pathlib import Path
from collections import Counter
import io, json, hashlib, math
import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader
from pypdf.generic import ContentStream
from reportlab.pdfbase.pdfmetrics import stringWidth

ROOT=Path(__file__).resolve().parent
DIR=ROOT/'education_final_visual_qa'
MM=72/25.4
FONT=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf',13)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def render(doc,index,scale=1):
    page=doc[index];bitmap=page.render(scale=scale)
    result=bitmap.to_pil().convert('RGB').copy()
    bitmap.close();page.close();return result


def margin_check(image,width,p):
    ink=np.asarray(image).min(axis=2)<245
    counts=ink.sum(axis=0)
    x=(np.arange(image.width)+.5)*width/image.width
    inner=x if p%2 else width-x
    outer=width-x if p%2 else x
    used=counts>0
    return dict(inner25=int(counts[inner<25*MM].sum()),
                inner28=int(counts[inner<28*MM].sum()),
                outer10=int(counts[outer<10*MM].sum()),
                min_inner_mm=float(inner[used].min()/MM)if used.any()else None,
                min_outer_mm=float(outer[used].min()/MM)if used.any()else None)


def folio_check(page,p):
    font=None;size=None;tm=None;found=[]
    for args,op in ContentStream(page.get_contents(),page.pdf).operations:
        if op==b'Tf':font=str(args[0]);size=float(args[1])
        if op==b'Tm':tm=[float(v)for v in args]
        if op==b'Tj':
            value=args[0];value=value.decode('latin1')if isinstance(value,bytes)else str(value)
            if value==str(p)and size==11 and tm:
                resource=page['/Resources']['/Font'][font].get_object()
                if str(resource.get('/BaseFont',''))=='/Helvetica-Bold':
                    width=stringWidth(str(p),'Helvetica-Bold',11)
                    expected_x=float(page.mediabox.width)-12*MM-width if p%2 else 12*MM
                    found.append(dict(font=font,size=size,x=tm[4],y=tm[5],
                                      x_error=tm[4]-expected_x,y_error=tm[5]-8*MM))
    return dict(matches=found,passed=len(found)==1 and abs(found[0]['x_error'])<.001 and abs(found[0]['y_error'])<.001)


def rect_mask(shape,width,height,rect,inset=0):
    h,w=shape
    x0,y0,x1,y1=rect
    px0=max(0,int(math.ceil((x0+inset)*w/width)))
    px1=min(w,int(math.floor((x1-inset)*w/width)))
    py0=max(0,int(math.ceil((height-y1+inset)*h/height)))
    py1=min(h,int(math.floor((height-y0-inset)*h/height)))
    mask=np.zeros((h,w),dtype=bool)
    if px1>px0 and py1>py0:mask[py0:py1,px0:px1]=True
    return mask


def protected_compare(current,previous,pm,desc,width,height):
    a=np.asarray(current,dtype=np.int16);b=np.asarray(previous,dtype=np.int16)
    assert a.shape==b.shape
    x,y,w,h=pm['clip_rect']
    mask=rect_mask(a.shape[:2],width,height,[x,y,x+w,y+h],inset=1.6)
    # Both editions put two vector tabs over source page margin space.
    for tab in desc.get('tabs',[]):
        mask &= ~rect_mask(a.shape[:2],width,height,tab['rect'],inset=-2)
    if pm.get('call_strip_rect'):
        mask &= ~rect_mask(a.shape[:2],width,height,pm['call_strip_rect'],inset=-2)
    diff=np.max(np.abs(a-b),axis=2)
    return dict(pixels_checked=int(mask.sum()),changed_gt4=int(((diff>4)&mask).sum()),
                changed_gt16=int(((diff>16)&mask).sum()),max_difference=int(diff[mask].max())if mask.any()else 0)


def contacts(cards):
    paths=[];cw,ch=300,447;cols=4;per=20
    for offset in range(0,len(cards),per):
        portion=cards[offset:offset+per];rows=math.ceil(len(portion)/cols)
        sheet=Image.new('RGB',(cols*cw,rows*ch),'#DCE4E8')
        for n,card in enumerate(portion):
            tile=Image.new('RGB',(cw,ch),'white')
            ImageDraw.Draw(tile).text((7,4),card['label'],font=FONT,fill='#18374D')
            with Image.open(card['png'])as im:
                im=im.convert('RGB');im.thumbnail((cw-12,ch-27));tile.paste(im,((cw-im.width)//2,25))
            sheet.paste(tile,((n%cols)*cw,(n//cols)*ch))
        path=DIR/f'all_body_{offset//per+1:03d}.png';sheet.save(path)
        paths.append(str(path))
    return paths


def focus_selection(manifest):
    selected={('01',3):'main_general',('01',5):'entry1',('01',9):'return_and_entry',
              ('03',5):'missing_source_notice',('05',138):'reference2',
              ('07-05',7):'reference3',('07-07',7):'reference4',
              ('07-12',20):'reference5',('07-12',19):'entry5',
              ('07-12',24):'return4to3',('01',6):'reference1'}
    for item in manifest['items']:
        if item['id']not in('03','05'):continue
        for desc in item['education_pages']:
            if desc['kind']=='source'and not desc['header_text']['depth']:
                title=desc['header_text']['current_title']
                if ' / 'in title:
                    selected.setdefault((item['id'],desc['page']),'mixed_component_'+item['id'])
                    if sum(key[0]==item['id']and val.startswith('mixed')for key,val in selected.items())>=2:break
    return selected


def main():
    DIR.mkdir(exist_ok=True)
    manifest=json.loads((ROOT/'education_booklets_manifest.json').read_text(encoding='utf8'))
    prior=json.loads((ROOT/'folio_booklets_manifest.json').read_text(encoding='utf8'))
    old={row['relative_path']:row for row in prior['items']+prior['indexes']}
    focus=focus_selection(manifest)
    margins=[];folios=[];protected=[];cards=[];focused=[];sources=[];errors=[];files=[]
    for item in manifest['items']+manifest['indexes']:
        path=Path(item['path']);code=item.get('id','master_'+path.stem[:2]);isbook='id'in item
        reader=PdfReader(path);doc=pdfium.PdfDocument(path)
        source_item=old[item['relative_path']];prior_reader=PdfReader(source_item['path']);prior_doc=pdfium.PdfDocument(source_item['path'])
        pm_by={p['local_page']:p for p in item.get('page_meta',[])}
        desc_by={p['page']:p for p in item.get('education_pages',[])}
        for number,page in enumerate(reader.pages,1):
            image=render(doc,number-1,1.0)
            width,height=float(page.mediabox.width),float(page.mediabox.height)
            m=margin_check(image,width,number);margins.append(dict(id=code,page=number,**m))
            for key in ('inner25','inner28','outer10'):
                if m[key]:errors.append(dict(id=code,page=number,check='margin_'+key,ink_pixels=m[key]))
            f=folio_check(page,number);folios.append(dict(id=code,page=number,**f))
            if not f['passed']:errors.append(dict(id=code,page=number,check='fixed_folio',detail=f))
            pm=pm_by.get(number);desc=desc_by.get(number,{})
            if pm:
                png=DIR/f'{code}_page_{number:03d}.png';image.save(png)
                depth=len(pm.get('active_reference_ids',[]))
                cards.append(dict(id=code,page=number,kind=pm['kind'],png=str(png),label=f'{code} p{number} | '+(f'ref {depth}'if depth else'main')))
                if pm['kind']=='source':
                    now_form=page['/Resources']['/XObject']['/Original'].get_object();old_form=prior_reader.pages[number-1]['/Resources']['/XObject']['/Original'].get_object()
                    source_ok=now_form.get_data()==old_form.get_data()
                    sources.append(dict(id=code,page=number,form_content_equal=source_ok))
                    if not source_ok:errors.append(dict(id=code,page=number,check='Original_form_bytes'))
                    comparison=protected_compare(image,render(prior_doc,number-1,1.0),pm,desc,width,height)
                    protected.append(dict(id=code,page=number,**comparison))
                    if comparison['changed_gt16']:
                        errors.append(dict(id=code,page=number,check='protected_source_render',**comparison))
                    clip=pm['clip_rect'];top=clip[1]+clip[3];bottom=clip[1]
                    if top>760 or bottom<82:errors.append(dict(id=code,page=number,check='source_overlay_vertical_clearance',clip=clip))
                if (code,number)in focus:
                    png=DIR/f'focus_{code}_page_{number:03d}.png';render(doc,number-1,1.65).save(png)
                    focused.append(dict(id=code,page=number,reason=focus[(code,number)],png=str(png)))
        files.append(dict(id=code,path=str(path),sha256=sha(path),pages=len(reader.pages)))
        doc.close();prior_doc.close()
        print(f'{code}: {len(reader.pages)} pages rendered, total issues {len(errors)}',flush=True)
    sheets=contacts(cards)
    report=dict(status='rendered_pending_manual_review',files=files,total_pages=len(margins),body_pages=len(cards),
                source_form_pages=len(sources),protected_source_pages=len(protected),
                margin_failures=[e for e in errors if e['check'].startswith('margin')],
                fixed_folio_failures=[e for e in errors if e['check']=='fixed_folio'],
                source_raster_failures=[e for e in errors if e['check']=='protected_source_render'],
                source_form_failures=[e for e in errors if e['check']=='Original_form_bytes'],
                minimum_inner_mm=min(v['min_inner_mm']for v in margins if v['min_inner_mm']is not None),
                minimum_outer_mm=min(v['min_outer_mm']for v in margins if v['min_outer_mm']is not None),
                margins=margins,folios=folios,protected_source_checks=protected,
                errors=errors,body_contacts=sheets,focused_pages=focused,
                manual_review=dict(agent_contact_sheets=[],root_contact_sheets=[],focused_pages=[]))
    (ROOT/'education_visual_qa.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(f'Complete: {len(margins)} pages, {len(cards)} body cards, {len(sheets)} contacts, {len(errors)} issues',flush=True)


if __name__=='__main__':main()
