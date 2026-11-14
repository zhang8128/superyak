mod common;

use common::*;
use room::*;

#[test]
fn items_lists_every_item_oldest_first() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let first = r.add_item(new_item()).unwrap();
    let second = open_item(&mut r);
    let third = r.add_item(new_item()).unwrap();
    let items = r.items().unwrap();
    assert_eq!(
        items.iter().map(|i| i.id.clone()).collect::<Vec<_>>(),
        vec![first, second, third]
    );
    assert_eq!(items[1].state, ItemState::Open);
}

#[test]
fn drafts_excludes_checks_already_frozen_even_if_weak() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let first = r.add_item(new_item()).unwrap();
    let weak = r.add_item(new_item()).unwrap();
    r.record_frozen(
        &weak,
        Frozen {
            red_on_base: false,
            ..frozen()
        },
    )
    .unwrap();
    let second = r.add_item(new_item()).unwrap();
    open_item(&mut r);
    assert_eq!(r.drafts().unwrap(), vec![first, second]);
}

#[test]
fn item_spec_round_trips_configuration_and_frozen_record() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let n = new_item();
    let id = r.add_item(n.clone()).unwrap();
    let spec = r.item_spec(&id).unwrap();
    assert_eq!(spec.repo, n.repo);
    assert_eq!(spec.base_commit, n.base_commit);
    assert_eq!(spec.check, n.check);
    assert_eq!(spec.frozen, None);
    r.record_frozen(&id, frozen()).unwrap();
    assert_eq!(r.item_spec(&id).unwrap().frozen, Some(frozen()));
}

#[test]
fn lease_duration_override_is_positive_and_not_persisted() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    open_item(&mut r);
    r.set_lease_secs(2).unwrap();
    for secs in [0, -1] {
        assert!(matches!(r.set_lease_secs(secs), Err(RoomError::Refused(_))));
    }
    let first = r.take("codex:sol", 100).unwrap().unwrap();
    assert_eq!(first.expires, 102);
    r.expire_due(102).unwrap();
    drop(r);
    let mut r = Room::open(d.path()).unwrap();
    assert_eq!(r.take("codex:sol", 103).unwrap().unwrap().expires, 1903);
}

#[test]
fn a_recheck_difference_demotes_and_is_listed_once() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = open_item(&mut r);
    let lease = r.take("codex:sol", 100).unwrap().unwrap();
    let v = verdict(true);
    r.hand_in(&lease, &v.commit, 101).unwrap();
    r.record_verdict(&id, 1, &v, 102).unwrap();
    assert_eq!(
        r.record_recheck(&id, 1, &v).unwrap(),
        ItemState::PassedVerified
    );
    assert!(r.disagreements().unwrap().is_empty());
    let mut child = new_item();
    child.after = vec![id.clone()];
    let child = r.add_item(child).unwrap();
    r.record_frozen(&child, frozen()).unwrap();
    let other = Verdict {
        commit: "8".repeat(40),
        ..verdict(false)
    };
    assert!(r.record_recheck(&id, 1, &other).is_err());
    assert!(matches!(
        r.record_recheck(&id, 0, &verdict(false)),
        Err(RoomError::Stale {
            lease_no: 0,
            current: 1
        })
    ));
    assert_eq!(
        r.record_recheck(&id, 1, &verdict(false)).unwrap(),
        ItemState::PassedUnverified
    );
    assert_eq!(r.item(&child).unwrap().state, ItemState::Blocked);
    assert!(matches!(
        r.record_recheck(&id, 1, &verdict(false)),
        Err(RoomError::Refused(_))
    ));
    assert!(matches!(
        r.record_recheck(&id, 1, &v),
        Err(RoomError::Refused(_))
    ));
    assert_eq!(r.item(&id).unwrap().state, ItemState::PassedUnverified);
    let ds = r.disagreements().unwrap();
    assert_eq!(ds.len(), 1);
    assert_eq!(ds[0].kind, DisagreementKind::RecheckDiffers);
    assert_eq!(ds[0].item, id);
}

#[test]
fn submission_returns_only_the_current_handed_in_artifact() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = open_item(&mut r);
    assert_eq!(r.submission(&id).unwrap(), None);
    let lease = r.take("codex:sol", 100).unwrap().unwrap();
    assert_eq!(r.submission(&id).unwrap(), None);
    r.hand_in(&lease, &verdict(true).commit, 101).unwrap();
    drop(r);
    let mut r = Room::open(d.path()).unwrap();
    assert_eq!(r.submission(&id).unwrap(), Some((1, "3".repeat(40))));
    r.expire_due(1900).unwrap();
    r.take("claude:opus", 1901).unwrap().unwrap();
    assert_eq!(r.submission(&id).unwrap(), None);
}

#[test]
fn directory_accessor_locates_room_artifacts() {
    let d = tempfile::tempdir().unwrap();
    let r = Room::init(d.path()).unwrap();
    assert_eq!(r.dir(), d.path());
    assert!(r.dir().join("room.sqlite3").is_file());
}

#[test]
fn current_lease_recovers_attempt_identity_and_renewed_expiry() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = open_item(&mut r);
    assert_eq!(r.current_lease(&id).unwrap(), None);
    let lease = r.take("codex:sol", 100).unwrap().unwrap();
    r.renew(&lease, 500).unwrap();
    r.hand_in(&lease, &verdict(true).commit, 501).unwrap();
    drop(r);
    let mut r = Room::open(d.path()).unwrap();
    assert_eq!(
        r.current_lease(&id).unwrap(),
        Some(Lease {
            expires: 2300,
            ..lease
        })
    );
    r.record_verdict(&id, 1, &verdict(true), 502).unwrap();
    assert_eq!(r.current_lease(&id).unwrap(), None);
}
