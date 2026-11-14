//! One turn: a sandbox, a worker and a frozen check. See the stage 1 plan, tasks 6 to 8.
//!
//! A turn's only effect is a commit on its own branch, in a local clone with no remote. Nothing a worker prints
//! is kept as text: its event stream becomes `Step`s, which have no free-text field (spec rule 9).

pub mod check;
mod filter;
pub mod jail;
mod process;
pub mod sandbox;
pub mod transcript;
pub mod worker;

pub use sandbox::{RunStatus, Sandbox};
pub use worker::{Worker, WorkerRun};

#[derive(Debug, thiserror::Error)]
pub enum TurnError {
    /// A git command the turn itself ran failed.
    #[error("git: {0}")]
    Git(String),
    /// A file or process operation failed.
    #[error("{0}")]
    Io(String),
    /// The input was refused before anything ran.
    #[error("refused: {0}")]
    Refused(String),
    #[error("unknown worker {0:?}: a worker is script:<path>, claude:<model> or codex:<model>")]
    UnknownWorker(String),
    /// A run could not be confirmed ended: something it started may still be going. Its record is kept. Whoever
    /// gets this removes nothing of that run and goes on with nothing else, since the record and the run's
    /// directories are what a person needs to find it and end it.
    #[error("a run could not be confirmed ended ({why}); its record, {record}, is kept")]
    Unended { record: String, why: String },
    /// What was found where a sandbox or its scratch directory should be was not what the room made there. It
    /// was left as it is; these are the paths.
    #[error("not removed, because it is not what the room made there: {}", listed(.0))]
    Left(Vec<std::path::PathBuf>),
}

fn listed(paths: &[std::path::PathBuf]) -> String {
    let names: Vec<String> = paths.iter().map(|p| p.display().to_string()).collect();
    names.join(", ")
}

/// Maps an `io::Error` to a `TurnError::Io` that says what was being done.
pub(crate) fn io(what: impl Into<String>) -> impl FnOnce(std::io::Error) -> TurnError {
    let what = what.into();
    move |e| TurnError::Io(format!("{what}: {e}"))
}
