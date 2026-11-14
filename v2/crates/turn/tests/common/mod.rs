//! Helpers the turn crate's tests share: a throwaway git repository and process probes.
#![allow(dead_code)]

use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread::sleep;
use std::time::{Duration, Instant};

/// Runs git in `dir` with a fixed identity and no hooks, and returns its trimmed stdout. Panics on failure.
pub fn git(dir: &Path, args: &[&str]) -> String {
    let out = git_raw(dir, args);
    assert!(
        out.status.success(),
        "git {args:?} failed: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout)
        .unwrap()
        .trim_end()
        .to_string()
}

pub fn git_raw(dir: &Path, args: &[&str]) -> std::process::Output {
    Command::new("git")
        .env_remove("GIT_DIR")
        .env_remove("GIT_WORK_TREE")
        .env_remove("GIT_INDEX_FILE")
        .arg("-C")
        .arg(dir)
        .args([
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=/dev/null",
        ])
        .args(args)
        .output()
        .expect("git runs")
}

/// A git repository in a temporary directory, with room beside it for sandboxes and checks.
pub struct Repo {
    pub tmp: tempfile::TempDir,
    pub path: PathBuf,
    pub base: String,
}

impl Repo {
    /// A repository whose first commit holds `files`; `base` is that commit.
    pub fn new(files: &[(&str, &str)]) -> Repo {
        let tmp = tempfile::tempdir().unwrap();
        let path = tmp.path().join("repo");
        std::fs::create_dir(&path).unwrap();
        git(&path, &["init", "-q", "-b", "main"]);
        let mut repo = Repo {
            tmp,
            path,
            base: String::new(),
        };
        for (name, content) in files {
            repo.write(name, content);
        }
        repo.base = repo.commit("base");
        repo
    }

    pub fn write(&self, name: &str, content: &str) {
        let file = self.path.join(name);
        std::fs::create_dir_all(file.parent().unwrap()).unwrap();
        std::fs::write(file, content).unwrap();
    }

    pub fn remove(&self, name: &str) {
        std::fs::remove_file(self.path.join(name)).unwrap();
    }

    /// Commits everything in the work tree and returns the commit.
    pub fn commit(&self, message: &str) -> String {
        git(&self.path, &["add", "-A"]);
        git(
            &self.path,
            &["commit", "-q", "--allow-empty", "-m", message],
        );
        git(&self.path, &["rev-parse", "HEAD"])
    }

    /// Makes a commit on its own branch from `from`, by `change`, and returns to `main` at `base`.
    pub fn branch_commit(&self, branch: &str, from: &str, change: impl FnOnce(&Repo)) -> String {
        git(&self.path, &["checkout", "-q", "-b", branch, from]);
        change(self);
        let commit = self.commit(branch);
        git(&self.path, &["checkout", "-q", "main"]);
        commit
    }

    /// A path beside the repository, for a sandbox or a check directory. It does not exist yet.
    pub fn scratch(&self, name: &str) -> PathBuf {
        self.tmp.path().join(name)
    }

    pub fn refs(&self) -> Vec<String> {
        git(&self.path, &["for-each-ref", "--format=%(refname)"])
            .lines()
            .map(str::to_string)
            .collect()
    }
}

pub fn strings(args: &[&str]) -> Vec<String> {
    args.iter().map(|a| a.to_string()).collect()
}

fn kill_zero(target: &str) -> bool {
    Command::new("kill")
        .args(["-0", "--", target])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
}

/// Whether a process with this id exists.
pub fn pid_alive(pid: u32) -> bool {
    kill_zero(&pid.to_string())
}

/// Whether any process remains in this process group.
pub fn group_alive(pgid: u32) -> bool {
    kill_zero(&format!("-{pgid}"))
}

/// Polls `done` until it is true or `deadline` passes; returns its last answer.
pub fn wait_until(deadline: Instant, mut done: impl FnMut() -> bool) -> bool {
    loop {
        if done() {
            return true;
        }
        if Instant::now() >= deadline {
            return false;
        }
        sleep(Duration::from_millis(50));
    }
}
