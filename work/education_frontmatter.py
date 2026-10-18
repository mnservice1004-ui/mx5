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


def _compact_pages(pages, max_width=None, size=8.4):
    """Physical page ranges; a compact label never changes the full evidence list."""
    values = sorted({int(p) for p in pages if int(p) >= 3})
    spans = []
    for value in values:
        if spans and value == spans[-1][-1]+1:
            spans[-1].append(value)
        else:
            spans.append([value])
    tokens = [str(s[0]) if len(s) == 1 else f'{s[0]}-{s[-1]}' for s in spans]
    text = ', '.join(tokens)+'쪽' if tokens else '본문 확인'
    if max_width is not None:
        while len(tokens) > 1 and pdfmetrics.stringWidth(text, 'EduKR', size) > max_width:
            tokens.pop()
            shown = sum(len(s) for s in spans[:len(tokens)])
            text = ', '.join(tokens)+f'쪽 외 {len(values)-shown}쪽'
        if pdfmetrics.stringWidth(text, 'EduKR', size) > max_width and values:
            text = f'{values[0]}쪽부터'
    return text, values


def _service_guide_panel(c, item, left, right, top, bottom=302):
    """Draw source-backed navigation summaries without adding a manual page.

    The caller supplies physical evidence pages, not the original-source pages.
    Long or dense books retain all source text in the body and use an explicit
    location summary here.  Missing data means unconfirmed, never unnecessary.
    """
    summary = item.get('service_summary', {})
    width = right-left
    col_gap = 17
    col_w = (width-24-col_gap)/2
    body_size, leading = 8.5, 12.0
    assert top-bottom >= 131, (item['id'], 'service panel height', top-bottom)
    counts = summary.get('counts', {})
    categories = [
        ('tools', '공구·보호 준비물', BLUE, '원문 공구 정보 미확인 / 상세 절차 확인'),
        ('parts', '교환 부품·적용 조건', AMBER, '교환 대상·조건은 해당 본문에서 확인'),
        ('principles', '작업 전 정비 원칙', TEAL, '본문의 적용 조건과 원문 주의사항 확인'),
        ('completion', '작업 후 완료 확인', NAVY, '해당 절차 끝의 원문 확인 사항 점검'),
    ]
    tool_status = summary.get('tool_status') if summary.get('tools') else None
    part_status = summary.get('part_number_status') if summary.get('parts') else None
    status = ' / '.join(v for v in [f'공구: {tool_status}' if tool_status else '',
                                    f'차량 부품번호: {part_status}' if part_status else ''] if v)
    status = status or '미확인 정보는 준비 불필요를 뜻하지 않음 / 원문의 적용 조건 확인'
    status_lines = wrap(status, width-24, 8.4)
    status_h = len(status_lines)*11.4
    assert len(status_lines) <= 2, (item['id'], 'service status', status_lines)
    detail = summary.get('detail_index', {})
    detail_page = detail.get('page')
    detail_text = f'준비물·정비원칙 상세: 종합색인 {detail_page}쪽' if detail_page else '준비물·정비원칙 상세는 원문 본문에서 확인'
    detail_h = 13

    # The few dense multi-component books use four full-width navigation rows.
    # This preserves the menu and the one-page guide without reducing type.
    if top-bottom < 190:
        c.setFillColor(PALE)
        c.roundRect(left, bottom, width, top-bottom, 6, fill=1, stroke=0)
        tx(c, left+12, top-17, '준비 공구·교환 부품 / 정비 원칙·완료 확인', 9.7, True, TEAL)
        rt(c, right-12, top-17, '핵심 요약 · 상세는 아래 색인', 8.4, color=GRAY)
        y, links, drawn = top-36, [], []
        short_titles = {'tools':'공구', 'parts':'교환', 'principles':'원칙', 'completion':'완료'}
        for key, title, color, fallback in categories:
            source_rows = summary.get(key, [])
            total = int(counts.get(key, len(source_rows)+int(summary.get(key+'_overflow', 0))))
            row = source_rows[0] if source_rows else {}
            text = row.get('text', fallback)
            label = row.get('label', '')
            heading = short_titles[key]+(f'·{label}' if label else '')
            heading_width = max(55, pdfmetrics.stringWidth(heading, 'EduKRB', 8.6)+8)
            pages_label, pages = _compact_pages(row.get('pages', []), 55, 8.4)
            body_width = width-24-heading_width-62
            lines = wrap(text, body_width, body_size)
            location_summary = False
            if len(lines) > 1:
                text = f'원문 {total}건 · 상세 색인에서 적용 조건 확인' if total else '원문 미확인 / 상세 절차에서 확인'
                lines = wrap(text, body_width, body_size)
                location_summary = True
            assert len(lines) == 1, (item['id'], 'dense guide row', key, lines)
            tx(c, left+12, y, heading, 8.6, True, color)
            tx(c, left+12+heading_width, y, lines[0], body_size)
            rt(c, right-12, y, pages_label, 8.4, True, BLUE if pages else GRAY)
            if pages:
                links.append(dict(kind='service_evidence', origin=1,
                                  rect=[right-72, y-3, right-12, y+10], target=pages[0]-1,
                                  category=key, evidence_pages=pages, visible_label=pages_label))
            drawn.append(dict(category=key, text=text, pages=pages, visible_pages=pages_label,
                              location_summary=location_summary, top=y, bottom=y-3))
            y -= 17
        assert y+15 >= bottom+status_h+detail_h+8, (item['id'], 'dense service footer', y)
        status_y = bottom+detail_h+8+(len(status_lines)-1)*11.4
        for line in status_lines:
            tx(c, left+12, status_y, line, 8.4, color=GRAY)
            status_y -= 11.4
        tx(c, left+12, bottom+8, detail_text, 8.4, True, BLUE)
        remote = []
        if detail_page and detail.get('file'):
            remote.append(dict(kind='service_master', origin=1, file=detail['file'],
                               relative_path=detail['file'], target=int(detail_page)-1,
                               rect=[left+12, bottom+5, right-12, bottom+18]))
        return dict(links=links, remote_links=remote, rows=drawn,
                    panel_rect=[left, bottom, right, top], counts=counts,
                    minimum_font=8.4, status=status, detail_index=detail,
                    body_and_reference=bool(summary.get('has_reference_preparation')), layout='compact_rows')

    # Prefer two precise entries where room permits. At the dense end, keep one
    # exact entry per category, with an explicit count and body-page destination.
    maximum_entries = 2 if top-bottom >= 208 else 1
    plans = []
    for key, title, color, fallback in categories:
        source_rows = summary.get(key, [])
        total = int(counts.get(key, len(source_rows)+int(summary.get(key+'_overflow', 0))))
        selected = source_rows[:maximum_entries]
        records = []
        for source in selected:
            label = source.get('label', '')
            text = (f'[{label}] ' if label else '')+source.get('text', '')
            pages_label, pages = _compact_pages(source.get('pages', []), col_w, body_size)
            lines = wrap(text, col_w, body_size)
            records.append(dict(text=text, label=label, lines=lines, pages=pages, pages_label=pages_label))
        if not records:
            records = [dict(text=fallback, lines=wrap(fallback, col_w, body_size),
                            pages=[], pages_label='본문 상세 확인')]
        plans.append(dict(key=key, title=title, color=color, total=total,
                          records=records, available_rows=len(source_rows)))

    def block_height(plan):
        return 16+sum((len(r['lines'])+1)*leading+3 for r in plan['records'])+5

    available = top-bottom-36-status_h-detail_h-5
    for pair in ((plans[0], plans[1]), (plans[2], plans[3])):
        # Excessive verbatim sentences are not cut halfway through a condition.
        # Instead show a clearly named evidence-location summary on this guide.
        if sum(block_height(p) for p in pair) > available:
            for plan in pair:
                if len(plan['records']) > 1:
                    plan['records'] = plan['records'][:1]
        if sum(block_height(p) for p in pair) > available:
            for plan in pair:
                for record in plan['records']:
                    if len(record['lines']) > 1:
                        label = record.get('label', '')
                        record['text'] = ((f'[{label}] ' if label else '')+
                                          '원문 '+str(plan['total'])+'건 / 본문에서 조건 확인'
                                          if plan['total'] else record['text'])
                        record['lines'] = wrap(record['text'], col_w, body_size)
                        record['location_summary'] = True
        assert sum(block_height(p) for p in pair) <= available, (
            item['id'], 'service category fit', available, pair)

    c.setFillColor(PALE)
    c.roundRect(left, bottom, width, top-bottom, 6, fill=1, stroke=0)
    tx(c, left+12, top-17, '준비 공구·교환 부품 / 정비 원칙·완료 확인', 9.7, True, TEAL)
    scope = '본문·참조 함께 집계' if summary.get('has_reference_preparation') else '해당 본문에서 확인'
    rt(c, right-12, top-31, scope+' · 핵심 요약', 8.4, color=GRAY)
    links, drawn = [], []
    for column, pair in enumerate(((plans[0], plans[1]), (plans[2], plans[3]))):
        x, y = left+12+column*(col_w+col_gap), top-48
        for plan in pair:
            count_text = f" ({plan['total']}건)" if plan['total'] else ''
            tx(c, x, y, plan['title']+count_text, 8.8, True, plan['color'])
            y -= 15
            for record in plan['records']:
                start_y = y
                for line in record['lines']:
                    tx(c, x, y, line, body_size)
                    y -= leading
                tx(c, x, y, record['pages_label'], 8.4, True, BLUE if record['pages'] else GRAY)
                if record['pages']:
                    links.append(dict(kind='service_evidence', origin=1,
                                      rect=[x, y-3, x+col_w, y+10],
                                      target=record['pages'][0]-1, category=plan['key'],
                                      evidence_pages=record['pages'], visible_label=record['pages_label']))
                drawn.append(dict(category=plan['key'], text=record['text'],
                                  pages=record['pages'], visible_pages=record['pages_label'],
                                  location_summary=record.get('location_summary', False),
                                  top=start_y, bottom=y-3))
                y -= leading+3
            y -= 6
        assert y+6 >= bottom+status_h+detail_h+7, (item['id'], 'service row bottom', y)
    status_y = bottom+detail_h+8+(len(status_lines)-1)*11.4
    for line in status_lines:
        tx(c, left+12, status_y, line, 8.4, color=GRAY)
        status_y -= 11.4
    tx(c, left+12, bottom+8, detail_text, 8.4, True, BLUE)
    remote = []
    if detail_page and detail.get('file'):
        remote.append(dict(kind='service_master', origin=1, file=detail['file'],
                           relative_path=detail['file'], target=int(detail_page)-1,
                           rect=[left+12, bottom+5, right-12, bottom+18]))
    return dict(links=links, remote_links=remote, rows=drawn, panel_rect=[left, bottom, right, top],
                counts={p['key']:p['total'] for p in plans}, minimum_font=8.4,
                status=status, detail_index=detail, layout='two_columns',
                body_and_reference=bool(summary.get('has_reference_preparation')))


def draw_guide(c, item, education=None):
    """Draw physical page 2 and return complete section and master links."""
    e = _edu(item, education)
    left, right = SAFE_REGIONS[2]
    left, right = left+.75, right-.75
    width = right-left
    c.saveState()
    _pill(c, left, H-43, 'WORK GUIDE')
    rt(c, right, H-43, f"{item['id']}  /  {item['title']}", 9, True, BLUE)
    tx(c, left, H-78, '작업 길잡이', 25, True)
    c.setStrokeColor(LINE)
    c.setLineWidth(.6)
    c.line(left, H-123, right, H-123)
    prep = e.get('preparation_prompt', '작업할 본문 항목과 원문 주의사항을 먼저 확인하세요.')
    prep_lines = wrap(prep, width, 8.8)
    assert len(prep_lines) <= 2, (item['id'], prep_lines)
    para(c, left, H-100, prep, width, 8.8, 12, color=GRAY)
    heading_y = H-145
    _section_title(c, left, heading_y, '수록 항목과 시작 쪽', '01')
    rt(c, right, heading_y, '본문 3쪽부터', 8.5, True, BLUE)
    ytop = heading_y-25
    links, drawn = [], []
    sections = item['sections']
    if len(sections) <= 8:
        y = ytop
        for ix, sec in enumerate(sections, 1):
            comp = _short_component(item, sec['component'])
            label = sec['procedure_display']
            if sec['component'] not in (item['title'], sec['procedure_display']):
                label = comp+' / '+label
            lines = wrap(label, width-77, 10.0, True)
            row_h = max(27, len(lines)*14+9)
            tx(c, left+1, y, f'{ix:02}', 9, True, BLUE)
            for n, line in enumerate(lines):
                tx(c, left+28, y-n*14, line, 10.0, True)
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
                tw = pdfmetrics.stringWidth(text, 'EduKR', 8.7)
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
            nn = len(wrap(title, col_w-(63 if single(g) else 26), 9.4, True))
            return nn*14+(0 if single(g) else len(tokens(g))*15)+10

        heights = [groupheight(g) for g in groups]
        split = min(range(1, len(groups)), key=lambda k: max(sum(heights[:k]), sum(heights[k:]))) if len(groups)>1 else 1
        tx(c, left, ytop+8, '왼쪽 열을 위에서 아래로 읽은 뒤 오른쪽 열로 이어집니다.', 8.4, color=GRAY)
        bottoms = []
        for col, gg in enumerate((groups[:split], groups[split:])):
            x, y = left+col*(col_w+18), ytop-13
            for g in gg:
                title = _short_component(item, g['component'])
                ls = wrap(title, col_w-(63 if single(g) else 26), 9.4, True)
                start_y = y
                ordn = sections.index(g['sections'][0])+1
                tx(c, x, y, f'{ordn:02}', 8.4, True, BLUE)
                for line in ls:
                    tx(c, x+25, y, line, 9.4, True)
                    y -= 14
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
                            tx(c, xx, y, text, 8.7)
                            links.append(dict(origin=1, rect=[xx, y-5, xx+tw, y+12], target=_local(item, sec['original_start'])-1,
                                              kind='procedure', source_file=sec['file']))
                            drawn.append(sec['file'])
                            xx += tw+10
                        y -= 15
                c.setStrokeColor(LINE)
                c.setLineWidth(.45)
                c.line(x+25, y+2, x+col_w, y+2)
                y -= 10
            bottoms.append(y)
        work_bottom = min(bottoms)

    assert work_bottom >= 447, (item['id'], 'work_bottom', work_bottom)
    service = _service_guide_panel(c, item, left, right, min(work_bottom-13, 606))
    links.extend(service['links'])
    # Review questions and learning outcomes remain on the first-page cards;
    # the second page uses that space for source-backed preparation information.
    objective_rows = []
    _section_title(c, left, 277, '함께 읽는 참조절차', '02')
    refnames = sorted({ev['title'] for ev in item['reference_events']})
    names = ' · '.join(refnames) if refnames else '이 항목에는 펼쳐 넣은 다른 절차가 없습니다.'
    ref_lines = wrap(names, width, 9.2)
    assert len(ref_lines) <= 3, (item['id'], 'reference names', ref_lines)
    para(c, left, 258, names, width, 9.2, 14, color=NAVY if refnames else GRAY)

    _section_title(c, left, 211, '참조 깊이와 복귀 읽기', '03')
    _draw_legend(c, left, right, 181)
    tx(c, left, 154, '4·5차는 1·2·3차 선 생략 / 5차는 4차 긴 점선과 5차 짧은 점선을 함께 표시', 8.4, color=GRAY)
    c.setFillColor(LIGHT)
    c.roundRect(left, 112, width, 31, 5, fill=1, stroke=0)
    tx(c, left+11, 130, '읽는 순서', 8.7, True, TEAL)
    tx(c, left+11, 117, '본문 → 표시된 참조절차 → 하단의 부모 복귀 쪽 → 원래 다음 단계', 9)

    hint = item.get('master_hint', {})
    first = hint.get('first_page')
    label = hint.get('title') or '종합색인'
    master_text = '상세 찾아보기  /  '+label+(f' {first}쪽' if first else '')
    tx(c, left, 94, master_text, 8.8, True, BLUE)
    remote = []
    remote.extend(service.get('remote_links', []))
    if hint.get('relative_path') and first:
        remote.append(dict(origin=1, rect=[left, 88, right, 107], file=hint['relative_path'],
                           relative_path=hint['relative_path'], target=first-1, kind='master_details'))
    missing = _missing_rows(item)
    if missing:
        missing_pages = hint.get('missing_pages', [])
        ptext = ' / 종합색인 '+', '.join(map(str, missing_pages))+'쪽' if missing_pages else ''
        text = f'원문 미수록 참조 {len(missing)}종: 본문 안내와 종합색인에서 확인'+ptext
        mlines = wrap(text, width, 8.4)
        assert len(mlines) <= 2, (item['id'], 'missing', mlines)
        para(c, left, 76, text, width, 8.4, 12, True, AMBER)
        if hint.get('relative_path') and missing_pages:
            remote.append(dict(origin=1, rect=[left, 76-len(mlines)*12+3, right, 86], file=hint['relative_path'],
                               relative_path=hint['relative_path'], target=missing_pages[0]-1, kind='master_missing'))
    else:
        tx(c, left, 76, '지금 읽는 참조를 마치면 돌아갈 쪽번호를 본문 하단에서 확인하세요.', 8.6, color=GRAY)
    tx(c, left, 43, 'A4 · 실제 크기 100% · 양면 · 긴 쪽 넘김', 8.4, color=GRAY)
    rt(c, right, 43, '쪽번호 = 이 PDF의 실제 쪽', 8.4, color=GRAY)
    c.restoreState()
    assert drawn == [sec['file'] for sec in sections], (item['id'], drawn)
    return dict(links=links, remote_links=remote, section_files=drawn, section_count=len(drawn),
                reference_names=refnames, missing_title_count=len(missing), work_bottom=work_bottom,
                minimum_body_font=8.4, master_hint=hint, preparation_prompt=prep,
                learning_objective_rows=objective_rows, service_summary=service)
