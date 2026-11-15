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

/// A tracked file a step named: its path in the repository and its blob at the base.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Named {
    pub path: String,
    pub blob: String,
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
    /// Every tracked file the step named, in the order named. Empty when it named none.
    pub named: Vec<Named>,
    /// Milliseconds from the turn's start to the call being seen, and to its result.
    pub seen_ms: Option<u32>,
    pub result_ms: Option<u32>,
}

/// What a worker's program reported for a whole turn. A part it did not report is `None`, never 0.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Tokens {
    pub fresh_in: Option<u64>,
    pub cache_write: Option<u64>,
    pub cache_read: Option<u64>,
    pub output: Option<u64>,
    pub reasoning: Option<u64>,
    /// True only when the program gave its closing total.
    pub complete: bool,
}

impl Tokens {
    /// Every part `None`, not complete.
    pub fn none() -> Tokens {
        Tokens {
            fresh_in: None,
            cache_write: None,
            cache_read: None,
            output: None,
            reasoning: None,
            complete: false,
        }
    }

    /// `fresh_in + cache_write + cache_read + output`, when the program gave its closing total and every one
    /// of those parts. `reasoning` is not added. A sum too large for a `u64` is not known either.
    pub fn total(&self) -> Option<u64> {
        if !self.complete {
            return None;
        }
        self.fresh_in?
            .checked_add(self.cache_write?)?
            .checked_add(self.cache_read?)?
            .checked_add(self.output?)
    }
}

/// How a turn's worker ended.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Ended {
    /// Its program ended by itself, with an exit code.
    Exited,
    /// A signal ended its program, and neither its limit nor a stop or a lost lease sent it.
    Signalled,
    /// Its program ran to the turn's limit and the room ended it.
    TimedOut,
    /// The room was stopped while its program ran, and the room ended it.
    Stopped,
    /// The turn's lease was lost while its program ran, and the room ended it.
    LeaseLost,
    /// No program was started.
    NotRun,
    /// A program was started and the room does not know how it ended: its run failed before it could say.
    Unknown,
}

/// A turn's measured record. Durations are milliseconds on a clock that does not jump.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Measured {
    /// How the turn's worker ended, not how the turn did: a stop or a lost lease that comes after the worker has
    /// ended (while its commit is brought in, at the hand-in, at the verdict) leaves it as the worker's own end.
    pub ended: Ended,
    pub exit_code: Option<i32>,
    pub tokens: Tokens,
    pub steps_seen: u64,
    pub unknown_steps: u64,
    /// Files the turn's commit changed that were counted and not kept: a path that is not plain, or one past
    /// `limits::MAX_CHANGES`.
    pub unknown_changes: u64,
    pub sandbox_ms: u64,
    pub worker_ms: u64,
    pub seal_ms: u64,
    /// Bringing the commit into the item's repository, and the hand-in. A turn that hands in nothing has no
    /// commit to bring, and still has a few milliseconds here, not 0: its hand-in is recorded in this phase.
    pub bring_ms: u64,
    pub check_ms: Option<u64>,
    pub recheck_ms: Option<u64>,
    /// sandbox_ms + worker_ms + seal_ms + bring_ms + check_ms. A second look is not in it.
    pub active_ms: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Change {
    Added,
    Changed,
    Removed,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChangedFile {
    pub path: String,
    pub change: Change,
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
    #[error(
        "the room's store is version {found}, and this build knows version {known}; bring it forward by opening it once for writing"
    )]
    OlderSchema { found: u32, known: u32 },
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

#[cfg(test)]
mod tests {
    use super::Tokens;

    fn tokens(complete: bool) -> Tokens {
        Tokens {
            fresh_in: Some(1),
            cache_write: Some(2),
            cache_read: Some(3),
            output: Some(4),
            reasoning: Some(100),
            complete,
        }
    }

    #[test]
    fn total_is_the_sum_of_the_four_parts_without_reasoning_when_complete() {
        assert_eq!(tokens(true).total(), Some(1 + 2 + 3 + 4));
    }

    #[test]
    fn total_is_none_when_a_part_is_missing() {
        let mut t = tokens(true);
        t.cache_read = None;
        assert_eq!(t.total(), None);
    }

    #[test]
    fn total_is_none_when_not_complete() {
        assert_eq!(tokens(false).total(), None);
    }

    #[test]
    fn total_is_none_when_the_sum_would_overflow() {
        for part in 0..4 {
            let mut t = tokens(true);
            let parts = [
                &mut t.fresh_in,
                &mut t.cache_write,
                &mut t.cache_read,
                &mut t.output,
            ];
            *parts.into_iter().nth(part).unwrap() = Some(u64::MAX);
            assert_eq!(t.total(), None, "part {part}");
        }
        // The control: the largest sum that fits is still given.
        let mut t = tokens(true);
        t.output = Some(u64::MAX - 6);
        assert_eq!(t.total(), Some(u64::MAX));
    }
}
