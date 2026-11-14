//! The types every crate in v2 shares. The stage 1 plan fixes these names; change them there first.

use std::path::PathBuf;

use serde::{Deserialize, Serialize};

/// Seconds since the Unix epoch, UTC.
pub type Ts = i64;

/// An item's id: "i" and 12 lowercase hex digits.
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub struct ItemId(pub String);

/// An attempt's id: "a" and 12 lowercase hex digits.
#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub struct AttemptId(pub String);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ItemState {
    Draft,
    Open,
    Leased,
    Checking,
    PassedVerified,
    PassedUnverified,
    Failed,
    Blocked,
    Abandoned,
}

/// Where a check came from. Only the first two can verify a pass.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CheckOrigin {
    /// Supplied from outside the room.
    Outside,
    /// Reproduces a failure someone observed.
    ObservedFailure,
    /// Written or judged by a model.
    Model,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CheckSpec {
    /// Run with `sh -c` at the repository root.
    pub command: String,
    /// Tracked paths the check reads; frozen by content.
    pub files: Vec<String>,
    pub timeout_secs: u32,
    pub origin: CheckOrigin,
    /// Commits the check must fail on.
    pub wrong_artifacts: Vec<String>,
    /// "person:<name>", "ship:<name>", "claude:<model>" or "codex:<model>".
    pub written_by: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct NewItem {
    pub title: String,
    pub repo: PathBuf,
    pub base_commit: String,
    pub after: Vec<ItemId>,
    pub check: CheckSpec,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Frozen {
    pub check_hash: String,
    pub red_on_base: bool,
    pub red_on_wrong: Vec<bool>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Lease {
    pub item: ItemId,
    pub attempt: AttemptId,
    pub lease_no: u32,
    pub worker: String,
    pub expires: Ts,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Verdict {
    pub passed: bool,
    pub exit_code: i32,
    pub timed_out: bool,
    pub commit: String,
    pub check_hash: String,
    pub output_sha256: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Tool {
    Read,
    Edit,
    Write,
    Search,
    Shell,
    Other,
}

/// What a step touched. Anything that is not a tracked file of the item's repository is `Outside`, with no name.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Target {
    TrackedFile { path: String, blob: String },
    Outside,
}

/// One observed tool call of a turn. It has no free-text field, on purpose (spec rule 9).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Step {
    pub seq: u32,
    pub tool: Tool,
    pub target: Target,
    pub ok: bool,
    pub tokens_in: Option<u32>,
    pub tokens_out: Option<u32>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DisagreementKind {
    RecheckDiffers,
    Abandoned,
    WeakCheck,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Disagreement {
    pub kind: DisagreementKind,
    pub item: ItemId,
    pub detail: String,
}

#[derive(Debug, thiserror::Error)]
pub enum RoomError {
    #[error("no room at {0}: run `yak init` to make one")]
    Missing(PathBuf),
    #[error("the room's store is damaged: {0}")]
    Damaged(String),
    #[error("the room's store is version {found}, and this build knows version {known}")]
    NewerSchema { found: u32, known: u32 },
    #[error("another process is writing to this room")]
    Locked,
    #[error("stale: lease {lease_no} is not the current lease {current}")]
    Stale { lease_no: u32, current: u32 },
    #[error("not takeable: {0}")]
    NotTakeable(String),
    #[error("the daily ceiling is reached: {used} of {limit} turns")]
    Ceiling { used: u32, limit: u32 },
    #[error("the room is stopped")]
    Stopped,
    #[error("refused: {0}")]
    Refused(String),
    #[error("store error: {0}")]
    Db(String),
}

/// A worker's family is the part of its name before the colon: "claude:opus" is "claude".
pub fn family(worker: &str) -> &str {
    worker.split(':').next().unwrap_or(worker)
}
