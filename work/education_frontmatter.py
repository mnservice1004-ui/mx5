"""Source-preserving educational cover and one-page guide for 30 manuals.

The caller owns canvases, page transitions, document assembly and fixed folios.
All returned link origins/targets are zero based. Printed page numbers are the
existing one-based physical PDF pages. Importing this module writes no files.
"""
from collections import defaultdict
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

W, H = A4
NAVY = '#18374D'
BLUE = '#087F9C'
TEAL = '#008476'
GRAY = '#536873'
LIGHT = '#EAF2F5'
PALE = '#F4F8FA'
LINE = '#CEDDE3'
AMBER = '#8B5B12'
SAFE_REGIONS = {1: (79.37007874015748, 566.9291338582677),
                2: (28.34645669291339, 515.9055118110236)}
STYLE = {
    1: ('#B52D32', (), '1차', '실선 1개'),
    2: ('#235F9A', (), '2차', '실선 2개'),
    3: ('#6B478F', (), '3차', '실선 3개'),
    4: ('#00756C', (9, 3.5), '4차', '긴 점선'),
    5: ('#3F4853', (2, 3), '5차', '긴+짧은 점선'),
}

for name, path in [('EduKR', 'C:/Windows/Fonts/malgun.ttf'),
                   ('EduKRB', 'C:/Windows/Fonts/malgunbd.ttf')]:
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, path))


def tx(c, x, y, text, size=10, bold=False, color=NAVY):
    c.setFillColor(color)
    c.setFont('EduKRB' if bold else 'EduKR', size)
    c.drawString(x, y, str(text).replace('—', '/').replace('–', '-').replace('‑', '-'))


def rt(c, x, y, text, size=10, bold=False, color=NAVY):
    c.setFillColor(color)
    c.setFont('EduKRB' if bold else 'EduKR', size)
    c.drawRightString(x, y, str(text).replace('—', '/').replace('–', '-').replace('‑', '-'))


def wrap(text, width, size=10, bold=False):
    font = 'EduKRB' if bold else 'EduKR'
    rows = []
    for paragraph in str(text).replace('—', '/').replace('–', '-').replace('‑', '-').split('\n'):
        line = ''
        for char in paragraph:
            if line and pdfmetrics.stringWidth(line + char, font, size) > width:
                rows.append(line.rstrip())
                line = char.lstrip()
            else:
                line += char
        rows.append(line.rstrip())
    return rows or ['']


def para(c, x, y, text, width, size=10, leading=15, bold=False, color=NAVY):
    rows = wrap(text, width, size, bold)
    for row in rows:
        tx(c, x, y, row, size, bold, color)
        y -= leading
    return y


def _edu(item, education):
    if education is None:
        return {}
    if education.get('id') == item['id']:
        return education
    data = education.get('items', education)
    if isinstance(data, list):
        return next((v for v in data if v['id'] == item['id']), {})
    return data.get(item['id'], {})


def _pill(c, x, y, text, color=BLUE, fill=LIGHT, size=8.7, pad=9):
    ww = pdfmetrics.stringWidth(text, 'EduKRB', size) + pad*2
    c.setFillColor(fill)
    c.roundRect(x, y-5, ww, 19, 4, fill=1, stroke=0)
    tx(c, x+pad, y, text, size, True, color)
    return ww


def _section_title(c, x, y, label, n=None):
    if n:
        tx(c, x, y, n, 12, True, BLUE)
        tx(c, x+27, y, label, 12, True)
    else:
        tx(c, x, y, label, 12, True)


def _local(item, old):
    return int(item['page_map'][str(old)])


def _missing_rows(item):
    merged = defaultdict(set)
    for desc in item.get('prior_front_descriptors', item.get('front_descriptors', [])):
        if desc['kind'] == 'missing_index':
            for title, locations in desc.get('rows', []):
                for rid, g in locations:
                    merged[title].add((rid, g))
    return [(title, sorted(locs, key=lambda v: (v[1], v[0])))
            for title, locs in sorted(merged.items())]


def _short_component(item, component):
    prefix = item.get('chapter_title', '')
    if prefix and component.startswith(prefix + ' '):
        return component[len(prefix)+1:]
    return component


def draw_cover(c, item, education=None):
    """Draw physical page 1, return cover links; caller draws the folio."""
    e = _edu(item, education)
    a = item['asset']
    left, right = SAFE_REGIONS[1]
    left, right = left+.75, right-.75  # Keep strokes/antialiasing inside the safe region.
    width = right-left
    c.saveState()
    tx(c, left, H-43, '정비교육  /  2025 · G 1.6 T-GDI HEV', 9, True, BLUE)
    c.setStrokeColor(LINE)
    c.setLineWidth(.6)
    c.line(left, H-54, right, H-54)

    tx(c, left, H-82, 'UNIT', 9, True, BLUE)
    tx(c, left-1, H-124, item['id'], 34, True, BLUE)
    title_x = left+113
    titles = wrap(item['title'], right-title_x, 22, True)
    assert len(titles) <= 2, (item['id'], 'cover title', titles)
    for n, row in enumerate(titles):
        tx(c, title_x, H-91-n*29, row, 22, True)
    intro_top = H-152
    intro_lines = wrap(a['intro'], width, 10.2)
    assert len(intro_lines) <= 2, (item['id'], 'intro', intro_lines)
    intro_end = para(c, left, intro_top, a['intro'], width, 10.2, 16)

    image_top = min(658, intro_end-12)
    image_bottom = 429
    image_height = image_top-image_bottom
    assert image_height >= 205, (item['id'], image_height)
    c.setFillColor(PALE)
    c.setStrokeColor(LINE)
    c.roundRect(left, image_bottom, width, image_height, 7, fill=1, stroke=1)
    tx(c, left+13, image_top-18, '부품과 위치를 먼저 확인하세요', 8.7, True, BLUE)
    img = ImageReader(a['image_path'])
    iw, ih = img.getSize()
    maxw, maxh = width-28, image_height-37
    scale = min(maxw/iw, maxh/ih)
    rw, rh = iw*scale, ih*scale
    ix = left+(width-rw)/2
    iy = image_bottom+7+(maxh-rh)/2
    c.drawImage(img, ix, iy, rw, rh, mask='auto')
    cap_lines = wrap(a['caption'], width, 8.2)
    assert len(cap_lines) <= 2, (item['id'], 'caption', cap_lines)
    para(c, left, 416, a['caption'], width, 8.2, 12, color=GRAY)
    tx(c, left, 387, f"그림 출처: 제공 원문 {a['source_file']} · {a['source_page']}쪽", 7.8, color=GRAY)

    scope_label = '이 장에서 확인할 범위' if item['part'] <= 6 else '이 장에서 다루는 내용'
    _section_title(c, left, 362, scope_label)
    # Numbering on these scope cards is deliberately avoided. Mixed-component
    # books are menus, not an instruction to disassemble every listed component.
    workflow = a['workflow']
    rows = []
    for step in workflow:
        titles = wrap(step['title'], 126, 9.5, True)
        descs = wrap(step['description'], width-164, 9.2)
        hh = max(len(titles)*14, len(descs)*14, 18)+10
        rows.append((step, titles, descs, hh))
    total_h = sum(r[3] for r in rows)
    y = 342
    assert y-total_h >= 148, (item['id'], total_h)
    for step, titles, descs, hh in rows:
        c.setFillColor(TEAL)
        c.circle(left+3, y+3, 2.2, fill=1, stroke=0)
        for n, line in enumerate(titles):
            tx(c, left+14, y-n*14, line, 9.5, True)
        for n, line in enumerate(descs):
            tx(c, left+158, y-n*14, line, 9.2)
        c.setStrokeColor(LINE)
        c.setLineWidth(.45)
        c.line(left+14, y-hh+8, right, y-hh+8)
        y -= hh

    # Review questions are explicit reading activities, not substitute service
    # instructions. Keep their entire wording and vary type only above 8.6 pt.
    questions = e.get('review_prompts', [])[:2] or [
        '작업할 본문 항목과 마지막 확인 사항은 어디에 있나요?',
        '참조를 마친 뒤 어느 쪽에서 원래 작업을 이어가나요?']
    review_top = min(145, y-10)
    size, leading = 8.8, 12.5
    qlines = [wrap(q, width-39, size) for q in questions]
    qheight = 22+sum(len(ls)*leading+4 for ls in qlines)+5
    assert review_top-qheight >= 55, (item['id'], 'review', review_top, qheight)
    c.setFillColor(LIGHT)
    c.roundRect(left, review_top-qheight, width, qheight, 6, fill=1, stroke=0)
    tx(c, left+12, review_top-16, '학습 후 확인', 9, True, TEAL)
    yy = review_top-34
    for ls in qlines:
        tx(c, left+12, yy, '·', 9, True, TEAL)
        for line in ls:
            tx(c, left+25, yy, line, size)
            yy -= leading
        yy -= 4

    tx(c, left, 43, '작업 길잡이 2쪽', 8.4, True, BLUE)
    second_x = left+105
    tx(c, second_x, 43, '본문 3쪽부터', 8.4, True, BLUE)
    rt(c, right, 43, f"이 책자 {item['total_pages']}쪽", 8.4, color=GRAY)
    c.restoreState()
    return [dict(kind='cover_guide', origin=0, rect=[left, 38, left+97, 55], target=1),
            dict(kind='cover_body', origin=0, rect=[second_x, 38, second_x+94, 55], target=2)]


def _guide_groups(item):
    groups = []
    for sec in item['sections']:
        if not groups or groups[-1]['component'] != sec['component']:
            groups.append(dict(component=sec['component'], sections=[]))
        groups[-1]['sections'].append(sec)
    return groups


def _draw_legend(c, left, right, y):
    stride = (right-left)/5
    for depth in range(1, 6):
        x = left+(depth-1)*stride
        stages = range(1, depth+1) if depth < 4 else range(4, depth+1)
        for offset, stage in enumerate(stages):
            color, dash, _, _ = STYLE[stage]
            c.saveState()
            c.setStrokeColor(color)
            c.setDash(list(dash))
            c.setLineWidth(1.6 if stage == depth else 1.1)
            c.line(x+5+offset*6, y+4, x+5+offset*6, y+21)
            c.restoreState()
        tx(c, x+29, y+10, STYLE[depth][2], 9, True, STYLE[depth][0])
        tx(c, x+3, y-9, STYLE[depth][3], 8.4, color=GRAY)


def draw_guide(c, item, education=None):
    """Draw physical page 2 and return complete section and master links."""
    e = _edu(item, education)
    left, right = SAFE_REGIONS[2]
    left, right = left+.75, right-.75
    width = right-left
    c.saveState()
    _pill(c, left, H-43, 'WORK GUIDE')
    rt(c, right, H-43, f"{item['id']}  /  {item['title']}", 9, True, BLUE)
    tx(c, left, H-84, '작업 길잡이', 26, True)
    tx(c, left, H-108, '작업할 항목을 고르고, 표시된 쪽에서 시작하세요.', 10.2, color=GRAY)
    c.setStrokeColor(LINE)
    c.setLineWidth(.6)
    c.line(left, H-122, right, H-122)
    prep = e.get('preparation_prompt', '작업할 본문 항목과 원문 주의사항을 먼저 확인하세요.')
    prep_lines = wrap(prep, width-22, 8.8)
    assert len(prep_lines) <= 2, (item['id'], prep_lines)
    prep_h = 13*len(prep_lines)+16
    c.setFillColor(PALE)
    c.roundRect(left, H-132-prep_h, width, prep_h, 5, fill=1, stroke=0)
    para(c, left+11, H-148, prep, width-22, 8.8, 13)
    heading_y = H-132-prep_h-24
    _section_title(c, left, heading_y, '수록 항목과 시작 쪽', '01')
    rt(c, right, heading_y, '본문 3쪽부터', 8.5, True, BLUE)
    ytop = heading_y-27
    links, drawn = [], []
    sections = item['sections']
    if len(sections) <= 8:
        y = ytop
        for ix, sec in enumerate(sections, 1):
            comp = _short_component(item, sec['component'])
            label = sec['procedure_display']
            if sec['component'] not in (item['title'], sec['procedure_display']):
                label = comp+' / '+label
            lines = wrap(label, width-77, 10.4, True)
            row_h = max(30, len(lines)*15+11)
            tx(c, left+1, y, f'{ix:02}', 9, True, BLUE)
            for n, line in enumerate(lines):
                tx(c, left+28, y-n*15, line, 10.4, True)
            dest = _local(item, sec['original_start'])
            rt(c, right-2, y, f'{dest}쪽', 10, True, BLUE)
            links.append(dict(origin=1, rect=[left, y-row_h+9, right, y+12], target=dest-1,
                              kind='procedure', source_file=sec['file']))
            drawn.append(sec['file'])
            c.setStrokeColor(LINE)
            c.setLineWidth(.45)
            c.line(left+28, y-row_h+8, right, y-row_h+8)
            y -= row_h
        work_bottom = y
    else:
        groups = _guide_groups(item)
        col_w = (width-18)/2

        def single(g):
            return len(g['sections']) == 1 and g['component'] == g['sections'][0]['procedure_display']

        def tokens(g):
            result, line, used = [], [], 0
            for sec in g['sections']:
                text = sec['procedure_display']+' '+str(_local(item, sec['original_start']))+'쪽'
                tw = pdfmetrics.stringWidth(text, 'EduKR', 9.1)
                assert tw <= col_w-26, (item['id'], text)
                if line and used+tw+10 > col_w-26:
                    result.append(line)
                    line, used = [], 0
                line.append((sec, text, tw))
                used += tw+10
            if line:
                result.append(line)
            return result

        def groupheight(g):
            title = _short_component(item, g['component'])
            nn = len(wrap(title, col_w-(63 if single(g) else 26), 9.8, True))
            return nn*15+(0 if single(g) else len(tokens(g))*17)+13

        heights = [groupheight(g) for g in groups]
        split = min(range(1, len(groups)), key=lambda k: max(sum(heights[:k]), sum(heights[k:]))) if len(groups)>1 else 1
        tx(c, left, ytop+8, '왼쪽 열을 위에서 아래로 읽은 뒤 오른쪽 열로 이어집니다.', 7.8, color=GRAY)
        bottoms = []
        for col, gg in enumerate((groups[:split], groups[split:])):
            x, y = left+col*(col_w+18), ytop-13
            for g in gg:
                title = _short_component(item, g['component'])
                ls = wrap(title, col_w-(63 if single(g) else 26), 9.8, True)
                start_y = y
                ordn = sections.index(g['sections'][0])+1
                tx(c, x, y, f'{ordn:02}', 8.4, True, BLUE)
                for line in ls:
                    tx(c, x+25, y, line, 9.8, True)
                    y -= 15
                if single(g):
                    sec = g['sections'][0]
                    dest = _local(item, sec['original_start'])
                    rt(c, x+col_w, start_y, f'{dest}쪽', 9, True, BLUE)
                    links.append(dict(origin=1, rect=[x+22, y-2, x+col_w, start_y+12], target=dest-1,
                                      kind='procedure', source_file=sec['file']))
                    drawn.append(sec['file'])
                else:
                    for row in tokens(g):
                        xx = x+25
                        for sec, text, tw in row:
                            tx(c, xx, y, text, 9.1)
                            links.append(dict(origin=1, rect=[xx, y-5, xx+tw, y+12], target=_local(item, sec['original_start'])-1,
                                              kind='procedure', source_file=sec['file']))
                            drawn.append(sec['file'])
                            xx += tw+10
                        y -= 17
                c.setStrokeColor(LINE)
                c.setLineWidth(.45)
                c.line(x+25, y+2, x+col_w, y+2)
                y -= 13
            bottoms.append(y)
        work_bottom = min(bottoms)

    assert work_bottom >= 329, (item['id'], 'work_bottom', work_bottom)
    # Short single-component guides have room for useful learning outcomes.
    # Dense menu-style guides retain every route and omit this optional panel.
    objective_rows = []
    if work_bottom >= 455:
        objectives = e.get('learning_objectives', [])[:2] or [
            '대상 부품과 본문 항목을 연결해 필요한 작업을 찾습니다.',
            ('참조 시작과 복귀 쪽을 확인하며 읽는 흐름을 이어갑니다.' if item['reference_events']
             else '각 항목의 그림과 주의사항을 원문에서 함께 확인합니다.')]
        objective_rows = [wrap(v, width-43, 9.3) for v in objectives]
        panel_h = 30+sum(len(v)*14+6 for v in objective_rows)
        panel_top = work_bottom-22
        assert panel_top-panel_h >= 326, (item['id'], 'objectives', panel_h)
        c.setFillColor(PALE)
        c.roundRect(left, panel_top-panel_h, width, panel_h, 6, fill=1, stroke=0)
        tx(c, left+12, panel_top-18, '학습 초점', 10, True, TEAL)
        yy = panel_top-37
        for rows in objective_rows:
            tx(c, left+12, yy, '·', 9.3, True, TEAL)
            for row in rows:
                tx(c, left+25, yy, row, 9.3)
                yy -= 14
            yy -= 6
    _section_title(c, left, 305, '함께 읽는 참조절차', '02')
    refnames = sorted({ev['title'] for ev in item['reference_events']})
    names = ' · '.join(refnames) if refnames else '이 항목에는 펼쳐 넣은 다른 절차가 없습니다.'
    ref_lines = wrap(names, width, 9.2)
    assert len(ref_lines) <= 3, (item['id'], 'reference names', ref_lines)
    para(c, left, 286, names, width, 9.2, 14, color=NAVY if refnames else GRAY)

    _section_title(c, left, 233, '참조 깊이와 복귀 읽기', '03')
    _draw_legend(c, left, right, 203)
    tx(c, left, 176, '4·5차는 1·2·3차 선을 생략합니다. 5차는 4차 긴 점선과 5차 짧은 점선을 함께 표시합니다.', 8.0, color=GRAY)
    c.setFillColor(LIGHT)
    c.roundRect(left, 130, width, 34, 5, fill=1, stroke=0)
    tx(c, left+11, 150, '읽는 순서', 8.7, True, TEAL)
    tx(c, left+11, 137, '본문 → 표시된 참조절차 → 하단의 부모 복귀 쪽 → 원래 다음 단계', 9)

    hint = item.get('master_hint', {})
    first = hint.get('first_page')
    label = hint.get('title') or '종합색인'
    master_text = '상세 찾아보기  /  '+label+(f' {first}쪽' if first else '')
    tx(c, left, 111, master_text, 8.8, True, BLUE)
    remote = []
    if hint.get('relative_path') and first:
        remote.append(dict(origin=1, rect=[left, 105, right, 124], file=hint['relative_path'],
                           relative_path=hint['relative_path'], target=first-1, kind='master_details'))
    missing = _missing_rows(item)
    if missing:
        missing_pages = hint.get('missing_pages', [])
        ptext = ' / 종합색인 '+', '.join(map(str, missing_pages))+'쪽' if missing_pages else ''
        text = f'원문 미수록 참조 {len(missing)}종: 본문 안내와 종합색인에서 확인'+ptext
        mlines = wrap(text, width, 8.4)
        assert len(mlines) <= 2, (item['id'], 'missing', mlines)
        para(c, left, 91, text, width, 8.4, 12, True, AMBER)
        if hint.get('relative_path') and missing_pages:
            remote.append(dict(origin=1, rect=[left, 91-len(mlines)*12+3, right, 101], file=hint['relative_path'],
                               relative_path=hint['relative_path'], target=missing_pages[0]-1, kind='master_missing'))
    else:
        tx(c, left, 91, '지금 읽는 참조를 마치면 돌아갈 쪽번호를 본문 하단에서 확인하세요.', 8.6, color=GRAY)
    tx(c, left, 57, '항목 이름·그림은 원문 기준 / 실제 작업은 본문의 순서·조건·주의사항을 따릅니다.', 7.9, color=GRAY)
    tx(c, left, 43, 'A4 · 실제 크기 100% · 양면 · 긴 쪽 넘김', 8.1, color=GRAY)
    rt(c, right, 43, '쪽번호 = 이 PDF의 실제 쪽', 8.1, color=GRAY)
    c.restoreState()
    assert drawn == [sec['file'] for sec in sections], (item['id'], drawn)
    return dict(links=links, remote_links=remote, section_files=drawn, section_count=len(drawn),
                reference_names=refnames, missing_title_count=len(missing), work_bottom=work_bottom,
                minimum_body_font=7.8, master_hint=hint, preparation_prompt=prep,
                learning_objective_rows=objective_rows)
