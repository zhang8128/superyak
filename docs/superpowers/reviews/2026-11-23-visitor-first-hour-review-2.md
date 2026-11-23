# A visitor's first hour, review 2: the re-check of draft 2 (d70becc6), verbatim

The same fresh reviewer read the diff from e82ccc82 and the whole of draft 2. It ran nothing of the walk.

---

**Re-check of draft 2 (d70becc6): APPROVED WITH REQUIRED CHANGES**

Draft 2 makes all eight of review 1's changes, W1 to W8. Three of the authors' choices stand: (ii) read-only outside
search for both walkers is sound and matched, (iv) keeping the spec and reports off main is right as far as it goes,
and (iii) environment-only containment is acceptable at this stage. Six gaps remain, and three of them come from the
choices themselves.

**Required**

1. **Freeze the invocation and protect the credential (i).** The frozen list doesn't include how the walker is
   started, so a walk that fails on permission prompts could be followed by a looser run. Fix:
   - add the exact `claude` command line to the frozen set: model id, print mode, permission mode, and the allowed
     tools (built-ins only, including WebSearch and WebFetch);
   - create `/var/tmp/visitor-walk-N/` with mode 0700;
   - delete the copied sign-in file when the walk ends, before scoring;
   - never commit or post anything from `home/`.

2. **"No ssh credentials" isn't true for the same user (iii).** OpenSSH finds its keys through the account's home in
   the password database (`/home/doctor/.ssh`), not through `$HOME`, so the cleared `HOME` doesn't hide them. Fix:
   - clone over https;
   - set `GIT_SSH_COMMAND=false` in the walker's environment, so any git-over-ssh fails;
   - correct the sentence;
   - name ssh use in the transcript check.

3. **A read outside the walk directory only counts as a stall (iii).** "Stalled then unaided" still meets the stop
   rule, so a walk that read Tardis's checkout or memory could stop the agent walks. Fix:
   - a read of any checkout, `~/.claude`, `~/.superyak` or another walk's directory makes the walk ineligible to stop
     the agent walks, though it still counts toward the five;
   - system paths the tools read themselves are exempt;
   - a write outside the walk directory ends the walk, and the transcript check covers writes as well as reads.

4. **The clone holds every branch (iv).** A plain `git clone` fetches all of origin's branches, and
   `tardis/visitor-walk-spec` is on origin now. So the spec, review 1 and any report pushed there are in the walker's
   clone (`git log --all`), and on GitHub's branch page within WebFetch's reach. Fix:
   - clone with `--single-branch` at the named train commit;
   - keep reports off origin, in a bundle, until the agent walks end;
   - a read of the spec, a review or a report, local or on the web, makes the walk ineligible to stop the agent walks.

5. **Title matching that ignores only case and whitespace will mark real sources "not done" (v).** PubMed titles end
   in a period, and Crossref titles can carry HTML tags and Unicode dashes. A correct source would fail, which invites
   loosening the rule after a walk. Fix:
   - freeze the normalization now: NFKC, casefold, strip tags, drop punctuation, collapse whitespace;
   - apply it to S5's titles and to S4's "verbatim" question;
   - resolve a DOI through Crossref and a PMID through PubMed esummary.

6. **The scorer, not the walker, completes S6.** In the checklist the scorer runs `refresh` and then reads the files,
   so S6 follows from S5 whether or not the walker ever saw its answer. Fix: S6 needs the transcript to show the
   walker, within budget, reading a view file or a Superyak command's output that holds the claim's id and
   identifier. The scorer's refresh only confirms.

**Advisory:** a copied OAuth sign-in that refreshes could rotate Tardis's own token. Watch the machine's sessions after
walk 1, or use an API key if one is ever available.

**Read:** the diff from e82ccc82 to HEAD, and the whole of draft 2.
