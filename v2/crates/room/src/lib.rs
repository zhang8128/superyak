//! The room: a pool of work with frozen checks, leases, a ledger and whole walks.
//!
//! Spec: docs/superpowers/specs/2026-11-14-superyak-v2-design.md
//! Plan: docs/superpowers/plans/2026-11-14-v2-stage-1-room.md

pub mod limits;
pub mod types;

pub use types::*;
