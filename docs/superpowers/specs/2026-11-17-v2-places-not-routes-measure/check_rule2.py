"""Written after plan_census.py ran, as a check of its reading only: the same names, with the first pilot's rules 2
and 3 (a file under a `plans` or `specs` folder holds one, the name held by five Markdown files or fewer, and no
matching file has a line beginning `def test_` after spaces), and rule 1 (the census line ends "passed"). Section 2
of the spec publishes 40 for rules 1 and 2 and names the twelve that meet all three. Usage: check_rule2.py <repo>
<census>"""
import re
import runpy
import sys

ns = runpy.run_path(sys.argv[0].replace("check_rule2.py", "plan_census.py"), run_name="plan_census")
git, tree, words_of = ns["git"], ns["tree"], ns["words_of"]
TEST = re.compile(rb"^[ \t]*def test_", re.M)
two, three = [], []
passed = {l.split()[0] for l in open(sys.argv[2]) if l.split()[-1] == "passed"}
for commit, part, names, held in ns["rows"]:
    if commit not in passed:
        continue
    parent = git("rev-parse", f"{commit}^1").decode().strip()
    md = [(p, b) for p, b in tree(parent) if p.lower().endswith((".md", ".markdown"))]
    ok = [n for n in names if sum(n.encode() in words_of(b) for _, b in md) <= 5]
    match = [(p, b) for p, b in md if {"plans", "specs"} & set(p.split("/")[:-1])
             and any(n.encode() in words_of(b) for n in ok)]
    if match:
        two.append(commit)
        if not any(TEST.search(git("cat-file", "blob", b)) for _, b in match):
            three.append(commit)
print(f"rules 1-2: {len(two)}; all three: {len(three)}")
print(" ".join(c[:8] for c in three))
