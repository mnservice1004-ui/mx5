"""Append readable, linked preparation/principle details to existing indexes."""
from pathlib import Path
import io
import re
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from pypdf import PdfReader
import education_frontmatter as front
from service_content import CATEGORIES, TITLES

W, H = A4
MM = 72 / 25.4


def wrap(text,width,size):
    """Keep part/tool identifiers and numeric tokens intact in detail rows."""
    result=[]
    for paragraph in str(text).split('\n'):
        line=''
        for token in re.findall(r'[A-Za-z0-9][A-Za-z0-9_.:/-]*|.',paragraph):
            if line and stringWidth(line+token,'EduKR',size)>width:
                if token in '.,;:)]}' and len(line)>1:
                    result.append(line[:-1].rstrip());line=line[-1]+token
                else:
                    result.append(line.rstrip());line=token.lstrip()
            else:line+=token
        result.append(line.rstrip())
    return result or ['']


def ranges(numbers):
    values = sorted(set(numbers))
    result = []
    for number in values:
        if result and number == result[-1][-1] + 1:
            result[-1].append(number)
        else:
            result.append([number])
    return [(v[0], str(v[0]) if len(v) == 1 else f'{v[0]}-{v[-1]}') for v in result]


def plan(index, books):
    wanted = set(index['item_ids'])
    selected = [b for b in books if b['id'] in wanted]
    pages, starts = [], {}
    current, y = None, 0

    def new_page(book, continued=False):
        nonlocal current, y
        current = {'book_id': book['id'], 'title': book['title'], 'rows': [],
                   'book_path': book['relative_path'], 'continued': continued,
                   'page': index['total_pages'] + len(pages) + 1}
        pages.append(current)
        y = 687
        return current

    for book in selected:
        new_page(book)
        starts[book['id']] = current['page']
        for category in CATEGORIES:
            rows = book['service_details'][category]
            if not rows:
                message = {'tools': '원문에서 확인한 공구 정보 없음. 공구 불필요를 뜻하지 않습니다.',
                           'parts': '확인된 교환 부품 목록 없음. 실제 상태와 원문 조건을 확인합니다.',
                           'principles': '공통 원칙과 해당 절차의 원문 지시를 확인합니다.',
                           'completion': '원문에서 별도 추출한 완료 확인 없음. 해당 작업 원문을 확인합니다.'}[category]
                label=TITLES[category]+': '+message
                lines=wrap(label,473,8.4)
                height=len(lines)*12+10
                if y-height<62:new_page(book,True)
                current['rows'].append({'kind':'empty_status','category':category,'y':y,
                                       'lines':lines,'height':height})
                y-=height
                continue
            for ordinal, row in enumerate(rows):
                title = (row.get('label','원문 확인')+': ' if category == 'principles' else '') + row['text']
                title_lines = wrap(title, 318, 9.1)
                refs = ranges(row['pages'])
                page_lines, line = [], []
                for target, label in refs:
                    if line and sum(stringWidth(v[1]+'쪽','EduKRB',8.0)+7
                                    for v in line + [(target,label)]) > 140:
                        page_lines.append(line); line = []
                    line.append((target, label))
                if line:
                    page_lines.append(line)
                detail = ' / '.join(row.get('contexts', []))
                source = ', '.join(f"{r['file']} {r['page']}쪽" for r in row.get('source_refs', []))
                purpose = row.get('purpose','')
                scope = row.get('scope_note','')
                specification = row.get('specification','')
                meta = ' / '.join(v for v in [purpose,scope,specification,detail] if v)
                meta += (' · 원문 ' + source if source else '')
                meta_lines = wrap(meta, 318, 7.5) if meta else []
                status = ''
                if category == 'parts' and row.get('label') != '확인 상태':
                    status = ('품번: ' + str(row['part_number']) if row.get('part_number')
                              else '차량용 주문 품번 미확인 / 차대번호로 적용 품번 확인')
                if category == 'tools' and row.get('number', row.get('tool_number')):
                    status = '위 번호는 특수공구 번호입니다. 차량 교환 부품번호가 아닙니다.'
                status_lines = wrap(status, 318, 7.5) if status else []
                height = max(len(title_lines)*13 + len(meta_lines)*10 + len(status_lines)*10 + 16,
                             len(page_lines)*12 + 25)
                heading = ordinal == 0
                required = height + (26 if heading else 0)
                if y - required < 62:
                    new_page(book, True)
                    heading = True
                if heading:
                    current['rows'].append({'kind': 'heading', 'category': category, 'y': y})
                    y -= 26
                current['rows'].append({'kind': 'entry', 'category': category, 'y': y,
                    'height': height, 'text_lines': title_lines, 'meta_lines': meta_lines,
                    'status_lines': status_lines, 'page_lines': page_lines,
                    'label': row.get('label', '원문 확인'), 'evidence': row})
                y -= height
    if len(pages) % 2:
        pages.append({'page': index['total_pages']+len(pages)+1, 'kind': 'binding_note'})
    return {'pages': pages, 'starts': starts, 'original_pages': index['total_pages']}


def render(index, layout, draw_folio):
    stream = io.BytesIO()
    c = canvas.Canvas(stream, pagesize=A4, pageCompression=1)
    links = []
    for page in layout['pages']:
        p = page['page']
        left, right = (28*MM+.75, W-10*MM-.75) if p%2 else (10*MM+.75, W-28*MM-.75)
        width = right-left
        front.tx(c, left, 808, '준비물·정비 원칙 상세 / 원문 확인 자료', 9, True, front.BLUE)
        if page.get('kind') == 'binding_note':
            front.tx(c, left, 765, '검토·실습 메모', 23, True)
            front.para(c, left, 729, '추가 확인한 공구 규격, 차량 적용 품번과 조회 근거를 기록하세요.', width, 10, 16)
            for y in range(674, 100, -32):
                c.setStrokeColor(front.LINE);c.setLineWidth(.5);c.line(left,y,right,y)
            front.tx(c,left,48,'양면 제본을 맞추는 마지막 쪽 / 이 쪽까지 포함하여 인쇄하세요.',8.4,color=front.GRAY)
        else:
            front.tx(c, left, 778, f"{page['book_id']}  {page['title']}", 17, True)
            front.tx(c, left, 756, '본절차와 삽입 참조절차의 정보를 함께 집계했습니다.' + (' / 계속' if page['continued'] else ''), 8.7, color=front.GRAY)
            front.tx(c,left,738,'공통 원칙: 원문 순서 준수 · 부품 보호 · 탈거품 정리 · 교환품/재사용품 구분',8.0)
            front.tx(c,left,724,'원문 일반 주의사항 기준 / 적용 조건·수치·순서는 해당 작업 원문을 확인하세요.',7.5,color=front.GRAY)
            destination = page['book_path']
            label = '이 책자 작업 길잡이 2쪽'
            tw = stringWidth(label,'EduKRB',8.7)
            front.rt(c,right,702,label,8.7,True,front.BLUE)
            links.append(dict(kind='service_book_guide',origin=p-1,
                              rect=[right-tw-2,698,right,714],file=destination,target=1))
            for row in page['rows']:
                y = row['y']
                if row['kind'] == 'heading':
                    c.setFillColor(front.LIGHT);c.roundRect(left,y-8,width,22,3,fill=1,stroke=0)
                    front.tx(c,left+8,y,TITLES[row['category']],10,True,front.BLUE)
                    continue
                if row['kind']=='empty_status':
                    for n,line in enumerate(row['lines']):
                        front.tx(c,left+6,y-n*12,line,8.4,color=front.GRAY)
                    continue
                yy = y
                for line in row['text_lines']:
                    front.tx(c,left+6,yy,line,9.1,True);yy-=13
                for line in row['meta_lines']:
                    front.tx(c,left+6,yy-1,line,7.5,color=front.GRAY);yy-=10
                for line in row['status_lines']:
                    front.tx(c,left+6,yy-1,line,7.5,color=front.AMBER);yy-=10
                front.rt(c,right-5,y,'본문 쪽',7.3,True,front.GRAY)
                for n, line in enumerate(row['page_lines']):
                    xx = left+335
                    for target,label in line:
                        label += '쪽'
                        ww = stringWidth(label,'EduKRB',8.0)
                        front.tx(c,xx,y-14-n*12,label,8.0,True,front.BLUE)
                        links.append(dict(kind='service_evidence',origin=p-1,
                            rect=[xx-1,y-17-n*12,xx+ww+1,y-4-n*12],
                            file=destination,target=target-1))
                        xx += ww+7
                    assert xx <= right+1,(page['book_id'],row['page_lines'],xx,right)
                c.setStrokeColor(front.LINE);c.setLineWidth(.35)
                c.line(left+6,y-row['height']+8,right,y-row['height']+8)
            front.tx(c,left,43,'필수·조건부·권고는 원문 표현을 보존 / 미확인 규격·품번·수량은 추정하지 않습니다.',7.7,color=front.GRAY)
        draw_folio(c,p)
        c.showPage()
    c.save()
    return PdfReader(io.BytesIO(stream.getvalue())), links
