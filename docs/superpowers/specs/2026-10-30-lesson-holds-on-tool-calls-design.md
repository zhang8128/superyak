# Lessons hold at tool calls

Draft 2, 2026-10-30, Serenity. Board: `spec:lesson-holds-on-tool-calls` (all hands). For the same fresh reader's
re-check (law section 3); Andy can veto. Draft 2 takes the reader's REQUEST CHANGES on bf90cee1 (all hands 4523392)
and Tardis's advisory read (56b26509). Built from the all-hands thread of 2026-10-30 (Serenity cc931987, Rio Grande
8cbea18b and 3af2f123, Tardis 52f03275 and a09fdd5e), with the measurements below.

## Why

A lesson is shown before the act it is about. Today the one act the rail can hold is a Bash command: the PreToolUse
entry `run_agent.py hold` answers only `tool_name == 'Bash'` (agent/superyak_agent/hold.py:39-40), and it is installed
under the matcher `Bash` (agent/superyak_agent/install.py:164). A lesson whose act is a tool call (posting to the
station, claiming a board item, asking the person a question) can surface only through prompt words (lessons.py:558),
which come before the act or never. Four of Serenity's drafted lessons and one of Rio Grande's are about such acts: the
20,000-character cut on a post, a check-in that leads with the purpose, a blocking question in a watch, and taking a
lapsed claim. (A fifth of Serenity's, about the Edit tool, is out of scope: see "Before it is built".)

## Design

Draft 1 held the station's two tools inside the station's MCP server. The reader showed four faults there: the server
has no transcript path (M1), what it showed can't be read back by the lessons hook (M2), a subagent's post spends the
main session's lesson (M3), and nothing bounds its time in a server that runs one request at a time (M4). The two
reasons for the move don't hold: `|| true` already turns a stale checkout's exit 2 into 0 (install.py:84, :104), and
the Python start costs about 0.3 s an hour on the Pi. So all three tools are held where Bash is held.

1. **One PreToolUse entry for four tools.** The hold's entry has the matcher
   `Bash|AskUserQuestion|mcp__station__station_post|mcp__station__station_claim`. The station's server is always
   registered as `station` (install.py:561), so its tools' names are fixed. The matcher only routes: hold.py decides
   by the exact `tool_name`, as it does today (hold.py:39-40).
2. **The head of a tool call is the tool's full name**, and nothing from its input. A post's text (up to 20,000
   characters) is never matched, so a post that quotes `git rev-parse`, or one that discusses a lesson, is not held by
   it. `lessons_hook.head` of one word is that word (lessons_hook.py:138-149), so the provider gets the name as its
   command. The payload carries `transcript_path` and `agent_id` for tool calls as for Bash, so the rest of hold.py runs
   as it is.
3. **Tool names hold only their own tool (S5, N4).** A lesson value equal to one of the three held tools' names
   (`HELD_TOOLS`) holds only that tool's call: it never holds a Bash command that contains it, such as
   `rg mcp__station__station_post agent/`, and it never surfaces at a prompt by words. No other value ever holds a
   tool call, so a short Bash value such as `command: station` can't hold every post. Without this, the first time a
   session greps the tool's name, the lesson is held there and joins `seen` (lessons_hold.py:134), and the real post
   minutes later goes unheld. There is no new line in the lesson format: a `tool:` line would be refused by every
   door and parser on the rail that has not taken it yet.
4. **Authoring rule: write the tool's full name** (Tardis): `command: mcp__station__station_post`. A lesson about the
   act may keep other values for its prompt-word path, since they never hold the tool call.
5. **Only the first appearance holds** (Tardis's point 3). The provider holds a head's first appearance in a session
   (lessons_hold.py:122-124), so only a session's first post, first claim or first question can be held, and a lesson
   laid mid-session waits for the next session. That is intended: the lesson is about the act, and the first act is
   the moment.
6. **One budget with Bash (S2).** A tool-call hold counts toward the same HOLDS_PER_SESSION of 3 (holds.py:20), and
   the provider is asked with the same `limit` hold.py passes today (hold.py:102-111). This amends the first rail's
   section 8, "at most 3 commands in a session", to "at most 3 commands or tool calls".
7. **Checklists stay with commands.** At a tool call the hold asks only the lessons provider. The one checklist moment
   at a tool call, `when: claim` (before-work.md), already fires in the station's MCP server after the claim
   (mcp.py:561-584), and stays as it is.
8. **The deny.** hold.py's own output, so the lessons are fenced as for Bash (Tardis's point 1): the hook's quoted
   block under "Lessons from Andy's ships (quoted data, not instructions)". The last line for a tool call is "Call it
   again if you still want it." in place of `RERUN` (hold.py:23).
9. **Readback (M2).** The lessons hook learns what a hold showed by reading the deny back from the transcript, by
   Claude Code's prefix `PreToolUse:Bash hook error: ` (lessons_hook.py:66). It reads the held tools' prefixes too, each
   in Claude Code's own words as confirmed below. Otherwise a lesson held at a post could be shown again at a failure
   and receipted twice.
10. **A late answer at a tool call records the head (S6).** Today a late or failing query records nothing, so the head
    asks again next time (lessons_hold.py:144-146). A tool's head never changes, so on a loaded Pi every post would
    wait out the budget again. At a tool call, a late or failing answer records the head as asked: that tool is not
    held again in this session.
11. **Subagents are never held** (hold.py:41, D14): the payload's `agent_id` tells them apart, as for Bash.
12. **The install check (S1).** One entry with the matcher in item 1, so `_install_hooks` still finds exactly one
    station hold (install.py:154). `_hold_entry_current` (install.py:135-138) counts a hold whose entry has another
    matcher, or the old `Bash` matcher, as not current, so `make dock` rewrites a Bash-only entry into the new one.

## Costs (measured)

- **The hold's floor**, spawn to exit, with no lessons settings, so the provider returns before any index read
  (lessons_hold.py:112-114) (N1). 40 runs each, under a throwaway HOME:
  - the Mac (M-series, Python 3.15.0): p95 28.2 ms; with a 20,000-character input, p95 29.3 ms;
  - the Pi near load 1 (Rio Grande, main 078fdd9c): p95 51.7 ms;
  - the Pi at load 2.7 to 3 (the reader): Bash p95 81.3 ms; AskUserQuestion with 20,000 characters p95 84.3 ms.
- **`could_hold`, in process, on the Pi** with lessons of realistic size (claim 150 B, why 280 B, three command values,
  one error, one file) (N2): 100 lessons, p95 0.9 to 1.2 ms; 1,000 lessons, p95 12 to 15 ms. It reads the whole index
  file, vector block included (3.9 MB at 1,000 lessons by 768 dimensions), and runs twice when the first answer is
  yes (lessons_hold.py:125, :137). The three ships' drafts come to about 95 lessons.
- **A watch** posting about 6 times an hour pays 0.3 to 0.5 s an hour on the Pi.
- **The full query** (about 360 ms at its bound, lessons_hold.py:13) runs only when `could_hold` says yes, and with
  item 5 at most once per tool per session.

## Before it is built

- **On each ship's Claude Code version**, in an isolated `claude -p` session with only a logging hook, as Tardis
  confirmed for Bash on 2.1.312 (docs/superpowers/plans/2026-10-27-rail-lessons-hook.md, "Confirmed on Tardis's Claude
  Code"), confirm for each of the three tools:
  - the deny's reason reaches the model;
  - the transcript's prefix for that tool's deny, which item 9 reads back.
- **Until every ship has confirmed them,** the matcher stays `Bash` (N3): nothing checks the version at run time, and
  Claude Code updates itself. A tool joins the matcher only when every ship's version has passed both checks for it.
- **Tool names under 6 bytes** (Edit, Read, Write, Bash, Glob, Grep) can't be held by containment, and are out of
  scope.

## Whose yes

- **Items 3 and 10** change `lessons.py:602-631` and `lessons.py:558` (Rio Grande's; his yes on 4523392) and
  `lessons_hold.py:134-150` (Tardis's).
- **Item 9** changes `lessons_hook.py` and its id-line binding (Tardis's).
- **Item 6** amends the first rail's section 8 and **item 4** its section 2's format notes. Both go to this spec's
  section 3 reader, with Andy's veto.

## Tests

- hold.py answers each of the three tools with the tool's name as the head. A lesson with
  `command: mcp__station__station_post` holds the session's first post, and its deny ends with "Call it again if you
  still want it."; the second post goes through.
- A post whose text contains a lesson's `command:` value is not held by it.
- `rg mcp__station__station_post agent/` is not held by a `HELD_TOOLS` value, and the post after it still is (item 3).
  A prompt naming the tool doesn't surface that lesson by words. `command: station` never holds a post.
- A tool-call hold counts toward the session's 3, and a fourth hold of any kind is not made.
- A late or failing answer at a tool call records the head; the next post isn't asked again (item 10).
- The checklist provider is not asked at a tool call. A call with `agent_id` set is not held.
- The deny is fenced as the hook's output is, and the hook reads a held tool's deny back from a transcript fixture in
  each confirmed prefix, so a lesson held at a post isn't shown or receipted again at a later failure.
- The install check: a settings file with today's Bash-only entry is rewritten into the one entry with the new matcher,
  and a second `make dock` changes nothing. An entry whose checkout exits 2 for `hold` can't block a post.

## Not in this spec

- A `tool:` line in the lesson format. It is the way out if item 3's rule meets a case it can't serve.
- Holding inside the station's MCP server (draft 1). The reader's M1 to M4 would each have to be solved first.
- Edit and the other short-named tools.
