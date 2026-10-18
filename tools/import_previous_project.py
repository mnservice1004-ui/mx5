"""Copy selected existing material; never move or modify the source workspace."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULES = (
    'build_education_booklets.py', 'education_frontmatter.py',
    'education_body_layout.py', 'education_index_style.py',
    'verify_education_booklets.py', 'verify_binding_booklets.py',
    'verify_compact_booklets.py', 'verify_nested_final.py',
    'verify_photo_intro.py', 'render_education_qa.py',
)
DATA = (
    'booklet_manifest.json', 'folio_booklets_manifest.json',
    'education_booklets_manifest.json', 'education_structure_recommendation.json',
    'textbook_reference_design.json', 'front_cover_assets.json',
    'rear_cover_assets.json', 'other_cover_assets.json', 'inventory.json',
    'book_structure.json', 'door_item_structure.json',
    'reference_audit_candidates.json', 'reference_map.json',
    'reference_locations.json', 'reference_scope_overrides.json',
    'reference_detail_extra_map.json', 'reference_guide_map.json',
    'reference_guide_locations.json', 'reference_visual_supplements.json',
    'cut_qa_overrides.json',
)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from', dest='source', type=Path, required=True)
    parser.add_argument('--source-archive', type=Path, required=True)
    args = parser.parse_args()
    source = args.source.resolve()
    if source == ROOT:
        parser.error('Source and destination must differ.')
    records = []

    def transfer(src, rel):
        src = Path(src)
        dst = ROOT / rel
        if not src.is_file():
            raise FileNotFoundError(src)
        before = digest(src)
        if dst.exists():
            raise FileExistsError(f'Refusing to overwrite: {dst}')
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        assert digest(src) == before == digest(dst), str(src)
        records.append({'path': dst.relative_to(ROOT).as_posix(),
                        'source': str(src), 'sha256': before,
                        'bytes': dst.stat().st_size})

    for name in MODULES + DATA:
        transfer(source / 'work' / name, Path('work') / name)
    for folder in ('source', 'ocr_text', 'ocr_bounds', 'cover_assets',
                   'book_headers', 'tools_parts_audit'):
        base = source / 'work' / folder
        if base.is_dir():
            for src in sorted(base.rglob('*')):
                if src.is_file():
                    transfer(src, Path('work') / folder / src.relative_to(base))
    for edition in ('정비매뉴얼_좌측제본_쪽번호정렬본', '정비매뉴얼_교육교재_개선본'):
        base = source / 'outputs' / edition
        for src in sorted(base.rglob('*')):
            if src.is_file():
                transfer(src, Path('outputs') / edition / src.relative_to(base))
    for src in sorted((source / 'outputs').glob('*교육교재*zip')):
        transfer(src, Path('outputs') / src.name)
    transfer(args.source_archive, Path('inputs') / '정비매뉴얼.zip')
    for name in ('education_qa_report.json', 'education_visual_qa.json',
                 'education_frontmatter_qa.json', 'education_body_review.json'):
        if (source / 'work' / name).is_file():
            transfer(source / 'work' / name, Path('docs/previous_reports') / name)

    # Rewrite path values in copied data only. PDF/ZIP/image bytes stay identical.
    old_forms = (str(source), source.as_posix(), '\\\\?\\' + str(source))
    new_zip = str(ROOT / 'inputs' / '정비매뉴얼.zip')
    source_zip_forms = (str(args.source_archive), args.source_archive.as_posix())

    def relocate(value):
        if isinstance(value, str):
            for prefix in old_forms:
                if value.startswith(prefix):
                    return str(ROOT) + value[len(prefix):]
            if value in source_zip_forms:
                return new_zip
            return value
        if isinstance(value, list):
            return [relocate(v) for v in value]
        if isinstance(value, dict):
            return {k: relocate(v) for k, v in value.items()}
        return value

    for rec in records:
        path = ROOT / rec['path']
        if path.suffix.lower() == '.json' and rec['path'].startswith('work/'):
            original = json.loads(path.read_text(encoding='utf-8-sig'))
            updated = relocate(original)
            if original != updated:
                path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + '\n',
                                encoding='utf-8')
                rec['project_sha256'] = digest(path)
                rec['change'] = 'copied JSON path values rebased to this project'
    report = {'created_at': datetime.now(timezone.utc).isoformat(),
              'source_workspace': str(source), 'project_root': str(ROOT),
              'source_files_unchanged': True, 'files': records,
              'copied_files': len(records), 'copied_bytes': sum(r['bytes'] for r in records)}
    report_path = ROOT / 'reports/import_manifest.json'
    report_path.parent.mkdir(exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'files'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
