mod common;

use common::*;
use room::*;

fn setup() -> (tempfile::TempDir, Room, ItemId, Lease) {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = open_item(&mut r);
    let lease = r.take("codex:sol", 100).unwrap().unwrap();
    (d, r, id, lease)
}

fn measured() -> Measured {
    Measured {
        ended: Ended::TimedOut,
        exit_code: None,
        tokens: Tokens {
            fresh_in: Some(4),
            cache_write: None,
            cache_read: Some(6),
            output: Some(7),
            reasoning: None,
            complete: false,
        },
        steps_seen: 10,
        unknown_steps: 3,
        sandbox_ms: 11,
        worker_ms: 12,
        seal_ms: 13,
        bring_ms: 14,
        check_ms: Some(15),
        recheck_ms: None,
        active_ms: 65,
    }
}

#[test]
fn a_measured_record_reads_back_whole() {
    let (d, mut r, _, lease) = setup();
    assert_eq!(r.measured(&lease.attempt).unwrap(), None);
    let mut m = measured();
    r.record_measured(&lease.attempt, &m).unwrap();
    drop(r);
    let r = Room::open_read_only(d.path()).unwrap();
    assert_eq!(r.measured(&lease.attempt).unwrap(), Some(m.clone()));
    drop(r);
    let mut r = Room::open(d.path()).unwrap();
    r.release(&lease, 101).unwrap();
    let next = r.take("codex:sol", 102).unwrap().unwrap();
    m.ended = Ended::Exited;
    m.exit_code = Some(-9);
    m.tokens = Tokens {
        fresh_in: Some(1),
        cache_write: Some(2),
        cache_read: Some(3),
        output: Some(4),
        reasoning: Some(5),
        complete: true,
    };
    m.check_ms = None;
    m.recheck_ms = Some(16);
    m.active_ms = 50;
    r.record_measured(&next.attempt, &m).unwrap();
    assert_eq!(r.measured(&next.attempt).unwrap(), Some(m));
}

#[test]
fn a_second_measured_record_for_one_attempt_is_refused() {
    let (_, mut r, _, lease) = setup();
    r.record_measured(&lease.attempt, &measured()).unwrap();
    assert!(r.record_measured(&lease.attempt, &measured()).is_err());
    assert_eq!(r.measured(&lease.attempt).unwrap(), Some(measured()));
    assert!(
        r.record_measured(&AttemptId("a000000000000".into()), &measured())
            .is_err()
    );
}

#[test]
fn numbers_outside_sqlites_integer_range_are_refused_without_changing_the_record() {
    let (d, mut r, _, lease) = setup();
    let mut m = measured();
    m.worker_ms = u64::MAX;
    assert!(r.record_measured(&lease.attempt, &m).is_err());
    assert_eq!(r.measured(&lease.attempt).unwrap(), None);
    m = measured();
    m.tokens.output = Some(u64::MAX);
    assert!(r.record_measured(&lease.attempt, &m).is_err());
    r.record_measured(&lease.attempt, &measured()).unwrap();
    assert!(r.record_recheck_ms(&lease.attempt, u64::MAX).is_err());
    assert_eq!(r.measured(&lease.attempt).unwrap(), Some(measured()));
    let c = rusqlite::Connection::open(d.path().join("room.sqlite3")).unwrap();
    for column in ["steps_seen", "output"] {
        c.execute(&format!("UPDATE measured SET {column}=-1"), [])
            .unwrap();
        assert!(r.measured(&lease.attempt).is_err());
        c.execute(&format!("UPDATE measured SET {column}=0"), [])
            .unwrap();
    }
}

#[test]
fn a_second_looks_seconds_are_kept_beside_the_turns() {
    let (_, mut r, _, lease) = setup();
    assert!(r.record_recheck_ms(&lease.attempt, 42).is_err());
    r.record_measured(&lease.attempt, &measured()).unwrap();
    r.record_recheck_ms(&lease.attempt, 42).unwrap();
    let m = r.measured(&lease.attempt).unwrap().unwrap();
    assert_eq!(m.recheck_ms, Some(42));
    assert_eq!(m.active_ms, 65);
}

#[test]
fn changes_read_back_in_order() {
    let (d, mut r, _, lease) = setup();
    let files = vec![
        ChangedFile {
            path: "z.rs".into(),
            change: Change::Added,
        },
        ChangedFile {
            path: "a b.txt".into(),
            change: Change::Changed,
        },
        ChangedFile {
            path: "a.rs".into(),
            change: Change::Removed,
        },
        ChangedFile {
            path: "m.rs".into(),
            change: Change::Changed,
        },
    ];
    assert_eq!(r.record_changes(&lease.attempt, &files).unwrap(), 1);
    drop(r);
    let r = Room::open_read_only(d.path()).unwrap();
    assert_eq!(
        r.changes(&lease.attempt).unwrap(),
        vec![files[0].clone(), files[2].clone(), files[3].clone()]
    );
}

#[test]
fn the_store_holds_no_free_text() {
    let (d, mut r, _, lease) = setup();
    let step = Step {
        seq: 0,
        tool: Tool::Shell,
        target: Target::Outside,
        ok: true,
        tokens_in: None,
        tokens_out: None,
        seen_ms: Some(1),
        result_ms: Some(2),
        named: vec![Named {
            path: "src/a.rs".into(),
            blob: "a".repeat(40),
        }],
    };
    r.record_walk(&lease.attempt, std::slice::from_ref(&step))
        .unwrap();
    r.record_measured(&lease.attempt, &measured()).unwrap();
    r.record_changes(
        &lease.attempt,
        &[ChangedFile {
            path: "src/a.rs".into(),
            change: Change::Changed,
        }],
    )
    .unwrap();
    let c = rusqlite::Connection::open(d.path().join("room.sqlite3")).unwrap();
    for (table, expected) in [
        ("step_files", vec!["attempt", "path", "blob"]),
        ("measured", vec!["attempt", "ended"]),
        ("changes", vec!["attempt", "path", "change"]),
    ] {
        let columns: Vec<String> = c
            .prepare(&format!("PRAGMA table_info({table})"))
            .unwrap()
            .query_map([], |r| Ok((r.get::<_, String>(1)?, r.get::<_, String>(2)?)))
            .unwrap()
            .map(Result::unwrap)
            .filter(|(_, ty)| ty == "TEXT")
            .map(|(name, _)| name)
            .collect();
        assert_eq!(columns, expected);
        for column in columns {
            let values: Vec<String> = c
                .prepare(&format!("SELECT \"{column}\" FROM {table}"))
                .unwrap()
                .query_map([], |r| r.get(0))
                .unwrap()
                .map(Result::unwrap)
                .collect();
            let expected = match column.as_str() {
                "attempt" => lease.attempt.0.clone(),
                "path" => "src/a.rs".into(),
                "blob" => "a".repeat(40),
                "ended" => "timed_out".into(),
                "change" => "changed".into(),
                _ => panic!("unexpected text"),
            };
            assert_eq!(values, vec![expected]);
        }
    }
    let mut bad = step;
    bad.seq = 1;
    bad.named[0].blob = "text from a turn".into();
    assert!(r.record_walk(&lease.attempt, &[bad]).is_err());
    assert_eq!(r.walk(&lease.attempt).unwrap().len(), 1);
}

#[test]
fn turns_lists_an_items_attempts_with_what_was_measured() {
    let (_, mut r, id, lease) = setup();
    let other = open_item(&mut r);
    r.record_measured(&lease.attempt, &measured()).unwrap();
    let file = ChangedFile {
        path: "a.rs".into(),
        change: Change::Added,
    };
    r.record_changes(&lease.attempt, std::slice::from_ref(&file))
        .unwrap();
    r.record_walk(
        &lease.attempt,
        &[Step {
            seq: 0,
            tool: Tool::Read,
            target: Target::Outside,
            ok: true,
            tokens_in: None,
            tokens_out: None,
            named: vec![Named {
                path: "a.rs".into(),
                blob: "b".repeat(40),
            }],
            seen_ms: None,
            result_ms: None,
        }],
    )
    .unwrap();
    r.hand_in(&lease, &verdict(false).commit, 101).unwrap();
    r.record_verdict(&id, 1, &verdict(false), 102).unwrap();
    let next = r.take("codex:sol", 103).unwrap().unwrap();
    let turns = r.turns(&id).unwrap();
    assert_eq!(turns.len(), 2);
    assert_eq!(turns[0].attempt, lease.attempt);
    assert_eq!(turns[0].lease_no, 1);
    assert_eq!(turns[0].worker, "codex:sol");
    assert_eq!(turns[0].state, "finished");
    assert_eq!(turns[0].commit, Some(verdict(false).commit));
    assert_eq!(turns[0].passed, Some(false));
    assert_eq!(turns[0].measured, Some(measured()));
    assert_eq!(turns[0].changes, vec![file]);
    assert_eq!((turns[0].steps, turns[0].steps_with_a_name), (1, 1));
    assert_eq!(turns[1].attempt, next.attempt);
    assert_eq!(turns[1].lease_no, 2);
    assert_eq!(turns[1].measured, None);
    assert_eq!(turns[1].passed, None);
    assert!(r.turns(&other).unwrap().is_empty());
    assert!(r.turns(&ItemId("i000000000000".into())).is_err());
}

#[test]
fn turns_counts_a_legacy_target_as_a_name() {
    let (_, mut r, id, lease) = setup();
    r.record_walk(
        &lease.attempt,
        &[Step {
            seq: 0,
            tool: Tool::Read,
            target: Target::TrackedFile {
                path: "a.rs".into(),
                blob: "b".repeat(40),
            },
            ok: true,
            tokens_in: None,
            tokens_out: None,
            named: vec![],
            seen_ms: None,
            result_ms: None,
        }],
    )
    .unwrap();
    assert_eq!(r.turns(&id).unwrap()[0].steps_with_a_name, 1);
}
