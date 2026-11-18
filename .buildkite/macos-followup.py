import hashlib
import json
import os
from pathlib import Path
import platform
import pwd
import stat
import subprocess
import time

def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=10)
        return {'exit': p.returncode, 'stdout': p.stdout.strip(), 'stderr': p.stderr.strip()}
    except Exception as e:
        return {'error': str(e)}

roots = ['/Users/runner/Library', '/Users/runner/.local', '/Library', '/Applications', '/usr/local/bin', '/Users', '/opt', '/usr/local', '/private/var/lib', '/private/var/root', '/private/etc', '/home', '/runner', '/actions-runner']
out = {'schema': 1, 'platform': platform.platform(), 'architecture': platform.machine(),
       'user': pwd.getpwuid(os.getuid()).pw_name, 'uid': os.getuid(),
       'os': command(['sw_vers']), 'roots': [], 'errors': [], 'symlinks': [],
       'metadata': [], 'nodes': [], 'limits': [],
       'environment': {k: os.environ.get(k) for k in ['RUNNER_TOOL_CACHE', 'AGENT_TOOLSDIRECTORY', 'RUNNER_ROOT', 'RUNNER_TEMP', 'NSC_IMAGE_ID', 'NSC_IMAGE_LABEL', 'NSC_IMAGE_SELECTORS']}}
seen = set()
nodes = set()
installations = set()
started = time.monotonic()
count = 0
skip = {'node_modules', '.git', 'builds', 'Caches', 'DerivedData', 'CoreSimulator', 'Developer', 'Android', 'Cellar', 'Caskroom', 'rustup', '.rustup'}
markers = {'Runner.Listener', 'Runner.Worker', 'run.sh', 'config.sh', 'runsvc.sh', '.runner'}

def walk(path, depth):
    global count
    if time.monotonic() - started > 180 or count > 350000:
        if not out['limits']:
            out['limits'].append('Global 180-second/350000-entry bound reached')
        return
    try:
        s = path.stat()
        if not stat.S_ISDIR(s.st_mode):
            return
        key = (s.st_dev, s.st_ino)
        if key in seen:
            return
        seen.add(key)
        entries = list(path.iterdir())
    except OSError as e:
        out['errors'].append({'path': str(path), 'error': str(e)})
        return
    names = {p.name for p in entries}
    found = sorted(names & markers)
    if found:
        out['metadata'].append({'directory': str(path), 'realpath': str(path.resolve()), 'markers': found})
        if 'Runner.Listener' in names or 'Runner.Worker' in names:
            installations.add(path.parent)
        if 'run.sh' in names and ('config.sh' in names or '.runner' in names):
            installations.add(path)
    for p in entries:
        count += 1
        try:
            if p.is_symlink():
                target = str(p.resolve())
                out['symlinks'].append({'path': str(p), 'target': target})
            if p.name == 'node' and 'externals' in p.parts and p.is_file():
                nodes.add(p)
            if p.is_dir() and p.name not in skip and not p.name.startswith('Xcode'):
                if depth < 14:
                    walk(p, depth + 1)
                else:
                    out['limits'].append('Depth14: ' + str(p))
        except (OSError, RuntimeError) as e:
            out['errors'].append({'path': str(p), 'error': str(e)})

for root in roots:
    p = Path(root)
    out['roots'].append({'path': root, 'exists': p.exists(), 'read': os.access(p, os.R_OK), 'search': os.access(p, os.X_OK)})
    walk(p, 0)

for root in sorted(installations):
    item = {'root': str(root), 'realpath': str(root.resolve()), 'entries': sorted(p.name for p in root.iterdir())}
    listener = root / 'bin/Runner.Listener'
    if listener.exists():
        item['version'] = command([str(listener), '--version'])
    out.setdefault('installations', []).append(item)
    ext = root / 'externals'
    if ext.exists():
        for p in ext.glob('node*/bin/node'):
            nodes.add(p)

for p in sorted(nodes):
    item = {'path': str(p), 'realpath': str(p.resolve()), 'readable': os.access(p, os.R_OK), 'executable': os.access(p, os.X_OK)}
    try:
        digest = hashlib.sha256()
        with p.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
        item['sha256'] = digest.hexdigest()
        item['version'] = command([str(p), '--version'])
        item['file'] = command(['file', '-L', str(p)])
    except Exception as e:
        item['error'] = str(e)
    out['nodes'].append(item)
out['search'] = {'entries': count, 'directories': len(seen), 'seconds': time.monotonic() - started,
                 'follow_symlinks': True, 'max_depth': 14, 'pruned_names': sorted(skip), 'pruned_prefixes': ['Xcode']}
out['packages'] = command(['sh', '-c', "pkgutil --pkgs | grep -Ei 'github|runner|namespace' || true"])
out['process_executables'] = command(['sh', '-c', "ps -axo comm= | grep -Ei 'runner|namespace|buildkite' || true"])
Path('macos-followup.json').write_text(json.dumps(out, indent=2) + '\n')
print(json.dumps({'nodes': out['nodes'], 'installations': out.get('installations', []), 'search': out['search'], 'errors': len(out['errors']), 'limits': len(out['limits'])}, indent=2))
