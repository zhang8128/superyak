//! What the clock and `yak offer render` need beside the room's reader of an offer file: the file's bytes, read
//! no further than the room's limit, and the files a base tracks, as the room's own git lists them.

use std::collections::HashSet;
use std::fs::File;
use std::io::Read;
use std::path::Path;
use std::sync::atomic::AtomicBool;
use std::time::Duration;

use room::offer::{self, MAX_OFFER_BYTES, Offer, OfferError};
use turn::TurnError;

#[derive(Debug, thiserror::Error)]
pub enum ReadError {
    #[error("the offer file {path} could not be read: {why}")]
    Io { path: String, why: String },
    #[error(transparent)]
    Refused(#[from] OfferError),
}

/// Reads the offer file at `path`: at most one byte past the room's limit is read, so a larger file is refused
/// without being read whole.
pub fn read_file(path: &Path) -> Result<Offer, ReadError> {
    let io = |e: std::io::Error| ReadError::Io {
        path: path.display().to_string(),
        why: e.to_string(),
    };
    let file = File::open(path).map_err(io)?;
    let mut bytes = Vec::new();
    file.take(MAX_OFFER_BYTES as u64 + 1)
        .read_to_end(&mut bytes)
        .map_err(io)?;
    Ok(offer::read(&bytes)?)
}

/// The regular files tracked at `commit` in `repo`, by path: what the room's own git lists there, within `limit`.
/// Links and submodules are not files, as a walk's tracked file is not.
pub fn tracked_at(
    repo: &Path,
    commit: &str,
    limit: Duration,
) -> Result<HashSet<String>, TurnError> {
    let mut command = turn::sandbox::safe_git();
    command.arg("-C").arg(repo).args([
        "ls-tree",
        "-r",
        "-z",
        "--full-tree",
        "--end-of-options",
        commit,
    ]);
    let listing = turn::sandbox::safe_git_output_until(
        command,
        "list the files tracked at the base",
        limit,
        &AtomicBool::new(false),
    )?;
    let mut files = HashSet::new();
    for entry in listing.split(|&b| b == 0) {
        // "<mode> <type> <object>\t<path>"
        let Some(tab) = entry.iter().position(|&b| b == b'\t') else {
            continue;
        };
        let (Ok(meta), Ok(path)) = (
            std::str::from_utf8(&entry[..tab]),
            std::str::from_utf8(&entry[tab + 1..]),
        ) else {
            continue;
        };
        let mut parts = meta.split(' ');
        if let (Some("100644" | "100755"), Some("blob")) = (parts.next(), parts.next()) {
            files.insert(path.to_string());
        }
    }
    Ok(files)
}
