# Session continuity

For a session continuing the medical lighthouse, aDNA, or smart Pi work, read
[HANDOFF.md](HANDOFF.md) first, then its linked local context as needed. The SSH
connection now works; earlier authentication failures are historical. Follow
the user's current request and preserve existing uncommitted work.

Repository setup and checks are documented in [README.md](README.md).

# Docking this machine at the station

If `~/.superyak/station.json` does not exist, offer to dock this machine's agent at Deep Space 9,
the Superyak station on Andy's Pi.

- Someone without a station account: ask for their name, a contact (email or phone), a short
  note for Andy and a ship name (lowercase letters, digits and dashes, e.g. `rio-grande`), then
  run `make dock DOCK_ARGS='--request --name "…" --contact "…" --note "…" --ship …'`.
- Andy's own machines: `make dock DOCK_ARGS='--ship <name>'`.
- Ask whether new room messages should appear in their Claude Code sessions; if yes, add `--hook`.
- `make dock` waits up to 9 minutes per run, so run it with a 10-minute Bash timeout (Claude
  Code's default is 2 minutes). While it waits for approval, the Tailscale share or confirmation
  in the browser it ends with a `STATUS:` line, and make reports `Error 3`; that is expected, not
  a failure. Relay the instructions it showed, then run it again until it prints `STATUS: docked`
  (`STATUS: denied` or `expired` means stop and tell them). Never ask for or type their password;
  they choose it in the browser.
