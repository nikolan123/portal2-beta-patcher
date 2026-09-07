"""Regenerate the compatibility matrix, or use --check to detect drift."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from patches.registry import DEFINITIONS, PROFILES

START = '<!-- compatibility:start -->'
END = '<!-- compatibility:end -->'


def render_matrix():
    profiles = sorted(PROFILES, key=lambda item: (item.target is None, item.id))
    lines = ['| Patch ID | ' + ' | '.join(profile.id for profile in profiles) + ' |',
             '| --- | ' + ' | '.join('---' for _ in profiles) + ' |']
    for definition in DEFINITIONS:
        cells = ['Required' if definition.id in profile.required else 'Optional' if definition.id in profile.optional else '—' for profile in profiles]
        lines.append(f'| `{definition.id}` | ' + ' | '.join(cells) + ' |')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    path = ROOT / 'src/patches/README.md'
    original = path.read_text(encoding='utf-8')
    before, remaining = original.split(START, 1)
    _, after = remaining.split(END, 1)
    updated = before + START + '\n\n' + render_matrix() + '\n\n' + END + after
    if args.check:
        if updated != original:
            raise SystemExit('Patch matrix is stale; run python tools/patch-docs.py')
        print('Patch documentation matches the registry.')
    else:
        path.write_text(updated, encoding='utf-8')


if __name__ == '__main__':
    main()
