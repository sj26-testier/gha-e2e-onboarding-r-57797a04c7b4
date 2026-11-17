import datetime
import glob
import hashlib
import json
import os
import platform
import shutil
import subprocess
from pathlib import Path


def command(args):
    try:
        p = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=15)
        return {'exit': p.returncode, 'stdout': p.stdout.strip(), 'stderr': p.stderr.strip()}
    except Exception as e:
        return {'error': str(e)}


def access(path):
    p = Path(path)
    return {'path': str(p), 'exists': p.exists(), 'realpath': os.path.realpath(p),
            'read': os.access(p, os.R_OK), 'write': os.access(p, os.W_OK),
            'execute': os.access(p, os.X_OK)}


report = {'utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'phase': 'host-before-compatibility-runtime', 'platform': platform.platform(),
          'architecture': platform.machine(), 'identity': command(['id']),
          'environment': {k: os.environ.get(k) for k in [
              'RUNNER_TOOL_CACHE', 'AGENT_TOOLSDIRECTORY', 'HOME', 'USER', 'ImageOS', 'ImageVersion',
              'NSC_BASE_IMAGE', 'NSC_IMAGE_ID', 'MISE_DATA_DIR', 'MISE_INSTALLS_DIR',
              'BUILDKITE_AGENT_META_DATA_QUEUE', 'BUILDKITE_AGENT_META_DATA_NSC_GHA_IMAGE',
              'BUILDKITE_AGENT_META_DATA_NSC_IMAGE_SELECTORS']},
          'os_release': Path('/etc/os-release').read_text() if Path('/etc/os-release').exists() else None,
          'sw_vers': command(['sw_vers']) if platform.system() == 'Darwin' else None,
          'errors': [], 'search_roots': [], 'executors': [], 'node_candidates': [], 'tool_caches': [],
          'root_directories': sorted(str(p) for p in Path('/').iterdir() if p.is_dir())}

roots = ['/opt', '/home/runner', '/Users/runner', '/usr/local/lib', '/usr/local/share',
         '/actions-runner', '/runner', '/runners', '/var/lib/github-runner', '/var/lib/buildkite-agent']
prune = {'.git', 'node_modules', 'hostedtoolcache', 'tool-cache', 'mise', '.cache', '.rustup',
         '.cargo', 'Library', 'Xcode.app', 'builds', 'cache', '.npm', '.local', 'site-packages'}
candidates = {}
for root in roots:
    report['search_roots'].append(access(root))
    if not os.path.isdir(root):
        continue
    base_depth = root.rstrip('/').count('/')
    def error(e):
        report['errors'].append(str(e))
    for directory, dirs, files in os.walk(root, onerror=error):
        depth = directory.count('/') - base_depth
        dirs[:] = [d for d in dirs if d not in prune and not d.startswith('Xcode')]
        if depth >= 7:
            dirs[:] = []
        if Path(directory).name == 'externals':
            report['executors'].append({'externals': directory, 'children': sorted(dirs)})
            for node in glob.glob(directory + '/node*/bin/node'):
                candidates[node] = 'action-executor'
            dirs[:] = []

cache_roots = set(filter(None, [os.environ.get('RUNNER_TOOL_CACHE'),
    os.environ.get('AGENT_TOOLSDIRECTORY'), '/opt/hostedtoolcache', '/Users/runner/hostedtoolcache',
    '/Users/runner/work/_tool', '/home/runner/work/_tool']))
for root in sorted(cache_roots):
    cache = access(root)
    cache['entries'] = []
    if os.path.isdir(root):
        try:
            for tool in sorted(Path(root).iterdir()):
                if not tool.is_dir():
                    continue
                versions = []
                for version in sorted(tool.iterdir()):
                    if not version.is_dir():
                        continue
                    architectures = []
                    for arch in sorted(version.iterdir()):
                        if arch.is_dir() or arch.name.endswith('.complete'):
                            architectures.append({'name': arch.name, 'directory': arch.is_dir(),
                                'read': os.access(arch, os.R_OK), 'write': os.access(arch, os.W_OK)})
                            if arch.is_dir() and tool.name.lower() == 'node':
                                node = arch / 'bin/node'
                                if node.is_file():
                                    candidates[str(node)] = 'setup-action-tool-cache'
                    versions.append({'version': version.name, 'architectures_and_markers': architectures})
                cache['entries'].append({'tool': tool.name, 'versions': versions})
        except Exception as e:
            cache['error'] = str(e)
    report['tool_caches'].append(cache)

path_node = shutil.which('node')
report['path_node'] = path_node
if path_node:
    candidates.setdefault(path_node, 'PATH')
report['mise_roots'] = []
for root in ['/cache/bkcache/buildkite-gha/mise', '/tmp/bkcache/buildkite-gha/mise',
             os.path.expanduser('~/.local/share/mise'), '/opt/mise']:
    item = access(root)
    item['node_directories'] = sorted(glob.glob(root + '/**/installs/node/*', recursive=True)) if item['exists'] else []
    report['mise_roots'].append(item)

for path, kind in sorted(candidates.items()):
    item = access(path)
    item['kind'] = kind
    item['version'] = command([path, '--version'])
    try:
        h = hashlib.sha256()
        with open(path, 'rb') as f:
            for block in iter(lambda: f.read(1024 * 1024), b''):
                h.update(block)
        item['sha256'] = h.hexdigest()
    except Exception as e:
        item['hash_error'] = str(e)
    report['node_candidates'].append(item)

out = os.environ.get('INVENTORY_OUTPUT', 'unix-inventory.json')
Path(out).write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report, indent=2))
