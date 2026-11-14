//! Task 6: the sandbox.

mod common;

use std::process::Command;
use std::time::{Duration, Instant};

use common::{EndGroupOnDrop, EndOnDrop, Repo, git, group_alive, pid_alive, strings, wait_until};
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
    let (status, lines) = sh(
        &sb,
        "echo $$; sleep 600 & echo $!; perl -MPOSIX -e '$|=1; setsid(); print \"DETACHED=$$\\n\"; sleep 600' & sleep 600",
        1,
    );
    let detached: u32 = lines
        .iter()
        .find_map(|l| l.strip_prefix("DETACHED="))
        .unwrap()
        .parse()
        .unwrap();
    let _cleanup = EndOnDrop(detached);
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
    assert!(wait_until(bound, || !group_alive(group)
        && !pid_alive(background)
        && !pid_alive(detached)));
    // These processes go at SIGTERM, so the run did not sit out the grace before a SIGKILL.
    assert!(
        start.elapsed() < Duration::from_secs(u64::from(TERM_GRACE_SECS)),
        "{:?}",
        start.elapsed()
    );
}

/// The clock ends a turn from another thread, when the room is stopped or the turn's lease is lost.
#[test]
fn a_stopped_run_is_ended_with_its_children_and_no_later_run_starts() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let stop = sb.stop_switch();
    let start = Instant::now();
    let (status, lines) = std::thread::scope(|scope| {
        scope.spawn(|| {
            std::thread::sleep(Duration::from_millis(700));
            stop.store(true, std::sync::atomic::Ordering::Relaxed);
        });
        sh(&sb, "echo $$; sleep 600 & echo $!; sleep 600", 60)
    });
    // It was ended, and not because its time was up.
    assert!(!status.timed_out);
    assert_ne!(status.exit_code, 0);
    assert!(
        start.elapsed() < Duration::from_secs(u64::from(TERM_GRACE_SECS)),
        "{:?}",
        start.elapsed()
    );
    let group: u32 = lines[0].parse().unwrap();
    let background: u32 = lines[1].parse().unwrap();
    assert!(wait_until(
        Instant::now() + Duration::from_secs(2),
        || !group_alive(group) && !pid_alive(background)
    ));
    // The switch stays set, so nothing more starts in this sandbox: not the turn's own git either.
    let mark = repo.scratch("started-after-the-stop");
    let touch = format!("touch '{}'", mark.display());
    let refused = sb.run("sh", &strings(&["-c", &touch]), "", 60, &mut |_| {});
    assert!(matches!(refused, Err(TurnError::Refused(_))));
    assert!(!mark.exists());
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
                let fields: Vec<_> = text.lines().collect();
                assert_eq!(fields.len(), 2);
                let group: u32 = fields[0].parse().expect("decimal group");
                assert!(!fields[1].is_empty());
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
fn stale_process_identity_is_never_signalled() {
    use std::os::unix::process::CommandExt;
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let mut child = Command::new("sleep")
        .arg("600")
        .env("YAK_TURN", "0".repeat(32))
        .process_group(0)
        .spawn()
        .unwrap();
    let path = repo.scratch("stale.pid");
    std::fs::write(&path, format!("{}\nnot-the-start-time\n", child.id())).unwrap();
    let result = Sandbox::end_stale(&path);
    let alive = child.try_wait().unwrap().is_none();
    child.kill().unwrap();
    child.wait().unwrap();
    assert!(!result.unwrap());
    assert!(alive);
}

#[test]
fn a_stored_identity_can_end_the_run_and_its_detached_children() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let mut sb = sandbox(&repo);
    let pid_file = repo.scratch("run.pid");
    sb.set_pid_file(pid_file.clone());
    let (tx, rx) = std::sync::mpsc::channel();
    let run = std::thread::spawn(move || {
        sb.run(
            "sh",
            &strings(&[
                "-c",
                "perl -MPOSIX -e '$|=1; setsid(); print \"$$\\n\"; sleep 600' & sleep 600",
            ]),
            "",
            30,
            &mut |line| {
                tx.send(line.to_owned()).unwrap();
            },
        )
    });
    let line = rx.recv_timeout(Duration::from_secs(5));
    let ended = if line.is_ok() {
        Sandbox::end_stale(&pid_file)
    } else {
        Ok(false)
    };
    let result = run.join().unwrap();
    let pid: u32 = line.unwrap().parse().unwrap();
    let _cleanup = EndOnDrop(pid);
    assert!(ended.unwrap());
    assert!(!result.unwrap().timed_out);
    assert!(wait_until(Instant::now() + Duration::from_secs(2), || {
        !pid_alive(pid)
    }));
    assert!(!pid_file.exists());
    assert!(!Sandbox::end_stale(&pid_file).unwrap());
}

#[test]
fn every_run_gets_its_own_marker() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let (_, first) = sh(&sb, "printf '%s\\n' \"$YAK_TURN\"", 30);
    let (_, second) = sh(&sb, "printf '%s\\n' \"$YAK_TURN\"", 30);
    assert_eq!(first[0].len(), 32);
    assert!(first[0].bytes().all(|b| b.is_ascii_hexdigit()));
    assert_ne!(first, second);
}

#[test]
fn an_unrelated_process_is_untouched_by_supervision() {
    use std::os::unix::process::CommandExt;
    use std::process::Stdio;
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let mut canary = None;
    let result = sb.run(
        "sh",
        &strings(&["-c", "echo \"$YAK_TURN\"; sleep 1"]),
        "",
        30,
        &mut |marker| {
            canary = Some(EndGroupOnDrop(
                Command::new("sh")
                    .args(["-c", "sleep 600 & wait", &format!("YAK_TURN={marker}")])
                    .stdin(Stdio::null())
                    .stdout(Stdio::null())
                    .stderr(Stdio::null())
                    .process_group(0)
                    .spawn()
                    .unwrap(),
            ));
        },
    );
    assert_eq!(result.unwrap().exit_code, 0);
    assert!(canary.as_mut().unwrap().0.try_wait().unwrap().is_none());
}

#[test]
fn a_finished_run_ends_its_detached_children() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let (status, lines) = sh(
        &sb,
        "perl -MPOSIX -e '$|=1; setsid(); print \"$$\\n\"; sleep 600' & sleep 1",
        30,
    );
    let pid = lines[0].parse().unwrap();
    let _cleanup = EndOnDrop(pid);
    assert_eq!(status.exit_code, 0);
    assert!(wait_until(Instant::now() + Duration::from_secs(2), || {
        !pid_alive(pid)
    }));
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

/// A worker can leave anything in its clone's `.git`. A named pipe where a ref should be would hold the room's
/// own git, which opens the ref to read it, for as long as nobody writes to the pipe: for ever.
#[test]
fn a_named_pipe_in_the_clones_git_directory_is_refused_and_holds_nothing_up() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let (status, _) = sh(
        &sb,
        "ref=$(git symbolic-ref HEAD) && rm -f \".git/$ref\" && mkfifo \".git/$ref\"",
        30,
    );
    assert_eq!(status.exit_code, 0);
    let start = Instant::now();
    let (done, wait) = std::sync::mpsc::channel();
    std::thread::scope(|scope| {
        scope.spawn(|| {
            let _ = done.send(sb.head());
        });
        let head = wait.recv_timeout(Duration::from_secs(20));
        // Open both ends of the pipe, which never waits, so a git that did stop on it goes on and a failing run
        // of this test ends.
        let _ = std::fs::OpenOptions::new()
            .read(true)
            .write(true)
            .open(sb.dir.join(".git/refs/heads/room/i1/1"));
        let head = head.expect("reading the head was held up by the pipe");
        assert!(matches!(head, Err(TurnError::Refused(_))), "{head:?}");
    });
    assert!(start.elapsed() < Duration::from_secs(20));
}

/// The sandbox is one directory, the one that was made. If a worker moves it away and leaves a link or another
/// directory at its path, nothing more runs there and the room's git does not read it.
#[test]
fn a_sandbox_whose_directory_was_replaced_is_refused() {
    for with_a_link in [true, false] {
        let repo = Repo::new(&[("a.txt", "hello\n")]);
        let sb = sandbox(&repo);
        let moved = repo.scratch("moved-away");
        let other = repo.scratch("somewhere-else");
        std::fs::create_dir(&other).unwrap();
        std::fs::rename(&sb.dir, &moved).unwrap();
        if with_a_link {
            std::os::unix::fs::symlink(&other, &sb.dir).unwrap();
        } else {
            // Another clone at the same path: a directory, and a repository, and not the one that was made.
            git(&repo.path, &["clone", "-q", ".", sb.dir.to_str().unwrap()]);
        }
        let mark = other.join("ran");
        let touch = format!("touch '{}'; echo ran", mark.display());
        for run in [Sandbox::run, Sandbox::run_untrusted] {
            let ran = run(&sb, "sh", &strings(&["-c", &touch]), "", 30, &mut |_| {});
            assert!(matches!(ran, Err(TurnError::Refused(_))), "{ran:?}");
        }
        assert!(!mark.exists());
        assert!(matches!(sb.head(), Err(TurnError::Refused(_))));
        assert!(matches!(sb.reclaim(), Err(TurnError::Refused(_))));
    }
}

/// The scratch directory of a jailed run is the room's own: made by the room, once, beside the sandbox. A
/// worker that is not jailed can reach it between runs. Something already at its path, or a link put where it
/// was, is refused: the next run would be let write wherever the link names.
#[test]
fn a_scratch_directory_that_is_not_the_rooms_own_is_refused() {
    let run = |sb: &Sandbox, script: &str| {
        sb.run_untrusted("sh", &strings(&["-c", script]), "", 30, &mut |_| {})
    };
    let scratch_of = |sb: &Sandbox| {
        let mut name = sb.dir.file_name().unwrap().to_os_string();
        name.push(".scratch");
        sb.dir.with_file_name(name)
    };

    // Replaced between two runs.
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    assert_eq!(run(&sb, "echo one > \"$HOME/made\"").unwrap().exit_code, 0);
    let scratch = scratch_of(&sb);
    assert!(scratch.join("made").exists());
    let elsewhere = repo.scratch("elsewhere");
    std::fs::create_dir(&elsewhere).unwrap();
    std::fs::rename(&scratch, repo.scratch("moved-scratch")).unwrap();
    std::os::unix::fs::symlink(&elsewhere, &scratch).unwrap();
    let again = run(&sb, "echo two > \"$HOME/made\"");
    assert!(matches!(again, Err(TurnError::Refused(_))), "{again:?}");
    assert!(!elsewhere.join("made").exists());

    // There before the first run.
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    std::fs::create_dir(scratch_of(&sb)).unwrap();
    let first = run(&sb, "echo one");
    assert!(first.is_err(), "{first:?}");
}
