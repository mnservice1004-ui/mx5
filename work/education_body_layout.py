"""ReportLab overlays for the maintenance education edition.

No files are written and no fonts are registered by this module.  The caller
keeps the /Original form with the existing clip/transform, registers EduKR and
EduKRB, then draws these vector overlays above it.  Returned links use zero
based destination page indexes; reference event input coordinates are GLOBAL.
"""
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth

W, H = A4
MM = 72 / 25.4
NAVY = '#18374D'
BLUE = '#087F9C'
TEAL = '#008476'
GRAY = '#5E6B75'
INK = '#263C4B'
PALE = '#F1F5F7'
AMBER = '#93601D'
STYLES = {
    0: dict(color=BLUE, dash=()),
    1: dict(color='#B52D32', dash=()),
    2: dict(color='#235F9A', dash=()),
    3: dict(color='#6B478F', dash=()),
    4: dict(color='#00756C', dash=(9, 3.5)),
    5: dict(color='#3F4853', dash=(2, 3)),
}


def _font(bold=False):
    return 'EduKRB' if bold else 'EduKR'


def _tx(c, x, y, value, size=9, bold=False, color=INK, width=None, minimum=None):
    value = str(value)
    if width is not None:
        minimum = minimum if minimum is not None else size
        while stringWidth(value, _font(bold), size) > width + .01 and size > minimum + .001:
            size = max(minimum, size - .1)
        assert stringWidth(value, _font(bold), size) <= width + .02, (value, size, width)
    c.setFont(_font(bold), size)
    c.setFillColor(color)
    c.drawString(x, y, value)
    return size


def _wrap(text, width, size, bold=False):
    lines, row = [], ''
    for character in str(text):
        if row and stringWidth(row + character, _font(bold), size) > width:
            lines.append(row.rstrip())
            row = character.lstrip()
        else:
            row += character
    if row:
        lines.append(row.rstrip())
    return lines or ['']


def _phase(title):
    if title == '작업요약표':
        return '요약'
    for name in ('조정', '점검', '탈거', '장착', '구성', '회로', '개요', '주의'):
        if name in title:
            return name
    return '본문'


def _short(item, title):
    for prefix in (item.get('chapter_title', '') + ' ', '프런트 도어 ', '리어 도어 '):
        if prefix.strip() and title.startswith(prefix):
            title = title[len(prefix):]
    for ending in (' 탈거 및 장착', ' 탈거', ' 장착'):
        if title.endswith(ending):
            title = title[:-len(ending)]
    return title


def _matrix_point(matrix, x, y):
    a, b, cc, d, e, f = matrix
    return a*x + cc*y + e, b*x + d*y + f


def _local(item, global_page):
    return global_page - item['original_start'] + 3


def _root_title(item, section):
    procedure = section['procedure_display']
    component = section.get('component', '')
    if component and component != item['title'] and component not in procedure:
        return component+' / '+procedure
    return procedure


def draw_body(c, item, pm, ctx, section, call_events, return_events, node):
    """Draw source-page navigation around an unchanged /Original form.

    ctx is the active GLOBAL reference event stack, outermost to innermost.
    section is the root section containing pm['old_page']; call_events and
    return_events are GLOBAL events whose origin/return is this source page.
    node is the source node from booklet_manifest.json, including missing[].
    The caller owns fixed outer folios and PDF annotation insertion.
    """
    p = pm['local_page']
    depth = len(ctx)
    assert depth == len(pm.get('active_reference_ids', [])) <= 5
    exact_x0, exact_x1 = ((28*MM, W-10*MM) if p % 2 else (10*MM, W-28*MM))
    x0, x1 = exact_x0+.75, exact_x1-.75
    width = x1-x0
    color = STYLES[depth]['color']
    links = []
    title = ctx[-1]['title'] if ctx else _root_title(item, section)
    phase = _phase(title)
    transition = ''
    if return_events:
        previous = max(1 + sum(e0['first_inserted_page'] <= e['origin_page'] < e0['return_page']
                               for e0 in item['reference_events']) for e in return_events)
        transition = f"복귀 {previous}차 → {str(depth)+'차' if depth else '본절차'}"

    # Strong hierarchy: stable unit, book title, current action, nesting path.
    unit_text = f"UNIT {item['id']}  /  {item.get('chapter_title', item['title'])}"
    if transition:
        unit_text += '  ·  '+transition
    _tx(c, x0, 805, unit_text,
        8.1, True, BLUE, width=width-80, minimum=7.6)
    guide_rect = [x1-66, 797.5, x1, 813]
    c.setFillColor(PALE)
    c.roundRect(guide_rect[0], guide_rect[1], 66, 15.5, 4, fill=1, stroke=0)
    _tx(c, x1-58, 803, '작업 길잡이 2쪽', 7.4, True, NAVY)
    links.append(dict(kind='guide', origin=p-1, rect=guide_rect, target=1))
    book_title_size = _tx(c, x0, 785, item['title'], 15, True, NAVY,
                          width=width, minimum=14)
    badge = f'참조 {depth}차' if depth else '본절차'
    c.setFillColor(color)
    c.roundRect(x0, 760, 53, 17, 3, fill=1, stroke=0)
    _tx(c, x0+7, 765.2, badge, 8.5, True, '#FFFFFF')
    current_size = _tx(c, x0+62, 765.2, title, 10.6, True, color,
                       width=width-62, minimum=9.8)
    breadcrumbs = ['본절차'] + [f'{n}차 {_short(item, e["title"])}'
                               for n, e in enumerate(ctx, 1)]
    breadcrumb_text = ' > '.join(breadcrumbs)
    if stringWidth(breadcrumb_text, _font(), 7.2) > width:
        breadcrumbs = ['본절차'] + [f'{n}차 {e["reference_id"]}'
                                   for n, e in enumerate(ctx, 1)]
        breadcrumb_text = ' > '.join(breadcrumbs)
    # Complete ancestry remains available in the bottom return chips.  Keeping
    # it out of the header prevents a fourth row from competing with source.

    # The approved reference frame positions and hierarchy remain physical.
    frames = []
    rails = []
    bm = pm.get('binding_transform', [1, 0, 0, 1, 0, 0])
    scale = abs(bm[0])
    if depth:
        rect = list(pm['border_rect'])
        c.saveState()
        c.setStrokeColor(color)
        c.setLineWidth(1.6*scale)
        c.setDash([v*scale for v in STYLES[depth]['dash']])
        c.rect(rect[0], rect[1], rect[2]-rect[0], rect[3]-rect[1], fill=0, stroke=1)
        c.restoreState()
        frames.append(dict(stage=depth, rect=rect, color=color,
                           dash=list(STYLES[depth]['dash']), line_width=1.6*scale))
        for old in pm.get('rail_relocations', []):
            stage = old['stage']
            assert stage in (list(range(1, depth)) if depth < 4 else list(range(4, depth)))
            xa, ya = _matrix_point(bm, old['to_x'], old['y1'])
            xb, yb = _matrix_point(bm, old['to_x'], old['y2'])
            c.saveState()
            c.setStrokeColor(STYLES[stage]['color'])
            c.setLineWidth(old['line_width']*scale)
            c.setDash([v*scale for v in STYLES[stage]['dash']])
            c.line(xa, ya, xb, yb)
            c.restoreState()
            rails.append(dict(stage=stage, line=[xa, ya, xb, yb],
                              color=STYLES[stage]['color'], dash=list(STYLES[stage]['dash'])))

    # Inline reference remains exactly at the interrupted source step.
    calls_meta = []
    for event in call_events:
        rect = list(pm['call_strip_rect'])
        a, b, cc, d = rect
        child = depth+1
        child_color = STYLES[child]['color']
        target = _local(item, event['first_inserted_page'])
        back = _local(item, event['return_page'])
        c.setFillColor('#F3F6F8')
        c.rect(a, b, cc-a, d-b, fill=1, stroke=0)
        c.setFillColor(child_color)
        c.rect(a, b, 3, d-b, fill=1, stroke=0)
        heading = f"다음 {target}쪽에서 {child}차 참조 시작  /  마친 뒤 {back}쪽으로 복귀"
        text_width = cc-a-16
        _tx(c, a+9, d-11, heading, 8.4, True, child_color,
            width=text_width, minimum=7.8)
        title_size = 9.0
        title_rows = _wrap(event['title'], text_width, title_size, True)
        if len(title_rows) > 1 and d-b < 34:
            title_size = _tx(c, a+9, d-23, event['title'], 8.8, True, INK,
                             width=text_width, minimum=7.4)
            title_rows = [event['title']]
        else:
            for rownum, row in enumerate(title_rows):
                _tx(c, a+9, d-23-10.5*rownum, row, title_size, True, INK)
        assert len(title_rows) <= 2 and d-23-10.5*(len(title_rows)-1) >= b+2
        links.append(dict(kind='enter_reference', origin=p-1, rect=rect,
                          target=target-1, reference_id=event['reference_id']))
        calls_meta.append(dict(rect=rect, child_depth=child, title=event['title'],
                               target=target, return_page=back, heading=heading))

    # Printed edge tabs retain their safe transformed positions.
    old_tab_x = W-39 if p % 2 else 27
    tabs = []
    original_phase = _phase(section['procedure_display'])
    categories = ['요약', '구성', '탈거', '장착', '조정', '점검', '회로', '개요', '주의', '본문']
    for label, old_y, old_h, fill in ((item['id'], 715, 69, NAVY),
                                     (phase, 635-categories.index(original_phase)*46, 42, color)):
        xx, yy = _matrix_point(bm, old_tab_x, old_y)
        tw, th = 12*scale, old_h*scale
        c.setFillColor(fill)
        c.rect(xx, yy, tw, th, fill=1, stroke=0)
        c.saveState()
        c.translate(xx+tw*.73, yy+6*scale)
        c.rotate(90)
        _tx(c, 0, 0, label, 6.6, True, '#FFFFFF')
        c.restoreState()
        tabs.append(dict(label=label, rect=[xx, yy, xx+tw, yy+th]))

    # One visible primary instruction and a complete path of ancestor returns.
    panel = [x0, 43, x1, 82]
    c.setFillColor(PALE)
    c.roundRect(x0, 43, width, 39, 4, fill=1, stroke=0)
    c.setFillColor(color)
    c.rect(x0, 43, 3, 39, fill=1, stroke=0)
    tx0 = x0+10
    if ctx:
        event = ctx[-1]
        back = _local(item, event['return_page'])
        parent_title = ctx[-2]['title'] if depth > 1 else _root_title(item, section)
        primary = f"{depth}차 참조를 마치면 → {str(depth-1)+'차 참조' if depth > 1 else '본절차'} {back}쪽에서 계속"
        _tx(c, tx0, 69, primary, 10.1, True, color, width=width-20, minimum=9.3)
        _tx(c, tx0, 56, '돌아갈 작업: '+parent_title, 8.3, False, INK,
            width=width-20, minimum=7.9)
        links.append(dict(kind='parent_return', origin=p-1, rect=[tx0, 53, x1-7, 80],
                          target=back-1, reference_id=event['reference_id']))
        labels = [(e, f"{n}차 {e['reference_id']} · {_local(item,e['return_page'])}쪽")
                  for n, e in enumerate(ctx, 1)]
        size = 7.0
        while sum(stringWidth(label, _font(True), size)+13 for _, label in labels) > width-20 and size > 6.5:
            size -= .1
        xpos = tx0
        for number, (event, label) in enumerate(labels):
            label_width = stringWidth(label, _font(True), size)
            _tx(c, xpos, 45.5, label, size, True, STYLES[number+1]['color'])
            rect = [xpos-1, 43, xpos+label_width+5, 53]
            links.append(dict(kind='ancestor_return', origin=p-1, rect=rect,
                              target=_local(item,event['return_page'])-1,
                              reference_id=event['reference_id']))
            xpos += label_width+13
        assert xpos <= x1+3
        secondary = '돌아갈 작업: '+parent_title
    else:
        primary = '본절차 계속  /  원문에 제시된 순서대로 진행'
        if return_events:
            primary = '본절차로 복귀했습니다  /  이 쪽의 다음 작업부터 계속'
        _tx(c, tx0, 67, primary, 10.1, True, color, width=width-20, minimum=9.3)
        secondary = f"현재 작업 {section['ordinal']:02d} / {len(item['sections']):02d}  ·  {_root_title(item, section)}"
        _tx(c, tx0, 51, secondary, 8.3, False, INK, width=width-20, minimum=7.9)
    missing = node.get('missing', [])
    source_text = f"원문 {node['file']} · {node['page']}쪽"
    if missing:
        source_text += '  /  미수록 참조: '+', '.join(r['reference_id'] for r in missing)
        source_text += ' · 상세는 종합색인'
        hint = item['master_hint']
        master_page = hint.get('missing_pages', [hint['first_page']])[0]
        links.append(dict(kind='missing_master', origin=p-1,
                          rect=[x0, 31.5, x1, 41.5], file='../'+hint['relative_path'],
                          target=master_page-1))
    _tx(c, x0, 34.5, source_text, 6.7, False, AMBER if missing else GRAY,
        width=width, minimum=6.5)
    return dict(links=links, header_text=dict(unit=item['id'], book_title=item['title'],
                current_title=title, current_component=section.get('component', ''),
                depth=depth, phase=phase, breadcrumbs=breadcrumbs,
                transition=transition, book_title_size=book_title_size,
                current_title_size=current_size),
                bottom_panel=dict(rect=panel, primary=primary, secondary=secondary),
                call_strip=calls_meta, frames=frames, rails=rails, tabs=tabs,
                source_provenance=source_text, safe_bounds=[x0, x1],
                exact_bounds=[exact_x0, exact_x1], overlay_horizontal_inset_pt=.75,
                overlay_bounds=dict(header=[x0, 760, x1, 813], footer=[x0, 31.5, x1, 82]))
