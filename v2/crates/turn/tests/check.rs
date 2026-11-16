//! Task 7: the frozen check.

mod common;

use std::os::unix::fs::PermissionsExt;
use std::time::{Duration, Instant};

use room::limits::TERM_GRACE_SECS;

use common::{Repo, git};
use room::{CheckOrigin, CheckSpec};
use sha2::{Digest, Sha256};
use turn::TurnError;
use turn::check::{freeze, run_check};

/// The check reads the fixture when present.
const COMMAND: &str = "if [ -f check.sh ]; then sh check.sh; fi";

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

fn sha256_hex(bytes: &[u8]) -> String {
    hex(&Sha256::digest(bytes))
}

/// A repository whose check (`check.sh`, which prints `fixed` when it passes) fails at base, with one wrong
/// commit and one fix, each on its own branch.
struct Item {
    repo: Repo,
    wrong: String,
    fix: String,
}

impl Item {
    fn new() -> Item {
        let repo = Repo::new(&[
            ("check.sh", "grep fixed src/a.txt\n"),
            ("src/a.txt", "broken\n"),
        ]);
        let base = repo.base.clone();
        let wrong = repo.branch_commit("wrong", &base, |r| r.write("src/a.txt", "still broken\n"));
        let fix = repo.branch_commit("fix", &base, |r| r.write("src/a.txt", "fixed\n"));
        Item { repo, wrong, fix }
    }

    fn spec(&self) -> CheckSpec {
        CheckSpec {
            command: COMMAND.to_string(),
            files: vec!["check.sh".to_string()],
            timeout_secs: 30,
            origin: CheckOrigin::Outside,
            wrong_artifacts: vec![self.wrong.clone()],
            written_by: "person:test".to_string(),
        }
    }
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn freeze_reports_red_on_base_and_on_each_wrong_artifact() {
    let item = Item::new();
    let checks = item.repo.scratch("checks");
    let mut spec = item.spec();
    spec.wrong_artifacts.push(item.fix.clone());
    let frozen = freeze(&item.repo.path, &item.repo.base, &spec, &checks).unwrap();
    assert!(frozen.red_on_base);
    assert_eq!(frozen.red_on_wrong, [true, false]);
    let copy = checks.join(&frozen.check_hash).join("check.sh");
    assert_eq!(
        std::fs::read_to_string(copy).unwrap(),
        "grep fixed src/a.txt\n"
    );
    let left: Vec<_> = std::fs::read_dir(&checks)
        .unwrap()
        .flatten()
        .map(|e| e.file_name())
        .collect();
    assert_eq!(
        left,
        [std::ffi::OsString::from(&frozen.check_hash)],
        "freeze leaves only the frozen copies"
    );
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn freeze_reports_a_check_that_passes_on_base() {
    let item = Item::new();
    let mut spec = item.spec();
    spec.command = "true".to_string();
    let frozen = freeze(
        &item.repo.path,
        &item.repo.base,
        &spec,
        &item.repo.scratch("checks"),
    )
    .unwrap();
    assert!(!frozen.red_on_base);
    assert_eq!(frozen.red_on_wrong, [false]);
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn the_same_spec_freezes_to_the_same_hash() {
    let item = Item::new();
    item.repo.write("other.txt", "x\n");
    let base = item.repo.commit("two check files");
    item.repo.write("check.sh", "exit 23\n");
    let head = item.repo.commit("later check");
    assert_ne!(head, base);
    let mut spec = item.spec();
    spec.files = vec!["other.txt".to_string(), "check.sh".to_string()];
    let first = freeze(&item.repo.path, &base, &spec, &item.repo.scratch("c1")).unwrap();
    let again = freeze(&item.repo.path, &base, &spec, &item.repo.scratch("c2")).unwrap();
    assert_eq!(first.check_hash, again.check_hash);
    spec.files.reverse();
    let reordered = freeze(&item.repo.path, &base, &spec, &item.repo.scratch("c3")).unwrap();
    assert_eq!(first.check_hash, reordered.check_hash);
    // The plan's definition, worked out here by hand: `v2`, a newline, the command, a newline, then each file
    // sorted as its path, a NUL, its mode in six octal digits, a NUL, its SHA-256 at base, a newline. Neither
    // file is executable.
    let mut text = format!("v2\n{COMMAND}\n").into_bytes();
    for (path, content) in [("check.sh", "grep fixed src/a.txt\n"), ("other.txt", "x\n")] {
        text.extend_from_slice(path.as_bytes());
        text.push(0);
        text.extend_from_slice(b"100644");
        text.push(0);
        text.extend_from_slice(sha256_hex(content.as_bytes()).as_bytes());
        text.push(b'\n');
    }
    assert_eq!(first.check_hash, sha256_hex(&text));
    spec.command.push(' ');
    let changed = freeze(&item.repo.path, &base, &spec, &item.repo.scratch("c4")).unwrap();
    assert_ne!(first.check_hash, changed.check_hash);
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_commit_that_rewrote_the_check_file_fails() {
    let item = Item::new();
    let checks = item.repo.scratch("checks");
    let mut spec = item.spec();
    // The check says "ran" when it runs. A check runs in the jail, so it can leave no file outside its
    // checkout to show that it ran; its output is the evidence.
    spec.command = format!("echo ran; {COMMAND}");
    let frozen = freeze(&item.repo.path, &item.repo.base, &spec, &checks).unwrap();
    let cheat = item.repo.branch_commit("changed-check", &item.fix, |r| {
        r.write("check.sh", "exit 0\n")
    });
    let work = item.repo.scratch("work");
    let verdict = run_check(
        &item.repo.path,
        &cheat,
        &spec,
        &frozen.check_hash,
        &checks,
        &work,
    )
    .unwrap();
    assert!(!verdict.passed);
    assert_eq!(verdict.exit_code, 125);
    assert!(!verdict.timed_out);
    assert_eq!(verdict.output_sha256, sha256_hex(b""), "the check ran");
    assert_eq!(item.repo.scratch("work").read_dir().unwrap().count(), 0);
    // The control: on the honest fix the same check does run, and its output shows it.
    let honest = run_check(
        &item.repo.path,
        &item.fix,
        &spec,
        &frozen.check_hash,
        &checks,
        &work,
    )
    .unwrap();
    assert!(honest.passed);
    assert_ne!(honest.output_sha256, sha256_hex(b""));
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_commit_that_deleted_the_check_file_fails() {
    let item = Item::new();
    let checks = item.repo.scratch("checks");
    let mut spec = item.spec();
    // The check says "ran" when it runs. A check runs in the jail, so it can leave no file outside its
    // checkout to show that it ran; its output is the evidence.
    spec.command = format!("echo ran; {COMMAND}");
    let frozen = freeze(&item.repo.path, &item.repo.base, &spec, &checks).unwrap();
    let gone = item
        .repo
        .branch_commit("gone", &item.fix, |r| r.remove("check.sh"));
    let work = item.repo.scratch("work");
    let verdict = run_check(
        &item.repo.path,
        &gone,
        &spec,
        &frozen.check_hash,
        &checks,
        &work,
    )
    .unwrap();
    assert!(!verdict.passed);
    assert_eq!(verdict.exit_code, 125);
    assert!(!verdict.timed_out);
    assert_eq!(verdict.output_sha256, sha256_hex(b""), "the check ran");
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_check_path_must_keep_its_frozen_type() {
    for directory in [false, true] {
        let item = Item::new();
        let checks = item.repo.scratch("checks");
        let mut spec = item.spec();
        spec.command = format!("echo ran; {COMMAND}");
        let frozen = freeze(&item.repo.path, &item.repo.base, &spec, &checks).unwrap();
        let commit = item.repo.branch_commit("typed-check", &item.fix, |r| {
            r.remove("check.sh");
            if directory {
                r.write("check.sh/inside", "fixture\n");
            } else {
                std::os::unix::fs::symlink("src/a.txt", r.path.join("check.sh")).unwrap();
            }
        });
        let v = run_check(
            &item.repo.path,
            &commit,
            &spec,
            &frozen.check_hash,
            &checks,
            &item.repo.scratch("work"),
        )
        .unwrap();
        assert!(!v.passed);
        assert_eq!(v.exit_code, 125);
        assert!(!v.timed_out);
        assert_eq!(v.output_sha256, sha256_hex(b""), "the check ran");
    }
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn the_frozen_copies_are_never_written_through_a_link() {
    let repo = Repo::new(&[
        ("checks/check.sh", "grep fixed a.txt\n"),
        ("a.txt", "broken\n"),
    ]);
    let spec = CheckSpec {
        command: "if [ -f checks/check.sh ]; then sh checks/check.sh; fi".to_string(),
        files: vec!["checks/check.sh".to_string()],
        timeout_secs: 30,
        origin: CheckOrigin::Outside,
        wrong_artifacts: vec![],
        written_by: "person:test".to_string(),
    };
    let checks = repo.scratch("checks");
    let frozen = freeze(&repo.path, &repo.base, &spec, &checks).unwrap();
    // The worker swaps the check's directory for a link to a place outside the clone.
    let outside = repo.scratch("outside");
    std::fs::create_dir(&outside).unwrap();
    let base = repo.base.clone();
    let link = repo.branch_commit("link", &base, |r| {
        std::fs::remove_dir_all(r.path.join("checks")).unwrap();
        std::os::unix::fs::symlink(&outside, r.path.join("checks")).unwrap();
    });
    let work = repo.scratch("work");
    let verdict = run_check(&repo.path, &link, &spec, &frozen.check_hash, &checks, &work).unwrap();
    assert!(!verdict.passed);
    assert_eq!(
        outside.read_dir().unwrap().count(),
        0,
        "nothing was written outside the clone"
    );
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn the_frozen_copy_keeps_its_mode() {
    let repo = Repo::new(&[
        ("check.sh", "#!/bin/sh\ngrep fixed a.txt\n"),
        ("a.txt", "broken\n"),
    ]);
    let script = repo.path.join("check.sh");
    std::fs::set_permissions(&script, std::fs::Permissions::from_mode(0o755)).unwrap();
    let base = repo.commit("executable check");
    let spec = CheckSpec {
        command: "./check.sh".to_string(),
        files: vec!["check.sh".to_string()],
        timeout_secs: 30,
        origin: CheckOrigin::Outside,
        wrong_artifacts: vec![],
        written_by: "person:test".to_string(),
    };
    let checks = repo.scratch("checks");
    let frozen = freeze(&repo.path, &base, &spec, &checks).unwrap();
    // Frozen executable modes are preserved and required in the artifact.
    let fix = repo.branch_commit("fix", &base, |r| {
        r.write("a.txt", "fixed\n");
        std::fs::set_permissions(
            r.path.join("check.sh"),
            std::fs::Permissions::from_mode(0o644),
        )
        .unwrap();
    });
    let verdict = run_check(
        &repo.path,
        &fix,
        &spec,
        &frozen.check_hash,
        &checks,
        &repo.scratch("work"),
    )
    .unwrap();
    assert!(!verdict.passed, "{verdict:?}");
    assert_eq!(verdict.exit_code, 125);
    assert_eq!(
        std::fs::metadata(checks.join(&frozen.check_hash).join("check.sh"))
            .unwrap()
            .permissions()
            .mode()
            & 0o111,
        0o111
    );
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_check_that_never_ends_times_out() {
    let item = Item::new();
    let checks = item.repo.scratch("checks");
    let mut spec = item.spec();
    spec.command = "sleep 600".to_string();
    spec.files = vec![];
    spec.timeout_secs = 1;
    let frozen = freeze(&item.repo.path, &item.repo.base, &spec, &checks).unwrap();
    assert!(frozen.red_on_base, "a timed-out check is red");
    let start = Instant::now();
    let verdict = run_check(
        &item.repo.path,
        &item.fix,
        &spec,
        &frozen.check_hash,
        &checks,
        &item.repo.scratch("work"),
    )
    .unwrap();
    assert!(verdict.timed_out);
    assert!(!verdict.passed);
    assert!(
        start.elapsed() < Duration::from_secs(u64::from(spec.timeout_secs + TERM_GRACE_SECS) + 5),
        "{:?}",
        start.elapsed()
    );
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn the_verdict_names_the_commit_and_the_check() {
    let item = Item::new();
    let checks = item.repo.scratch("checks");
    let spec = item.spec();
    let frozen = freeze(&item.repo.path, &item.repo.base, &spec, &checks).unwrap();
    let work = item.repo.scratch("work");
    let verdict = run_check(
        &item.repo.path,
        &item.fix,
        &spec,
        &frozen.check_hash,
        &checks,
        &work,
    )
    .unwrap();
    assert!(verdict.passed);
    assert_eq!(verdict.exit_code, 0);
    assert!(!verdict.timed_out);
    assert_eq!(verdict.commit, item.fix);
    assert_eq!(verdict.check_hash, frozen.check_hash);
    // The output, a line at a time with its line end: grep printed the matching line.
    assert_eq!(verdict.output_sha256, sha256_hex(b"fixed\n"));
    // A name for the commit is resolved to the commit it names.
    let by_name = run_check(
        &item.repo.path,
        "fix",
        &spec,
        &frozen.check_hash,
        &checks,
        &work,
    )
    .unwrap();
    assert_eq!(by_name.commit, item.fix);
    assert_eq!(
        work.read_dir().unwrap().count(),
        0,
        "the check's clone is gone"
    );
}

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_changed_frozen_copy_is_refused() {
    let item = Item::new();
    let checks = item.repo.scratch("checks");
    let spec = item.spec();
    let frozen = freeze(&item.repo.path, &item.repo.base, &spec, &checks).unwrap();
    std::fs::write(checks.join(&frozen.check_hash).join("check.sh"), "exit 0\n").unwrap();
    let work = item.repo.scratch("work");
    let refused = run_check(
        &item.repo.path,
        &item.wrong,
        &spec,
        &frozen.check_hash,
        &checks,
        &work,
    );
    assert!(matches!(refused, Err(TurnError::Refused(_))), "{refused:?}");
    // A hash that is not one cannot name a directory elsewhere.
    let escape = run_check(
        &item.repo.path,
        &item.wrong,
        &spec,
        "../checks",
        &checks,
        &work,
    );
    assert!(matches!(escape, Err(TurnError::Refused(_))));
    // Freezing again puts the copy back as it was at base.
    let again = freeze(&item.repo.path, &item.repo.base, &spec, &checks).unwrap();
    assert_eq!(again.check_hash, frozen.check_hash);
    let verdict = run_check(
        &item.repo.path,
        &item.wrong,
        &spec,
        &frozen.check_hash,
        &checks,
        &work,
    )
    .unwrap();
    assert!(!verdict.passed);
}

#[test]
fn freeze_refuses_a_path_that_is_not_plain_or_not_tracked() {
    let item = Item::new();
    for bad in [
        "/etc/passwd",
        "../x",
        "a/../check.sh",
        ".git/config",
        "a\nb",
        "",
        "src",
        "missing.txt",
        "./check.sh",
    ] {
        let mut spec = item.spec();
        spec.files = vec![bad.to_string()];
        let result = freeze(
            &item.repo.path,
            &item.repo.base,
            &spec,
            &item.repo.scratch("checks"),
        );
        assert!(result.is_err(), "{bad:?} was frozen");
    }
    // git tracks a name with a line end in it, which would make the hash's own lines ambiguous.
    item.repo.write("a\nb", "x\n");
    let with_newline = item.repo.commit("a tracked name with a line end");
    let mut spec = item.spec();
    spec.files = vec!["a\nb".to_string()];
    let result = freeze(
        &item.repo.path,
        &with_newline,
        &spec,
        &item.repo.scratch("checks"),
    );
    assert!(matches!(result, Err(TurnError::Refused(_))), "{result:?}");
    git(&item.repo.path, &["reset", "-q", "--hard", &item.repo.base]);
    let mut spec = item.spec();
    spec.timeout_secs = 0;
    assert!(
        freeze(
            &item.repo.path,
            &item.repo.base,
            &spec,
            &item.repo.scratch("checks")
        )
        .is_err()
    );
    let head = git(&item.repo.path, &["rev-parse", "HEAD"]);
    assert_eq!(head, item.repo.base, "the repository was not moved");
}

/// A freeze runs its check in a sandbox inside a work directory of its own, and removes that directory when it
/// is done. If something else is at the sandbox's path by then, it is not the room's to remove: it is left,
/// with the work directory that holds it, and the freeze says so and gives no result.
#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn a_freeze_leaves_its_work_directory_when_something_took_its_sandboxs_place() {
    let item = Item::new();
    let checks = item.repo.scratch("checks");
    let mut spec = item.spec();
    spec.command = "sleep 3; exit 1".to_string();
    let moved = item.repo.scratch("moved-away");
    let swapper = {
        let checks = checks.clone();
        std::thread::spawn(move || {
            // The sandbox of the freeze's first run, once it is running: the one name without a dot in the
            // work directory beside its record.
            let deadline = Instant::now() + Duration::from_secs(60);
            let mut sandbox = None;
            assert!(common::wait_until(deadline, || {
                let record = std::fs::read_dir(&checks)
                    .into_iter()
                    .flatten()
                    .flatten()
                    .map(|e| e.path())
                    .find(|p| {
                        let name = p.file_name().unwrap().to_string_lossy().into_owned();
                        name.starts_with(".work-") && name.ends_with(".pid")
                    });
                sandbox = record.and_then(|record| {
                    std::fs::read_dir(record.with_extension(""))
                        .into_iter()
                        .flatten()
                        .flatten()
                        .map(|e| e.path())
                        .find(|p| !p.file_name().unwrap().to_string_lossy().contains('.'))
                });
                sandbox.is_some()
            }));
            // Well inside the check's three seconds.
            std::thread::sleep(Duration::from_secs(1));
            let at = sandbox.unwrap();
            std::fs::rename(&at, &moved).unwrap();
            std::fs::create_dir(&at).unwrap();
            std::fs::write(at.join("canary"), "KEEP").unwrap();
            at
        })
    };
    let frozen = freeze(&item.repo.path, &item.repo.base, &spec, &checks);
    let at = swapper.join().unwrap();
    let Err(TurnError::Left { paths: left, .. }) = &frozen else {
        panic!("{frozen:?}");
    };
    assert_eq!(left.len(), 1, "{left:?}");
    assert_eq!(left[0].file_name(), at.file_name());
    assert_eq!(std::fs::read_to_string(at.join("canary")).unwrap(), "KEEP");
}

/// What a removal left is said even when the check itself failed for a reason of its own. Here a scratch
/// directory is put beside the check's sandbox before its first run: with the jail on that run cannot start,
/// which is an ordinary failure, and the removal then finds a scratch directory the room never made. The
/// freeze says what was left, with the failure beside it, and leaves the work directory that holds it.
#[test]
fn a_check_that_failed_still_says_what_its_removal_left() {
    let item = Item::new();
    let checks = item.repo.scratch("checks");
    let planter = {
        let checks = checks.clone();
        std::thread::spawn(move || {
            // The sandbox of the freeze's first check, as soon as its directory is there: the one name
            // without a dot in the work directory. Its clone is still being made, and no run has started.
            let deadline = Instant::now() + Duration::from_secs(60);
            let mut sandbox = None;
            while sandbox.is_none() && Instant::now() < deadline {
                sandbox = std::fs::read_dir(&checks)
                    .into_iter()
                    .flatten()
                    .flatten()
                    .map(|e| e.path())
                    .filter(|p| {
                        p.file_name()
                            .unwrap()
                            .to_string_lossy()
                            .starts_with(".work-")
                    })
                    .flat_map(|work| std::fs::read_dir(work).into_iter().flatten().flatten())
                    .map(|e| e.path())
                    .find(|p| !p.file_name().unwrap().to_string_lossy().contains('.'));
                std::thread::sleep(Duration::from_millis(1));
            }
            let sandbox = sandbox.expect("the freeze made a sandbox");
            let mut name = sandbox.file_name().unwrap().to_os_string();
            name.push(".scratch");
            let scratch = sandbox.with_file_name(name);
            std::fs::create_dir(&scratch).unwrap();
            std::fs::write(scratch.join("canary"), "KEEP").unwrap();
            scratch
        })
    };
    let frozen = freeze(&item.repo.path, &item.repo.base, &item.spec(), &checks);
    let scratch = planter.join().unwrap();
    let Err(TurnError::Left { paths, also }) = &frozen else {
        panic!("{frozen:?}");
    };
    assert_eq!(paths.len(), 1, "{paths:?}");
    assert_eq!(paths[0].file_name(), scratch.file_name());
    assert_eq!(
        std::fs::read_to_string(scratch.join("canary")).unwrap(),
        "KEEP"
    );
    // With the jail on, the run could not start, and that is kept beside what was left. With the jail off no
    // scratch directory is asked for, the check runs, and there is nothing beside it.
    if turn::jail::wanted() {
        assert!(
            also.as_deref().is_some_and(|why| why.contains("scratch")),
            "{also:?}"
        );
    }
}
