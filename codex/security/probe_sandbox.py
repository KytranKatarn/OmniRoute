"""Run inside an empty, non-root probe container; no credentials/inference needed."""
import json
import os
from pathlib import Path
import subprocess

root = Path('/work/probe')
root.mkdir(parents=True, exist_ok=True)
(root / '.git').mkdir(exist_ok=True)
outside = Path('/work/outside')
outside.mkdir(exist_ok=True)
assert os.getuid() != 0
status = Path('/proc/self/status').read_text()
assert 'CapEff:\t0000000000000000' in status
assert 'NoNewPrivs:\t1' in status
assert 'Seccomp:\t2' in status
assert 'archie-codex-sandbox' in Path('/proc/self/attr/current').read_text()


def sandbox(mode, code):
    result = subprocess.run(
        ['codex', 'sandbox', '-c', 'sandbox_mode="' + mode + '"', '--',
         'python3', '-c', code], cwd=root, capture_output=True, text=True)
    assert result.returncode == 0, (result.returncode, result.stderr)
    return result.stdout.strip()


assert sandbox('workspace-write',
               "from pathlib import Path; Path('result').write_text('fixture'); print('written')") == 'written'
assert (root / 'result').read_text() == 'fixture'

for mode, target in [('read-only', root / 'readonly-denied'),
                     ('workspace-write', outside / 'outside-denied'),
                     ('workspace-write', root / '.git' / 'git-denied')]:
    code = """import errno
from pathlib import Path
try:
    Path(%r).write_text('unexpected')
except OSError as error:
    assert error.errno in (errno.EROFS, errno.EACCES, errno.EPERM), error
    print('denied')
else:
    raise AssertionError('write unexpectedly permitted')
""" % str(target)
    assert sandbox(mode, code) == 'denied'
    assert not target.exists()

network = """import errno, socket
try:
    socket.socket(socket.AF_INET, socket.SOCK_STREAM)
except OSError as error:
    assert error.errno in (errno.EACCES, errno.EPERM), error
    print('denied')
else:
    raise AssertionError('AF_INET socket unexpectedly permitted')
"""
assert sandbox('workspace-write', network) == 'denied'
print(json.dumps({'workspace_write': 'pass', 'readonly_denial': 'pass',
                  'outside_workspace_denial': 'pass', 'git_metadata_denial': 'pass',
                  'network_denial': 'pass', 'uid': os.getuid(),
                  'effective_capabilities': 0, 'no_new_privileges': True,
                  'apparmor': 'enforce', 'seccomp': 'filter'}))
