"""Convert project-internal paths in tracked work manifests to portable paths.

Run from any directory. Only paths under this checkout are changed; recorded
external source paths and PDF hashes are preserved. Use --check in CI or after
editing a manifest and --write to convert newly introduced local paths.
"""
from pathlib import Path
import argparse
import json
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def tracked_manifests():
    names = subprocess.check_output(['git', 'ls-files', '-z', '--', 'work/*.json'], cwd=ROOT)
    return [ROOT / name for name in names.decode('utf-8').split('\0') if name]


def portable(value, changes):
    if isinstance(value, dict):
        return {key: portable(item, changes) for key, item in value.items()}
    if isinstance(value, list):
        return [portable(item, changes) for item in value]
    if isinstance(value, str):
        normalized = value.replace('/', '\\')
        prefix = str(ROOT).replace('/', '\\') + '\\'
        if normalized.lower().startswith(prefix.lower()):
            relative = normalized[len(prefix):].replace('\\', '/')
            assert relative and '..' not in Path(relative).parts
            changes.append(relative)
            return relative
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--check', action='store_true', help='Fail if a tracked manifest still uses this PC path')
    group.add_argument('--write', action='store_true', help='Convert this PC paths to project-relative paths')
    args = parser.parse_args()
    changed = []
    for path in tracked_manifests():
        before = json.loads(path.read_text(encoding='utf-8-sig'))
        found = []
        after = portable(before, found)
        if not found:
            continue
        changed.append({'manifest': path.relative_to(ROOT).as_posix(), 'paths': len(found)})
        if args.write:
            path.write_bytes((json.dumps(after, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps({'status': 'passed' if args.write or not changed else 'failed',
                      'changed': changed, 'total_paths': sum(x['paths'] for x in changed)},
                     ensure_ascii=False, indent=2))
    return int(args.check and bool(changed))


if __name__ == '__main__':
    raise SystemExit(main())
