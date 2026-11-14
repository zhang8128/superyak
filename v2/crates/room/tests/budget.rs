mod common;

use common::*;
use room::{limits::LEASE_SECS, *};

fn finish(r: &mut Room, lease: &Lease, now: Ts) {
    let v = verdict(true);
    r.hand_in(lease, &v.commit, now).unwrap();
    r.record_verdict(&lease.item, lease.lease_no, &v, now)
        .unwrap();
}

#[test]
fn the_ceiling_refuses_the_next_take() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    r.set_ceiling(2, 1).unwrap();
    for _ in 0..3 {
        open_item(&mut r);
    }
    for now in [100, 200] {
        let lease = r.take("codex:sol", now).unwrap().unwrap();
        finish(&mut r, &lease, now + 1);
    }
    assert!(matches!(
        r.take("codex:sol", 300),
        Err(RoomError::Ceiling { used: 2, limit: 2 })
    ));
    assert_eq!(r.turns_today(300).unwrap(), 2);
}

#[test]
fn a_killed_turn_still_counts() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    open_item(&mut r);
    r.take("codex:sol", 100).unwrap().unwrap();
    r.expire_due(100 + LEASE_SECS).unwrap();
    drop(r);
    let r = Room::open(d.path()).unwrap();
    assert_eq!(r.turns_today(100 + LEASE_SECS).unwrap(), 1);
}

#[test]
fn the_day_rolls_over_at_utc_midnight() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    r.set_ceiling(1, 1).unwrap();
    open_item(&mut r);
    open_item(&mut r);
    let lease = r.take("codex:sol", 86_399).unwrap().unwrap();
    finish(&mut r, &lease, 86_400);
    r.take("codex:sol", 86_401).unwrap().unwrap();
    assert_eq!(r.turns_today(86_399).unwrap(), 1);
    assert_eq!(r.turns_today(86_401).unwrap(), 1);
}

#[test]
fn only_one_turn_runs_at_a_time_by_default() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    open_item(&mut r);
    open_item(&mut r);
    let lease = r.take("codex:sol", 100).unwrap().unwrap();
    assert!(r.take("claude:opus", 100).unwrap().is_none());
    r.hand_in(&lease, &verdict(true).commit, 101).unwrap();
    assert!(r.take("claude:opus", 102).unwrap().is_none());
    assert_eq!(r.turns_today(102).unwrap(), 1);
    r.record_verdict(&lease.item, 1, &verdict(true), 102)
        .unwrap();
    assert!(r.take("claude:opus", 103).unwrap().is_some());
}

#[test]
fn a_stop_file_refuses_every_take() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    open_item(&mut r);
    std::fs::write(d.path().join("STOP"), []).unwrap();
    assert!(r.stopped());
    assert!(matches!(r.take("codex:sol", 100), Err(RoomError::Stopped)));
    assert_eq!(r.turns_today(100).unwrap(), 0);
    std::fs::remove_file(d.path().join("STOP")).unwrap();
    assert!(!r.stopped());
    assert!(r.take("codex:sol", 101).unwrap().is_some());
}

#[test]
fn failed_reservations_and_ineligible_workers_do_not_spend_turns() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let mut n = new_item();
    n.check.written_by = "codex:sol".into();
    let id = r.add_item(n).unwrap();
    r.record_frozen(&id, frozen()).unwrap();
    assert!(r.take("codex:sol", 100).unwrap().is_none());
    assert_eq!(r.turns_today(100).unwrap(), 0);
    assert!(r.take("claude:opus", i64::MAX).is_err());
    assert_eq!(r.turns_today(i64::MAX).unwrap(), 0);
    assert_eq!(r.item(&id).unwrap().attempts, 0);
}

#[test]
fn configured_concurrency_and_ceiling_survive_reopen() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    r.set_ceiling(2, 2).unwrap();
    for _ in 0..3 {
        open_item(&mut r);
    }
    drop(r);
    let mut r = Room::open(d.path()).unwrap();
    r.take("codex:sol", 100).unwrap().unwrap();
    r.take("claude:opus", 100).unwrap().unwrap();
    assert!(matches!(
        r.take("codex:sol", 100),
        Err(RoomError::Ceiling { used: 2, limit: 2 })
    ));
}
