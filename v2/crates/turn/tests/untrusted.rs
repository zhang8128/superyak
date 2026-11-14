//! What the room does not trust runs in the jail: a check, a script worker, and the room's own git in a
//! worker's tree. Each test would pass a write or a connection through if the run were not jailed.
//!
//! Like `tests/jail.rs`, these enter a real jail and so cannot run inside another sandbox.

mod common;

use std::fs;
use std::net::TcpListener;
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::time::{Duration, Instant};

use common::Repo;
use room::{CheckOrigin, CheckSpec};
use turn::Sandbox;
use turn::check::{freeze, run_check};
use turn::worker;

fn spec(command: String) -> CheckSpec {
    CheckSpec {
        command,
        files: vec![],
        timeout_secs: 30,
        origin: CheckOrigin::Outside,
        wrong_artifacts: vec![],
        written_by: "person:test".into(),
    }
}

fn quote(path: &Path) -> String {
    format!("'{}'", path.to_str().unwrap())
}

fn reached(listener: &TcpListener) -> bool {
    let end = Instant::now() + Duration::from_millis(400);
    while Instant::now() < end {
        if listener.accept().is_ok() {
            return true;
        }
        std::thread::sleep(Duration::from_millis(20));
    }
    false
}

/// The check's command tries to write beside the repository, then passes only if the file is not there. So the
/// verdict is a pass exactly when the write was stopped.
#[test]
fn a_check_cannot_write_outside_its_checkout() {
    let repo = Repo::new(&[("a.txt", "one\n")]);
    repo.write("a.txt", "two\n");
    let fix = repo.commit("fix");
    let outside = repo.scratch("outside");
    fs::create_dir(&outside).unwrap();
    let canary = outside.join("made-by-the-check");
    let spec = spec(format!(
        "echo x > {0} 2>/dev/null; test ! -e {0}",
        quote(&canary)
    ));
    let checks = repo.scratch("checks");
    let frozen = freeze(&repo.path, &repo.base, &spec, &checks).unwrap();
    let verdict = run_check(
        &repo.path,
        &fix,
        &spec,
        &frozen.check_hash,
        &checks,
        &repo.scratch("work"),
    )
    .unwrap();
    assert!(!canary.exists(), "the check wrote outside its checkout");
    assert!(verdict.passed, "exit {}", verdict.exit_code);
}

#[test]
fn a_check_has_no_network() {
    let repo = Repo::new(&[("a.txt", "one\n")]);
    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    listener.set_nonblocking(true).unwrap();
    let port = listener.local_addr().unwrap().port();
    let spec = spec(format!(
        "curl -s -m 3 -o /dev/null http://127.0.0.1:{port}/; true"
    ));
    let checks = repo.scratch("checks");
    let frozen = freeze(&repo.path, &repo.base, &spec, &checks).unwrap();
    assert!(
        !reached(&listener),
        "freezing the check reached the listener"
    );
    let verdict = run_check(
        &repo.path,
        &repo.base,
        &spec,
        &frozen.check_hash,
        &checks,
        &repo.scratch("work"),
    )
    .unwrap();
    assert!(verdict.exit_code == 0);
    assert!(!reached(&listener), "the check reached the listener");
}

/// A check may still use temporary files and a home directory: both are its scratch directory.
#[test]
fn a_check_has_a_home_and_a_place_for_temporary_files() {
    let repo = Repo::new(&[("a.txt", "one\n")]);
    let spec = spec(
        "t=$(mktemp) && echo ok > \"$t\" && echo also > \"$HOME/made\" && cat <<END\nhere\nEND"
            .into(),
    );
    let checks = repo.scratch("checks");
    let frozen = freeze(&repo.path, &repo.base, &spec, &checks).unwrap();
    let verdict = run_check(
        &repo.path,
        &repo.base,
        &spec,
        &frozen.check_hash,
        &checks,
        &repo.scratch("work"),
    )
    .unwrap();
    assert!(verdict.passed, "exit {}", verdict.exit_code);
}

/// A script worker is a stand-in for a worker's own code, so it is jailed too. It makes its own commit, as a
/// script worker does, which also shows git works inside the jail.
#[test]
fn a_script_worker_cannot_write_outside_its_sandbox_and_its_commit_still_lands() {
    let repo = Repo::new(&[("a.txt", "one\n")]);
    let outside = repo.scratch("outside");
    fs::create_dir(&outside).unwrap();
    let canary = outside.join("made-by-the-worker");
    let script = outside.join("worker.sh");
    fs::write(
        &script,
        format!(
            "#!/bin/sh\necho x > {} 2>/dev/null\necho two > a.txt\n\
                 git add -A && git -c user.name=t -c user.email=t@example.invalid commit -q -m two\n",
            quote(&canary)
        ),
    )
    .unwrap();
    fs::set_permissions(&script, fs::Permissions::from_mode(0o755)).unwrap();

    let sandbox =
        Sandbox::create(&repo.path, &repo.base, &repo.scratch("turn"), "room/i1/1").unwrap();
    let before = sandbox.head().unwrap();
    let run = worker::from_name(&format!("script:{}", script.display()))
        .unwrap()
        .run(&sandbox, "an item", "true", 30)
        .unwrap();
    assert_eq!(run.exit_code, 0);
    assert!(!canary.exists(), "the worker wrote outside its sandbox");
    assert_ne!(
        sandbox.head().unwrap(),
        before,
        "the worker's change was not committed"
    );
    sandbox.destroy().unwrap();
    assert!(
        !repo.scratch("turn.scratch").exists(),
        "the scratch directory was left behind"
    );
}

/// A tripwire, not a behaviour test. After `reclaim`, nothing known makes the room's git run a worker's code,
/// so no test can show the jail stopping it. This reads the source and fails if the room's git in a worker's
/// tree stops going through the jail.
#[test]
fn the_rooms_git_in_a_workers_tree_goes_through_the_jail() {
    let source = include_str!("../src/worker.rs");
    let seal = source
        .split("fn seal(")
        .nth(1)
        .expect("worker.rs has a seal function");
    let body = seal.split("\nfn ").next().unwrap();
    assert!(body.contains("sandbox.run_untrusted("));
    assert!(!body.contains("sandbox.run("));
}
