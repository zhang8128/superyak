# A visitor's first hour, review 4: the re-check of draft 4 (fbdffe2e), verbatim

The same fresh reviewer read the diff from e05c3616 to fbdffe2e. On Tardis it also checked `/etc/claude-code`, the
ownership of `/var/tmp`, `/var` and `/`, and the user-namespace sysctl. It ran a bubblewrap refusal test in its own
scratchpad and then deleted it. It didn't run the walk or any of the repository's tools.

---

**Re-check of draft 4 (fbdffe2e): APPROVED WITH REQUIRED CHANGES**

Draft 4 makes Y2 and Y3 and takes all three advisories (the reset, the revoke, the process scope and the
`--allowedTools` note). Y1, the explicit-writes rule, can't be scored without judgement, and the ancestor check misses
one load path.

**Required**

1. **Make outside writes impossible rather than judged (Y1).** A stream-json transcript can't settle the rule
   mechanically. A relative path after an earlier `cd ..`, a shell variable, or a Python `open()` all name no outside
   path in the command text. Catching them means rebuilding the working directory and expansions by hand, and any miss
   goes unseen.
   - **Tested on Tardis:** bubblewrap (`/usr/bin/bwrap`) is installed and works for this user under Ubuntu's
     user-namespace restriction. In a scratch test, a write outside the one bound directory failed with "Read-only
     file system", and the write inside it succeeded.
   - **Fix:** inside the systemd scope, wrap `claude` in `bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp
     --tmpfs /var/tmp --bind <walk dir> <walk dir> --bind <config dir> <config dir> --die-with-parent`, and freeze that
     as part of the invocation.
   - **What the rule becomes:** an outside write can't happen, and an attempt shows in the transcript as a "Read-only
     file system" error, logged as a stall. That needs no judgement.
   - **Before walk 1:** run a one-line refusal test inside the wrapper.
   - **Side effects:** `--tmpfs /var/tmp` also hides other walks' directories, and the read-only root keeps Claude Code
     from updating itself mid-series.

2. **Extend the ancestor check (Tardis's lesson).** The answer to your question is that checking `/var/tmp`, `/var` and
   `/` is enough for directories above the walk, and the walk doesn't need fewer ancestors. `/var` and `/` are
   root-owned, mode 755. `/var/tmp` is world-writable, so another account could add a `CLAUDE.md` between the check and
   the start, but change 1's `--tmpfs /var/tmp` closes that gap. What the check misses is Claude Code's managed policy,
   `/etc/claude-code/` (`CLAUDE.md` and `managed-settings.json`), which loads whatever the working directory is. It's
   absent on Tardis today. Fix: add `/etc/claude-code/` to the pre-walk check, and look for `CLAUDE.local.md` as well as
   `CLAUDE.md` and `.claude/`.

**Advisory**

- Mounting a `--tmpfs` over `/home/doctor`, with the `claude` and `uv` binaries bound back read-only, would make the read
  rule mechanical too and hide the ssh keys.
- Put `claude --version` in each report.

**Read:** the diff from e05c3616 to fbdffe2e. On Tardis I also checked `/etc/claude-code`, the ownership of
`/var/tmp`, `/var` and `/`, the user-namespace sysctl, and ran the bubblewrap refusal test in my scratchpad, since
deleted. I didn't run the walk or any of the repository's tools.
