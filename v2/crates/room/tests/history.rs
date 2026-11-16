mod common;

use common::*;
use room::*;

#[test]
fn arrived_turns_keep_typed_walks_verdicts_changes_and_legacy_targets() {
    let dir = tempfile::tempdir().unwrap();
    let mut room = Room::init(dir.path()).unwrap();
    let item = open_item(&mut room);
    let lease = room.take("codex:PRIVATE_WORKER", 100).unwrap().unwrap();
    let names = ["b.rs", "a.rs", "c.rs"].map(|path| Named {
        path: path.into(),
        blob: "a".repeat(40),
    });
    let steps = vec![
        Step {
            seq: 1,
            tool: Tool::Shell,
            target: Target::Outside,
            named: names.to_vec(),
            ok: true,
            tokens_in: Some(0),
            tokens_out: Some(12),
            seen_ms: Some(15),
            result_ms: Some(30),
        },
        Step {
            seq: 2,
            tool: Tool::Read,
            target: Target::TrackedFile {
                path: "old.rs".into(),
                blob: "b".repeat(64),
            },
            named: vec![],
            ok: false,
            tokens_in: None,
            tokens_out: None,
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
    room.record_walk(&lease.attempt, &steps).unwrap();
    let changes = [Change::Added, Change::Changed, Change::Removed]
        .into_iter()
        .enumerate()
        .map(|(n, change)| ChangedFile {
            path: format!("file{n}"),
            change,
        })
        .collect::<Vec<_>>();
    room.record_changes(&lease.attempt, &changes).unwrap();
    room.hand_in(&lease, &verdict(false).commit, 101).unwrap();
    room.record_verdict(&item, lease.lease_no, &verdict(false), 102)
        .unwrap();
    let records = room.arrived_turns(&item).unwrap();
    assert_eq!(records.len(), 1);
    let record = &records[0];
    assert_eq!(record.attempt, lease.attempt);
    assert_eq!(record.family, "codex");
    assert_eq!(record.verdict, Some(false));
    assert_eq!(record.standing, Standing::Failed);
    assert_eq!(record.recorded, 102);
    assert_eq!(record.steps[0], steps[0]);
    assert_eq!(
        record.steps[1].named,
        vec![Named {
            path: "old.rs".into(),
            blob: "b".repeat(64)
        }]
    );
    assert_eq!(record.steps[2], steps[2]);
    assert_eq!(record.changed, changes);
}

#[test]
fn only_finished_verdicts_arrive_and_old_failures_keep_their_standing() {
    let dir = tempfile::tempdir().unwrap();
    let mut room = Room::init(dir.path()).unwrap();
    let item = open_item(&mut room);
    let released = room.take("script:private", 100).unwrap().unwrap();
    room.release(&released, 101).unwrap();
    let failed = room.take("script:private", 102).unwrap().unwrap();
    room.hand_in(&failed, &verdict(false).commit, 103).unwrap();
    room.record_verdict(&item, failed.lease_no, &verdict(false), 104)
        .unwrap();
    let running = room.take("claude:private", 105).unwrap().unwrap();
    assert_eq!(room.arrived_turns(&item).unwrap().len(), 1);
    room.hand_in(&running, &verdict(true).commit, 106).unwrap();
    assert_eq!(room.arrived_turns(&item).unwrap().len(), 1);
    room.record_verdict(&item, running.lease_no, &verdict(true), 107)
        .unwrap();
    let records = room.arrived_turns(&item).unwrap();
    assert_eq!(
        records.iter().map(|r| r.standing).collect::<Vec<_>>(),
        vec![Standing::Failed, Standing::PassedVerified]
    );
}

#[test]
fn a_recheck_changes_standing_but_never_rewrites_the_original_verdict() {
    let dir = tempfile::tempdir().unwrap();
    let mut room = Room::init(dir.path()).unwrap();
    let item = open_item(&mut room);
    let lease = room.take("codex:private", 100).unwrap().unwrap();
    room.hand_in(&lease, &verdict(true).commit, 101).unwrap();
    room.record_verdict(&item, lease.lease_no, &verdict(true), 102)
        .unwrap();
    assert_eq!(
        room.arrived_turns(&item).unwrap()[0].standing,
        Standing::PassedVerified
    );
    room.record_recheck(&item, lease.lease_no, &verdict(false))
        .unwrap();
    let record = &room.arrived_turns(&item).unwrap()[0];
    assert_eq!(record.verdict, Some(true));
    assert_eq!(record.standing, Standing::PassedUnverified);
}

#[test]
fn an_unchanged_commit_and_a_model_check_cannot_export_a_verified_standing() {
    for unchanged in [true, false] {
        let dir = tempfile::tempdir().unwrap();
        let mut room = Room::init(dir.path()).unwrap();
        let mut new = new_item();
        new.check.origin = CheckOrigin::Model;
        let item = room.add_item(new).unwrap();
        room.record_frozen(&item, frozen()).unwrap();
        let lease = room.take("codex:private", 100).unwrap().unwrap();
        let mut v = verdict(true);
        if unchanged {
            v.commit = "0".repeat(40);
        }
        room.hand_in(&lease, &v.commit, 101).unwrap();
        room.record_verdict(&item, lease.lease_no, &v, 102).unwrap();
        assert_eq!(
            room.arrived_turns(&item).unwrap()[0].standing,
            if unchanged {
                Standing::Failed
            } else {
                Standing::PassedUnverified
            }
        );
    }
}

#[test]
fn an_unknown_worker_family_is_refused_without_repeating_its_name() {
    let dir = tempfile::tempdir().unwrap();
    let mut room = Room::init(dir.path()).unwrap();
    let item = open_item(&mut room);
    let lease = room.take("MARKER:PRIVATE", 100).unwrap().unwrap();
    room.hand_in(&lease, &verdict(false).commit, 101).unwrap();
    room.record_verdict(&item, lease.lease_no, &verdict(false), 102)
        .unwrap();
    assert_eq!(
        room.arrived_turns(&item).unwrap_err().to_string(),
        "refused: walk.family"
    );
}
