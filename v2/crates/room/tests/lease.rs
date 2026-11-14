mod common;

use common::*;
use room::{limits::LEASE_SECS, *};

#[test]
fn take_gives_the_oldest_open_item_and_lease_one() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let first = open_item(&mut r);
    let _second = open_item(&mut r);
    let lease = r.take("codex:sol", 100).unwrap().unwrap();
    assert_eq!(lease.item, first);
    assert_eq!(lease.lease_no, 1);
    assert_eq!(lease.expires, 100 + LEASE_SECS);
    assert_eq!(lease.worker, "codex:sol");
    assert_eq!(r.item(&first).unwrap().state, ItemState::Leased);
    assert_eq!(r.item(&first).unwrap().attempts, 1);
    assert_eq!(lease.attempt.0.len(), 13);
}

#[test]
fn the_check_author_is_skipped() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let mut n = new_item();
    n.check.written_by = "codex:sol".into();
    let id = r.add_item(n).unwrap();
    r.record_frozen(&id, frozen()).unwrap();
    assert!(r.take("codex:sol", 100).unwrap().is_none());
    assert!(r.take("claude:opus", 100).unwrap().is_some());
}

#[test]
fn an_expired_lease_reopens_the_item_with_the_next_number() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = open_item(&mut r);
    let first = r.take("codex:sol", 100).unwrap().unwrap();
    drop(r); // restart loses all in-memory state
    let mut r = Room::open(d.path()).unwrap();
    assert_eq!(
        r.expire_due(100 + LEASE_SECS + 1).unwrap(),
        vec![id.clone()]
    );
    assert_eq!(r.item(&id).unwrap().state, ItemState::Open);
    let second = r
        .take("claude:opus", 100 + LEASE_SECS + 1)
        .unwrap()
        .unwrap();
    assert_eq!(second.lease_no, 2);
    assert_ne!(first.attempt, second.attempt);
}

#[test]
fn a_late_hand_in_is_stale() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    open_item(&mut r);
    let first = r.take("codex:sol", 100).unwrap().unwrap();
    let now = 100 + LEASE_SECS + 1;
    r.expire_due(now).unwrap();
    let second = r.take("claude:opus", now).unwrap().unwrap();
    assert!(matches!(
        r.hand_in(&first, &verdict(true).commit, now),
        Err(RoomError::Stale {
            lease_no: 1,
            current: 2
        })
    ));
    assert_eq!(r.item(&second.item).unwrap().state, ItemState::Leased);
}

#[test]
fn a_hand_in_after_expiry_is_stale_even_with_no_new_lease() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    open_item(&mut r);
    let lease = r.take("codex:sol", 100).unwrap().unwrap();
    assert!(matches!(
        r.hand_in(&lease, &verdict(true).commit, lease.expires),
        Err(RoomError::Stale {
            lease_no: 1,
            current: 1
        })
    ));
    assert!(matches!(
        r.renew(&lease, lease.expires),
        Err(RoomError::Stale { .. })
    ));
}

#[test]
fn hand_in_twice_is_one_submission() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = open_item(&mut r);
    let lease = r.take("codex:sol", 100).unwrap().unwrap();
    r.hand_in(&lease, &verdict(true).commit, 101).unwrap();
    r.hand_in(&lease, &"9".repeat(40), 102).unwrap();
    let c = rusqlite::Connection::open(d.path().join("room.sqlite3")).unwrap();
    let (count, commit): (u32, String) = c
        .query_row("SELECT count(*),submitted_commit FROM attempts", [], |r| {
            Ok((r.get(0)?, r.get(1)?))
        })
        .unwrap();
    assert_eq!(count, 1);
    assert_eq!(commit, "3".repeat(40));
    assert_eq!(r.item(&id).unwrap().state, ItemState::Checking);
}

#[test]
fn three_failed_attempts_abandon_the_item() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = open_item(&mut r);
    for i in 1..=3 {
        let lease = r.take("codex:sol", 100 + i as i64).unwrap().unwrap();
        assert_eq!(lease.lease_no, i);
        r.hand_in(&lease, &verdict(false).commit, 110).unwrap();
        let want = if i == 3 {
            ItemState::Abandoned
        } else {
            ItemState::Failed
        };
        assert_eq!(
            r.record_verdict(&id, lease.lease_no, &verdict(false), 111)
                .unwrap(),
            want
        );
    }
    assert!(r.take("codex:sol", 120).unwrap().is_none());
    let ds = r.disagreements().unwrap();
    assert_eq!(ds.len(), 1);
    assert_eq!(ds[0].kind, DisagreementKind::Abandoned);
    assert_eq!(r.item(&id).unwrap().attempts, 3);
}

#[test]
fn renewal_uses_stored_identity_and_extends_expiry() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    open_item(&mut r);
    let lease = r.take("codex:sol", 100).unwrap().unwrap();
    assert_eq!(r.renew(&lease, 400).unwrap(), 400 + LEASE_SECS);
    assert!(r.expire_due(100 + LEASE_SECS).unwrap().is_empty());
    let forged = Lease {
        worker: "claude:opus".into(),
        ..lease.clone()
    };
    assert!(r.hand_in(&forged, &verdict(true).commit, 500).is_err());
    r.hand_in(&lease, &verdict(true).commit, 100 + LEASE_SECS + 1)
        .unwrap();
}

#[test]
fn verdict_is_bound_to_the_current_submission_and_releases_dependencies() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let a = open_item(&mut r);
    let mut child = new_item();
    child.after = vec![a.clone()];
    let b = r.add_item(child).unwrap();
    r.record_frozen(&b, frozen()).unwrap();
    let lease = r.take("codex:sol", 100).unwrap().unwrap();
    assert!(r.record_verdict(&a, 1, &verdict(true), 100).is_err());
    r.hand_in(&lease, &verdict(true).commit, 101).unwrap();
    let wrong = Verdict {
        commit: "5".repeat(40),
        ..verdict(true)
    };
    assert!(r.record_verdict(&a, 1, &wrong, 102).is_err());
    assert_eq!(
        r.record_verdict(&a, 1, &verdict(true), 102).unwrap(),
        ItemState::PassedVerified
    );
    assert_eq!(r.item(&b).unwrap().state, ItemState::Open);
    assert!(r.record_verdict(&a, 1, &verdict(false), 103).is_err());
    assert_eq!(r.item(&a).unwrap().state, ItemState::PassedVerified);
}

#[test]
fn expired_checking_attempts_abandon_after_three_and_refuse_old_verdicts() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = open_item(&mut r);
    for i in 0..3 {
        let now = i * (LEASE_SECS + 1);
        let lease = r.take("codex:sol", now).unwrap().unwrap();
        r.hand_in(&lease, &verdict(true).commit, now + 1).unwrap();
        assert_eq!(r.expire_due(now + LEASE_SECS).unwrap(), vec![id.clone()]);
        assert!(
            r.record_verdict(&id, lease.lease_no, &verdict(true), now + LEASE_SECS)
                .is_err()
        );
    }
    assert_eq!(r.item(&id).unwrap().state, ItemState::Abandoned);
    assert_eq!(r.disagreements().unwrap().len(), 1);
}

#[test]
fn an_unchanged_artifact_cannot_pass() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = open_item(&mut r);
    let lease = r.take("codex:sol", 100).unwrap().unwrap();
    let unchanged = Verdict {
        commit: "0".repeat(40),
        ..verdict(true)
    };
    r.hand_in(&lease, &unchanged.commit, 101).unwrap();
    assert_eq!(
        r.record_verdict(&id, 1, &unchanged, 102).unwrap(),
        ItemState::Failed
    );
}

#[test]
fn artifact_metadata_cannot_carry_free_text() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = open_item(&mut r);
    let lease = r.take("codex:sol", 100).unwrap().unwrap();
    assert!(matches!(
        r.hand_in(&lease, "MARKER-9f3a", 101),
        Err(RoomError::Refused(_))
    ));
    assert_eq!(r.item(&id).unwrap().state, ItemState::Leased);
    r.hand_in(&lease, &verdict(true).commit, 102).unwrap();
    for v in [
        Verdict {
            output_sha256: "MARKER-9f3a".into(),
            ..verdict(true)
        },
        Verdict {
            check_hash: "MARKER-9f3a".into(),
            ..verdict(true)
        },
    ] {
        assert!(matches!(
            r.record_verdict(&id, 1, &v, 103),
            Err(RoomError::Refused(_))
        ));
    }
    assert_eq!(r.item(&id).unwrap().state, ItemState::Checking);
    assert_eq!(
        r.record_verdict(&id, 1, &verdict(true), 103).unwrap(),
        ItemState::PassedVerified
    );
}
