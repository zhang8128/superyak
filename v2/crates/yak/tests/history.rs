//! Tests use real read-only room stores and git objects, without a worker, process listing or jail.
use std::fs;
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use room::*;
use serde_json::{Value, json};
use yak::history::{self, HistoryList, Measure, Plan, PlanItem};

fn git(repo: &Path, args: &[&str], input: &str) -> String {
    let mut command = turn::sandbox::safe_git();
    let mut child = command
        .arg("-C")
        .arg(repo)
        .args(args)
        .env("GIT_AUTHOR_NAME", "fixture")
        .env("GIT_COMMITTER_NAME", "fixture")
        .env("GIT_AUTHOR_EMAIL", "fixture@example.invalid")
        .env("GIT_COMMITTER_EMAIL", "fixture@example.invalid")
        .env("GIT_AUTHOR_DATE", "2000-01-01T00:00:00Z")
        .env("GIT_COMMITTER_DATE", "2000-01-01T00:00:00Z")
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child
        .stdin
        .take()
        .unwrap()
        .write_all(input.as_bytes())
        .unwrap();
    let output = child.wait_with_output().unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout).unwrap().trim().into()
}

struct World {
    tmp: tempfile::TempDir,
    repo: PathBuf,
    dir: PathBuf,
    room: Room,
    base: String,
    commit: String,
    blob: String,
}

impl World {
    fn new() -> Self {
        let tmp = tempfile::tempdir().unwrap();
        let repo = tmp.path().join("repo");
        fs::create_dir(&repo).unwrap();
        git(&repo, &["init", "-q"], "");
        let blob = git(&repo, &["hash-object", "-w", "--stdin"], "base content\n");
        let tree = git(
            &repo,
            &["mktree"],
            &format!(
                "100644 blob {blob}\ta.txt\n100644 blob {blob}\tb.txt\n100644 blob {blob}\tc.txt\n"
            ),
        );
        let base = git(&repo, &["commit-tree", &tree], "base\n");
        let commit = git(&repo, &["commit-tree", &tree, "-p", &base], "answer\n");
        let dir = tmp.path().join("room");
        let room = Room::init(&dir).unwrap();
        Self {
            tmp,
            repo,
            dir,
            room,
            base,
            commit,
            blob,
        }
    }

    fn item(&mut self, title: &str) -> ItemId {
        let item = self
            .room
            .add_item(NewItem {
                title: title.into(),
                repo: self.repo.clone(),
                base_commit: self.base.clone(),
                after: vec![],
                check: CheckSpec {
                    command: "fixture-check".into(),
                    files: vec![],
                    timeout_secs: 1,
                    origin: CheckOrigin::Outside,
                    wrong_artifacts: vec![self.base.clone()],
                    written_by: "person:PRIVATE_AUTHOR".into(),
                },
            })
            .unwrap();
        self.room
            .record_frozen(
                &item,
                Frozen {
                    check_hash: "a".repeat(64),
                    red_on_base: true,
                    red_on_wrong: vec![true],
                },
            )
            .unwrap();
        item
    }

    fn finish(&mut self, item: &ItemId, at: i64, passed: bool, paths: &[&str]) -> Lease {
        let lease = self.room.take("codex:PRIVATE_WORKER", at).unwrap().unwrap();
        assert_eq!(&lease.item, item);
        let steps = vec![
            Step {
                seq: 1,
                tool: Tool::Shell,
                target: Target::Outside,
                ok: true,
                named: ["b.txt", "a.txt", "c.txt"]
                    .map(|path| Named {
                        path: path.into(),
                        blob: self.blob.clone(),
                    })
                    .to_vec(),
                tokens_in: Some(0),
                tokens_out: None,
                seen_ms: Some(3),
                result_ms: Some(9),
            },
            Step {
                seq: 2,
                tool: Tool::Read,
                target: Target::TrackedFile {
                    path: "a.txt".into(),
                    blob: self.blob.clone(),
                },
                named: vec![],
                ok: false,
                tokens_in: None,
                tokens_out: Some(2),
                seen_ms: None,
                result_ms: None,
            },
            Step {
                seq: 3,
                tool: Tool::Other,
                target: Target::Outside,
                named: vec![],
                ok: false,
                tokens_in: None,
                tokens_out: None,
                seen_ms: None,
                result_ms: None,
            },
        ];
        self.room.record_walk(&lease.attempt, &steps).unwrap();
        self.room
            .record_changes(
                &lease.attempt,
                &paths
                    .iter()
                    .enumerate()
                    .map(|(n, path)| ChangedFile {
                        path: (*path).into(),
                        change: [Change::Added, Change::Changed, Change::Removed][n % 3],
                    })
                    .collect::<Vec<_>>(),
            )
            .unwrap();
        self.room.hand_in(&lease, &self.commit, at + 1).unwrap();
        let verdict = self.verdict(passed);
        self.room
            .record_verdict(item, lease.lease_no, &verdict, at + 2)
            .unwrap();
        lease
    }

    fn verdict(&self, passed: bool) -> Verdict {
        Verdict {
            passed,
            exit_code: if passed { 0 } else { 1 },
            timed_out: false,
            commit: self.commit.clone(),
            check_hash: "a".repeat(64),
            output_sha256: history::sha256(b"TURN_OUTPUT_MARKER"),
        }
    }

    fn plan(&self, items: &[ItemId]) -> Plan {
        Plan {
            items: items
                .iter()
                .map(|item| PlanItem {
                    room: self.dir.clone(),
                    item: item.clone(),
                })
                .collect(),
        }
    }

    fn out(&self, name: &str) -> PathBuf {
        self.tmp.path().join(name)
    }

    fn make(&self, plan: &Plan, name: &str) -> PathBuf {
        let out = self.out(name);
        history::make(plan, Measure::parse("share:1").unwrap(), &out).unwrap();
        out
    }
}

fn canonical(value: &Value) -> Vec<u8> {
    let mut value = value.clone();
    value.sort_all_objects();
    serde_json::to_vec(&value).unwrap()
}

fn edit_list(out: &Path, edit: impl FnOnce(&mut Value)) {
    let path = out.join("history.json");
    let mut list: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    edit(&mut list);
    fs::write(path, canonical(&list)).unwrap();
}

fn edit_walk(out: &Path, attempt: &str, edit: impl FnOnce(&mut Value)) {
    let path = out.join(history::walk_filename(attempt));
    let mut walk: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    edit(&mut walk);
    let mut bytes = canonical(&walk);
    bytes.push(b'\n');
    fs::write(path, &bytes).unwrap();
    edit_list(out, |list| {
        let turn = list["turns"]
            .as_array_mut()
            .unwrap()
            .iter_mut()
            .find(|entry| entry["attempt"] == attempt)
            .unwrap();
        turn["sha256"] = json!(history::sha256(&bytes));
    });
}

fn refused(result: history::Result<impl std::fmt::Debug>, name: &str) {
    assert_eq!(result.unwrap_err().0, name);
}

#[test]
fn export_is_exact_sorted_json_lines_with_all_fields_and_no_turn_text() {
    let mut w = World::new();
    let item = w.item("some title");
    let lease = w.finish(&item, 100, false, &["new.txt", "a.txt", "removed.txt"]);
    let bytes = history::item_walks(&w.dir, &item, None).unwrap();
    let value: Value = serde_json::from_slice(&bytes).unwrap();
    let expected = json!({"v":1,"source":"room","repo":w.base,"base":w.base,"item":item,"attempt":lease.attempt,
        "family":"codex","verdict":"failed","standing":"failed",
        "changed":[["new.txt","added"],["a.txt","changed"],["removed.txt","removed"]],
        "steps":[{"seq":1,"tool":"shell","ok":true,"named":[["b.txt",w.blob],["a.txt",w.blob],["c.txt",w.blob]],
            "seen_ms":3,"result_ms":9,"tokens_in":0,"tokens_out":null},
            {"seq":2,"tool":"read","ok":false,"named":[["a.txt",w.blob]],"seen_ms":null,"result_ms":null,"tokens_in":null,"tokens_out":2},
            {"seq":3,"tool":"other","ok":false,"named":[],"seen_ms":null,"result_ms":null,"tokens_in":null,"tokens_out":null}]});
    assert_eq!(value, expected);
    assert_eq!(bytes, [canonical(&expected), vec![b'\n']].concat());
    let out = w.out("walks");
    assert!(
        history::item_walks(&w.dir, &item, Some(&out))
            .unwrap()
            .is_empty()
    );
    assert_eq!(
        fs::read(out.join(format!("{}.jsonl", lease.attempt.0))).unwrap(),
        bytes
    );
    let out = w.make(&w.plan(std::slice::from_ref(&item)), "history");
    for file in fs::read_dir(out).unwrap() {
        let bytes = fs::read(file.unwrap().path()).unwrap();
        let text = String::from_utf8(bytes).unwrap();
        for marker in ["TURN_OUTPUT_MARKER", "PRIVATE_WORKER", "PRIVATE_AUTHOR"] {
            assert!(!text.contains(marker));
        }
    }
    let mut cmd = assert_cmd::Command::new(assert_cmd::cargo::cargo_bin!("yak"));
    cmd.arg("--room")
        .arg(&w.dir)
        .args(["item", "walks", &item.0, "--json"])
        .assert()
        .success()
        .stdout(bytes);
}

#[test]
fn manifest_is_plan_order_independent_hashes_exact_bytes_and_keeps_empty_taught_turns() {
    let mut w = World::new();
    let a = w.item("alpha");
    w.finish(&a, 100, true, &[]);
    let b = w.item("beta");
    let lease = w.room.take("script:private", 200).unwrap().unwrap();
    w.room.hand_in(&lease, &w.commit, 201).unwrap();
    w.room
        .record_verdict(&b, lease.lease_no, &w.verdict(true), 202)
        .unwrap();
    let plan = w.plan(&[a.clone(), b.clone()]);
    let one = w.make(&plan, "one");
    let two = w.make(&w.plan(&[b, a]), "two");
    let bytes = fs::read(one.join("history.json")).unwrap();
    assert_eq!(bytes, fs::read(two.join("history.json")).unwrap());
    let (list, digest) = HistoryList::read(&one.join("history.json")).unwrap();
    assert_eq!(digest, history::sha256(&bytes));
    assert_eq!(list.turns.len(), 2);
    assert!(list.turns.windows(2).all(|p| p[0].attempt < p[1].attempt));
    let empty: Value = serde_json::from_slice(
        &fs::read(one.join(history::walk_filename(&lease.attempt.0))).unwrap(),
    )
    .unwrap();
    assert_eq!(empty["steps"], json!([]));
    history::check(&plan, &one.join("history.json"), &one).unwrap();
    let path = w.out("plan.json");
    fs::write(&path, json!({"items":plan.items.iter().map(|p| json!({"room":p.room,"item":p.item})).collect::<Vec<_>>()} ).to_string()).unwrap();
    let out = w.out("cli");
    let output = Command::new(assert_cmd::cargo::cargo_bin!("yak"))
        .args(["history", "make", "--measure", "share:1", "--plan"])
        .arg(&path)
        .arg("--out")
        .arg(&out)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(output.stdout, format!("{digest}\n").as_bytes());
    assert!(
        Command::new(assert_cmd::cargo::cargo_bin!("yak"))
            .args(["history", "check", "--plan"])
            .arg(path)
            .arg("--list")
            .arg(out.join("history.json"))
            .arg("--walks")
            .arg(out)
            .status()
            .unwrap()
            .success()
    );
}

#[test]
fn each_finished_retry_has_its_own_line_file_and_original_verdict() {
    let mut w = World::new();
    let item = w.item("alpha");
    let failed = w.finish(&item, 100, false, &[]);
    let passed = w.finish(&item, 200, true, &[]);
    let bytes = history::item_walks(&w.dir, &item, None).unwrap();
    let records = std::str::from_utf8(&bytes)
        .unwrap()
        .lines()
        .map(|line| serde_json::from_str::<Value>(line).unwrap())
        .collect::<Vec<_>>();
    assert_eq!(records.len(), 2);
    assert_eq!(records[0]["attempt"], json!(failed.attempt));
    assert_eq!(records[0]["verdict"], "failed");
    assert_eq!(records[1]["attempt"], json!(passed.attempt));
    assert_eq!(records[1]["verdict"], "passed");
    let out = w.make(&w.plan(&[item]), "retries");
    assert_eq!(fs::read_dir(out).unwrap().count(), 3);
}

#[test]
fn make_refuses_mixed_repositories_no_arrival_duplicate_attempt_and_nonempty_output() {
    let mut w = World::new();
    let item = w.item("alpha");
    refused(
        history::make(
            &w.plan(std::slice::from_ref(&item)),
            Measure::parse("share:1").unwrap(),
            &w.out("none"),
        ),
        "no_arrived_turn",
    );
    w.finish(&item, 100, true, &[]);
    refused(
        history::make(
            &w.plan(&[item.clone(), item.clone()]),
            Measure::parse("share:1").unwrap(),
            &w.out("duplicate"),
        ),
        "duplicate_attempt",
    );
    let mut other = World::new();
    other.base = git(
        &other.repo,
        &[
            "commit-tree",
            &git(
                &other.repo,
                &["rev-parse", &format!("{}^{{tree}}", other.base)],
                "",
            ),
        ],
        "another root\n",
    );
    let b = other.item("beta");
    other.finish(&b, 100, true, &[]);
    let mut plan = w.plan(std::slice::from_ref(&item));
    plan.items.push(PlanItem {
        room: other.dir.clone(),
        item: b,
    });
    refused(
        history::make(&plan, Measure::parse("share:1").unwrap(), &w.out("mixed")),
        "another_repository",
    );
    let plan = w.plan(&[item]);
    let out = w.make(&plan, "nonempty");
    refused(
        history::make(&plan, Measure::parse("share:1").unwrap(), &out),
        "out.not_empty",
    );
    refused(Measure::parse("share:2"), "measure");
    refused(Measure::parse("other:1"), "measure");
    refused(Measure::parse("share"), "measure");
    refused(
        history::make(
            &Plan { items: vec![] },
            Measure::parse("share:1").unwrap(),
            &w.out("empty"),
        ),
        "plan.empty",
    );
}

#[test]
fn check_refuses_every_admission_and_integrity_error_by_name() {
    let mut w = World::new();
    let item = w.item("alpha");
    let lease = w.finish(&item, 100, true, &[]);
    let plan = w.plan(std::slice::from_ref(&item));
    let check = |out: &Path| history::check(&plan, &out.join("history.json"), out);
    let out = w.make(&plan, "extra");
    fs::write(out.join("unlisted.jsonl"), b"{}").unwrap();
    refused(check(&out), "unlisted_file");
    let out = w.make(&plan, "duplicate");
    edit_list(&out, |v| {
        let entry = v["turns"][0].clone();
        v["turns"].as_array_mut().unwrap().push(entry);
    });
    refused(check(&out), "duplicate_attempt");
    let out = w.make(&plan, "second_copy");
    fs::copy(
        out.join(history::walk_filename(&lease.attempt.0)),
        out.join("copy.jsonl"),
    )
    .unwrap();
    refused(check(&out), "duplicate_attempt");
    let out = w.make(&plan, "hash");
    fs::write(
        out.join(history::walk_filename(&lease.attempt.0)),
        "TURN_OUTPUT_MARKER",
    )
    .unwrap();
    refused(check(&out), "wrong_hash");
    let out = w.make(&plan, "wrong_repo");
    edit_walk(&out, &lease.attempt.0, |v| {
        v["repo"] = json!("f".repeat(40))
    });
    refused(check(&out), "another_repository");
    let out = w.make(&plan, "wrong_list_repo");
    edit_list(&out, |v| v["repo"] = json!("f".repeat(40)));
    edit_walk(&out, &lease.attempt.0, |v| {
        v["repo"] = json!("f".repeat(40))
    });
    refused(check(&out), "another_repository");
    let out = w.make(&plan, "ship");
    edit_walk(&out, &lease.attempt.0, |v| v["source"] = json!("ship"));
    refused(check(&out), "ship_walk");
    let out = w.make(&plan, "not_planned");
    edit_list(&out, |v| v["turns"][0]["item"] = json!("iffffffffffff"));
    refused(check(&out), "not_planned_item");
    let out = w.make(&plan, "not_arrived");
    edit_list(&out, |v| v["turns"][0]["attempt"] = json!("affffffffffff"));
    refused(check(&out), "not_arrived");
    let out = w.make(&plan, "missing");
    fs::remove_file(out.join(history::walk_filename(&lease.attempt.0))).unwrap();
    refused(check(&out), "missing_walk");
    let out = w.make(&plan, "base_mismatch");
    edit_list(&out, |v| v["turns"][0]["base"] = json!("f".repeat(40)));
    refused(check(&out), "base_mismatch");
    let out = w.make(&plan, "store_mismatch");
    edit_walk(&out, &lease.attempt.0, |v| {
        v["steps"][0]["ok"] = json!(false)
    });
    refused(check(&out), "walk.store_mismatch");
    let out = w.make(&plan, "extra_line");
    let path = out.join(history::walk_filename(&lease.attempt.0));
    let mut bytes = fs::read(&path).unwrap();
    bytes.push(b'\n');
    fs::write(&path, &bytes).unwrap();
    edit_list(&out, |v| {
        v["turns"][0]["sha256"] = json!(history::sha256(&bytes))
    });
    refused(check(&out), "walk.store_mismatch");
    // A plan that holds a room of another repository beside the right one is refused by the admission and by
    // the ranker, as it is when a list is made.
    let out = w.make(&plan, "other_room");
    let mut other = World::new();
    other.base = git(
        &other.repo,
        &[
            "commit-tree",
            &git(
                &other.repo,
                &["rev-parse", &format!("{}^{{tree}}", other.base)],
                "",
            ),
        ],
        "another root\n",
    );
    let elsewhere = other.item("beta");
    other.finish(&elsewhere, 100, true, &[]);
    let mut mixed = w.plan(std::slice::from_ref(&item));
    mixed.items.push(PlanItem {
        room: other.dir.clone(),
        item: elsewhere,
    });
    refused(
        history::check(&mixed, &out.join("history.json"), &out),
        "another_repository",
    );
    refused(
        history::goals(&mixed, &out.join("history.json"), "alpha"),
        "another_repository",
    );
    history::check(&plan, &out.join("history.json"), &out).unwrap();
    history::goals(&plan, &out.join("history.json"), "alpha").unwrap();
    // The ranker holds the rooms to the list's repository, as the admission does: here the rooms are all of
    // one repository and the list is of another. Its goals and its question would else be for the wrong one.
    let out = w.make(&plan, "ranker_list_repo");
    edit_list(&out, |v| v["repo"] = json!("f".repeat(40)));
    refused(
        history::goals(&plan, &out.join("history.json"), "alpha"),
        "another_repository",
    );
    let out = w.make(&plan, "changed_standing");
    w.room
        .record_recheck(&item, lease.lease_no, &w.verdict(false))
        .unwrap();
    refused(check(&out), "standing_changed");
}

#[test]
fn check_validates_named_paths_and_blobs_against_the_real_base_tree() {
    for (path, blob) in [("absent.txt", None), ("a.txt", Some("f".repeat(40)))] {
        let mut w = World::new();
        let item = w.item("alpha");
        let lease = w.finish(&item, 100, true, &[]);
        w.room
            .record_walk(
                &lease.attempt,
                &[Step {
                    seq: 4,
                    tool: Tool::Read,
                    target: Target::Outside,
                    ok: true,
                    named: vec![Named {
                        path: path.into(),
                        blob: blob.unwrap_or(w.blob.clone()),
                    }],
                    tokens_in: None,
                    tokens_out: None,
                    seen_ms: None,
                    result_ms: None,
                }],
            )
            .unwrap();
        let plan = w.plan(&[item]);
        let out = w.make(&plan, "bad_tree");
        refused(
            history::check(&plan, &out.join("history.json"), &out),
            "path_or_blob_not_in_base",
        );
    }
}

#[test]
fn nonregular_git_entries_never_count_as_named_tracked_files() {
    for (mode, kind) in [("160000", "commit"), ("120000", "blob")] {
        let mut w = World::new();
        let old = w.base.clone();
        let object = if kind == "commit" {
            old.clone()
        } else {
            w.blob.clone()
        };
        let tree = git(
            &w.repo,
            &["mktree"],
            &format!(
                "100644 blob {}\ta.txt\n{mode} {kind} {object}\tmodule\n",
                w.blob
            ),
        );
        w.base = git(
            &w.repo,
            &["commit-tree", &tree, "-p", &old],
            "base with gitlink\n",
        );
        let item = w.item("alpha");
        let lease = w.room.take("script:private", 100).unwrap().unwrap();
        w.room
            .record_walk(
                &lease.attempt,
                &[Step {
                    seq: 1,
                    tool: Tool::Read,
                    target: Target::Outside,
                    ok: true,
                    named: vec![Named {
                        path: "module".into(),
                        blob: object,
                    }],
                    tokens_in: None,
                    tokens_out: None,
                    seen_ms: None,
                    result_ms: None,
                }],
            )
            .unwrap();
        w.room.hand_in(&lease, &w.commit, 101).unwrap();
        w.room
            .record_verdict(&item, lease.lease_no, &w.verdict(true), 102)
            .unwrap();
        let plan = w.plan(&[item]);
        let out = w.make(&plan, "gitlink");
        refused(
            history::check(&plan, &out.join("history.json"), &out),
            "path_or_blob_not_in_base",
        );
    }
}

#[test]
fn executable_files_are_regular_and_exported_repo_is_a_root_not_the_base() {
    let mut w = World::new();
    let root = w.base.clone();
    let tree = git(
        &w.repo,
        &["mktree"],
        &format!(
            "100755 blob {}\ta.txt\n100644 blob {}\tb.txt\n100644 blob {}\tc.txt\n",
            w.blob, w.blob, w.blob
        ),
    );
    w.base = git(
        &w.repo,
        &["commit-tree", &tree, "-p", &root],
        "executable base\n",
    );
    let item = w.item("alpha");
    w.finish(&item, 100, true, &[]);
    let value: Value =
        serde_json::from_slice(&history::item_walks(&w.dir, &item, None).unwrap()).unwrap();
    assert_eq!(value["repo"], root);
    assert_eq!(value["base"], w.base);
    assert_ne!(value["repo"], value["base"]);
    let plan = w.plan(&[item]);
    let out = w.make(&plan, "executable");
    history::check(&plan, &out.join("history.json"), &out).unwrap();
}

#[test]
fn repository_id_is_the_bytewise_first_reachable_root_even_with_multiple_roots() {
    let w = World::new();
    let tree = git(&w.repo, &["rev-parse", &format!("{}^{{tree}}", w.base)], "");
    let other = git(&w.repo, &["commit-tree", &tree], "other root\n");
    let merge = git(
        &w.repo,
        &["commit-tree", &tree, "-p", &w.base, "-p", &other],
        "merge\n",
    );
    assert_eq!(
        history::repository_id(&w.repo, &merge).unwrap(),
        w.base.min(other)
    );
}

#[test]
fn repository_identity_and_tree_reads_ignore_git_replacement_objects() {
    let mut w = World::new();
    let tree = git(&w.repo, &["rev-parse", &format!("{}^{{tree}}", w.base)], "");
    let other = git(&w.repo, &["commit-tree", &tree], "other root\n");
    let replacement = git(
        &w.repo,
        &["commit-tree", &tree, "-p", &other],
        "replacement\n",
    );
    git(&w.repo, &["replace", &w.base, &replacement], "");
    assert_eq!(history::repository_id(&w.repo, &w.base).unwrap(), w.base);
    let item = w.item("alpha");
    w.finish(&item, 100, true, &[]);
    let plan = w.plan(&[item]);
    let out = w.make(&plan, "replacement");
    history::check(&plan, &out.join("history.json"), &out).unwrap();
}

#[test]
fn plans_and_lists_refuse_unknown_missing_wrong_types_and_invalid_identity_fields_without_echo() {
    let mut w = World::new();
    let item = w.item("alpha");
    w.finish(&item, 100, true, &[]);
    let plan = w.plan(std::slice::from_ref(&item));
    let path = w.out("plan.json");
    let valid = json!({"items":[{"room":w.dir,"item":item}]});
    fs::write(&path, valid.to_string()).unwrap();
    assert_eq!(history::read_plan(&path).unwrap().items[0].room, w.dir);
    for bad in [
        json!({}),
        json!({"items":"MARKER"}),
        json!({"items":[],"MARKER":"MARKER"}),
        json!({"items":[{"room":w.dir,"item":item,"MARKER":true}]}),
        json!({"items":[{"room":w.dir}]}),
        json!({"items":[{"room":w.dir,"item":false}]}),
    ] {
        fs::write(&path, bad.to_string()).unwrap();
        refused(history::read_plan(&path), "plan.format");
    }
    fs::write(
        &path,
        json!({"items":[{"room":"relative","item":item}]}).to_string(),
    )
    .unwrap();
    refused(history::read_plan(&path), "plan.room_absolute");
    fs::write(
        &path,
        json!({"items":[{"room":w.dir,"item":"MARKER"}]}).to_string(),
    )
    .unwrap();
    refused(history::read_plan(&path), "plan.item");
    let out = w.make(&plan, "list_fields");
    let path = out.join("history.json");
    let valid: Value = serde_json::from_slice(&fs::read(&path).unwrap()).unwrap();
    for (pointer, bad, refusal) in [
        ("/v", json!(2), "list.v"),
        ("/repo", json!("MARKER"), "list.repo"),
        ("/turns/0/attempt", json!("MARKER"), "list.attempt"),
        ("/turns/0/item", json!("MARKER"), "list.item"),
        ("/turns/0/base", json!("MARKER"), "list.base"),
        ("/turns/0/sha256", json!("MARKER"), "list.sha256"),
        ("/turns/0/standing", json!("MARKER"), "list.format"),
        ("/measure/version", json!(2), "measure"),
    ] {
        let mut changed = valid.clone();
        *changed.pointer_mut(pointer).unwrap() = bad;
        fs::write(&path, canonical(&changed)).unwrap();
        refused(HistoryList::read(&path), refusal);
    }
    let mut unknown = valid.clone();
    unknown["MARKER"] = json!(true);
    fs::write(&path, canonical(&unknown)).unwrap();
    refused(HistoryList::read(&path), "list.format");
    for pointer in ["/measure", "/turns/0"] {
        let mut unknown = valid.clone();
        unknown.pointer_mut(pointer).unwrap()["MARKER"] = json!("MARKER");
        fs::write(&path, canonical(&unknown)).unwrap();
        refused(HistoryList::read(&path), "list.format");
    }
    fs::write(&path, serde_json::to_string_pretty(&valid).unwrap()).unwrap();
    refused(HistoryList::read(&path), "list.canonical");
}

#[test]
fn a_list_must_be_in_attempt_order_and_walks_must_be_regular_files() {
    let mut w = World::new();
    let a = w.item("alpha");
    let lease = w.finish(&a, 100, true, &[]);
    let b = w.item("beta");
    w.finish(&b, 200, true, &[]);
    let plan = w.plan(&[a, b]);
    let out = w.make(&plan, "order");
    edit_list(&out, |list| list["turns"].as_array_mut().unwrap().reverse());
    refused(HistoryList::read(&out.join("history.json")), "list.order");
    let out = w.make(&plan, "symlink");
    let path = out.join(history::walk_filename(&lease.attempt.0));
    let real = w.out("real.jsonl");
    fs::rename(&path, &real).unwrap();
    std::os::unix::fs::symlink(real, &path).unwrap();
    refused(
        history::check(&plan, &out.join("history.json"), &out),
        "walk.not_file",
    );
}

#[test]
fn exactly_half_the_item_titles_still_score_and_equal_arrivals_use_attempt_id() {
    let mut w = World::new();
    let mut items = Vec::new();
    let mut attempts = Vec::new();
    for title in ["half alpha", "half beta", "gamma", "delta"] {
        let item = w.item(title);
        attempts.push(w.finish(&item, 100, true, &[]).attempt.0);
        items.push(item);
    }
    let plan = w.plan(&items);
    let out = w.make(&plan, "half");
    let result = history::goals(&plan, &out.join("history.json"), "half alpha").unwrap();
    assert_eq!(result.chosen[0].attempt, attempts[0]);
    assert_eq!(result.chosen[0].score, 2);
    let result = history::goals(&plan, &out.join("history.json"), "half").unwrap();
    let mut expected = attempts[..2].to_vec();
    expected.sort_by(|a, b| b.cmp(a));
    assert_eq!(
        result
            .chosen
            .into_iter()
            .map(|turn| turn.attempt)
            .collect::<Vec<_>>(),
        expected
    );
}

#[test]
fn common_word_frequency_counts_items_once_instead_of_weighting_their_retries() {
    let mut w = World::new();
    let a = w.item("needle alpha");
    w.finish(&a, 100, false, &[]);
    w.finish(&a, 110, false, &[]);
    let arrived = w.finish(&a, 120, true, &[]);
    let b = w.item("beta");
    w.finish(&b, 130, true, &[]);
    let c = w.item("gamma");
    w.finish(&c, 140, true, &[]);
    let plan = w.plan(&[a, b, c]);
    let out = w.make(&plan, "frequency");
    let result = history::goals(&plan, &out.join("history.json"), "needle").unwrap();
    assert_eq!(
        result.chosen,
        vec![history::Chosen {
            attempt: arrived.attempt.0,
            score: 1
        }]
    );
}

#[test]
fn offer_make_cli_checks_real_base_identity_writes_all_states_and_preserves_output_on_refusal() {
    let w = World::new();
    let goals = json!({"ranker":"title-words-1","history":"a".repeat(64),"measure":{"name":"share","version":1},
        "chosen":[{"attempt":"a000000000001","score":2}],"goals":["a.txt","b.txt","gone.txt"],
        "question":{"v":1,"repo":w.base,"list":"a".repeat(64),"measure":{"name":"share","version":1},"goals":["a.txt","b.txt","gone.txt"]}});
    let road = |from: Value, to: &str| json!({"from":from,"to":to,"turns":1,"witness":"attempt-1"});
    let cost = json!({"num":"1","den":"1","nats":"0.000000000"});
    let valid = json!({"v":1,"store":"fixture-store-3","kernel":"fixture-kernel-1","repo":w.base,"list":"a".repeat(64),
        "for_experiment":true,"measure":{"name":"share","version":1,"teaches":["passed_verified"]},"path_rule":1,"taught":1,
        "answers":[{"goal":"a.txt","route":{"paths":["a.txt"],"roads":[road(Value::Null,"a.txt")],"roads_n":1,
            "blobs":{"a.txt":[w.blob]},"cost":cost,"detours":[]}},
            {"goal":"b.txt","route":{"paths":["a.txt","b.txt"],"roads":[road(Value::Null,"a.txt"),road(json!("a.txt"),"b.txt")],"roads_n":2,
            "blobs":{"a.txt":[w.blob],"b.txt":["f".repeat(40)]},"cost":cost,"detours":[]}},
            {"goal":"gone.txt","none":"never_named"}]});
    let goals_path = w.out("goals.json");
    fs::write(&goals_path, canonical(&goals)).unwrap();
    let answer_path = w.out("answer.json");
    let out = w.out("offer.json");
    let write_answer = |value: &Value| {
        let mut bytes = canonical(value);
        bytes.push(b'\n');
        fs::write(&answer_path, bytes).unwrap();
    };
    let run = || {
        Command::new(assert_cmd::cargo::cargo_bin!("yak"))
            .args(["offer", "make", "--goals"])
            .arg(&goals_path)
            .arg("--answer")
            .arg(&answer_path)
            .arg("--repo")
            .arg(&w.repo)
            .arg("--base")
            .arg(&w.base)
            .arg("--out")
            .arg(&out)
            .output()
            .unwrap()
    };
    write_answer(&valid);
    let output = run();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert!(output.stdout.is_empty());
    let bytes = fs::read(&out).unwrap();
    let value: Value = serde_json::from_slice(&bytes).unwrap();
    assert_eq!(
        value["goals"]
            .as_array()
            .unwrap()
            .iter()
            .map(|goal| goal["state"].as_str().unwrap())
            .collect::<Vec<_>>(),
        ["same", "changed", "gone"]
    );
    assert_eq!(value["measure"]["version"], "1");
    assert_eq!(bytes, canonical(&value));
    // The program's own `offer render` takes the file `offer make` wrote, checked against the same base. The
    // two commands were built apart; this is where they meet.
    for arm in ["route", "shuffled"] {
        let output = Command::new(assert_cmd::cargo::cargo_bin!("yak"))
            .args(["offer", "render", "--arm", arm, "--seed", "17", "--offer"])
            .arg(&out)
            .arg("--repo")
            .arg(&w.repo)
            .arg("--base")
            .arg(&w.base)
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "{arm}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert!(!output.stdout.is_empty());
    }
    for (pointer, bad) in [
        ("/list", json!("b".repeat(64))),
        ("/repo", json!("b".repeat(40))),
        ("/for_experiment", json!(false)),
    ] {
        let mut value = valid.clone();
        *value.pointer_mut(pointer).unwrap() = bad;
        write_answer(&value);
        let output = run();
        assert!(!output.status.success());
        assert!(output.stdout.is_empty());
        assert_eq!(fs::read(&out).unwrap(), bytes);
        assert!(
            String::from_utf8_lossy(&output.stderr).contains(&format!("answer.{}", &pointer[1..]))
        );
    }
    let mut wrong = goals.clone();
    wrong["question"]["repo"] = json!("c".repeat(40));
    fs::write(&goals_path, canonical(&wrong)).unwrap();
    write_answer(&valid);
    let output = run();
    assert!(!output.status.success());
    assert_eq!(fs::read(&out).unwrap(), bytes);
    assert!(String::from_utf8_lossy(&output.stderr).contains("goals.repo"));
}

#[test]
fn ranker_ignores_common_words_breaks_ties_by_later_turn_and_orders_unique_goals() {
    let mut w = World::new();
    let mut items = Vec::new();
    let mut leases = Vec::new();
    for (n, title) in [
        "common Alpha alpha",
        "common Beta",
        "common Gamma",
        "common Delta",
        "rare Éclair42",
    ]
    .iter()
    .enumerate()
    {
        let item = w.item(title);
        let paths: &[&str] = match n {
            0 => &["a.txt", "shared.txt"],
            1 => &["beta.txt", "shared.txt"],
            2 => &["gamma.txt", "a.txt"],
            3 => &["delta.txt", "shared.txt"],
            _ => &["b.txt"],
        };
        leases.push(w.finish(&item, 100 + n as i64 * 20, true, paths));
        items.push(item);
    }
    let plan = w.plan(&items);
    let out = w.make(&plan, "history");
    let list = out.join("history.json");
    assert!(
        history::goals(&plan, &list, "common")
            .unwrap()
            .chosen
            .is_empty()
    );
    assert!(
        history::goals(&plan, &list, "no overlap")
            .unwrap()
            .goals
            .is_empty()
    );
    let chosen = history::goals(&plan, &list, "alpha beta gamma delta").unwrap();
    assert_eq!(chosen.ranker, "title-words-1");
    assert_eq!(
        chosen
            .chosen
            .iter()
            .map(|c| (&c.attempt, c.score))
            .collect::<Vec<_>>(),
        [3, 2, 1].map(|i| (&leases[i].attempt.0, 1)).to_vec()
    );
    assert_eq!(
        chosen.goals,
        ["delta.txt", "shared.txt", "gamma.txt", "a.txt", "beta.txt"]
    );
    assert_eq!(chosen.question.goals, chosen.goals);
    assert_eq!(
        chosen.question.list,
        history::sha256(&fs::read(&list).unwrap())
    );
    assert_eq!(chosen.question.repo, w.base);
    assert_eq!(chosen.question.v, 1);
    let alpha = history::goals(&plan, &list, "ALPHA alpha").unwrap();
    assert_eq!(alpha.chosen[0].score, 1);
    let unicode = history::goals(&plan, &list, "ÉCLAIR42").unwrap();
    assert_eq!(unicode.chosen[0].attempt, leases[4].attempt.0);
    let plan_file = w.out("goals-plan.json");
    fs::write(&plan_file,json!({"items":plan.items.iter().map(|p|json!({"room":p.room,"item":p.item})).collect::<Vec<_>>()} ).to_string()).unwrap();
    let output = Command::new(assert_cmd::cargo::cargo_bin!("yak"))
        .args(["offer", "goals", "--plan"])
        .arg(plan_file)
        .arg("--list")
        .arg(&list)
        .args(["--title", "alpha beta gamma delta"])
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    assert_eq!(
        serde_json::from_slice::<Value>(&output.stdout).unwrap(),
        serde_json::to_value(&chosen).unwrap()
    );
    w.room
        .record_recheck(&items[3], leases[3].lease_no, &w.verdict(false))
        .unwrap();
    let refreshed = w.make(&plan, "refreshed");
    let chosen = history::goals(
        &plan,
        &refreshed.join("history.json"),
        "alpha beta gamma delta",
    )
    .unwrap();
    assert_eq!(
        chosen.chosen.iter().map(|c| &c.attempt).collect::<Vec<_>>(),
        [2, 1, 0].map(|i| &leases[i].attempt.0)
    );
}
