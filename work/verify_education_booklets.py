"""Independent, read-only structural QA of the educational maintenance edition.

Imports only earlier independent verification helpers, never authoring modules.
Checks actual PDF graphs, composed source matrices/clips, rendered bounded text,
link destination multisets, nested-reference strokes, and archive member bytes.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import sys
import traceback
import zipfile

import pypdfium2 as pdfium
from pypdf import PdfReader
from pypdf.generic import ContentStream
from reportlab.pdfbase.pdfmetrics import stringWidth

from verify_binding_booklets import annotation_rows, drawings, rectangle, rect_wh
from verify_nested_final import STYLE, close, multiply, rgb
from verify_photo_intro import Canonical, count_outlines, filehash, normalized_text, outlines, xobjects

ROOT = Path(__file__).resolve().parent
MM = 72 / 25.4
IDENTITY = [1., 0., 0., 1., 0., 0.]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def normal(text):
    return normalized_text(str(text).replace("—", "/").replace("–", "-").replace("‑", "-"))


def local(item, global_page):
    return global_page - item["original_start"] + 3


def events_at(item, global_page):
    return sorted([e for e in item["reference_events"]
                   if e["first_inserted_page"] <= global_page < e["return_page"]],
                  key=lambda e: e["return_page"] - e["first_inserted_page"], reverse=True)


def annotation_key(row):
    # Direct /Dest and equivalent /A /GoTo are the same local destination.
    return (row["subtype"], "remote" if row["file"] else "local",
            row["target"], row["file"], tuple(row["view"]), row["uri"])


def link_key(row):
    return (row["origin"], row["target"], str(row.get("file", "")).replace("\\", "/"))


def check_folio(page, reader, physical, rendered_text):
    """Read actual BT/Tf/Tm operators; never use visitor text geometry."""
    fonts = page["/Resources"].get("/Font", {})
    current, stack, block, matches = IDENTITY[:], [], None, []
    font_state = None
    for args, op in ContentStream(page.get_contents(), reader).operations:
        if op == b"q":
            stack.append((current[:], font_state))
        elif op == b"Q":
            current, font_state = stack.pop()
        elif op == b"cm":
            current = multiply(current, list(map(float, args)))
        elif op == b"BT":
            block = {"ctm": current[:], "fonts": [], "matrices": [], "shows": [], "show_fonts": []}
        elif op == b"Tf":
            name, size = str(args[0]), float(args[1])
            font_state = (name, size, str(fonts[name].get_object().get("/BaseFont")))
            if block is not None:
                block["fonts"].append(font_state)
        elif op == b"Tm" and block is not None:
            block["matrices"].append(list(map(float, args)))
        elif op == b"Tj" and block is not None:
            block["shows"].append(str(args[0]))
            block["show_fonts"].append(font_state)
        elif op == b"ET" and block is not None:
            if (len(block["show_fonts"]) == 1 and block["show_fonts"][0][2] == "/Helvetica-Bold"
                    and abs(block["show_fonts"][0][1] - 11) < 0.000001
                    and block["shows"] and all(v.isdigit() for v in block["shows"])):
                matches.append(block)
            block = None
    assert not stack, "Unbalanced graphics state at end of page"
    assert len(matches) == 1, ("Missing or duplicate fixed numeric folio", physical, matches)
    folio = matches[0]
    width = float(page.mediabox.width)
    advance = stringWidth(str(physical), "Helvetica-Bold", 11)
    x = width - 12 * MM - advance if physical % 2 else 12 * MM
    y = 8 * MM
    assert folio["shows"] == [str(physical)], ("Wrong actual folio number", physical, folio)
    assert close(folio["ctm"], IDENTITY, .000001), ("Folio scaled/translated", physical, folio)
    assert len(folio["matrices"]) == 1 and close(folio["matrices"][0], [1,0,0,1,x,y], .0001), ("Folio anchor differs", physical, folio)
    visible = rendered_text.get_text_bounded(x - 1, y - 1, x + advance + 1, y + 9).strip()
    assert visible == str(physical), ("PDFium visible folio differs", physical, visible)
    return {"text": visible, "font_size": 11, "x": x, "baseline": y,
            "side": "right" if physical % 2 else "left"}


def check_frame(page, reader, pm, old_page, old_reader):
    depth = len(pm.get("active_reference_ids", []))
    if not depth:
        return {"depth": 0, "frame_count": 0, "ancestor_rails": 0}
    _, old_shapes = drawings(old_page, old_reader)
    _, shapes = drawings(page, reader)
    border = pm["border_rect"]
    full = [s for s in shapes if s["shape"] == "rect" and close(s["coordinates"], border, .005)]
    old_full = [s for s in old_shapes if s["shape"] == "rect" and close(s["coordinates"], border, .005)]
    assert len(full) == len(old_full) == 1, ("Nested-reference frame lost or duplicated", depth)
    scale = abs(pm.get("binding_transform", IDENTITY)[0])
    color, dash = STYLE[depth]
    assert close(full[0]["color"], rgb(color), .000002), ("Reference-frame color differs from approved key", depth, full[0])
    assert close(full[0]["dash"], [v * scale for v in dash], .002), ("Reference-frame dash differs", depth)
    assert abs(full[0]["width"] - 1.6 * scale) < .002, ("Reference-frame width differs", depth)
    assert close(full[0]["coordinates"], old_full[0]["coordinates"], .002), "Reference frame placement changed"
    old_rails, rails = [], []
    for source, target in [(old_shapes, old_rails), (shapes, rails)]:
        for s in source:
            if s["shape"] != "line":
                continue
            x1,y1,x2,y2 = s["coordinates"]
            if abs(x1-x2) < .002 and close(sorted([y1,y2]), [border[1],border[3]], .002):
                target.append(s)
    ancestors = list(range(1, depth)) if depth < 4 else list(range(4, depth))
    assert len(rails) == len(old_rails) == len(ancestors), ("Wrong visible reference-line count", depth, rails)
    for stage in ancestors:
        col, pattern = STYLE[stage]
        candidate = [s for s in rails if close(s["color"], rgb(col), .000002)]
        original = [s for s in old_rails if close(s["color"], rgb(col), .000002)]
        assert len(candidate) == len(original) == 1, ("Ancestor rail color absent or repeated", depth, stage)
        assert close(candidate[0]["coordinates"], original[0]["coordinates"], .002), ("Ancestor rail placement/order changed", stage)
        assert close(candidate[0]["dash"], [v * scale for v in pattern], .002), ("Ancestor rail dash changed", stage)
    return {"depth": depth, "frame_count": 1, "ancestor_rails": len(ancestors)}


def check_navigation(item, reader, old_reader, baseline, page_text, counts, is_book):
    descriptors = item.get("navigation_links", []) if is_book else []
    declared = Counter(link_key(v) for v in descriptors)
    actual = Counter()
    actual_rectangles = []
    rows = []
    for p,(old_page,page) in enumerate(zip(old_reader.pages,reader.pages),1):
        old = annotation_rows(old_reader, old_page)
        new = annotation_rows(reader, page)
        assert Counter(map(annotation_key, old)) == Counter(map(annotation_key, new)), ("Actual per-page destination multiset changed", p)
        width = float(page.mediabox.width)
        physical = (25*MM,width) if p%2 else (0,width-25*MM)
        for a in new:
            rect = a["rect"]
            assert a["subtype"] == "/Link" and len(rect) == 4 and rect[0] < rect[2] and rect[1] < rect[3], ("Invalid link hit rectangle", p,a)
            assert physical[0]-.02 <= rect[0] and rect[2] <= physical[1]+.02 and 0 <= rect[1] < rect[3] <= float(page.mediabox.height), ("Link enters binding strip or lies outside page", p,a)
            if a["file"]:
                assert not Path(a["file"]).is_absolute(), ("External link not relative",p,a)
                old_target = next((e for e in baseline["items"]+baseline["indexes"] if Path(e["path"]).name == Path(a["file"]).name), None)
                assert old_target is not None and 0 <= a["target"] < old_target["total_pages"], ("External destination invalid",p,a)
                counts["remote_links"] += 1
            else:
                assert a["target"] is not None and 0 <= a["target"] < len(reader.pages), ("Local destination invalid",p,a)
                counts["internal_links"] += 1
            actual_key = (p-1,a["target"],a["file"] or "")
            actual[actual_key] += 1
            actual_rectangles.append((actual_key,rect))
            text = page_text[p-1].get_text_bounded(*rect).strip()
            assert text, ("Link has no visible selectable label in its actual hit area",p,a)
            counts["links_with_visible_labels"] += 1
        counts["actual_links_preserved"] += len(new)
        rows.append(new)
    if is_book:
        assert actual == declared, ("Actual link targets differ from declared navigation", actual-declared,declared-actual)
        unmatched = list(actual_rectangles)
        for link in descriptors:
            match = next((i for i,(key,rect) in enumerate(unmatched)
                          if key == link_key(link) and close(rect,link["rect"],.0002)),None)
            assert match is not None,("Actual link rectangle differs from declared navigation",link)
            unmatched.pop(match)
        assert not unmatched,"Undeclared actual annotation rectangles"
        for link in descriptors:
            counts["link_kind_"+link["kind"]] += 1
        guide = normal(reader.pages[1].extract_text())
        targets = {v["target"] for v in rows[1] if not v["file"]}
        for section in item["sections"]:
            assert local(item,section["original_start"])-1 in targets, ("Main procedure absent from one-page guide",section)
            assert normal(section["procedure_display"]) in guide, ("Procedure label absent from guide",section)
            counts["guide_procedures"] += 1
        for event in item["reference_events"]:
            origin,start = local(item,event["origin_page"]),local(item,event["first_inserted_page"])
            assert start-1 in {v["target"] for v in rows[origin-1] if not v["file"]}, ("Inline reference entry missing",event)
            counts["reference_entries"] += 1
        for pm in item["page_meta"]:
            if pm["kind"] != "source":
                continue
            contexts = events_at(item,pm["old_page"])
            if contexts:
                target = local(item,contexts[-1]["return_page"])-1
                assert target in {v["target"] for v in rows[pm["local_page"]-1] if not v["file"]}, ("Immediate parent resume absent",pm)
                for context in contexts:
                    target = local(item,context["return_page"])-1
                    assert target in {v["target"] for v in rows[pm["local_page"]-1] if not v["file"]}, ("Ancestor resume absent",pm,context)
                counts["reference_pages"] += 1
                counts["parent_resumes"] += 1
                counts["ancestor_resumes"] += len(contexts)
    return rows


def check_entry(item, old, baseline, global_manifest, is_book):
    assert Path(item["path"]).resolve() != Path(old["path"]).resolve(), "New edition overwrote old PDF"
    assert filehash(old["path"]) == old["sha256"] == item["source_sha256"], "Approved source PDF changed"
    assert Path(item["source_path"]).resolve() == Path(old["path"]).resolve(), "Wrong source PDF"
    assert filehash(item["path"]) == item["sha256"], "Final hash differs from manifest"
    before,after = PdfReader(old["path"]),PdfReader(item["path"])
    assert len(before.pages) == len(after.pages) == item["total_pages"] and len(after.pages)%2 == 0, "Page count/parity changed"
    assert outlines(before) == outlines(after), "Bookmark titles/order/destinations changed"
    prefs = after.trailer["/Root"]["/ViewerPreferences"]
    assert prefs.get("/PrintScaling") == "/None" and prefs.get("/Duplex") == "/DuplexFlipLongEdge" and prefs.get("/Direction") == "/L2R", "Wrong print preferences"
    assert after.trailer["/Root"].get("/PageLayout") == "/TwoPageRight", "Wrong spread parity"
    counts=Counter(pdfs=1,pages=len(after.pages),bookmarks=count_outlines(after.outline))
    ca,cb=Canonical(),Canonical()
    pm_by_page={v["local_page"]:v for v in item.get("page_meta",[])}
    if is_book:
        for key in ("sections","page_map","page_meta","reference_events","local_reference_events","asset","master_hint"):
            assert item.get(key) == old.get(key), ("Source coverage, source asset, or route metadata changed",key)
        assert item["front_pages"] == 2 and item["education_pages"][0]["kind"] == "cover" and item["education_pages"][1]["kind"] == "work_guide", "Opening structure changed"
        cover=normal(after.pages[0].extract_text());asset=item["asset"]
        for text in [item["title"],asset["intro"],asset["caption"]]+[value for row in asset["workflow"] for value in (row["title"],row["description"])]:
            assert normal(text) in cover,("Component introduction/scope text lost",text)
        old_images=Counter(ca.hash(v) for _,v in xobjects(before.pages[0]["/Resources"]) if v.get("/Subtype")=="/Image")
        new_images=Counter(cb.hash(v) for _,v in xobjects(after.pages[0]["/Resources"]) if v.get("/Subtype")=="/Image")
        assert old_images and old_images == new_images,"Component image bytes/resources changed"
        counts["component_images_preserved"]+=1;counts["complete_introductions"]+=1;counts["one_page_guides"]+=1
        counts["booklet_pages"]+=len(after.pages);counts["booklet_pdfs"]+=1
    else:
        for key in ("descriptors","item_details","transfer_counts","item_ids"):
            assert item.get(key)==old.get(key),("Detailed index metadata changed",key)
        counts["index_pages"]+=len(after.pages);counts["index_pdfs"]+=1
    pdf=pdfium.PdfDocument(item["path"]); rendered=[];texts=[];checks=[]
    try:
        for n in range(len(pdf)):
            page=pdf[n];rendered.append(page);texts.append(page.get_textpage())
        links=check_navigation(item,after,before,baseline,texts,counts,is_book)
        for p,(left,right) in enumerate(zip(before.pages,after.pages),1):
            assert close(list(map(float,right.mediabox)),[0,0,595.2755905511812,841.8897637795277],.001),"Non-A4 page"
            row={"page":p,"folio":check_folio(right,after,p,texts[p-1]),"links":len(links[p-1])}
            counts["fixed_folios"]+=1
            if not is_book:
                assert right.extract_text().startswith(left.extract_text()),("Detailed index text changed",p)
                assert len(left.get("/Annots",[]))==len(right.get("/Annots",[])),("Index annotations lost",p)
                counts["index_text_prefix_preserved"]+=1
            if is_book and p in pm_by_page:
                pm=pm_by_page[p]
                if pm["kind"]=="source":
                    a=left["/Resources"]["/XObject"]["/Original"]
                    b=right["/Resources"]["/XObject"]["/Original"]
                    assert ca.hash(a)==cb.hash(b),("Original form/images/fonts/deep streams changed",p)
                    actual,_=drawings(right,after);prior_actual,_=drawings(left,before)
                    assert actual and prior_actual,"Missing original source draw"
                    assert close(actual["matrix"],prior_actual["matrix"],.000001),("Source transform changed",p,actual,prior_actual)
                    assert close(actual["clip"],prior_actual["clip"],.000001),("Source clipping changed",p)
                    assert close(actual["matrix"],pm["transform"],.000001) and close(rect_wh(actual["clip"]),pm["clip_rect"],.000001),("Actual Source Do differs from manifest",p)
                    row["reference"]=check_frame(right,after,pm,left,before)
                    row["original_form_sha256"]=cb.hash(b)
                    counts["original_forms"]+=1
                    counts["source_transforms_and_clips"]+=1
                    counts["reference_frames"]+=row["reference"]["frame_count"]
                    counts["ancestor_rails"]+=row["reference"]["ancestor_rails"]
                    counts["depth_"+str(row["reference"]["depth"])+"_pages"]+=1
                else:
                    node=global_manifest["nodes"][pm["old_page"]-global_manifest["front_pages"]-1]
                    text=normal(right.extract_text())
                    for missing in node["missing"]:
                        assert normal(missing["reference_id"]) in text and normal(missing["target_title"]) in text,("Missing-source notice content lost",p,missing)
                        if missing.get("note"):
                            assert normal(missing["note"]) in text,("Missing-source explanation lost",p,missing)
                    counts["notices_preserved"]+=1
            checks.append(row)
    finally:
        for text in texts:text.close()
        for page in rendered:page.close()
        pdf.close()
    return {"relative_path":item["relative_path"],"path":item["path"],"status":"passed","pages":checks,"totals":dict(counts)},counts


def check_archives(manifest):
    result=[]
    for bundle in manifest.get("bundles",[]):
        assert filehash(bundle["path"])==bundle["sha256"] and Path(bundle["path"]).stat().st_size==bundle["bytes"],"Archive hash or size differs"
        name=Path(bundle["path"]).name
        part=7 if "프런트" in name else 8 if "리어" in name else None
        expected=[i for i in manifest["items"] if part is None or i["part"]==part]
        expected+=manifest["indexes"] if part is None else [manifest["indexes"][1 if part==7 else 2]]
        with zipfile.ZipFile(bundle["path"]) as archive:
            assert archive.testzip() is None,"Archive CRC failure"
            names=archive.namelist();wanted={v["relative_path"].replace("\\","/"):v for v in expected}
            assert len(names)==len(set(names))==bundle["files"]==len(wanted) and set(names)==set(wanted),"Archive contents/count differs"
            for filename,entry in wanted.items():
                assert archive.read(filename)==Path(entry["path"]).read_bytes(),("Archive member bytes differ",filename)
        result.append({"path":bundle["path"],"files":len(expected),"crc_passed":True,"bytes_identical":True})
    return result


def source_archive_check(global_manifest, archive_path):
    import hashlib
    path=Path(archive_path)
    expected=global_manifest["source_sha256"];actual={}
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            base=Path(name).name
            if base in expected:
                assert base not in actual,("Duplicate original PDF member",base)
                actual[base]=hashlib.sha256(archive.read(name)).hexdigest()
    assert actual==expected,"Original archived technical PDFs changed"
    return {"archive":str(path),"source_pdf_hashes_preserved":len(actual)}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    parser=argparse.ArgumentParser();parser.add_argument("--manifest",default=str(ROOT/"education_booklets_manifest.json"));parser.add_argument("--report",default=str(ROOT/"education_qa_report.json"));parser.add_argument("--pilot",action="store_true")
    parser.add_argument("--source-archive",default=str(ROOT.parent/"inputs"/"정비매뉴얼.zip"))
    args=parser.parse_args()
    manifest,baseline,global_manifest=read(args.manifest),read(ROOT/"folio_booklets_manifest.json"),read(ROOT/"booklet_manifest.json")
    report={"status":"running","manifest":args.manifest,"pilot":args.pilot,"records":[],"bundles":[],"failures":[]};totals=Counter()
    by_name={v["relative_path"]:v for v in baseline["items"]+baseline["indexes"]}
    for is_book,entries in [(True,manifest["items"]),(False,manifest["indexes"])]:
        for entry in entries:
            name=entry["relative_path"]
            try:
                record,counts=check_entry(entry,by_name[name],baseline,global_manifest,is_book)
                report["records"].append(record);totals.update(counts);print("PASS",name,counts["pages"],"pages",flush=True)
            except Exception as e:
                report["failures"].append({"file":name,"message":str(e),"traceback":traceback.format_exc()});print("FAIL",name,str(e),flush=True)
    if not args.pilot:
        try:
            assert len(manifest["items"])==30 and len(manifest["indexes"])==3 and len(manifest["bundles"])==3,"Incomplete 30+3+3 deliverables"
            finals={Path(e["path"]).resolve():e for e in manifest["items"]+manifest["indexes"]}
            for entry in manifest["items"]+manifest["indexes"]:
                reader=PdfReader(entry["path"])
                for page in reader.pages:
                    for row in annotation_rows(reader,page):
                        if row["file"]:
                            target=(Path(entry["path"]).parent/row["file"]).resolve()
                            assert target in finals and target.is_file(),("Remote PDF missing from final folder",entry["relative_path"],row)
                            assert 0<=row["target"]<finals[target]["total_pages"],("Remote PDF page invalid",row)
            report["bundles"]=check_archives(manifest)
            report["original_archive"]=source_archive_check(global_manifest,args.source_archive)
        except Exception as e:
            report["failures"].append({"deliverables":str(e),"traceback":traceback.format_exc()})
        for key,expected in {"pdfs":33,"pages":1092,"booklet_pdfs":30,"booklet_pages":1006,"index_pdfs":3,"index_pages":86,"bookmarks":638,"original_forms":921,"source_transforms_and_clips":921,"notices_preserved":9,"component_images_preserved":30,"complete_introductions":30,"one_page_guides":30,"guide_procedures":149,"reference_entries":150,"reference_pages":484,"parent_resumes":484,"ancestor_resumes":798,"fixed_folios":1092,"actual_links_preserved":4255,"links_with_visible_labels":4255,"index_text_prefix_preserved":86,"reference_frames":484,"ancestor_rails":212,"link_kind_guide":930,"link_kind_enter_reference":150,"link_kind_parent_return":484,"link_kind_ancestor_return":798,"link_kind_missing_master":28,"link_kind_notice_continue":9}.items():
            if totals[key]!=expected:report["failures"].append({"aggregate":key,"expected":expected,"actual":totals[key]})
    report["totals"]=dict(totals);report["status"]="failed" if report["failures"] else "passed"
    Path(args.report).parent.mkdir(parents=True,exist_ok=True)
    Path(args.report).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":report["status"],"totals":report["totals"],"failures":report["failures"]},ensure_ascii=False),flush=True)
    return 1 if report["failures"] else 0


if __name__=="__main__":raise SystemExit(main())
