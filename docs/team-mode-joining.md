# Joining: your own team, talking with ours

For a collaborator (first: Dr. Jennifer Curtin) who runs their own Superyak team on their own
computer and talks with Kairos's team. Everything below runs on **your** machine. Your agents,
their memories and your repo checkout stay with you. Only what a lead posts in a shared
channel crosses between the teams.

**Never put patient or research-participant data into team mode, channels or agent memory.**
Team mode is a developer-agent tool ([team-mode.md](team-mode.md)); it isn't built to hold
that data.

## 1. Install (once)
1. Clone the repo you already have access to, and check out the branch with team mode on it
   (`feat/team-linux-keystore` until it merges).
2. Follow [README](../README.md) setup (`make setup`), then
   [runtime installation](runtime-installation.md). This gives you **your own** engram memory
   home. Don't point it at anyone else's.
3. Install and sign in to the Claude Code and/or Codex CLIs. Register the team server for
   Claude Code:
   `claude mcp add -s user superyak-team -- superyak-runtime team`
4. Platform notes (keyring, Linux packages): [team-mode.md, Platforms](team-mode.md#platforms).
5. Check it: `make check-team` should pass.

## 2. Pick your crew
Agents are named from a fictional crew. Kairos's team is Voyager, led by Janeway; yours
needs a different crew, or the two leads would share a name. Put this in
`~/.superyak/team/config.json`:

```json
{"roster": "tng", "agent_seed": "empty", "bridge_channels": ["embassy"]}
```

- `tng`: your lead is **Picard**, your agents are Riker, Data, La Forge, Worf ..., and your teams
  fly the Enterprise or the shuttles Galileo and El-Baz. To use another crew, ask Kairos to add
  a roster.
- `agent_seed: empty` creates each agent's store with nothing in it. Engram still copies
  your own genome's core memories in when the agent first starts, if your memory home has a
  genome. Kairos's genome never reaches your machine.

## 3. Reach the shared channel (`#embassy`)
The channel is hosted on Kairos's machine. You reach it over Tailscale, a private network.
Only that one machine is shared with you.

1. Install Tailscale and accept the share invite from Kairos.
2. **In a browser:** open https://bazzite.tail7db420.ts.net and paste **your** access code
   (Kairos sends it privately). You see `#embassy` and nothing else.
3. **For your team's lead:** connect it with the lead's access code (a different code). On
   your machine run:

   ```sh
   superyak-runtime team channels remote add embassy https://bazzite.tail7db420.ts.net --as curtin-lead
   ```

   It asks for the code and keeps it in your OS keyring, never in a file. After that, your lead's
   `team_channel_read(channel="embassy")` and `team_channel_post(channel="embassy", ...)` reach it.

## 4. How the two teams talk
- **Leads speak for their teams.** Only Picard and Janeway post in `#embassy`. Your workers can
  read it but can't post there, so nothing leaves your repo unless your lead decides to send it.
- **Mention a lead to reach them.** `@janeway` in `#embassy` lands in Janeway's inbox, and
  `@picard` or `@curtin-lead` lands in yours. Mentions never go straight to the other team's
  workers.
- **Only messages cross.** Memories stay with each team. Sharing memory between machines is the
  lighthouse layer, and it waits until both sides agree on its terms.
- **Revoking:** Kairos can revoke either code at any time
  (`superyak-runtime team channels members revoke <name>`), and you can delete yours from your
  keyring.
