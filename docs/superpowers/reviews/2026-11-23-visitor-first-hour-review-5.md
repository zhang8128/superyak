# A visitor's first hour, review 5: the final verdict on draft 5 (44ecc9fa), verbatim

The same fresh reviewer read the diff from fbdffe2e to 44ecc9fa and grepped draft 5 for wording left from before
bubblewrap. Inside a bubblewrap on scratch directories, since removed, it checked what the sandbox can see of other
processes through `/proc`, with and without `--unshare-pid`. It also checked `~/.local/bin` and grepped the walk path's
docs for `uvx`. It didn't run the walk or any of the repository's tools.

---

**Re-check of draft 5 (44ecc9fa): APPROVED**

Draft 5 makes Z1 and Z2 and takes both advisories. The wording and wrapper fixes below don't change the design and need
no further review.

**(1) The invocation's order is sound.**
- **Transcript redirect:** it binds in the outer shell, and the walker can't see the path because `/var/tmp` is a tmpfs
  inside the wrapper. The walker's own stdout is still that file, though, and is probably reachable through
  `/proc/<claude pid>/fd/1` (not tested). So the transcript's sha256 shows it wasn't changed after the walk, not that
  it wasn't changed during it.
- **`$(cat brief.txt)`:** expanding it outside is fine. It becomes a single argv string, visible only in process
  listings, and that's harmless.
- **PATH:** fine. `claude` runs by its pinned absolute path, and inside the wrapper `/home/doctor/.local/bin` holds only
  `uv`. `uvx` sits beside it on Tardis but isn't bound. Nothing on the walk path uses it today (I grepped the README,
  the Makefile and the linked docs), but a visitor who installs uv gets `uvx` too, so binding it as well would prevent
  a stall that isn't the docs' fault.

**(2) Pre-bwrap wording that's still there:**
- Line 82 says `/var/tmp` "shows only the walk's directory". It also shows the config directory, which is bound there.
- Line 103 says only the walk and config directories are writable. The `/tmp`, `/var/tmp` and `/home/doctor` tmpfs
  mounts are writable too; they're private and discarded when the walk ends. Better wording: "writes persist only in
  the walk and config directories".
- Line 143's "ssh use" check is now moot, since the keys are hidden, and harmless.

**(3) Approved as a whole.**

**Advisory**
- **Add `--unshare-pid`.** In a test I ran inside the wrapper, the sandbox saw 241 of Tardis's processes and could read
  their command lines, and those can carry ships' prompts. Their `/proc/<pid>/root`, `fd` and `environ` were denied, so
  Tardis's home stays hidden. With `--unshare-pid` those processes disappear from view, and `timeout` ending the walk
  takes the walker's whole process tree with it.
- **Run a harness check before walk 1.** The smoke run covered only `--version`. Give the walker a prompt unrelated to
  the repo that uses the sign-in and each allowed tool once (Grep and WebFetch especially). Then a tool broken by the
  wrapper shows up as a machine fault and voids the walk, rather than being scored as a stall against the docs.

**Read:** the diff from fbdffe2e to 44ecc9fa, and a grep of draft 5 for wording left from before bwrap. Inside a bwrap
on scratch directories, since removed, I checked what the sandbox can see of other processes through `/proc`, with and
without `--unshare-pid`. I also checked `~/.local/bin` and grepped the walk path's docs for `uvx`. I didn't run the walk
or any of the repository's tools.
