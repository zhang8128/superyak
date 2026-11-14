//! Task 7: the frozen check.

mod common;

use std::os::unix::fs::PermissionsExt;

use common::{Repo, git};
use room::{CheckOrigin, CheckSpec};
use sha2::{Digest, Sha256};
use turn::TurnError;
use turn::check::{freeze, run_check};

/// The check passes when its file is missing, so only a frozen copy can make a commit that deleted it fail.
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

    /// A commit from base that makes `change`, on its own branch.
    fn commit(&self, branch: &str, change: impl FnOnce(&Repo)) -> String {
        self.repo.branch_commit(branch, &self.repo.base, change)
    }
}

#[test]
fn freeze_reports_red_on_base_and_on_each_wrong_artifact() {
    let item = Item::new();
    let checks = item.repo.scratch("checks");
    let frozen = freeze(&item.repo.path, &item.repo.base, &item.spec(), &checks).unwrap();
    assert!(frozen.red_on_base);
    assert_eq!(frozen.red_on_wrong, [true]);
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
fn the_same_spec_freezes_to_the_same_hash() {
    let item = Item::new();
    item.repo.write("other.txt", "x\n");
    let base = item.repo.commit("two check files");
    let mut spec = item.spec();
    spec.files = vec!["other.txt".to_string(), "check.sh".to_string()];
    let first = freeze(&item.repo.path, &base, &spec, &item.repo.scratch("c1")).unwrap();
    let again = freeze(&item.repo.path, &base, &spec, &item.repo.scratch("c2")).unwrap();
    assert_eq!(first.check_hash, again.check_hash);
    spec.files.reverse();
    let reordered = freeze(&item.repo.path, &base, &spec, &item.repo.scratch("c3")).unwrap();
    assert_eq!(first.check_hash, reordered.check_hash);
    // The plan's definition, worked out here by hand: the command, a newline, then each file sorted as its
    // path, a NUL, its SHA-256 at base, a newline.
    let mut text = format!("{COMMAND}\n").into_bytes();
    for (path, content) in [("check.sh", "grep fixed src/a.txt\n"), ("other.txt", "x\n")] {
        text.extend_from_slice(path.as_bytes());
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
fn a_commit_that_rewrote_the_check_file_is_judged_by_the_frozen_copy() {
    let item = Item::new();
    let checks = item.repo.scratch("checks");
    let spec = item.spec();
    let frozen = freeze(&item.repo.path, &item.repo.base, &spec, &checks).unwrap();
    let cheat = item.commit("cheat", |r| r.write("check.sh", "exit 0\n"));
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
    assert_eq!(item.repo.scratch("work").read_dir().unwrap().count(), 0);
}

#[test]
fn a_commit_that_deleted_the_check_file_is_judged_by_the_frozen_copy() {
    let item = Item::new();
    let checks = item.repo.scratch("checks");
    let spec = item.spec();
    let frozen = freeze(&item.repo.path, &item.repo.base, &spec, &checks).unwrap();
    let gone = item.commit("gone", |r| r.remove("check.sh"));
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
}

#[test]
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
    // A fix that also takes the check's execute bit away still runs the check as it was frozen.
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
    assert!(verdict.passed, "{verdict:?}");
}

#[test]
fn a_check_that_never_ends_times_out() {
    let item = Item::new();
    let checks = item.repo.scratch("checks");
    let mut spec = item.spec();
    spec.command = "sleep 600".to_string();
    spec.files = vec![];
    spec.timeout_secs = 1;
    let frozen = freeze(&item.repo.path, &item.repo.base, &spec, &checks).unwrap();
    assert!(frozen.red_on_base, "a timed-out check is red");
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
}

#[test]
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
