import os, pty, re, sys, time, select, shutil
from pathlib import Path
W = __import__("os").environ["W"]  # the repository checkout at the reviewed head
PY = W + "/engram/.venv/bin/python"
home = Path(sys.argv[1]); shutil.rmtree(home, ignore_errors=True); home.mkdir(parents=True)
cap = home / "captured.txt"
env = dict(os.environ, ENGRAM_HOME=str(home), PYTHONPATH=W + "/engram")
pid, fd = pty.fork()
if pid == 0:     # the person's terminal is the pty; the command's stdout is captured by 'an agent'
    out = os.open(str(cap), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.dup2(out, 1)
    os.execve(PY, [PY, "-c", "import sys, permission_cli; sys.exit(permission_cli.main(['init']))"], env)
seen = b""; code = None; t0 = time.time()
while time.time() - t0 < 20:
    r, _, _ = select.select([fd], [], [], 0.2)
    if r:
        try: chunk = os.read(fd, 4096)
        except OSError: break
        if not chunk: break
        seen += chunk
    if code is None and cap.exists():
        m = re.search(r"code: ([a-z0-9]{6})", cap.read_text())
        if m:
            code = m.group(1); print("terminal showed before the answer:", repr(seen))
            os.write(fd, code.encode() + b"\n")
_, st = os.waitpid(pid, 0)
print("exit", os.waitstatus_to_exitcode(st), "| ledger made:", (home / ".engram" / "permissions.db").exists())
