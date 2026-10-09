#!/usr/bin/env python3
"""Browser-lane acceptance, the worker's side (docs/superpowers/specs/2026-10-08-browser-lane-design.md, "Mac
acceptance", steps 2, 3, 5 and 6). team/scripts/lane_acceptance.py copies this folder into a browser worker's
node_modules/.superyak-lane-acceptance/ and asks the worker to run it once:

    <python> node_modules/.superyak-lane-acceptance/worker_probes.py <round>

so every probe runs INSIDE the worker's sandbox, with the lane's environment. It reads params.json (written by the
driver from outside) and writes results-<round>.json beside it. The driver, not the model, judges each row: "expect"
is ok (must succeed, exit 0), fail (must be refused) or info. It never prints a file's contents or the endpoint.
Stdlib only.
"""
import ctypes
import errno
import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEAKS = ("SUPERYAK_BROKER_SECRET=", "PW_TEST_CONNECT_WS_ENDPOINT=")
# Every negative probe returns (code, text) in profile_probe.js's convention: 0 the action SUCCEEDED, 1 it was REFUSED
# ("refused: <CODE> (...)"), 2 the probe could not tell ("broken: ..."). The driver counts a refusal only if its code
# is one the sandbox gives (the lists below); a timeout, ENOENT or a crash proves nothing and is BROKEN.
NET_REFUSALS = ("EPERM", "EACCES", "ECONNREFUSED", "ENETUNREACH", "EHOSTUNREACH", "ENOTFOUND", "EAI_AGAIN", "EAI_FAIL",
                "curl-6", "curl-7")
SOCKET_REFUSALS = ("EPERM", "EACCES")
READ_REFUSALS = ("EPERM", "EACCES")
CONNECT = ("const s = require('net').connect(process.argv[1]);"
           "s.on('connect', () => { console.log('succeeded'); process.exit(0); });"
           "s.on('error', e => { console.log('refused: ' + (e.code || 'nocode')); process.exit(1); });"
           "s.setTimeout(5000, () => { console.log('broken: timeout'); process.exit(2); });")
CONNECT_TCP = ("const s = require('net').connect(80, '1.1.1.1');"
               "s.on('connect', () => { console.log('succeeded'); process.exit(0); });"
               "s.on('error', e => { console.log('refused: ' + (e.code || 'nocode')); process.exit(1); });"
               "s.setTimeout(5000, () => { console.log('broken: timeout'); process.exit(2); });")
FETCH = ("fetch('https://' + process.argv[1], { signal: AbortSignal.timeout(8000) })"
         ".then(() => { console.log('succeeded'); process.exit(0); },"
         " e => { console.log('refused: ' + String((e.cause && e.cause.code) || e.code || 'nocode'));"
         " process.exit(1); })")


def run(cmd, timeout=60, cwd=None):
    """(exit code, the first 300 characters of its output on one line). Never raises."""
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, str(e)[:300]
    return r.returncode, " ".join(((r.stdout or "") + (r.stderr or "")).split())[:300]


def node(code, *args, timeout=60):
    return run(["node", "-e", code, *args], timeout=timeout)


def classify(rc, text):
    """A node probe's (exit code, text) as the convention above: anything else is "could not tell" (2)."""
    text = (text or "").strip()
    if rc == 0:
        return 0, text or "succeeded"
    if rc == 1 and text.startswith("refused:"):
        return 1, text
    return 2, text or ("exit %d" % rc)


def curl_result(rc, text):
    """curl's exit 6 (couldn't resolve) and 7 (couldn't connect) are the sandbox's refusals; 28 (timeout) and the
    rest prove nothing."""
    if rc == 0:
        return 0, "succeeded"
    if rc in (6, 7):
        return 1, "refused: curl-%d (%s)" % (rc, text[:120])
    if rc in (22, 56):                      # an HTTP error or a failed receive: a proxy answering, not the sandbox
        return 2, "broken: curl exit %d (proxy?) (%s)" % (rc, text[:120])
    return 2, "broken: curl exit %d (%s)" % (rc, text[:120])


def link_failure(e):
    """Making the link itself failed: ((code, text), accepted refusal codes). A deny-default sandbox refusing link()
    (EPERM or EACCES) IS the wall holding; EXDEV (another volume) or anything else says nothing about the wall."""
    name = errno.errorcode.get(e.errno, "nocode")
    if name in ("EPERM", "EACCES"):
        return (1, "refused: %s (the sandbox refused the link)" % name), ("EPERM", "EACCES")
    return (1, "refused: %s (can't make the link: not the sandbox's wall)" % name), ()


def libsystem():
    return ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)


def bootstrap_look_up(name):
    """bootstrap_look_up's kern_return_t: 0 found, 1100 not privileged (a sandbox denial), 1102 unknown service."""
    libc = libsystem()
    look_up = libc.bootstrap_look_up
    look_up.argtypes = [ctypes.c_uint, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint)]
    look_up.restype = ctypes.c_int
    port = ctypes.c_uint(0)
    return look_up(ctypes.c_uint.in_dll(libc, "bootstrap_port").value, name.encode(), ctypes.byref(port))


def procargs(pid):
    """Another process's argv and environment through sysctl KERN_PROCARGS2, or None when the kernel refuses."""
    libc = libsystem()
    mib = (ctypes.c_int * 3)(1, 49, pid)                 # CTL_KERN, KERN_PROCARGS2
    size = ctypes.c_size_t(1 << 20)
    buf = ctypes.create_string_buffer(size.value)
    if libc.sysctl(mib, 3, buf, ctypes.byref(size), None, ctypes.c_size_t(0)) != 0:
        return None
    return buf.raw[:size.value].decode("latin-1")


def can_read(path):
    """(0, what was read) when the path can be read or listed, else (1, why). Never returns contents or names."""
    try:
        if os.path.isdir(path):
            return 0, "listed %d entries" % len(os.listdir(path))
        with open(path, "rb") as f:
            f.read(1)
        return 0, "readable"
    except OSError as e:
        return 1, "refused: %s (%s)" % (errno.errorcode.get(e.errno, "nocode"), e.strerror or e.__class__.__name__)


def hold(marker, seconds):
    """Keep this round (and the worker's turn) open until the driver writes `marker` or `seconds` pass. The second
    lane's worker looks at this turn's processes meanwhile. True when the marker appeared."""
    end = time.time() + seconds
    while time.time() < end:
        if os.path.lexists(marker):
            return True
        time.sleep(0.2)
    return os.path.lexists(marker)


def leaked(text):
    return [name.rstrip("=") for name in LEAKS if name in (text or "")]


def lane_round(p, rows):
    """Steps 2 and 3: the worker's own walls, then the broker's, from inside the lane."""
    lane, uid, base, worktree = Path(p["lane"]), os.getuid(), p["base"], p["worktree"]

    def add(name, expect, result, refusals=None):
        rows.append({"probe": name, "expect": expect, "code": result[0], "detail": result[1], "refusals": refusals})
    code, out = node("console.log(require('os').tmpdir())")
    want = os.path.realpath(lane / "tmp" / ("claude-%d" % uid))
    add("tmpdir is <lane>/tmp/claude-<uid>", "ok", (0 if code == 0 and os.path.realpath(out) == want else 1, out))
    for domain in p["domains"]:
        add("curl %s" % domain, "fail", curl_result(*run(["curl", "-sSf", "--max-time", "5", "-o", "/dev/null",
                                                           "https://" + domain])), NET_REFUSALS)
        add("node fetch %s" % domain, "fail", classify(*node(FETCH, domain)), NET_REFUSALS)
    add("curl 1.1.1.1", "fail", curl_result(*run(["curl", "-sSf", "--max-time", "5", "-o", "/dev/null",
                                                   "http://1.1.1.1"])), NET_REFUSALS)
    add("node connect 1.1.1.1:80", "fail", classify(*node(CONNECT_TCP)), NET_REFUSALS)
    add("listen on a lane port", "ok", node("require('net').createServer().listen(+process.argv[1], '127.0.0.1',"
                                            "function () { process.exit(0); }).on('error', e => { console.log(e.code);"
                                            "process.exit(1); })", str(base + 4)))
    code, out = node("require('net').createServer().listen(0, function () {"
                     "console.log(this.address().address); process.exit(0); })")
    add("listen(0) binds 127.0.0.1", "ok", (0 if code == 0 and out == "127.0.0.1" else 1, out))
    add("npx tsx -e 1", "ok", run(["npx", "--no", "tsx", "-e", "1"], timeout=180, cwd=worktree))
    cache = Path(os.environ.get("npm_config_cache", lane / "npm-cache"))
    try:
        (cache / "superyak-lane-acceptance").write_text("x")
        add("npm cache write", "ok", (0, str(cache)))
    except OSError as e:
        add("npm cache write", "ok", (1, str(e)[:200]))
    for i, sock in enumerate(p["sockets"]):
        add("socket %s" % sock, "fail", classify(*node(CONNECT, sock)), SOCKET_REFUSALS)
        for kind, make in (("symlink", os.symlink), ("hard link", os.link)):
            link = lane / "tmp" / ("acceptance-%s-%d.sock" % (kind.replace(" ", ""), i))
            try:
                make(sock, link)
            except OSError as e:
                result, accepted = link_failure(e)
                add("%s to %s" % (kind, sock), "fail", result, accepted)
                continue
            try:
                add("%s to %s" % (kind, sock), "fail", classify(*node(CONNECT, str(link))), SOCKET_REFUSALS)
            finally:
                link.unlink()
    for name, path in sorted(p["reads"].items()):       # only targets the driver saw exist, outside the sandbox
        add("read %s" % name, "fail", can_read(path), READ_REFUSALS)
    rc = bootstrap_look_up(p["rendezvous"])
    rows.append({"probe": "rendezvous lookup", "expect": "denied", "code": rc, "detail": p["rendezvous"],
                 "refusals": None})
    client = str(HERE / "broker_client.js")
    for what in ("page", "wrongsecret", "external", "file", "canary", "write", "getusermedia", "exposenetwork"):
        expect = {"page": "ok", "exposenetwork": "info", "write": "info"}.get(what, "fail")
        code, text = run(["node", client, what, json.dumps(p)], timeout=120, cwd=worktree)
        # the client speaks the convention itself: it exits 1 only for a refusal it has recognised by its code
        add("browser %s" % what, expect, (code, text) if expect != "fail" else classify(code, text), None)


def peer_round(p, rows):
    """Step 3, last check: this second lane's worker can't read the first lane's endpoint from its processes. Each row
    names its target pid; the driver counts a row only if that process was alive before and after."""
    for pid in p["peer_pids"]:
        try:
            r = subprocess.run(["/bin/ps", "-E", "-ww", "-p", str(pid)], capture_output=True, text=True, timeout=30)
            found, seen = leaked(r.stdout), str(pid) in r.stdout
        except (OSError, subprocess.TimeoutExpired):
            found, seen = [], False
        rows.append({"probe": "ps -E of pid %d" % pid, "pid": pid, "expect": "fail", "code": 0 if found else 1,
                     "detail": ("reads " + ", ".join(found)) if found else ("no endpoint (process %s)" % ("seen" if seen else "not seen"))})
        text = procargs(pid)
        found = leaked(text)
        rows.append({"probe": "KERN_PROCARGS2 of pid %d" % pid, "pid": pid, "expect": "fail", "code": 0 if found else 1,
                     "detail": ("reads " + ", ".join(found)) if found else ("refused" if text is None else "no endpoint")})


def spec_round(p, rows):
    """Steps 5 and 6: Bricks' specs, in order, with Playwright's JSON reporter, each into its own file."""
    for i, spec in enumerate(p["specs"]):
        out = HERE / ("spec-%d.json" % i)
        with open(out, "w") as f:
            try:
                r = subprocess.run(["npx", "--no", "playwright", "test", spec, "--reporter=json"], cwd=p["worktree"],
                                   stdout=f, stderr=subprocess.DEVNULL, timeout=2300)
                code = r.returncode
            except subprocess.TimeoutExpired:
                code = -1
        rows.append({"probe": "spec %s" % spec, "expect": "info", "code": code, "detail": out.name})


def main():
    which = sys.argv[1]
    params = json.loads((HERE / "params.json").read_text())
    rows = []
    {"lane": lane_round, "peer": peer_round, "spec": spec_round}[which](params, rows)
    (HERE / ("results-%s.json" % which)).write_text(json.dumps({"round": which, "pid": os.getpid(), "rows": rows}))
    print("done: %d rows" % len(rows))
    if which == "lane" and params.get("hold_marker"):     # the second lane looks at this turn's processes meanwhile
        hold(params["hold_marker"], params.get("hold_s", 900))


if __name__ == "__main__":
    main()
