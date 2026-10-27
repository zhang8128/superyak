import sys, os, sqlite3, shutil
from pathlib import Path
W = __import__("os").environ["W"]  # the repository checkout at the reviewed head
sys.path.insert(0, W + "/engram")
os.chdir(W + "/engram")
from tests.test_permissions_migrate import build_legacy
from drive import run
home = Path(sys.argv[1]); shutil.rmtree(home, ignore_errors=True); home.mkdir(parents=True)
build_legacy(home)
# the terminal closes (SIGHUP) part-way: after the 6th ledger act
pre = """
import os, signal, permission_ledger
_real = permission_ledger.Ledger.perform
_n = [0]
def perform(self, *a, **k):
    _n[0] += 1
    if _n[0] == 6:
        os.kill(os.getpid(), signal.SIGHUP)
    return _real(self, *a, **k)
permission_ledger.Ledger.perform = perform
"""
rc, out = run(home, ["migrate"], pre=pre)
print("first run exit", rc)
led = home / ".engram" / "permissions.db"
print("ledger exists after the kill:", led.exists())
con = sqlite3.connect(led)
print("log rows:", [r for r in con.execute("SELECT seq, kind, ref FROM ledger_log")])
print("records:", con.execute("SELECT count(*) FROM records").fetchone()[0])
con.close()
rc, out = run(home, ["migrate"])
print("second run exit", rc)
print(out.strip().splitlines()[-1])
