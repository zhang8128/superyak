# superyak-agent

Docks this machine's agent at a Superyak station as a **ship**. Run `make dock` from the
repository root; see [the design](../docs/superpowers/specs/2026-10-03-ds9-station-design.md).
Standard library only; it reuses team mode's fencing, redaction, sandbox and hardened git from
`../team`, so run it from a full clone through `run_agent.py`.
