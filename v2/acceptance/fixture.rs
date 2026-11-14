//! Builds a tiny git repository with seeded red items. Stage 1 plan, task 0. Builders do not edit this crate.
//!
//! Five items, each one file (`items/itemN.txt`) and one check (`checks/itemN.sh`, a tracked shell script, so the
//! check is frozen by content and no toolchain is needed inside a turn). On the base commit every check fails. Each
//! item has a branch `fix-N` whose one commit makes its check pass, and a branch `wrong-N` whose one commit must not.
//! The workers the tests hand to `yak clock run` are scripts written next to the repository by [`worker`].

use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

/// One seeded item.
pub struct FixtureItem {
    pub title: String,
    /// The item's file, relative to the repository root.
    pub file: String,
    /// The check's tracked script, relative to the repository root.
    pub check_file: String,
    /// The command `yak item add --check` takes: run with `sh -c` at the repository root.
    pub check_command: String,
    /// The one commit that makes the check pass.
    pub fix_commit: String,
    /// The one commit the check must fail on.
    pub wrong_commit: String,
}

pub struct Fixture {
    pub repo: PathBuf,
    pub base_commit: String,
    pub items: Vec<FixtureItem>,
}

pub const ITEMS: usize = 5;

/// `git` in `repo`, with no system or global config, a fixed identity and fixed dates, so two builds give the same
/// commits. Panics with git's stderr when it fails.
pub fn git(repo: &Path, args: &[&str]) -> String {
    let out = Command::new("git")
        .arg("-C")
        .arg(repo)
        .args([
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "commit.gpgsign=false",
        ])
        .args(args)
        .env("GIT_CONFIG_NOSYSTEM", "1")
        .env("GIT_CONFIG_GLOBAL", "/dev/null")
        .env("GIT_AUTHOR_DATE", "2026-11-14T00:00:00Z")
        .env("GIT_COMMITTER_DATE", "2026-11-14T00:00:00Z")
        .output()
        .expect("git runs");
    assert!(
        out.status.success(),
        "git {args:?} failed: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout)
        .expect("git prints UTF-8")
        .trim()
        .to_string()
}

fn write(path: &Path, text: &str) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("make the parent");
    }
    fs::write(path, text).expect("write the file");
}

/// The value item `n`'s check wants in its file.
pub fn green(n: usize) -> String {
    format!("green-{n}")
}

/// Builds the repository under `dir/repo` and returns it with its five items.
pub fn build(dir: &Path) -> Fixture {
    let repo = dir.join("repo");
    fs::create_dir_all(&repo).expect("make the repository");
    git(&repo, &["init", "-q", "-b", "main"]);
    for n in 0..ITEMS {
        write(&repo.join(format!("items/item{n}.txt")), "red\n");
        write(
            &repo.join(format!("checks/item{n}.sh")),
            &format!(
                "#!/bin/sh\n# Item {n}: passes only when its file says {g}.\ntest \"$(cat items/item{n}.txt)\" = \"{g}\"\n",
                g = green(n)
            ),
        );
    }
    git(&repo, &["add", "-A"]);
    git(&repo, &["commit", "-q", "-m", "base: five red items"]);
    let base_commit = git(&repo, &["rev-parse", "HEAD"]);
    let mut items = Vec::new();
    for n in 0..ITEMS {
        let file = format!("items/item{n}.txt");
        let fix_commit = commit_on_branch(
            &repo,
            &base_commit,
            &format!("fix-{n}"),
            &file,
            &format!("{}\n", green(n)),
        );
        let wrong_commit = commit_on_branch(
            &repo,
            &base_commit,
            &format!("wrong-{n}"),
            &file,
            &format!("{}-not\n", green(n)),
        );
        items.push(FixtureItem {
            title: format!("Make item {n} green"),
            check_file: format!("checks/item{n}.sh"),
            check_command: format!("sh checks/item{n}.sh"),
            file,
            fix_commit,
            wrong_commit,
        });
    }
    git(&repo, &["checkout", "-q", "main"]);
    Fixture {
        repo,
        base_commit,
        items,
    }
}

fn commit_on_branch(repo: &Path, base: &str, branch: &str, file: &str, text: &str) -> String {
    git(repo, &["checkout", "-q", "-b", branch, base]);
    write(&repo.join(file), text);
    git(repo, &["commit", "-q", "-am", &format!("{branch}: {file}")]);
    git(repo, &["rev-parse", "HEAD"])
}

/// Every ref in `repo`, one `<sha> <name>` per line, sorted.
pub fn refs(repo: &Path) -> Vec<String> {
    let mut lines: Vec<String> = git(repo, &["for-each-ref", "--format=%(objectname) %(refname)"])
        .lines()
        .map(str::to_string)
        .collect();
    lines.sort();
    lines
}

/// Writes an executable worker script at `dir/name.sh` and returns its `script:<path>` worker name. The body runs
/// with `sh` in the turn's sandbox, a clone of the repository; `commit MESSAGE` commits every tracked change.
pub fn worker(dir: &Path, name: &str, body: &str) -> String {
    let path = dir.join(format!("{name}.sh"));
    let script = format!(
        "#!/bin/sh\nset -u\ncommit() {{ git -c user.name=Worker -c user.email=worker@example.invalid -c commit.gpgsign=false commit -q -am \"$1\"; }}\n{body}\n"
    );
    write(&path, &script);
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&path, fs::Permissions::from_mode(0o755))
            .expect("make the worker executable");
    }
    format!("script:{}", path.display())
}

/// A worker that makes every item green and commits, whichever item it was given.
pub fn fixing_worker(dir: &Path) -> String {
    let lines: Vec<String> = (0..ITEMS)
        .map(|n| format!("echo {} > items/item{n}.txt", green(n)))
        .collect();
    worker(
        dir,
        "fix-all",
        &format!("{}\ncommit 'make every item green'", lines.join("\n")),
    )
}
