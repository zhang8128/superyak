mod common;

use common::*;
use room::*;

fn steps() -> Vec<Step> {
    vec![
        Step {
            seq: 0,
            tool: Tool::Read,
            target: Target::TrackedFile {
                path: "src/a.rs".into(),
                blob: "a".repeat(40),
            },
            ok: true,
            tokens_in: Some(10),
            tokens_out: None,
        },
        Step {
            seq: 1,
            tool: Tool::Shell,
            target: Target::Outside,
            ok: false,
            tokens_in: None,
            tokens_out: Some(20),
        },
        Step {
            seq: 2,
            tool: Tool::Edit,
            target: Target::TrackedFile {
                path: "src/a.rs".into(),
                blob: "b".repeat(64),
            },
            ok: true,
            tokens_in: Some(0),
            tokens_out: Some(0),
        },
    ]
}

fn attempt(r: &mut Room) -> AttemptId {
    open_item(r);
    r.take("codex:sol", 100).unwrap().unwrap().attempt
}

#[test]
fn a_walk_comes_back_in_order() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let attempt = attempt(&mut r);
    let want = steps();
    let mut shuffled = want.clone();
    shuffled.swap(0, 2);
    assert_eq!(r.record_walk(&attempt, &shuffled).unwrap(), 3);
    drop(r);
    let r = Room::open_read_only(d.path()).unwrap();
    assert_eq!(r.walk(&attempt).unwrap(), want);
}

#[test]
fn a_path_that_is_not_a_plain_relative_path_is_refused() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let attempt = attempt(&mut r);
    for path in [
        "/etc/passwd".into(),
        "../x".into(),
        "a\nb".into(),
        "x".repeat(513),
        "a/../x".into(),
        "".into(),
        "a b".into(),
        "a\\b".into(),
    ] {
        let mut batch = steps();
        batch[2].target = Target::TrackedFile {
            path,
            blob: "b".repeat(40),
        };
        assert!(matches!(
            r.record_walk(&attempt, &batch),
            Err(RoomError::Refused(_))
        ));
        assert!(r.walk(&attempt).unwrap().is_empty());
    }
}

#[test]
fn the_store_holds_no_free_text() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let attempt = attempt(&mut r);
    r.record_walk(&attempt, &steps()).unwrap();
    let c = rusqlite::Connection::open(d.path().join("room.sqlite3")).unwrap();
    let columns: Vec<(String, String)> = c
        .prepare("PRAGMA table_info(steps)")
        .unwrap()
        .query_map([], |r| Ok((r.get(1)?, r.get(2)?)))
        .unwrap()
        .map(Result::unwrap)
        .collect();
    for (name, ty) in columns {
        if ty != "TEXT" {
            continue;
        }
        let mut q = c.prepare(&format!("SELECT \"{name}\" FROM steps")).unwrap();
        let values = q.query_map([], |r| r.get::<_, Option<String>>(0)).unwrap();
        for value in values {
            if let Some(value) = value.unwrap() {
                assert!(
                    value
                        .bytes()
                        .all(|c| c.is_ascii_alphanumeric() || b"_./-".contains(&c)),
                    "free text in {name}"
                );
            }
        }
    }
    for blob in ["MARKER-9f3a".into(), "z".repeat(40), "c".repeat(41)] {
        let invalid = [Step {
            seq: 3,
            tool: Tool::Read,
            target: Target::TrackedFile {
                path: "src/b.rs".into(),
                blob,
            },
            ok: true,
            tokens_in: None,
            tokens_out: None,
        }];
        assert!(matches!(
            r.record_walk(&attempt, &invalid),
            Err(RoomError::Refused(_))
        ));
    }
    assert_eq!(r.walk(&attempt).unwrap().len(), 3);
}

#[test]
fn status_counts_only_verified_passes_toward_checks_per_day() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    for (origin, passed) in [
        (CheckOrigin::Outside, true),
        (CheckOrigin::Model, true),
        (CheckOrigin::Outside, false),
    ] {
        let mut n = new_item();
        n.check.origin = origin;
        let id = r.add_item(n).unwrap();
        r.record_frozen(&id, frozen()).unwrap();
        let lease = r.take("codex:sol", 100).unwrap().unwrap();
        let v = verdict(passed);
        r.hand_in(&lease, &v.commit, 101).unwrap();
        r.record_verdict(&id, lease.lease_no, &v, 1000).unwrap();
    }
    let now = 1010;
    let s = r.status(now).unwrap();
    assert_eq!(s.verified_passes_last_day, 1);
    assert_eq!(s.counts[&ItemState::PassedVerified], 1);
    assert_eq!(s.counts[&ItemState::PassedUnverified], 1);
    assert_eq!(s.counts[&ItemState::Failed], 1);
    assert_eq!(s.counts[&ItemState::Draft], 0);
    assert_eq!(s.daily_ceiling, 40);
    assert!(!s.stopped);
    assert_eq!(r.status(100).unwrap().turns_today, 3);
    assert_eq!(r.status(now + 86_401).unwrap().verified_passes_last_day, 0);
}

#[test]
fn a_walk_batch_is_atomic_and_cannot_overwrite_a_step() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let attempt = attempt(&mut r);
    let first = steps()[0].clone();
    r.record_walk(&attempt, std::slice::from_ref(&first))
        .unwrap();
    let batch = vec![steps()[1].clone(), first.clone()];
    assert!(r.record_walk(&attempt, &batch).is_err());
    assert_eq!(r.walk(&attempt).unwrap(), vec![first]);
    assert!(
        r.record_walk(&AttemptId("a000000000000".into()), &steps())
            .is_err()
    );
}

#[test]
fn read_only_connections_refuse_writes() {
    let d = tempfile::tempdir().unwrap();
    let mut writer = Room::init(d.path()).unwrap();
    let attempt = attempt(&mut writer);
    let mut reader = Room::open_read_only(d.path()).unwrap();
    assert!(reader.add_item(new_item()).is_err());
    assert!(reader.record_walk(&attempt, &steps()).is_err());
    assert!(reader.set_ceiling(1, 1).is_err());
    assert!(reader.walk(&attempt).unwrap().is_empty());
    assert_eq!(reader.status(100).unwrap().daily_ceiling, 40);
}
