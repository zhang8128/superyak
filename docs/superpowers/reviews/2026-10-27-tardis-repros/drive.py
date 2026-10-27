"""Run engram-permissions in a fresh pty (a 'person'), answering the printed code. Usage:
drive.py HOME [--answer X|--auto] -- args..."""
import os, pty, re, sys, select, time
W = __import__("os").environ["W"]  # the repository checkout at the reviewed head
PY = W + "/engram/.venv/bin/python"

def run(home, args, answer="auto", env_extra=None, pre=None, timeout=60):
    env = dict(os.environ, ENGRAM_HOME=str(home), PYTHONPATH=W + "/engram")
    env.update(env_extra or {})
    code = "import sys; sys.argv=['engram-permissions']+sys.argv[1:]\n" + (pre or "") + \
           "\nimport permission_cli; sys.exit(permission_cli.main(sys.argv[1:]))"
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(W + "/engram")
        os.execve(PY, [PY, "-c", code] + list(args), env)
    out = b""; answered = False; t0 = time.time()
    while time.time() - t0 < timeout:
        r, _, _ = select.select([fd], [], [], 0.5)
        if r:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            m = re.search(rb"code: ([a-z0-9]{6})", out)
            if m and not answered and answer is not None:
                os.write(fd, (m.group(1).decode() if answer == "auto" else answer).encode() + b"\n")
                answered = True
    _, status = os.waitpid(pid, 0)
    rc = os.waitstatus_to_exitcode(status)
    return rc, out.decode("utf-8", "replace").replace("\r\n", "\n")

if __name__ == "__main__":
    home = sys.argv[1]; args = sys.argv[sys.argv.index("--") + 1:]
    rc, out = run(home, args)
    print(out); print("EXIT", rc)
