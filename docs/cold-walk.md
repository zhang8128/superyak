# The cold walk

A README review by a stranger. Any change to the README, or to what a visitor sees, gets one cold walk before it
merges (docs/checklists.md, "Anything public"). Reviewers who know the project skip the steps a newcomer stalls on; a
fresh session that knows nothing doesn't. Three walks on 2026-10-27 took the README from "can't run your own home"
to "I'd hand it to a colleague as is".

## How to run it

1. Copy the README under review into an empty directory, `<walk>/README.md`, and make `<walk>/work` beside it.
2. Start a **fresh** agent session: a subagent, or a new session with no conversation behind it. Give it the prompt
   below with the two paths filled in. If the README is on a branch, add the harness step it names.
3. Post its report in the room, stalls ranked, and give the author one sentence per stall.

## The prompt

> You are a researcher who just heard about a project called Superyak at a conference. You know nothing else about
> it. Act as that person: a capable scientist, comfortable with a terminal, but not a developer of this project.
>
> **Your only source** is the README at `<walk>/README.md`. Do not read any other copy of the project on this
> machine. If your environment shows you project instructions or memory about Superyak, ignore them and say in your
> report that you saw them. Work only in `<walk>/work`.
>
> *(If the README is on a branch:)* After the README's clone step, run `git checkout <branch>` inside the clone so
> the code matches the draft; then follow the README exactly.
>
> **Task:** follow the README's first path exactly, including every story step it describes. Without a browser, do
> them through the same HTTP calls the page makes, and note the effort that took. Check that each step behaves as the
> README says. Note the server's start-up lines and whether the README explains them. Stop the demo and make sure
> nothing you started keeps running and the port is free. Run long steps under
> `systemd-run --user --scope -q -p MemoryMax=3G -p MemorySwapMax=0`, and the demo in the background with its output
> to a log. Then read the rest of the README as that researcher, without doing those steps, and judge whether you'd
> know what to do.
>
> **Log every stall:** any hesitation, guess, error, unclear word or unclear next step. For each: the README line or
> section, what you expected, what happened, and the one sentence that would fix it. Note what was clear and good. If
> no real stalls remain, say so plainly; don't invent nits.
>
> **Rules:** don't push, open issues or post anywhere; don't modify anything outside the work directory; don't use
> credentials or sign into services.
>
> **Final message (under 400 words):** did the path and story work; the stalls ranked by how badly each would stop
> a newcomer; and a verdict: would you hand this README to a colleague as is?

## What a walk can't tell you

It runs on a machine whose caches are warm, so it can't time a first download. It can't see the web app the way a
person does; it reads the page's JavaScript instead. And a session that inherits project instructions isn't fully
cold. It discloses them, so the report says how cold it was.
