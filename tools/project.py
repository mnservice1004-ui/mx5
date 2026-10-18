"""Local entry points for the maintenance-booklet project."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'project.json').read_text(encoding='utf-8'))


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def manifest_path(edition):
    return ROOT / CONFIG[{'current': 'edition_manifest', 'pilot': 'pilot_manifest',
                         'draft': 'draft_manifest'}[edition]]


def run_work(name, *args):
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    return subprocess.call([sys.executable, str(ROOT / 'work' / name), *map(str, args)],
                           cwd=ROOT, env=env)


def doctor():
    failures = []
    versions = {}
    for row in (ROOT / 'requirements.txt').read_text().splitlines():
        if not row or row.startswith('#'):
            continue
        name, expected = row.split('==')
        try:
            actual = importlib.metadata.version(name)
            versions[name] = actual
            if actual != expected:
                failures.append(f'{name}: expected {expected}, got {actual}')
        except importlib.metadata.PackageNotFoundError:
            failures.append(f'Missing dependency: {name}')
    for name in ('malgun.ttf', 'malgunbd.ttf'):
        if not (Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / name).is_file():
            failures.append(f'Missing Korean font: {name}')
    checked = {}

    def check(path, expected=None):
        path = Path(path).resolve()
        if not path.is_relative_to(ROOT):
            failures.append(f'Input still outside this project: {path}')
            return
        if not path.is_file():
            failures.append(f'Missing file: {path}')
            return
        if path not in checked:
            checked[path] = sha256(path)
        if expected and checked[path] != expected:
            failures.append(f'Hash mismatch: {path}')

    global_manifest = load(ROOT / 'work/booklet_manifest.json')
    for filename, expected in global_manifest['source_sha256'].items():
        check(ROOT / 'work/source' / filename, expected)
    for key in ('baseline_manifest', 'edition_manifest'):
        manifest = load(ROOT / CONFIG[key])
        for item in manifest['items'] + manifest['indexes']:
            check(item['path'], item['sha256'])
            if 'asset' in item:
                check(item['asset']['image_path'])
    edition = load(manifest_path('current'))
    for bundle in edition['bundles']:
        check(bundle['path'], bundle['sha256'])
    check(ROOT / CONFIG['source_archive'])
    receipt = ROOT / 'reports/import_manifest.json'
    if receipt.is_file():
        for record in load(receipt)['files']:
            if record['path'] == CONFIG['source_archive']:
                check(ROOT / record['path'], record['sha256'])
    result = {'status': 'passed' if not failures else 'failed',
              'python': sys.executable, 'packages': versions,
              'source_pdfs': len(global_manifest['source_sha256']),
              'booklets': len(edition['items']), 'indexes': len(edition['indexes']),
              'pages': sum(v['total_pages'] for v in edition['items'] + edition['indexes']),
              'files_hash_checked': len(checked), 'failures': failures}
    save(ROOT / 'reports/project_check.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return int(bool(failures))


def preview(args, original=False):
    import pypdfium2 as pdfium
    if original:
        if Path(args.file).name != args.file:
            raise ValueError('Use a source PDF filename without folders.')
        source = ROOT / 'work/source' / args.file
        stem = Path(args.file).stem + '-source'
    else:
        manifest = load(manifest_path(args.edition))
        match = next((v for v in manifest['items'] if v['id'] == args.book), None)
        if match is None:
            raise ValueError(f'Unknown booklet ID: {args.book}')
        source = Path(match['path'])
        stem = args.book + '-' + args.edition
    with pdfium.PdfDocument(source) as pdf:
        if not 1 <= args.page <= len(pdf):
            raise ValueError(f'Page must be between 1 and {len(pdf)}')
        page = pdf[args.page - 1]
        bitmap = page.render(scale=1.5)
        destination = ROOT / 'reports/previews' / f'{stem}-p{args.page:03d}.png'
        destination.parent.mkdir(parents=True, exist_ok=True)
        bitmap.to_pil().save(destination)
        bitmap.close()
        page.close()
    print(destination)
    return 0


def relocate():
    location_file = ROOT / '.project-location.json'
    receipt = load(location_file) if location_file.exists() else load(ROOT / 'reports/import_manifest.json')
    old = receipt['project_root']
    prefixes = (old, old.replace('\\', '/'))

    def convert(value):
        if isinstance(value, str):
            for prefix in prefixes:
                if value.startswith(prefix):
                    return str(ROOT) + value[len(prefix):]
            return value
        if isinstance(value, list):
            return [convert(v) for v in value]
        if isinstance(value, dict):
            return {k: convert(v) for k, v in value.items()}
        return value

    changed = []
    for path in (ROOT / 'work').rglob('*.json'):
        original = load(path)
        updated = convert(original)
        if original != updated:
            save(path, updated)
            changed.append(path.relative_to(ROOT).as_posix())
    save(location_file, {'project_root': str(ROOT)})
    print(json.dumps({'project_root': str(ROOT), 'rebased_json_files': changed}, ensure_ascii=False))
    return 0


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='Check packages, local files, and preserved source/output hashes')
    sub.add_parser('relocate', help='Rebase copied JSON paths after moving this whole project')
    pilot = sub.add_parser('pilot', help='Build selected booklets and all three indexes as a local draft')
    pilot.add_argument('--books', default='07-02')
    sub.add_parser('build', help='Build 30 booklets, three indexes and three ZIPs in the draft location')
    verify = sub.add_parser('verify', help='Verify the imported edition or a generated draft')
    verify.add_argument('--edition', choices=('current', 'pilot', 'draft'), default='current')
    render=sub.add_parser('render', help='Run full visual QA of an education edition')
    render.add_argument('--edition', choices=('current','pilot','draft'),default='draft')
    service_check=sub.add_parser('verify-service',help='Verify service evidence, guide summaries, and index details')
    service_check.add_argument('--edition',choices=('pilot','draft'),default='draft')
    page = sub.add_parser('preview', help='Render one booklet page as a PNG')
    page.add_argument('--book', default='07-02')
    page.add_argument('--page', type=int, default=2)
    page.add_argument('--edition', choices=('current', 'pilot', 'draft'), default='current')
    source = sub.add_parser('preview-source', help='Render one original source page as a PNG')
    source.add_argument('--file', required=True)
    source.add_argument('--page', type=int, default=1)
    args = parser.parse_args()
    if args.command == 'doctor':
        return doctor()
    if args.command == 'relocate':
        return relocate()
    if args.command == 'pilot':
        return run_work('build_education_booklets.py', '--pilot', args.books,
                        '--output-dir', ROOT / 'work/education_pilot',
                        '--manifest', manifest_path('pilot'))
    if args.command == 'build':
        return run_work('build_education_booklets.py', '--output-dir', ROOT / CONFIG['draft_output'],
                        '--manifest', ROOT / CONFIG['draft_manifest'])
    if args.command == 'verify':
        extra = ['--pilot'] if args.edition == 'pilot' else []
        return run_work('verify_education_booklets.py', '--manifest', manifest_path(args.edition),
                        '--source-archive', ROOT / CONFIG['source_archive'],
                        '--report', ROOT / f'reports/{args.edition}_edition_qa.json', *extra)
    if args.command == 'render':
        return run_work('render_education_qa.py','--manifest',manifest_path(args.edition),
                        '--output-dir',ROOT/f'work/service_visual_qa/{args.edition}',
                        '--report',ROOT/f'reports/{args.edition}_visual_qa.json')
    if args.command == 'verify-service':
        return subprocess.call([sys.executable,str(ROOT/'tools/verify_service_additions.py'),
            '--manifest',str(manifest_path(args.edition)),
            '--report',str(ROOT/('reports/service_content_qa.json' if args.edition=='draft'
                                else 'reports/service_pilot_content_qa.json'))],cwd=ROOT,
            env=dict(os.environ,PYTHONIOENCODING='utf-8'))
    if args.command in ('preview', 'preview-source'):
        return preview(args, original=args.command == 'preview-source')
    return 2


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1)
