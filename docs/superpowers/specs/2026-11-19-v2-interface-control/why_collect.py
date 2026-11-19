import json, runpy, sys, tempfile, subprocess, shutil
from pathlib import Path
m = runpy.run_path(sys.argv[1]); repo = Path(sys.argv[2]); items = json.load(open(sys.argv[3]))["items"]; out = Path(sys.argv[4])
for key in sys.argv[5:]:
    item = items[key]
    with tempfile.TemporaryDirectory(prefix="ifc-why-") as scratch:
        tree = m["make_tree"](repo, item, Path(scratch), "parent")
        patch = (out / "interfaces" / f"{key}.patch").read_bytes()
        subprocess.run(["patch", "-p1", "-s"], input=patch, cwd=tree, check=True)
        home = Path(tempfile.mkdtemp())
        done = subprocess.run(m["CAP"] + [m["PYTHON"], "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
            *[p[len("peer/"):] for p in item["tests"]]], cwd=tree / "peer", env=m["environment"](tree, home), capture_output=True, text=True)
        shutil.rmtree(home, ignore_errors=True)
        lines = [l for l in done.stdout.splitlines() if "Error" in l or "error" in l or l.startswith("E ")]
        print(key, *lines[:6], sep="\n   ")
