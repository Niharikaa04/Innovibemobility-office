#!/usr/bin/env python3
"""Mounts fleet_gps next to fleetapi in your FastAPI app. Run from your backend folder:
    python mount_fleet_gps.py            # dry run: shows the change, writes nothing
    python mount_fleet_gps.py --apply    # writes it (saves <file>.bak first)
It only edits when it finds exactly one line that mounts fleetapi in a form it understands; otherwise it prints what to add by hand."""
import difflib, re, shutil, sys
from pathlib import Path

APPLY = '--apply' in sys.argv
MOUNT = re.compile(r'^(?P<ind>[ \t]*)(?P<obj>[A-Za-z_][\w.]*)\.include_router\(\s*fleetapi\.build_router\(', re.M)   # \s also spans line breaks

def balanced_args(text: str, start: int):
    """text[start] is just after '('. Returns the argument string up to the matching ')'."""
    depth, i = 1, start
    while i < len(text) and depth:
        depth += {'(': 1, ')': -1}.get(text[i], 0); i += 1
    return text[start:i - 1] if depth == 0 else None

def first_arg(args: str):
    depth = 0
    for i, ch in enumerate(args):
        if ch in '([{': depth += 1
        elif ch in ')]}': depth -= 1
        elif ch == ',' and depth == 0: return args[:i].strip()
    return args.strip()

def process(path: Path):
    src = path.read_text(encoding='utf-8')
    if 'fleet_gps' in src: return ('skip', f'{path}: already mentions fleet_gps - nothing to do')
    hits = list(MOUNT.finditer(src))
    if not hits:
        if 'fleetapi.build_router(' in src:
            return ('manual', f'{path}: mounts fleetapi in a form I will not guess at. Add by hand, after that router is included, using the SAME arguments:\n'
                              '    import fleet_gps\n    app.include_router(fleet_gps.build_router(<same args as fleetapi.build_router>))\n    app.include_router(fleet_gps.build_ingest_router(<first arg: dsn>))')
        return None
    if len(hits) != 1: return ('manual', f'{path}: found {len(hits)} mount lines for fleetapi (need exactly 1)')
    m = hits[0]; stmt_start = m.start()
    # the whole statement may span lines: take text from this line to the end of the matching paren of include_router(
    body = src[stmt_start:]
    call_open = body.index('include_router(') + len('include_router(')
    inner = balanced_args(body, call_open)
    if inner is None: return ('manual', f'{path}: could not parse the mount statement')
    bm = re.match(r'\s*fleetapi\.build_router\(', inner)
    args = balanced_args(inner, bm.end())
    if args is None: return ('manual', f'{path}: could not parse build_router arguments')
    end_stmt = stmt_start + call_open + len(inner) + 1             # just after the closing ')' of include_router
    nl = src.index('\n', end_stmt) + 1 if '\n' in src[end_stmt:] else len(src)
    dsn = re.sub(r'^\w+\s*=\s*', '', first_arg(args))
    ind, obj = m['ind'], m['obj']
    add = (f"{ind}{obj}.include_router(fleet_gps.build_router({args.strip()}))\n"
           f"{ind}{obj}.include_router(fleet_gps.build_ingest_router({dsn}))   # device-token auth, no session/CSRF\n")
    out = src[:nl] + add + src[nl:]
    imp = re.search(r'^(?P<ind>[ \t]*)import\s+[^\n#]*\bfleetapi\b[^\n]*\n', out, re.M)
    if imp: out = out[:imp.end()] + f"{imp['ind']}import fleet_gps\n" + out[imp.end():]
    else:
        fi = re.search(r'^(?:from\s+\S+\s+)?import\s+[^\n]*\bfleetapi\b[^\n]*\n', out, re.M)
        if not fi: return ('manual', f'{path}: mount line found but could not find the `import fleetapi` line; add `import fleet_gps` yourself')
        out = out[:fi.end()] + "import fleet_gps\n" + out[fi.end():]
    return ('edit', path, src, out)

def main():
    results = [r for p in sorted(Path('.').glob('*.py')) if p.name not in ('fleet_gps.py', 'fleetapi.py', Path(__file__).name) for r in [process(p)] if r]
    if not results: print('No file mounting fleetapi.build_router(...) found in this folder. Send me the file that creates your FastAPI app.'); return 1
    for r in results:
        if r[0] != 'edit': print(r[1]); continue
        _, path, old, new = r
        print(''.join(difflib.unified_diff(old.splitlines(1), new.splitlines(1), f'{path} (before)', f'{path} (after)', n=2)))
        if APPLY: shutil.copy(path, f'{path}.bak'); path.write_text(new, encoding='utf-8'); print(f'WROTE {path} (backup: {path}.bak). Restart the backend.')
        else: print('Dry run only. Re-run with --apply to write it.')
        if re.search(r'csrf', old, re.I) and re.search(r'add_middleware|@\w+\.middleware', old): print('NOTE: this file has middleware mentioning CSRF - make sure /api/gps/* is exempt (devices have no cookies).')
    return 0
sys.exit(main())
