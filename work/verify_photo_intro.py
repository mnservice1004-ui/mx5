"""Independent verification of cover replacement, without editing artifacts."""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
import unicodedata
import zipfile

from PIL import Image
from pypdf import PdfReader
from pypdf.generic import (
    ArrayObject, BooleanObject, ByteStringObject, DictionaryObject,
    IndirectObject, NullObject, StreamObject,
)

ROOT = pathlib.Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def filehash(path):
    return digest(pathlib.Path(path).read_bytes())


def normalized_text(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


class Canonical:
    """Resolve PDF objects while ignoring serialization object numbers."""
    def __init__(self):
        self.memo = {}

    def value(self, value, active=frozenset()):
        if isinstance(value, IndirectObject):
            key = (id(value.pdf), value.idnum, value.generation)
            if key in active:
                return {"circular_reference": True}
            if key not in self.memo:
                self.memo[key] = self.value(value.get_object(), active | {key})
            return self.memo[key]
        if isinstance(value, StreamObject):
            return {
                "stream_dictionary": {
                    str(k): self.value(v, active)
                    for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))
                    if str(k) != "/Length"
                },
                "encoded_sha256": digest(value._data),
                "decoded_sha256": digest(value.get_data()),
            }
        if isinstance(value, DictionaryObject):
            return {str(k): self.value(v, active)
                    for k, v in sorted(value.items(), key=lambda kv: str(kv[0]))}
        if isinstance(value, ArrayObject) or isinstance(value, (list, tuple)):
            return [self.value(v, active) for v in value]
        if isinstance(value, ByteStringObject) or isinstance(value, bytes):
            return {"bytes_sha256": digest(bytes(value))}
        if isinstance(value, (NullObject, type(None))):
            return None
        if isinstance(value, BooleanObject):
            return bool(value.value)
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return float(value)
        return str(value)

    def hash(self, value):
        return digest(json.dumps(self.value(value), ensure_ascii=False,
                                 sort_keys=True, separators=(",", ":")).encode())


def page_reference(reader, obj):
    if isinstance(obj, IndirectObject):
        return reader._get_page_number_by_indirect(obj)
    if isinstance(obj, int):
        return int(obj)
    return str(obj)


def destination(reader, value, canon):
    value = value.get_object() if isinstance(value, IndirectObject) else value
    if isinstance(value, (list, ArrayObject)) and value:
        return [page_reference(reader, value[0])] + canon.value(list(value[1:]))
    return canon.value(value)


def annotations(reader, page, canon):
    output = []
    for raw in page.get("/Annots", []):
        annot = raw.get_object()
        record = {}
        for key, value in annot.items():
            if key == "/P":
                continue  # Back reference to its own page.
            if key == "/Dest":
                record[str(key)] = destination(reader, value, canon)
            elif key == "/A":
                action = value.get_object()
                action_record = {}
                for ak, av in action.items():
                    if ak == "/D" and action.get("/S") == "/GoTo":
                        action_record[str(ak)] = destination(reader, av, canon)
                    else:
                        action_record[str(ak)] = canon.value(av)
                record[str(key)] = action_record
            else:
                record[str(key)] = canon.value(value)
        output.append(record)
    return output


def outlines(reader, entries=None):
    if entries is None:
        entries = reader.outline
    result = []
    for entry in entries:
        if isinstance(entry, list):
            result.append(outlines(reader, entry))
            continue
        result.append({
            "title": entry.title,
            "page": reader.get_destination_page_number(entry),
            "type": str(entry.typ),
            "left": str(entry.left), "right": str(entry.right),
            "top": str(entry.top), "bottom": str(entry.bottom),
            "zoom": str(entry.zoom),
            "extra": {str(k): str(v) for k, v in entry.items()
                      if k not in ("/Title", "/Page", "/Type", "/Left", "/Right",
                                   "/Top", "/Bottom", "/Zoom")},
        })
    return result


def count_outlines(entries):
    return sum(count_outlines(e) if isinstance(e, list) else 1 for e in entries)


def xobjects(resources, seen=None):
    seen = set() if seen is None else seen
    output = []
    for name, raw in resources.get("/XObject", {}).items():
        value = raw.get_object()
        identity = id(value)
        if identity in seen:
            continue
        seen.add(identity)
        output.append((str(name), value))
        if value.get("/Subtype") == "/Form" and "/Resources" in value:
            output.extend(xobjects(value["/Resources"], seen))
    return output


def remote_links(path, reader):
    rows = []
    for page_no, page in enumerate(reader.pages, 1):
        for raw in page.get("/Annots", []):
            a = raw.get_object().get("/A")
            if not a:
                continue
            a = a.get_object()
            if a.get("/S") != "/GoToR":
                continue
            filename = a["/F"]
            if isinstance(filename, DictionaryObject):
                filename = filename.get("/UF", filename.get("/F"))
            filename = str(filename).replace("\\", "/")
            target = pathlib.Path(path).parent / filename
            assert target.is_file(), ("missing remote target", str(path), filename)
            d = a.get("/D")
            if isinstance(d, (list, ArrayObject)) and d and isinstance(d[0], int):
                tr = PdfReader(target)
                assert 0 <= int(d[0]) < len(tr.pages), ("remote page", filename, d)
            rows.append({"page": page_no, "target": filename})
    return rows


def main():
    manifest_path = ROOT / "photo_intro_manifest.json"
    assert manifest_path.is_file(), "Wait for photo_intro_manifest.json to be complete."
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    old_manifest = json.loads((ROOT / "door_booklets_manifest.json").read_text(encoding="utf-8"))
    old_by_id = {item["id"]: item for item in old_manifest["items"]}
    assert len(manifest["items"]) == 30
    report = {"status": "passed", "items": [], "indexes": [], "bundles": []}
    counters = {"noncover_pages_preserved": 0, "technical_body_pages_preserved": 0,
                "reference_pages_preserved": 0, "annotations_preserved": 0,
                "links_preserved": 0, "original_forms_preserved": 0,
                "outlines_preserved": 0, "cover_images": 0, "index_remote_links": 0}

    for item in manifest["items"]:
        original = old_by_id[item["id"]]
        before = pathlib.Path(item["source_path"])
        after = pathlib.Path(item["path"])
        assert filehash(before) == item["source_sha256"] == original["sha256"]
        assert filehash(after) == item["sha256"]
        src, new = PdfReader(before), PdfReader(after)
        assert len(src.pages) == len(new.pages) == item["total_pages"]
        assert len(new.pages) % 2 == 0
        old_canon, new_canon = Canonical(), Canonical()
        item_links = item_forms = 0
        for page_index in range(1, len(src.pages)):
            left, right = src.pages[page_index], new.pages[page_index]
            assert left.get_contents().get_data() == right.get_contents().get_data(), \
                (item["id"], page_index + 1, "page content changed")
            assert old_canon.hash(left["/Resources"]) == new_canon.hash(right["/Resources"]), \
                (item["id"], page_index + 1, "fonts/images/forms/resources changed")
            page_keys = (set(left.keys()) | set(right.keys())) - {"/Parent", "/Resources", "/Contents", "/Annots"}
            for key in page_keys:
                assert old_canon.hash(left.get(key)) == new_canon.hash(right.get(key)), \
                    (item["id"], page_index + 1, key)
            ann_old = annotations(src, left, old_canon)
            ann_new = annotations(new, right, new_canon)
            assert ann_old == ann_new, (item["id"], page_index + 1, "annotation changed")
            count = sum(a.get("/Subtype") == "/Link" for a in ann_old)
            item_links += count
            counters["annotations_preserved"] += len(ann_old)
            if "/Original" in left["/Resources"].get("/XObject", {}):
                item_forms += 1
            counters["noncover_pages_preserved"] += 1
        old_outline, new_outline = outlines(src), outlines(new)
        assert old_outline == new_outline, (item["id"], "outlines changed")
        bookmark_count = count_outlines(old_outline)

        asset = item["asset"]
        extracted = normalized_text(new.pages[0].extract_text())
        expected = [item["title"], asset["intro"], asset["caption"], asset["image_kind"],
                    asset["source_file"], f"{asset['source_page']}쪽"]
        for step in asset["workflow"]:
            expected += [step["title"], step.get("description", "")]
        for text in expected:
            assert normalized_text(text) in extracted, (item["id"], "cover text missing", text)
        images = [obj for _, obj in xobjects(new.pages[0]["/Resources"])
                  if obj.get("/Subtype") == "/Image"]
        assert images, (item["id"], "no cover image")
        expected_img = Image.open(asset["image_path"]).convert("RGB")
        image_hash = digest(expected_img.tobytes())
        assert any(int(obj["/Width"]) == expected_img.width
                   and int(obj["/Height"]) == expected_img.height
                   and digest(obj.get_data()) == image_hash for obj in images), \
            (item["id"], "embedded image differs from chosen source crop")
        cover_links = annotations(new, new.pages[0], new_canon)
        assert len(cover_links) == 2 and [a.get("/Dest", [None])[0] for a in cover_links] == [2, item["front_pages"]], \
            (item["id"], "cover index/body link incorrect", cover_links)
        for link in cover_links:
            rect = link["/Rect"]
            assert 0 <= rect[0] < rect[2] <= 595.28 and 0 <= rect[1] < rect[3] <= 841.89
        counters["technical_body_pages_preserved"] += original["body_pages"]
        counters["reference_pages_preserved"] += len(original["reference_page_meta"])
        counters["links_preserved"] += item_links
        counters["original_forms_preserved"] += item_forms
        counters["outlines_preserved"] += bookmark_count
        counters["cover_images"] += len(images)
        report["items"].append({"id": item["id"], "pages": len(new.pages),
                                "noncover_pages_preserved": len(new.pages) - 1,
                                "technical_body_pages_preserved": original["body_pages"],
                                "links_preserved": item_links, "outlines_preserved": bookmark_count,
                                "original_forms_preserved": item_forms, "cover_image_sha256": image_hash})
        print(f"{item['id']}: {len(new.pages)-1} non-cover pages, {item_links} links, {bookmark_count} bookmarks unchanged", flush=True)

    assert counters["technical_body_pages_preserved"] == 930
    assert counters["reference_pages_preserved"] == 484
    assert len(manifest["indexes"]) == 3
    for index in manifest["indexes"]:
        src = pathlib.Path(index["source_path"])
        dst = pathlib.Path(index["path"])
        assert src.read_bytes() == dst.read_bytes()
        assert filehash(dst) == index["sha256"]
        links = remote_links(dst, PdfReader(dst))
        counters["index_remote_links"] += len(links)
        report["indexes"].append({"path": str(dst), "byte_identical": True,
                                  "remote_links": len(links), "all_targets_exist": True})

    assert len(manifest["bundles"]) == 3
    for bundle in manifest["bundles"]:
        path = pathlib.Path(bundle["path"])
        if "프런트" in path.name:
            expected = [r for r in manifest["items"] if r["part"] == 7] + [manifest["indexes"][1]]
        elif "리어" in path.name:
            expected = [r for r in manifest["items"] if r["part"] == 8] + [manifest["indexes"][2]]
        else:
            expected = manifest["items"] + manifest["indexes"]
        assert filehash(path) == bundle["sha256"]
        assert path.stat().st_size == bundle["bytes"]
        with zipfile.ZipFile(path) as archive:
            assert archive.testzip() is None, (path, "CRC failure")
            names = archive.namelist()
            assert len(names) == len(set(names)) == bundle["files"] == len(expected)
            assert set(names) == {r["relative_path"] for r in expected}
            for record in expected:
                assert archive.read(record["relative_path"]) == pathlib.Path(record["path"]).read_bytes(), \
                    (path, record["relative_path"], "ZIP member differs")
        report["bundles"].append({"path": str(path), "files": len(expected), "crc_passed": True,
                                  "all_members_byte_identical": True, "sha256": bundle["sha256"]})
    report["totals"] = counters
    (ROOT / "photo_intro_qa_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(counters, ensure_ascii=False), flush=True)
    print("PASS: cover-only changes verified; source PDFs preserved; all bundles verified.", flush=True)


if __name__ == "__main__":
    main()
