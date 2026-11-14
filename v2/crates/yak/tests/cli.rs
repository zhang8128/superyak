//! Task 10 contracts at the real command-line boundary. Scripts only touch their checkout.
use std::fs;
use std::io::{BufRead, BufReader};
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Output, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

use assert_cmd::Command;
use room::{ItemId, Room, RoomError};
use serde_json::{Value, json};

// A failed assertion must still stop the real clock and its worker.
struct RunningClock {
    child: std::process::Child,
    room: PathBuf,
}

impl Drop for RunningClock {
    fn drop(&mut self) {
        if self.child.try_wait().ok().flatten().is_none() {
            let _ = fs::write(self.room.join("STOP"), []);
            let deadline = std::time::Instant::now() + Duration::from_secs(15);
            while self.child.try_wait().ok().flatten().is_none()
                && std::time::Instant::now() < deadline
            {
                thread::sleep(Duration::from_millis(50));
            }
            let _ = self.child.kill();
            let _ = self.child.wait();
        }
    }
}

fn yak(room: &Path) -> Command {
    let mut cmd = Command::new(assert_cmd::cargo::cargo_bin!("yak"));
    cmd.arg("--room").arg(room).env_remove("YAK_JAIL_READ");
    for name in ["YAK_JAIL", "YAK_SUPERVISION"] {
        if let Some(value) = std::env::var_os(name) {
            cmd.env(name, value);
        } else {
            cmd.env_remove(name);
        }
    }
    cmd.timeout(Duration::from_secs(40));
    cmd
}

fn success(out: Output) -> String {
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    assert!(out.stderr.is_empty(), "{:?}", out.stderr);
    String::from_utf8(out.stdout).unwrap().trim().to_owned()
}

fn refusal(out: Output) -> String {
    assert!(!out.status.success());
    let err = String::from_utf8(out.stderr).unwrap();
    assert_eq!(err.lines().count(), 1, "{err:?}");
    err
}

struct Fixture {
    tmp: tempfile::TempDir,
    room: PathBuf,
    repo: PathBuf,
    base: String,
}

impl Fixture {
    fn new() -> Self {
        let tmp = tempfile::tempdir().unwrap();
        let room = tmp.path().join("room");
        let repo = tmp.path().join("repo");
        fs::create_dir(&repo).unwrap();
        git(&repo, &["init", "-q", "-b", "main"]);
        fs::write(repo.join("answer"), "red\n").unwrap();
        fs::write(repo.join("check.sh"), "grep -qx green answer\n").unwrap();
        git(&repo, &["add", "."]);
        git(&repo, &["commit", "-qm", "base"]);
        let base = git(&repo, &["rev-parse", "HEAD"]);
        success(yak(&room).arg("init").output().unwrap());
        Self {
            tmp,
            room,
            repo,
            base,
        }
    }

    fn add_command(&self, base: &str) -> Command {
        let mut cmd = yak(&self.room);
        cmd.args(["item", "add", "--title", "Make answer green", "--repo"])
            .arg(&self.repo)
            .args([
                "--base",
                base,
                "--check",
                "sh check.sh",
                "--file",
                "check.sh",
                "--wrong",
                &self.base,
                "--origin",
                "outside",
                "--by",
                "person:test",
            ]);
        cmd
    }

    fn add(&self) -> String {
        success(self.add_command("main").output().unwrap())
    }

    fn show(&self, id: &str) -> Value {
        serde_json::from_str(&success(
            yak(&self.room)
                .args(["item", "show", id, "--json"])
                .output()
                .unwrap(),
        ))
        .unwrap()
    }

    fn script(&self, body: &str) -> String {
        let path = self.tmp.path().join("worker.sh");
        fs::write(&path, format!("#!/bin/sh\n{body}\n")).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
        format!("script:{}", path.display())
    }

    fn clock(&self, worker: &str) -> Command {
        let mut cmd = yak(&self.room);
        cmd.args(["clock", "run", "--once-through", "--worker", worker]);
        cmd
    }
}

fn git(repo: &Path, args: &[&str]) -> String {
    let out = turn::sandbox::safe_git()
        .arg("-C")
        .arg(repo)
        .args([
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
        ])
        .args(args)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout).unwrap().trim().to_owned()
}

#[test]
fn status_on_an_empty_directory_fails_and_creates_nothing() {
    let tmp = tempfile::tempdir().unwrap();
    for exists in [false, true] {
        let room = tmp.path().join(if exists { "empty" } else { "absent" });
        if exists {
            fs::create_dir(&room).unwrap();
        }
        let err = refusal(yak(&room).arg("status").output().unwrap());
        assert_eq!(
            err.trim(),
            RoomError::Missing(room.join("room.sqlite3")).to_string()
        );
        if exists {
            assert_eq!(fs::read_dir(&room).unwrap().count(), 0);
        } else {
            assert!(!room.exists());
        }
    }
}

#[test]
fn item_add_then_show_round_trips() {
    let f = Fixture::new();
    let first = f.add();
    let second = success(
        f.add_command("main")
            .args(["--after", &first])
            .output()
            .unwrap(),
    );
    let shown = f.show(&second);
    assert_eq!(shown["id"], second);
    assert_eq!(shown["title"], "Make answer green");
    assert_eq!(shown["state"], "draft");
    assert_eq!(shown["origin"], "outside");
    assert_eq!(shown["written_by"], "person:test");
    assert_eq!(shown["after"], json!([first]));
    let listed: Value = serde_json::from_str(&success(
        yak(&f.room)
            .args(["item", "list", "--json"])
            .output()
            .unwrap(),
    ))
    .unwrap();
    assert_eq!(listed.as_array().unwrap().len(), 2);
    assert_eq!(listed[1], shown);
}

#[test]
fn a_refusal_is_one_line_on_stderr_and_a_non_zero_exit() {
    let f = Fixture::new();
    refusal(
        yak(&f.room)
            .args(["item", "show", "missing\nitem"])
            .output()
            .unwrap(),
    );
    refusal(
        yak(&f.room)
            .args([
                "clock",
                "run",
                "--worker",
                "script:absent",
                "--turn-secs",
                "no\nnumber",
            ])
            .output()
            .unwrap(),
    );
    refusal(yak(&f.room).arg("nonsense").output().unwrap());
    let err = refusal(f.clock("unknown:missing\nsecond-line").output().unwrap());
    assert!(!err.contains('\r'));
}

#[test]
fn item_base_is_resolved_and_unknown_bases_are_refused() {
    let f = Fixture::new();
    for base in ["main", &f.base[..8]] {
        let id = success(f.add_command(base).output().unwrap());
        let room = Room::open_read_only(&f.room).unwrap();
        assert_eq!(room.item_spec(&ItemId(id)).unwrap().base_commit, f.base);
    }
    let err = refusal(f.add_command("not-a-commit\nline").output().unwrap());
    assert!(err.contains("base"));
    refusal(f.add_command("--help").output().unwrap());
    refusal(f.add_command("main^{tree}").output().unwrap());
    assert_eq!(
        Room::open_read_only(&f.room)
            .unwrap()
            .items()
            .unwrap()
            .len(),
        2
    );
}

#[test]
fn author_origin_and_repeated_values_are_kept_and_malformed_authors_are_refused() {
    let f = Fixture::new();
    for (origin, stored, author) in [
        ("observed", "observed_failure", "script:fixture"),
        ("model", "model", "new-family:fixture"),
        ("outside", "outside", "person:fixture"),
        ("outside", "outside", "missing-colon"),
        ("outside", "outside", ":missing-family"),
        ("outside", "outside", "missing-name:"),
    ] {
        let out = yak(&f.room)
            .args(["item", "add", "--title", "fixture", "--repo"])
            .arg(&f.repo)
            .args([
                "--base", "main", "--check", "false", "--file", "check.sh", "answer", "--file",
                "check.sh", "--wrong", &f.base, &f.base, "--origin", origin, "--by", author,
            ])
            .output()
            .unwrap();
        if author == "missing-colon" || author.starts_with(':') || author.ends_with(':') {
            assert!(refusal(out).contains("--by"));
        } else {
            let id = success(out);
            let room = Room::open_read_only(&f.room).unwrap();
            let spec = room.item_spec(&ItemId(id)).unwrap().check;
            assert_eq!(serde_json::to_value(spec.origin).unwrap(), stored);
            assert_eq!(spec.written_by, author);
            assert_eq!(spec.files, ["check.sh", "answer", "check.sh"]);
            assert_eq!(spec.wrong_artifacts, [f.base.clone(), f.base.clone()]);
            assert_eq!(spec.timeout_secs, 900);
        }
    }
}

#[test]
fn default_room_help_version_and_global_room_after_the_command_work() {
    let tmp = tempfile::tempdir().unwrap();
    for arg in ["--help", "--version"] {
        let mut cmd = Command::new(assert_cmd::cargo::cargo_bin!("yak"));
        assert!(success(cmd.arg(arg).output().unwrap()).contains("yak"));
    }
    let mut cmd = Command::new(assert_cmd::cargo::cargo_bin!("yak"));
    success(cmd.arg("init").env("HOME", tmp.path()).output().unwrap());
    let dir = tmp.path().join(".superyak/v2/room");
    assert!(dir.join("room.sqlite3").is_file());
    let mut cmd = Command::new(assert_cmd::cargo::cargo_bin!("yak"));
    success(
        cmd.args(["status", "--json", "--room"])
            .arg(dir)
            .output()
            .unwrap(),
    );
    let mut cmd = Command::new(assert_cmd::cargo::cargo_bin!("yak"));
    assert!(refusal(cmd.arg("status").env_remove("HOME").output().unwrap()).contains("--room"));
}

#[test]
fn erase_removes_the_item() {
    let f = Fixture::new();
    let id = f.add();
    success(yak(&f.room).args(["item", "erase", &id]).output().unwrap());
    refusal(
        yak(&f.room)
            .args(["item", "show", &id, "--json"])
            .output()
            .unwrap(),
    );
    assert_eq!(
        success(
            yak(&f.room)
                .args(["item", "list", "--json"])
                .output()
                .unwrap()
        ),
        "[]"
    );
}

#[test]
fn unsafe_worker_settings_are_refused_before_worker_validation() {
    let f = Fixture::new();
    for (variable, value, other, safe_value) in [
        ("YAK_JAIL", "off", "YAK_SUPERVISION", "strict"),
        ("YAK_SUPERVISION", "best-effort", "YAK_JAIL", "on"),
    ] {
        for worker in ["codex:missing", "claude:missing", "unknown:missing"] {
            let err = refusal(
                f.clock(worker)
                    .args(["--worker", "script:missing"])
                    .env(variable, value)
                    .env(other, safe_value)
                    .output()
                    .unwrap(),
            );
            assert!(err.contains(variable), "{err}");
        }
    }
    let script = f.script("exit 0");
    success(
        f.clock(&script)
            .env("YAK_JAIL", "off")
            .env("YAK_SUPERVISION", "best-effort")
            .output()
            .unwrap(),
    );
    if turn::jail::Jail::detect().is_some() {
        let err = refusal(
            f.clock("unknown:worker")
                .env("YAK_JAIL", "on")
                .env("YAK_SUPERVISION", "strict")
                .output()
                .unwrap(),
        );
        assert!(err.contains("unknown worker"), "{err}");
    }
}

#[test]
fn bad_jail_read_is_refused_at_start_before_a_draft_is_frozen() {
    let f = Fixture::new();
    let id = f.add();
    let err = refusal(
        f.clock("script:/no/such/worker")
            .env("YAK_JAIL", "on")
            .env("YAK_JAIL_READ", "relative-toolchain")
            .output()
            .unwrap(),
    );
    if turn::jail::Jail::detect().is_some() {
        assert!(err.contains("YAK_JAIL_READ"), "{err}");
    } else {
        assert!(err.contains("no jail"), "{err}");
    }
    assert_eq!(f.show(&id)["state"], "draft");
    assert!(!f.room.join("checks").exists());
}

#[test]
fn a_successful_clock_prints_events_without_transcript_text() {
    let f = Fixture::new();
    let id = f.add();
    let script = f.script("echo TRANSCRIPT-MARKER-98\necho green > answer\ngit -c user.name=Test -c user.email=test@example.invalid commit -qm fix -a");
    let out = success(
        f.clock(&script)
            .args([
                "--lease-secs",
                "9",
                "--turn-secs",
                "3",
                "--daily-turns",
                "7",
                "--concurrent",
                "2",
            ])
            .output()
            .unwrap(),
    );
    assert!(
        out.contains("frozen") && out.contains("started") && out.contains("ended"),
        "{out}"
    );
    assert!(!out.contains("TRANSCRIPT-MARKER-98"));
    assert_eq!(f.show(&id)["state"], "passed_verified");
    let status = Room::open_read_only(&f.room).unwrap().status(0).unwrap();
    assert_eq!(status.daily_ceiling, 7);
}

#[test]
fn clock_restarts_with_only_the_allowed_environment_and_does_not_loop() {
    let f = Fixture::new();
    let id = f.add();
    let script = f.script("env | sort > env.txt\necho green > answer\ngit add env.txt answer\ngit -c user.name=Test -c user.email=test@example.invalid commit -qm fix");
    let out = success(
        f.clock(&script)
            .env("YAK_TEST_CANARY", "task10-canary")
            .output()
            .unwrap(),
    );
    assert_eq!(
        out.lines().next(),
        Some("starting again with a clean environment")
    );
    assert_eq!(
        out.matches("starting again with a clean environment")
            .count(),
        1
    );
    let worker_environment = git(
        &f.repo,
        &["show", &format!("refs/heads/room/{id}/1:env.txt")],
    );
    assert!(
        !worker_environment.contains("YAK_TEST_CANARY")
            && !worker_environment.contains("task10-canary")
    );
    assert_eq!(f.show(&id)["state"], "passed_verified");
    let mut clean = f.clock(&script);
    clean.env_clear();
    for name in [
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "SHELL",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TERM",
        "TMPDIR",
        "TZ",
        "CODEX_HOME",
        "CLAUDE_CONFIG_DIR",
        "YAK_JAIL",
        "YAK_JAIL_READ",
        "YAK_SUPERVISION",
    ] {
        if let Some(value) = std::env::var_os(name) {
            clean.env(name, value);
        }
    }
    clean
        .envs([
            ("USER", "fixture"),
            ("LOGNAME", "fixture"),
            ("SHELL", "/bin/sh"),
            ("LANG", "C"),
            ("LC_ALL", "C"),
            ("LC_CTYPE", "C"),
            ("TERM", "dumb"),
            ("TZ", "UTC"),
            ("YAK_JAIL_READ", ""),
        ])
        .env("TMPDIR", f.tmp.path())
        .env("CODEX_HOME", f.tmp.path().join("codex-config"))
        .env("CLAUDE_CONFIG_DIR", f.tmp.path().join("claude-config"));
    assert!(!success(clean.output().unwrap()).contains("starting again"));
}

#[test]
fn clock_errors_including_once_through_ceiling_exit_nonzero() {
    let f = Fixture::new();
    let first = f.add();
    let second = f.add();
    let script = f.script("exit 0");
    let out = f
        .clock(&script)
        .args(["--daily-turns", "1"])
        .output()
        .unwrap();
    assert!(String::from_utf8_lossy(&out.stdout).contains("no new commit"));
    let err = refusal(out);
    assert!(err.contains("daily ceiling"), "{err}");
    assert_eq!(f.show(&first)["state"], "failed");
    assert_eq!(f.show(&second)["state"], "open");
}

#[test]
fn a_bad_lease_and_a_failed_resume_are_refused() {
    let f = Fixture::new();
    let script = f.script("exit 0");
    let err = refusal(
        f.clock(&script)
            .args(["--lease-secs", "0"])
            .output()
            .unwrap(),
    );
    assert!(err.contains("lease"));
    fs::create_dir(f.room.join("STOP")).unwrap();
    refusal(yak(&f.room).arg("resume").output().unwrap());
    assert!(f.room.join("STOP").is_dir());
}

#[test]
fn stop_and_resume_work_without_the_writer_lock() {
    let f = Fixture::new();
    let _writer = Room::open(&f.room).unwrap();
    success(yak(&f.room).arg("stop").output().unwrap());
    assert!(f.room.join("STOP").is_file());
    success(yak(&f.room).arg("resume").output().unwrap());
    assert!(!f.room.join("STOP").exists());
    success(yak(&f.room).arg("resume").output().unwrap());
}

#[test]
fn turn_limit_reaches_the_clock() {
    let f = Fixture::new();
    let id = f.add();
    let script = f.script("echo green > answer\ngit -c user.name=Test -c user.email=test@example.invalid commit -qm fix -a\nsleep 600");
    let out = success(
        f.clock(&script)
            .args(["--turn-secs", "1"])
            .output()
            .unwrap(),
    );
    assert!(out.contains("timed out"), "{out}");
    assert_eq!(f.show(&id)["state"], "passed_verified");
}

#[test]
fn concurrent_sets_the_room_ceiling_without_dispatching_parallel_turns() {
    let f = Fixture::new();
    let id = f.add();
    let script = f.script("exit 0");
    success(
        f.clock(&script)
            .args(["--concurrent", "0"])
            .output()
            .unwrap(),
    );
    assert_eq!(f.show(&id)["state"], "open");
    let mut room = Room::open(&f.room).unwrap();
    assert!(room.take("script:test", 0).unwrap().is_none());
}

#[test]
fn events_arrive_during_a_turn_and_stop_works_while_the_clock_holds_the_lock() {
    let f = Fixture::new();
    let id = f.add();
    let script = f.script("sleep 600");
    let mut command = yak(&f.room);
    command.args([
        "clock",
        "run",
        "--worker",
        &script,
        "--lease-secs",
        "20",
        "--turn-secs",
        "30",
    ]);
    let mut process = std::process::Command::new(command.get_program());
    process.args(command.get_args());
    for (key, value) in command.get_envs() {
        if let Some(value) = value {
            process.env(key, value);
        } else {
            process.env_remove(key);
        }
    }
    let child = process
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    let mut clock = RunningClock {
        child,
        room: f.room.clone(),
    };
    let stdout = clock.child.stdout.take().unwrap();
    let (tx, rx) = mpsc::channel();
    let reader = thread::spawn(move || {
        for line in BufReader::new(stdout).lines() {
            if tx.send(line.unwrap()).is_err() {
                break;
            }
        }
    });
    let started = loop {
        let line = rx
            .recv_timeout(Duration::from_secs(20))
            .expect("events before turn finishes");
        if line.contains("started") {
            break line;
        }
    };
    assert!(started.contains(&id));
    let room = Room::open_read_only(&f.room).unwrap();
    let lease = room.current_lease(&ItemId(id.clone())).unwrap().unwrap();
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs() as i64;
    assert!(
        (now + 17..=now + 20).contains(&lease.expires),
        "{} {now}",
        lease.expires
    );
    success(yak(&f.room).arg("stop").output().unwrap());
    assert!(clock.child.wait().unwrap().success());
    reader.join().unwrap();
    assert!(f.room.join("STOP").exists());
    assert_eq!(f.show(&id)["state"], "open");
    success(yak(&f.room).arg("resume").output().unwrap());
    success(yak(&f.room).arg("resume").output().unwrap());
    assert!(!f.room.join("STOP").exists());
}

// The lead's additions at the join, after reading the builder's work.

/// `yak stop` makes a file named STOP. If something else is at that name, it says so and writes nothing: a link
/// there would have it empty whatever file the link names, and a link to nowhere would leave the room running
/// while the command said it had stopped.
#[test]
fn stop_writes_nothing_through_a_link_and_says_when_it_did_not_stop() {
    let f = Fixture::new();
    let kept = f.tmp.path().join("kept.txt");
    fs::write(&kept, "keep me\n").unwrap();
    std::os::unix::fs::symlink(&kept, f.room.join("STOP")).unwrap();
    let err = refusal(yak(&f.room).arg("stop").output().unwrap());
    assert!(err.contains("STOP"), "{err}");
    assert_eq!(fs::read_to_string(&kept).unwrap(), "keep me\n");

    fs::remove_file(f.room.join("STOP")).unwrap();
    std::os::unix::fs::symlink(f.tmp.path().join("nowhere"), f.room.join("STOP")).unwrap();
    refusal(yak(&f.room).arg("stop").output().unwrap());
    assert!(!f.tmp.path().join("nowhere").exists());

    // Stopping twice is fine: the second finds the file the first made.
    fs::remove_file(f.room.join("STOP")).unwrap();
    success(yak(&f.room).arg("stop").output().unwrap());
    success(yak(&f.room).arg("stop").output().unwrap());
    assert!(f.room.join("STOP").is_file());
}

#[test]
fn a_turn_of_no_length_is_refused() {
    let f = Fixture::new();
    let script = f.script("exit 0");
    let err = refusal(
        f.clock(&script)
            .args(["--turn-secs", "0"])
            .output()
            .unwrap(),
    );
    assert!(err.contains("turn-secs"), "{err}");
}

/// A check can be a command alone, with no file of its own to freeze. The room takes such a check, so the
/// command line does too.
#[test]
fn an_item_can_have_a_check_with_no_file_to_freeze() {
    let f = Fixture::new();
    let mut cmd = yak(&f.room);
    cmd.args(["item", "add", "--title", "Make answer green", "--repo"])
        .arg(&f.repo)
        .args([
            "--base",
            "main",
            "--check",
            "grep -qx green answer",
            "--origin",
            "outside",
            "--by",
            "person:test",
        ]);
    let id = success(cmd.output().unwrap());
    assert_eq!(f.show(&id)["state"], "draft");
}

/// Checking the jail's settings before the first turn leaves nothing behind beside the room.
#[test]
fn starting_a_clock_leaves_nothing_beside_the_room() {
    let f = Fixture::new();
    f.add();
    let script = f.script("exit 0");
    let beside = |f: &Fixture| {
        let mut names: Vec<String> = fs::read_dir(f.tmp.path())
            .unwrap()
            .map(|entry| entry.unwrap().file_name().to_string_lossy().into_owned())
            .collect();
        names.sort();
        names
    };
    let before = beside(&f);
    let _ = f.clock(&script).output().unwrap();
    assert_eq!(beside(&f), before);
}

/// A number given twice is not a mistake to refuse: a script that wraps `yak` adds its own after the defaults
/// it was handed. The last one wins, as it does in most command lines.
#[test]
fn a_number_given_twice_takes_the_last() {
    let f = Fixture::new();
    f.add();
    let script = f.script("echo green > answer\ngit commit -qam fix");
    // The first lease of 0 would be refused if it were the one used.
    let out = f
        .clock(&script)
        .args(["--lease-secs", "0", "--lease-secs", "30"])
        .args(["--turn-secs", "1", "--turn-secs", "60"])
        .args(["--daily-turns", "0", "--daily-turns", "5"])
        .args(["--concurrent", "9", "--concurrent", "1"])
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    let status: Value = serde_json::from_str(&success(
        yak(&f.room).args(["status", "--json"]).output().unwrap(),
    ))
    .unwrap();
    assert_eq!(status["counts"]["passed_verified"], json!(1), "{status}");
    assert_eq!(status["daily_ceiling"], json!(5), "{status}");
}
