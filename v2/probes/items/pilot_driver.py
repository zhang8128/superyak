#!/usr/bin/env python3
"""Structured parts of the POSIX sh item drivers; Python 3.9+, standard library only.

The first pilot's records.py remains the manifest/check/table authority. A list is
validated before making any output. No shell evaluates any of the list's words.
YAK names the executable; YAK_PROBE_PATH names the clock's PATH; YAK_JAIL_READ
names the directories shown to its workers. SDKROOT and TMPDIR pass through when
set. A pilot supplies YAK_PILOT_SLOT/KIND for the manifest. There is no vendor.
References distinguish a failed hand-in or check, another tree or frozen hash,
a differing recheck, and an unusable observation. Only a verified check on the
reference's exact tree can pass.
"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import subprocess
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
RECORDS = HERE.parent / "pilot" / "records.py"
PARTS = ("history", "pilot", "scored", "left out by rule 5")


class Refused(Exception):
    pass


def load(path):
    with open(path, encoding="utf-8") as held:
        return json.load(held)


def write_json(path, value):
    with open(path, "x", encoding="utf-8") as out:
        json.dump(value, out, sort_keys=True, indent=1)
        out.write("\n")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def command(words, **kwargs):
    done = subprocess.run(list(map(str, words)), stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
    if done.returncode:
        raise Refused("%s failed: %s" % (words[0], done.stderr.decode("utf-8", "replace").strip()))
    return done.stdout


def git(repo, *words):
    # No inherited object directory, alternate, replacement, hook or machine filter.
    environment = {"PATH": os.environ.get("PATH", ""), "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_NO_REPLACE_OBJECTS": "1", "GIT_ATTR_NOSYSTEM": "1"}
    return command(["git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
        "-c", "core.autocrlf=false", "-C", repo, *words], env=environment)


def listed(items):
    raw = (Path(items) / "list" / "items.json").read_bytes()
    try:
        data = json.loads(raw)
    except RecursionError:
        raise Refused("items.json is nested too deeply") from None
    if not isinstance(data, dict) or not isinstance(data.get("commits"), list):
        raise Refused("items.json has no commits list")
    return data, raw


def item_from(data, commit):
    entries = [entry for entry in data["commits"] if isinstance(entry, dict) and entry.get("commit") == commit]
    if not entries:
        raise Refused("%s is not in the list" % commit)
    if len(entries) != 1:
        raise Refused("%s is in the list more than once" % commit)
    entry = entries[0]
    if "reason" in entry or entry.get("part") not in PARTS:
        raise Refused("%s is not eligible" % commit)
    for field in ("commit", "base", "wrong", "reference"):
        if not isinstance(entry.get(field), str) or not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", entry[field]):
            raise Refused("%s lacks a full %s commit" % (commit, field))
    if not isinstance(entry.get("title"), str) or not entry["title"].strip():
        raise Refused("%s lacks a title" % commit)
    check = entry.get("check")
    if not isinstance(check, dict) or not isinstance(check.get("command"), str) or not check["command"].strip():
        raise Refused("%s lacks its check command" % commit)
    files = check.get("files")
    if not isinstance(files, list) or not files or any(not isinstance(path, str) or not path for path in files):
        raise Refused("%s lacks its check files" % commit)
    if len(files) != len(set(files)):
        raise Refused("%s repeats a check file" % commit)
    for path in files:
        if any(c in path for c in "\0\r\n") or any(p in ("", ".", "..") or p.lower() == ".git" for p in path.split("/")):
            raise Refused("%s has a check file that is not plain: %r" % (commit, path))
    return entry


def check_hash(repo, entry):
    # The room's v2 hash, turn/src/check.rs::hash_of: command and sorted file paths,
    # modes and content SHA-256s. Unlike one git blob it binds a multi-file check.
    chunks = [b"v2\n", entry["check"]["command"].encode("utf-8"), b"\n"]
    for path in sorted(entry["check"]["files"]):
        row = git(repo, "ls-tree", "-z", entry["base"], "--", path).split(b"\0")[0]
        meta, _, found = row.partition(b"\t")
        if not found or found.decode("utf-8") != path or meta.split()[0] not in (b"100644", b"100755"):
            raise Refused("%s lacks the check file %s at its base" % (entry["commit"], path))
        mode, _, blob = meta.split()
        content = git(repo, "cat-file", "blob", blob.decode("ascii"))
        chunks += [path.encode("utf-8"), b"\0", mode, b"\0", digest(content).encode("ascii"), b"\n"]
    return digest(b"".join(chunks))


def source_checks(items, entry):
    repo = Path(items).resolve() / "repo"
    for kind in ("base", "wrong", "reference"):
        ref = "refs/yak-items/%s/%s" % (entry["commit"], kind)
        actual = git(repo, "rev-parse", "--verify", ref + "^{commit}").decode().strip()
        if actual != entry[kind]:
            raise Refused("%s: %s ref differs from the list" % (entry["commit"], kind))
    return repo, check_hash(repo, entry)


def settings(items, out, references=None):
    yak = os.environ.get("YAK", "")
    if not yak or not os.path.isfile(yak) or not os.access(yak, os.X_OK):
        raise Refused("YAK is not a program")
    for key in ("YAK_PROBE_PATH", "YAK_JAIL_READ", "HOME", "USER", "LOGNAME"):
        if not os.environ.get(key):
            raise Refused("%s is not set" % key)
    protected = [Path(items).resolve(), Path(out).resolve()]
    if references is not None:
        protected.append(Path(references).resolve())
    for entry in os.environ["YAK_JAIL_READ"].split(os.pathsep):
        if not entry:
            continue
        read = Path(entry).resolve()
        for answer in protected:
            if read == answer or read in answer.parents or answer in read.parents:
                raise Refused("YAK_JAIL_READ overlaps the items, references or output directory")
            # Compare directory identities too: resolve() need not restore the
            # on-disk case. Only compare each endpoint with the other's ancestry;
            # siblings sharing a parent are allowed.
            for child, parent in ((read, answer), (answer, read)):
                for ancestor in (child, *child.parents):
                    try:
                        if os.path.samefile(ancestor, parent):
                            raise Refused("YAK_JAIL_READ overlaps the items, references or output directory")
                    except FileNotFoundError:
                        pass
    return str(Path(yak).resolve())


def new_output(path):
    path = Path(path)
    if os.path.lexists(path):
        raise Refused("%s exists" % path)
    path.mkdir(parents=True)
    return path.resolve()


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def turn(out, items, commit, worker, extra):
    if not worker or any(word.isspace() for word in worker):
        raise Refused("worker must be one word")
    entry = item_from(listed(items)[0], commit)
    source, frozen_hash = source_checks(items, entry)
    yak = settings(items, out)
    out = new_output(out)
    repo = out / "repo"
    # Init plus explicit fetch uses git transport even for a local path; never a local
    # clone's hardlinks or copied object directory. No other source ref is fetched.
    repo.mkdir()
    git(repo, "init", "-q", "--template=")
    for kind in ("base", "wrong"):
        ref = "refs/yak-items/%s/%s" % (commit, kind)
        git(repo, "fetch", "-q", "--no-tags", "--no-write-fetch-head", str(source), ref + ":refs/item-input/" + kind)
    git(repo, "checkout", "-q", "-b", "item-base", entry["base"])
    for kind in ("base", "wrong"):
        git(repo, "cat-file", "-e", entry[kind] + "^{commit}")
    for kind in ("reference", "commit"):
        try:
            git(repo, "cat-file", "-e", entry[kind])
        except Refused:
            continue
        raise Refused("%s: the copy holds the %s %s" % (commit, kind, entry[kind]))
    command([yak, "--room", out / "room", "init"])
    add = [yak, "--room", out / "room", "item", "add", "--title", entry["title"], "--repo", repo,
        "--base", entry["base"], "--check", entry["check"]["command"]]
    for path in entry["check"]["files"]:
        add += ["--file", path]
    add += ["--wrong", entry["wrong"], "--origin", "observed", "--by", "claude:merged"]
    identity = command(add).decode().strip()
    (out / "item.txt").write_text("%s %s %s\n" % (commit, identity, worker), encoding="utf-8")
    (out / "started.txt").write_text(now() + "\n", encoding="utf-8")
    environment = {key: os.environ.get(key, "") for key in ("HOME", "USER", "LOGNAME")}
    environment.update(SHELL=os.environ.get("SHELL", "/bin/sh"), LANG="en_US.UTF-8", TERM="dumb",
        PATH=os.environ["YAK_PROBE_PATH"], YAK_JAIL_READ=os.environ["YAK_JAIL_READ"])
    for key in ("SDKROOT", "TMPDIR"):
        if os.environ.get(key):
            environment[key] = os.environ[key]
    argv = [yak, "--room", str(out / "room"), "clock", "run", "--once-through", "--daily-turns", "1", "--worker", worker] + extra
    # records.py's slug is the full item commit. Its singular check_file is the JSON array in list order;
    # check_blob names the entire multi-file check by the room's v2 SHA-256 above.
    pairs = {"slot": os.environ.get("YAK_PILOT_SLOT", ""), "kind": os.environ.get("YAK_PILOT_KIND", ""),
        "slug": commit, "worker": worker, "item": identity, "base": entry["base"], "wrong": entry["wrong"],
        "check": entry["check"]["command"], "check_file": json.dumps(entry["check"]["files"]), "check_blob": frozen_hash}
    command([sys.executable, "-I", RECORDS, "manifest", out, *[key + "=" + value for key, value in pairs.items()],
        "--", *[key + "=" + value for key, value in environment.items()], *argv])
    (out / "load-before.txt").write_bytes(command(["uptime"]))
    with (out / "clock.log").open("w", encoding="utf-8") as log:
        with subprocess.Popen(argv, env=environment, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT) as clock:
            for line in iter(clock.stdout.readline, b""):
                stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S")
                log.write(stamp + " " + line.decode("utf-8", "replace").rstrip("\n") + "\n")
                log.flush()
            code = clock.wait()
    (out / "clock.exit").write_text(str(code) + "\n", encoding="utf-8")
    (out / "ended.txt").write_text(now() + "\n", encoding="utf-8")
    (out / "load-after.txt").write_bytes(command(["uptime"]))
    (out / "turns.json").write_bytes(command([yak, "--room", out / "room", "item", "turns", identity, "--json"]))
    return subprocess.call([sys.executable, "-I", str(RECORDS), "check", str(out)])


def machine():
    return {"name": platform.node(), "kind": platform.system(), "architecture": platform.machine()}


def reference(out, items, commit):
    entry = item_from(listed(items)[0], commit)
    source, expected_hash = source_checks(items, entry)
    yak = settings(items, out)
    yak_hash = digest(Path(yak).read_bytes())
    out = new_output(out)
    stand_in = out / "stand-in"
    stand_in.mkdir()
    (stand_in / "reference.patch").write_bytes(git(source, "diff", "--binary", "--no-ext-diff", "--no-textconv",
        "--no-color", "--src-prefix=a/", "--dst-prefix=b/",
        entry["base"], entry["reference"], "--"))
    shutil.copyfile(HERE / "stand-in.sh", stand_in / "worker.sh")
    (stand_in / "worker.sh").chmod(0o755)
    environment = dict(os.environ)
    environment["YAK"] = yak
    # Only this reference's turn sees this directory, holding just its worker and
    # patch. Pilot turns never receive it, so it gives them no reference answer.
    environment["YAK_JAIL_READ"] += os.pathsep + str(stand_in)
    done = subprocess.run(["sh", str(HERE / "turn.sh"), str(out / "turn"), str(items), commit,
        "script:" + str(stand_in / "worker.sh")], env=environment)
    receipt = {"machine": machine(), "yak_sha256": yak_hash, "commit": commit,
        "base": entry["base"], "reference": entry["reference"], "check_hash": None,
        "reference_tree": git(source, "rev-parse", entry["reference"] + "^{tree}").decode().strip(),
        "handed_in_tree": None, "state": None,
        "handed_in": None, "verified": False, "outcome": "no usable observation", "note": None}
    try:
        attempts = load(out / "turn" / "turns.json")
        observed = attempts[0] if isinstance(attempts, list) and len(attempts) == 1 else {}
        handed = observed.get("commit")
        receipt["handed_in"] = handed
        if handed:
            receipt["handed_in_tree"] = git(out / "turn" / "repo", "rev-parse", handed + "^{tree}").decode().strip()
            # Read the submitted tree, never a file a worker could have left in our directory.
            names = git(out / "turn" / "repo", "ls-tree", "--name-only", handed, "--", "hand-in-note.txt")
            if names.strip():
                receipt["note"] = git(out / "turn" / "repo", "show", handed + ":hand-in-note.txt").decode("utf-8", "replace")
                receipt["outcome"] = "hand-in failed"
        identity = (out / "turn" / "item.txt").read_text().split()[1]
        # item show exposes the verified state; the frozen hash is read from the
        # room's store in read-only mode because that CLI view omits it.
        view = json.loads(command([yak, "--room", out / "turn" / "room", "item", "show", identity, "--json"]))
        receipt["state"] = view.get("state")
        db_path = out / "turn" / "room" / "room.sqlite3"
        db = sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)
        try:
            row = db.execute("SELECT frozen FROM checks WHERE item=?", (identity,)).fetchone()
        finally:
            db.close()
        receipt["check_hash"] = json.loads(row[0])["check_hash"] if row and row[0] else None
        if receipt["note"]:
            receipt["outcome"] = "hand-in failed"
        elif done.returncode == 0 and not handed:
            receipt["outcome"] = "hand-in failed"
        elif done.returncode == 0 and receipt["check_hash"] != expected_hash:
            receipt["outcome"] = "another frozen hash"
        elif done.returncode == 0 and receipt["handed_in_tree"] != receipt["reference_tree"]:
            receipt["outcome"] = "another tree"
        elif done.returncode == 0 and observed.get("passed") is False:
            receipt["outcome"] = "check failed"
        elif done.returncode == 0 and observed.get("passed") is True and view.get("state") != "passed_verified":
            receipt["outcome"] = "recheck differs"
        elif (done.returncode == 0 and observed.get("passed") is True and view.get("state") == "passed_verified"
                and receipt["check_hash"] == expected_hash):
            receipt.update(outcome="passed", verified=True)
    except (OSError, ValueError, TypeError, AttributeError, KeyError, sqlite3.Error, Refused) as error:
        receipt["detail"] = str(error)
    write_json(out / "reference.json", receipt)
    print("%s: %s%s" % (commit, receipt["outcome"], ": " + receipt["note"] if receipt["note"] else ""))
    return 0 if receipt["outcome"] == "passed" else 1


def plan(data, worker):
    if not worker or any(word.isspace() for word in worker):
        raise Refused("worker must be one word")
    entries = [item_from(data, entry.get("commit")) for entry in data["commits"]
        if isinstance(entry, dict) and entry.get("part") == "pilot"]
    if len(entries) != 3:
        raise Refused("the list must name three eligible pilot items")
    rounds = os.environ.get("YAK_PILOT_ROUNDS", "5")
    if not re.fullmatch(r"[0-9]+", rounds):
        raise Refused("YAK_PILOT_ROUNDS is not a number")
    rows = [(1, "thrown-away", entries[0]["commit"], worker, "--own-prompts")]
    for n in range(1, int(rounds) + 1):
        for entry in entries:
            rows.append((len(rows) + 1, "round-%d" % n, entry["commit"], worker, "--own-prompts"))
    return entries, "".join(" ".join(map(str, row)) + "\n" for row in rows)


def pilot(args):
    if len(args) == 3 and args[0] == "--plan":
        print(plan(listed(args[1])[0], args[2])[1], end="")
        return 0
    if len(args) != 5 or args[3] != "--references":
        raise Refused("pilot.sh <pilot-dir> <items-dir> <worker> --references <dir> is required")
    out, items, worker, _, references = args
    data, list_bytes = listed(items)
    entries, text = plan(data, worker)
    yak = settings(items, out, references)
    # Every receipt is checked before creating even the pilot directory.
    receipts = {}
    for entry in entries:
        source, frozen_hash = source_checks(items, entry)
        receipt = load(Path(references) / entry["commit"] / "reference.json")
        wanted = {"commit": entry["commit"], "base": entry["base"], "reference": entry["reference"],
            "check_hash": frozen_hash, "machine": machine(), "yak_sha256": digest(Path(yak).read_bytes()), "outcome": "passed"}
        if receipt.get("verified") is not True or not receipt.get("handed_in") or any(receipt.get(key) != value for key, value in wanted.items()):
            raise Refused("%s: reference.json is not a verified pass for this item, machine, check and yak" % entry["commit"])
        reference_turn = Path(references) / entry["commit"] / "turn"
        command([sys.executable, "-I", RECORDS, "check", reference_turn])
        manifest = load(reference_turn / "manifest.json")
        attempts = load(reference_turn / "turns.json")
        if (manifest.get("yak", {}).get("sha256") != receipt["yak_sha256"]
                or manifest.get("slug") != receipt["commit"]
                or attempts[0].get("commit") != receipt["handed_in"]):
            raise Refused("%s: reference.json names another turn" % entry["commit"])
        if attempts[0].get("passed") is not True:
            raise Refused("%s: reference turn did not pass" % entry["commit"])
        if (git(reference_turn / "repo", "rev-parse", receipt["handed_in"] + "^{tree}")
                != git(source, "rev-parse", entry["reference"] + "^{tree}")):
            raise Refused("%s: reference turn handed in another tree" % entry["commit"])
        receipts[entry["commit"]] = receipt
    out = new_output(out)
    (out / "plan.txt").write_text(text, encoding="utf-8")
    # Freeze the actual list and reference evidence alongside the plan, before a turn.
    list_path = Path(items) / "list" / "items.json"
    (out / "items.json").write_bytes(list_bytes)
    list_hash = digest(list_bytes)
    write_json(out / "inputs.json", {"items_sha256": list_hash,
        "plan_sha256": digest(text.encode("utf-8")), "references": receipts})
    environment = dict(os.environ, PATH=os.environ["YAK_PROBE_PATH"])

    def say(message):
        with (out / "pilot.log").open("a", encoding="utf-8") as log:
            log.write(now() + " " + message + "\n")

    def block(which):
        with (out / ("block-%s.txt" % which)).open("w", encoding="utf-8") as report:
            code = subprocess.call(["sh", str(HERE.parent / "block-check.sh"), str(out), yak],
                env=environment, stdout=report, stderr=subprocess.STDOUT)
        if code:
            say("refused by the block check " + which)
        return code

    say("the plan is written: %d turns" % len(text.splitlines()))
    if block("before"):
        return 1
    for line in text.splitlines():
        slot, kind, commit, worker, flag = line.split()
        if digest(list_path.read_bytes()) != list_hash:
            say("refused: the list changed after the plan was written")
            return 1
        if (out / "STOP").exists():
            say("stopped before turn " + slot)
            return 1
        say("turn %s begins: %s %s %s %s" % (slot, kind, commit, worker, flag))
        # A known limit: this name holds the item's whole commit id, so a test that looks for 32 hexadecimal
        # characters in a path it prints fails under it, whatever the code under test does. The pass names its
        # own directories by ten characters for that reason; records.py's tables find these names again whole.
        turn_out = out / ("%s-%s-%s" % (slot, kind, commit))
        with (out / "pilot.log").open("a", encoding="utf-8") as log:
            code = subprocess.call(["sh", str(HERE / "turn.sh"), str(turn_out), str(items), commit, worker, flag],
                env=dict(os.environ, YAK=yak, YAK_PILOT_SLOT=slot, YAK_PILOT_KIND=kind), stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT)
        if not code and load(turn_out / "manifest.json").get("yak", {}).get("sha256") != receipts[commit]["yak_sha256"]:
            say("turn %s names another yak: the pilot ends here" % slot)
            return 1
        if code:
            say("turn %s left no usable observation, or its script failed: the pilot ends here" % slot)
            return 1
        say("turn %s ended: the clock's exit %s" % (slot, (turn_out / "clock.exit").read_text().strip()))
    if digest(list_path.read_bytes()) != list_hash:
        say("refused: the list changed after the plan was written")
        return 1
    if block("after"):
        return 1
    with (out / "tables.md").open("w", encoding="utf-8") as tables:
        code = subprocess.call([sys.executable, "-I", str(RECORDS), "tables", str(out)], stdout=tables)
    say("the tables are REFUSED" if code else "every turn of the plan is in tables.md")
    return code


def main(args):
    try:
        if args and args[0] == "turn" and len(args) >= 5:
            return turn(*args[1:5], args[5:])
        if args and args[0] == "reference" and len(args) == 4:
            return reference(*args[1:])
        if args and args[0] == "pilot":
            return pilot(args[1:])
        raise Refused("use turn.sh, reference.sh or pilot.sh with their documented arguments")
    except (Refused, OSError, ValueError, TypeError, AttributeError) as error:
        print("REFUSED: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
