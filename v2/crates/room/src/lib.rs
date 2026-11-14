//! The room: a pool of work with frozen checks, leases, a ledger and whole walks.
//!
//! Spec: docs/superpowers/specs/2026-11-14-superyak-v2-design.md
//! Plan: docs/superpowers/plans/2026-11-14-v2-stage-1-room.md

mod budget;
pub mod item;
mod lease;
pub mod limits;
mod store;
pub mod types;
mod views;
mod walk;

pub use item::{ItemSpec, ItemView};
pub use types::*;
pub use views::Status;

/// A validated room connection. Writing connections retain an advisory lock until dropped.
pub struct Room {
    pub(crate) conn: rusqlite::Connection,
    pub(crate) dir: std::path::PathBuf,
    pub(crate) _lock: Option<std::fs::File>,
    pub(crate) lease_secs: i64,
}
