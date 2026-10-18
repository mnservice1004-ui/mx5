"""Restrained educational running labels for the existing linked master indexes.

The existing index content is retained in place.  Its established accent colour
is normalised by changing only numeric RGB operands.  A small, original Korean
running label is added in the formerly empty top margin.  No links, destinations,
page boxes, old fonts, table rows, or fixed outer folios are edited.
"""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

from pypdf import PdfReader
from pypdf.generic import DecodedStreamObject
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas


NAVY = (24 / 255, 55 / 255, 77 / 255)
BLUE = (8 / 255, 127 / 255, 156 / 255)
OLD_BLUE = (0, 126 / 255, 155 / 255)
LIGHT = (234 / 255, 241 / 255, 244 / 255)
SLATE = (77 / 255, 97 / 255, 112 / 255)
MM = 72 / 25.4
TOP_STRIP = (799.0, 813.0)

_NUMBER = rb"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
_RGB_OPERATION = re.compile(
    rb"(?<!\S)(" + _NUMBER + rb")\s+(" + _NUMBER + rb")\s+("
    + _NUMBER + rb")\s+(rg|RG)(?!\S)"
)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _register_fonts() -> None:
    registered = set(pdfmetrics.getRegisteredFontNames())
    if "EduKR" not in registered:
        pdfmetrics.registerFont(TTFont("EduKR", r"C:\Windows\Fonts\malgun.ttf"))
    if "EduKRB" not in registered:
        pdfmetrics.registerFont(TTFont("EduKRB", r"C:\Windows\Fonts\malgunbd.ttf"))


def _accent_only(data: bytes) -> tuple[bytes, list[dict]]:
    """Preserve raw operators/strings byte for byte except the old blue RGB triplet."""
    substitutions = []

    def replace(match):
        values = tuple(float(match.group(i)) for i in (1, 2, 3))
        if all(abs(a - b) <= 0.000002 for a, b in zip(values, OLD_BLUE)):
            result = b"0.031372549020 0.498039215686 0.611764705882 " + match.group(4)
            substitutions.append({
                "offset": match.start(),
                "before": match.group(0).decode("ascii"),
                "after": result.decode("ascii"),
            })
            return result
        return match.group(0)

    return _RGB_OPERATION.sub(replace, data), substitutions


def _descriptor(record: dict, physical_page: int) -> dict:
    descriptors = record.get("descriptors", [])
    if physical_page <= len(descriptors):
        return descriptors[physical_page - 1]
    return {"kind": "index"}


def _margin_limits(page, physical_page: int, record: dict) -> tuple[float, float]:
    pages = record.get("binding_pages", [])
    if physical_page <= len(pages):
        limits = pages[physical_page - 1].get("content_limits")
        if limits:
            return float(limits[0]), float(limits[1])
    width = float(page.mediabox.width)
    return (28 * MM, width - 10 * MM) if physical_page % 2 else (10 * MM, width - 28 * MM)


def restyle_index_page(page, physical_page: int, record: dict, writer) -> dict:
    """Restyle one writer-owned existing page and return a JSON-ready audit.

    ``record`` is the unchanged source master-index manifest record. ``writer``
    is accepted for the shared assembly interface; annotations are deliberately
    left to the calling writer, with their destinations and rectangles intact.
    """
    if physical_page < 1:
        raise ValueError("physical_page must be one based")
    descriptor = _descriptor(record, physical_page)
    kind = descriptor.get("kind", "index")
    contents = page.get_contents()
    old_data = contents.get_data() if contents else b""
    new_data, substitutions = _accent_only(old_data)
    old_font_names = sorted(str(key) for key in page["/Resources"].get("/Font", {}))
    old_annotations = list(page.get("/Annots", []))
    if new_data != old_data:
        stream = DecodedStreamObject()
        stream.set_data(new_data)
        page.replace_contents(stream)

    audit = {
        "page": physical_page,
        "kind": kind,
        "source_content_sha256": _digest(old_data),
        "accent_content_sha256": _digest(new_data),
        "accent_replacements": substitutions,
        "old_font_names": old_font_names,
        "annotations_preserved": len(old_annotations),
        "fixed_folio_preserved": True,
        "body_reflow": False,
        "running_label_added": kind != "blank",
    }
    if kind == "blank":
        audit["final_content_sha256"] = _digest(page.get_contents().get_data())
        return audit

    _register_fonts()
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    left, right = _margin_limits(page, physical_page, record)
    bottom, top = TOP_STRIP
    if top > height - 10 * MM + 0.01:
        raise ValueError("Index running label exceeds the ten millimetre top margin")
    role = {
        "guide": "사용 안내",
        "files": "책자 목록",
        "details": "상세 찾아보기",
    }.get(kind, "종합색인")
    output = io.BytesIO()
    c = canvas.Canvas(output, pagesize=(width, height), pageCompression=1)
    c.setFillColorRGB(*LIGHT)
    c.rect(left, bottom, right - left, top - bottom, stroke=0, fill=1)
    c.setFillColorRGB(*BLUE)
    c.rect(left, bottom, 2.2, top - bottom, stroke=0, fill=1)
    c.setFillColorRGB(*NAVY)
    c.setFont("EduKRB", 9.0)
    title = "종합 찾아보기"
    c.drawString(left + 8, 802.6, title)
    x = left + 8 + pdfmetrics.stringWidth(title, "EduKRB", 9.0) + 11
    c.setFillColorRGB(*SLATE)
    c.setFont("EduKR", 8.0)
    subtitle = "/  본절차 · 참조 · 복귀"
    c.drawString(x, 802.8, subtitle)
    c.setFont("EduKRB", 7.5)
    c.drawRightString(right - 8, 803.0, role)
    c.save()
    overlay_data = output.getvalue()
    overlay_reader = PdfReader(io.BytesIO(overlay_data))
    page.merge_page(overlay_reader.pages[0], over=True, expand=False)

    if list(page.get("/Annots", [])) != old_annotations:
        raise AssertionError("Index overlay must preserve every original annotation")
    new_font_names = sorted(str(key) for key in page["/Resources"].get("/Font", {}))
    if not set(old_font_names).issubset(new_font_names):
        raise AssertionError("Index overlay removed an original font resource")
    audit.update({
        "label": title + " " + subtitle,
        "role": role,
        "running_label_rect": [left, bottom, right, top],
        "top_clearance_mm": (height - top) / MM,
        "overlay_sha256": _digest(overlay_data),
        "new_font_names": new_font_names,
        "final_content_sha256": _digest(page.get_contents().get_data()),
    })
    return audit
