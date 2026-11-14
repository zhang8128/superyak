//! Task 6: the sandbox.

mod common;

use std::process::Command;
use std::time::{Duration, Instant};

use common::{Repo, git, group_alive, pid_alive, strings, wait_until};
use room::limits::TERM_GRACE_SECS;
use turn::sandbox::MAX_LINE_BYTES;
use turn::{Sandbox, TurnError};

fn sandbox(repo: &Repo) -> Sandbox {
    Sandbox::create(
        &repo.path,
        &repo.base,
        &repo.scratch("sandbox"),
        "room/i1/1",
    )
    .unwrap()
}

/// Runs `script` with `sh -c` in the sandbox and returns its status and lines.
fn sh(sb: &Sandbox, script: &str, limit: u32) -> (turn::RunStatus, Vec<String>) {
    let mut lines = Vec::new();
    let status = sb
        .run("sh", &strings(&["-c", script]), "", limit, &mut |l| {
            lines.push(l.to_string())
        })
        .unwrap();
    (status, lines)
}

#[test]
fn the_sandbox_is_a_clone_with_no_remote() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    repo.write("a.txt", "later\n");
    let later = repo.commit("later");
    let sb = sandbox(&repo);
    assert_eq!(git(&sb.dir, &["remote"]), "");
    assert_eq!(git(&sb.dir, &["rev-parse", "HEAD"]), repo.base);
    assert_ne!(
        repo.base, later,
        "the clone sits at base_commit, not at the repository's head"
    );
    assert_eq!(
        git(&sb.dir, &["rev-parse", "--abbrev-ref", "HEAD"]),
        "room/i1/1"
    );
    assert_eq!(sb.branch, "room/i1/1");
    assert_eq!(sb.head().unwrap(), repo.base);
    assert_eq!(
        std::fs::read_to_string(sb.dir.join("a.txt")).unwrap(),
        "hello\n"
    );
}

#[test]
fn a_push_from_the_sandbox_fails_even_to_a_path() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let before = repo.refs();
    let (plain, _) = sh(&sb, "git push", 30);
    assert_ne!(plain.exit_code, 0);
    let target = repo.path.to_str().unwrap();
    let (to_path, _) = sh(
        &sb,
        &format!("git push '{target}' HEAD:refs/heads/escape"),
        30,
    );
    assert_ne!(to_path.exit_code, 0);
    assert_eq!(repo.refs(), before);
}

#[test]
fn create_refuses_an_unknown_commit_and_a_bad_branch() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let missing = "0123456789012345678901234567890123456789";
    let bad_commit = Sandbox::create(&repo.path, missing, &repo.scratch("s1"), "room/x");
    assert!(bad_commit.is_err());
    assert!(
        !repo.scratch("s1").exists(),
        "a failed create leaves nothing behind"
    );
    let bad_branch = Sandbox::create(&repo.path, &repo.base, &repo.scratch("s2"), "-x..y");
    assert!(matches!(bad_branch, Err(TurnError::Refused(_))));
    let option = Sandbox::create(&repo.path, "--orphan", &repo.scratch("s3"), "room/x");
    assert!(option.is_err());
}

#[test]
fn the_environment_is_scrubbed() {
    // A test cannot set variables in its own process without `unsafe`, so it runs this binary again with them
    // set, and the child reports what a run in its sandbox sees.
    let out = Command::new(std::env::current_exe().unwrap())
        .args([
            "env_probe",
            "--exact",
            "--ignored",
            "--nocapture",
            "--test-threads=1",
        ])
        .env("TURN_ENV_PROBE", "1")
        .env("GH_TOKEN", "secret")
        .env("GITHUB_TOKEN", "secret")
        .env("SSH_AUTH_SOCK", "/tmp/agent.sock")
        .env("SUPERYAK_X", "secret")
        .env("GIT_DIR", "/nowhere")
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(
        out.status.success(),
        "the probe failed: {stdout}{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let names: Vec<&str> = stdout
        .lines()
        .filter_map(|l| l.strip_prefix("ENV:"))
        .collect();
    assert!(
        names.contains(&"PATH"),
        "the probe saw the run's environment: {names:?}"
    );
    for hidden in [
        "GH_TOKEN",
        "GITHUB_TOKEN",
        "SSH_AUTH_SOCK",
        "SUPERYAK_X",
        "GIT_DIR",
    ] {
        assert!(!names.contains(&hidden), "{hidden} reached the sandbox");
    }
}

#[test]
#[ignore = "run in a child process by the_environment_is_scrubbed"]
fn env_probe() {
    if std::env::var_os("TURN_ENV_PROBE").is_none() {
        return;
    }
    assert!(
        std::env::var_os("GH_TOKEN").is_some(),
        "the parent set the variables"
    );
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let mut names = Vec::new();
    let status = sb
        .run("env", &[], "", 30, &mut |l| {
            if let Some((name, _)) = l.split_once('=') {
                names.push(name.to_string());
            }
        })
        .unwrap();
    assert_eq!(status.exit_code, 0);
    for name in names {
        println!("ENV:{name}");
    }
}

#[test]
fn a_run_past_its_limit_is_ended_with_its_children() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let start = Instant::now();
    // The plan's `sleep 600 & sleep 600`, telling us the group (the shell's own id) and the background job.
    let (status, lines) = sh(&sb, "echo $$; sleep 600 & echo $!; sleep 600", 1);
    assert!(status.timed_out);
    assert_ne!(status.exit_code, 0);
    let group: u32 = lines[0].parse().unwrap();
    let background: u32 = lines[1].parse().unwrap();
    let bound = start + Duration::from_secs(1 + u64::from(TERM_GRACE_SECS) + 2);
    assert!(
        Instant::now() < bound,
        "run returned after {:?}",
        start.elapsed()
    );
    assert!(wait_until(bound, || !group_alive(group) && !pid_alive(background)));
    // These processes go at SIGTERM, so the run did not sit out the grace before a SIGKILL.
    assert!(
        start.elapsed() < Duration::from_secs(u64::from(TERM_GRACE_SECS)),
        "{:?}",
        start.elapsed()
    );
}

#[test]
fn a_group_that_ignores_term_is_killed_after_the_grace() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let start = Instant::now();
    let (status, lines) = sh(
        &sb,
        "trap '' TERM; echo $$; sleep 600 & echo $!; sleep 600",
        1,
    );
    assert!(status.timed_out);
    let elapsed = start.elapsed();
    assert!(
        elapsed >= Duration::from_secs(u64::from(TERM_GRACE_SECS)),
        "it waited the grace: {elapsed:?}"
    );
    let group: u32 = lines[0].parse().unwrap();
    let background: u32 = lines[1].parse().unwrap();
    let bound = start + Duration::from_secs(1 + u64::from(TERM_GRACE_SECS) + 2);
    assert!(wait_until(bound, || !group_alive(group) && !pid_alive(background)));
}

#[test]
fn a_job_left_behind_by_a_finished_run_is_ended() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let start = Instant::now();
    // The job keeps the output pipe open, so a run that waited for the pipe to close would wait 600 seconds.
    let (status, lines) = sh(&sb, "echo $$; sleep 600 & echo $!", 60);
    assert!(!status.timed_out);
    assert_eq!(status.exit_code, 0);
    assert!(
        start.elapsed() < Duration::from_secs(5),
        "returned after {:?}",
        start.elapsed()
    );
    let group: u32 = lines[0].parse().unwrap();
    let background: u32 = lines[1].parse().unwrap();
    assert!(wait_until(Instant::now() + Duration::from_secs(2), || {
        !group_alive(group) && !pid_alive(background)
    }));
}

#[test]
fn lines_are_handed_over_as_they_come() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let start = Instant::now();
    let mut first = None;
    let status = sb
        .run(
            "sh",
            &strings(&["-c", "echo first; sleep 600"]),
            "",
            2,
            &mut |_| {
                first.get_or_insert(start.elapsed());
            },
        )
        .unwrap();
    assert!(status.timed_out);
    let first = first.expect("a line arrived");
    assert!(
        first + Duration::from_secs(1) < start.elapsed(),
        "the line came at {first:?}, during the run"
    );
}

#[test]
fn stdout_stderr_stdin_and_the_exit_code() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let mut lines = Vec::new();
    let status = sb
        .run(
            "sh",
            &strings(&["-c", "cat; echo err >&2; exit 3"]),
            "one\ntwo\n",
            30,
            &mut |l| lines.push(l.to_string()),
        )
        .unwrap();
    assert_eq!(status.exit_code, 3);
    assert!(!status.timed_out);
    assert_eq!(lines, ["one", "two", "err"]);
}

#[test]
fn a_run_that_never_reads_a_large_stdin_still_ends() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    // Far more than a pipe holds, to a process that never reads it: a run that wrote it before watching the
    // clock would never reach its limit.
    let big = "x".repeat(4 << 20);
    let start = Instant::now();
    let status = sb
        .run("sh", &strings(&["-c", "sleep 600"]), &big, 2, &mut |_| {})
        .unwrap();
    assert!(status.timed_out);
    assert!(start.elapsed() < Duration::from_secs(2 + u64::from(TERM_GRACE_SECS)));
}

#[test]
fn create_refuses_a_directory_that_holds_something() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let dir = repo.scratch("taken");
    std::fs::create_dir(&dir).unwrap();
    std::fs::write(dir.join("keep.txt"), "mine").unwrap();
    let made = Sandbox::create(&repo.path, &repo.base, &dir, "room/x");
    assert!(matches!(made, Err(TurnError::Refused(_))));
    assert_eq!(
        std::fs::read_to_string(dir.join("keep.txt")).unwrap(),
        "mine"
    );
}

#[test]
fn a_line_longer_than_the_cap_is_cut() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let long = MAX_LINE_BYTES + (1 << 20);
    let script = format!("head -c {long} /dev/zero | tr '\\000' a; echo; echo next");
    let mut lengths = Vec::new();
    let mut last = String::new();
    let status = sb
        .run("sh", &strings(&["-c", &script]), "", 60, &mut |l| {
            lengths.push(l.len());
            last = l.to_string();
        })
        .unwrap();
    assert_eq!(status.exit_code, 0);
    assert_eq!(lengths, [MAX_LINE_BYTES, 4]);
    assert_eq!(last, "next");
}

#[test]
fn the_pid_file_holds_the_running_group_and_is_gone_after() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let mut sb = sandbox(&repo);
    let pid_file = repo.scratch("a1.pid");
    sb.set_pid_file(pid_file.clone());
    let mut seen = None;
    let status = sb
        .run(
            "sh",
            &strings(&["-c", "echo $$; sleep 1"]),
            "",
            30,
            &mut |l| {
                let text =
                    std::fs::read_to_string(&pid_file).expect("the pid file exists during the run");
                let group: u32 = text.parse().expect("decimal text");
                seen = Some((l.parse::<u32>().unwrap(), group, group_alive(group)));
            },
        )
        .unwrap();
    assert_eq!(status.exit_code, 0);
    let (shell, group, alive) = seen.unwrap();
    assert_eq!(group, shell, "the file names the run's own process group");
    assert!(alive);
    assert!(!pid_file.exists());
}

#[test]
fn destroy_removes_the_directory() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let dir = sb.dir.clone();
    // A worker may leave a directory nobody can write to, holding one nobody can read.
    let (status, _) = sh(
        &sb,
        "mkdir -p ro/inner && touch ro/inner/f && chmod 000 ro/inner && chmod 555 ro",
        30,
    );
    assert_eq!(status.exit_code, 0);
    assert!(dir.exists());
    sb.destroy().unwrap();
    assert!(!dir.exists());
    assert!(
        repo.path.join("a.txt").exists(),
        "the repository itself is untouched"
    );
}

#[test]
fn a_clone_whose_git_directory_was_swapped_is_refused() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let before = repo.refs();
    // The worker points its clone at the item's own repository.
    let swap = format!(
        "mv .git .git-moved && ln -s '{}/.git' .git",
        repo.path.display()
    );
    let (status, _) = sh(&sb, &swap, 30);
    assert_eq!(status.exit_code, 0);
    assert!(matches!(sb.head(), Err(TurnError::Refused(_))));
    assert!(matches!(sb.reclaim(), Err(TurnError::Refused(_))));
    assert_eq!(repo.refs(), before);
}
