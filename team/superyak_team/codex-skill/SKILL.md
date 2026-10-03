---
name: superyak-team
description: Lead a Superyak team of Codex (gpt-6.1-sol) and Claude Code workers — builders that implement in their own git worktrees and read-only collaborators that research, debate and write documents — coordinated on Slack with local + shared engram memory. Use when the user asks to run something as a team, spin up workers or collaborators, or parallelize work across agents.
---

# Superyak team (Codex as lead)

Read and follow the lead brief: run `superyak-runtime team brief` (it prints
`team/superyak_team/roles/lead.md` from wherever the Superyak repo is checked out).

Use the `team` MCP tools: `team_start(goal, preset, config)`, `team_list`, `team_plan`,
`team_spawn(task, kind, mode, context)`, `team_status`, `team_message`, `team_collect`,
`team_stop`, `team_post`, `team_end(summary)`. Without the tools, the same operations exist as
`superyak-runtime team <op> key=value ...`.

Plan before spawning; pick the preset that fits (build, research, review, mixed). Never push or
merge to main without the user.
