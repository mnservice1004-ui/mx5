"""Make and verify a portable bundle of files deliberately excluded from Git.

Git carries the code and tracked manifests. This bundle carries the original
media, produced editions, source/OCR images, local manifests and review records.
It never contains the virtual environment, credentials or rendering caches.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE = ROOT / 'handoff/mx5-handoff-state-2026-10-19.zip'
WORK_DIRS = {'source', 'ocr_text', 'ocr_bounds', 'ocr_images',
             'cover_assets', 'book_headers', 'education_pilot', 'tools_parts_audit'}
REQUIRED = {'inputs/정비매뉴얼.zip', 'work/draft_education_manifest.json',
            '.project-location.json'}


def sha_stream(stream):
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
        digest.update(chunk)
    return digest.hexdigest()


def wanted(name):
    parts = PurePosixPath(name).parts
    if len(parts) == 1:
        return name == '.project-location.json'
    if parts[0] in {'inputs', 'outputs', 'reports'}:
        return True
    if parts[0] == 'work':
        return parts[1] in WORK_DIRS or (len(parts) == 2 and name.endswith('.json'))
    return False


def sources():
    names = subprocess.check_output(
        ['git', 'ls-files', '--others', '--ignored', '--exclude-standard', '-z'], cwd=ROOT)
    selected = []
    for name in names.decode('utf-8').split('\0'):
        if name and wanted(name):
            path = ROOT / name
            if path.is_file() and not path.is_symlink():
                selected.append(name.replace('\\', '/'))
    selected = sorted(set(selected))
    assert REQUIRED.issubset(selected), f'Missing handoff input: {sorted(REQUIRED-set(selected))}'
    assert len([x for x in selected if x.startswith('work/source/') and x.endswith('.pdf')]) == 149
    assert len([x for x in selected if x.startswith('work/ocr_images/') and x.endswith('.png')]) == 383
    assert len([x for x in selected if x.startswith('outputs/') and x.endswith('.pdf')]) >= 33
    return selected


def checked_manifest(archive):
    with zipfile.ZipFile(archive) as bundle:
        assert 'handoff_manifest.json' in bundle.namelist(), 'Bundle has no handoff manifest'
        manifest = json.loads(bundle.read('handoff_manifest.json'))
        assert manifest['schema_version'] == 1
        expected = {row['path']: row for row in manifest['files']}
        assert len(expected) == len(manifest['files']), 'Duplicate paths in handoff manifest'
        assert set(bundle.namelist()) == set(expected) | {'handoff_manifest.json'}
        for name, row in expected.items():
            parts = PurePosixPath(name).parts
            assert parts and not any(p in {'', '.', '..'} for p in parts), name
            assert wanted(name), f'Unexpected path in bundle: {name}'
            assert bundle.getinfo(name).file_size == row['bytes'], f'Size differs: {name}'
            with bundle.open(name) as stream:
                assert sha_stream(stream) == row['sha256'], f'SHA-256 differs: {name}'
    return manifest


def create(archive):
    assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT).strip(), \
        'Commit and push project changes before taking a handoff snapshot'
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    branch = subprocess.check_output(['git', 'branch', '--show-current'], cwd=ROOT, text=True).strip()
    remote = subprocess.check_output(['git', 'ls-remote', 'origin', f'refs/heads/{branch}'],
                                     cwd=ROOT, text=True).split()[0]
    assert commit == remote, 'Push and verify the source commit before making a handoff snapshot'
    names = sources()
    assert not archive.exists(), 'Handoff archive already exists; choose a new path to preserve it'
    archive.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=3, allowZip64=True) as bundle:
        for index, name in enumerate(names, 1):
            path = ROOT / name
            with path.open('rb') as stream:
                digest = sha_stream(stream)
            rows.append({'path': name, 'bytes': path.stat().st_size, 'sha256': digest})
            bundle.write(path, name)
            if index % 200 == 0:
                print(f'Packed {index}/{len(names)} files', flush=True)
        manifest = {'schema_version': 1, 'repository': 'mnservice1004-ui/mx5',
                    'source_commit': commit, 'source_project_root': str(ROOT),
                    'files': rows, 'excluded': ['.git/', '.venv/', '.cache/',
                                               'work/service_visual_qa/']}
        bundle.writestr('handoff_manifest.json',
                        json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    verified = checked_manifest(archive)
    assert verified['source_commit'] == commit
    with archive.open('rb') as stream:
        archive_sha = sha_stream(stream)
    receipt = {'status': 'passed', 'archive': str(archive), 'bytes': archive.stat().st_size,
               'sha256': archive_sha, 'source_commit': commit,
               'files': len(rows), 'uncompressed_bytes': sum(row['bytes'] for row in rows)}
    report = ROOT / 'reports/handoff_bundle.json'
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


def restore(archive, destination):
    manifest = checked_manifest(archive)
    destination = destination.resolve()
    assert (destination / '.git').exists(), 'Restore into a Git clone, not an empty folder'
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=destination, text=True).strip()
    compatible_successor = False
    if head != manifest['source_commit']:
        ancestor = subprocess.run(['git', 'merge-base', '--is-ancestor',
                                   manifest['source_commit'], head], cwd=destination)
        assert ancestor.returncode == 0, 'Clone the source commit recorded in the bundle'
        changed = subprocess.check_output(
            ['git', 'diff', '--name-only', '-z', manifest['source_commit'], head],
            cwd=destination).decode('utf-8').split('\0')
        changed = set(filter(None, changed))
        allowed = {'docs/다른_PC에서_이어하기.md', 'tools/handoff_bundle.py'}
        assert changed and changed.issubset(allowed), \
            f'Newer checkout changes project contents; make a new bundle: {sorted(changed-allowed)}'
        compatible_successor = True
    copied = skipped = 0
    with zipfile.ZipFile(archive) as bundle:
        for row in manifest['files']:
            target = destination.joinpath(*PurePosixPath(row['path']).parts)
            assert target.resolve().is_relative_to(destination), 'Path escapes destination'
            if target.exists():
                with target.open('rb') as stream:
                    assert sha_stream(stream) == row['sha256'], f'Existing file differs: {target}'
                skipped += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.handoff-', delete=False) as temp:
                temporary = Path(temp.name)
                with bundle.open(row['path']) as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        temp.write(chunk)
            try:
                with temporary.open('rb') as stream:
                    assert sha_stream(stream) == row['sha256'], f'Restored file differs: {target}'
                # An exclusive hard link makes a verified file visible without
                # replacing a file another process may have created meanwhile.
                os.link(temporary, target)
            finally:
                if temporary.exists():
                    temporary.unlink()
            copied += 1
    print(json.dumps({'status': 'passed', 'copied': copied, 'identical_existing': skipped,
                      'compatible_documentation_update': compatible_successor,
                      'destination': str(destination), 'next': 'python tools/project.py relocate'},
                     ensure_ascii=False, indent=2))


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    make = commands.add_parser('create')
    make.add_argument('--archive', type=Path, default=DEFAULT_ARCHIVE)
    check = commands.add_parser('verify')
    check.add_argument('archive', type=Path)
    unpack = commands.add_parser('restore')
    unpack.add_argument('archive', type=Path)
    unpack.add_argument('--destination', type=Path, default=ROOT)
    args = parser.parse_args()
    if args.command == 'create':
        create(args.archive.resolve())
    elif args.command == 'verify':
        manifest = checked_manifest(args.archive)
        print(json.dumps({'status': 'passed', 'files': len(manifest['files']),
                          'source_commit': manifest['source_commit']}, ensure_ascii=False))
    else:
        restore(args.archive.resolve(), args.destination)


if __name__ == '__main__':
    main()
