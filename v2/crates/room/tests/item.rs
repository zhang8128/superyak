mod common;

use common::*;
use room::{item::classify, *};

#[test]
fn frozen_red_on_base_opens_the_item() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = r.add_item(new_item()).unwrap();
    assert_eq!(r.item(&id).unwrap().state, ItemState::Draft);
    assert_eq!(r.record_frozen(&id, frozen()).unwrap(), ItemState::Open);
    let view = r.item(&id).unwrap();
    assert_eq!(view.title, "Fix fixture");
    assert_eq!((view.lease_no, view.attempts), (0, 0));
    assert_eq!(view.written_by, "person:fixture");
    assert_eq!(view.origin, CheckOrigin::Outside);
}

#[test]
fn a_check_that_passes_on_base_stays_draft_and_is_listed() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = r.add_item(new_item()).unwrap();
    let mut weak = frozen();
    weak.red_on_base = false;
    assert_eq!(
        r.record_frozen(&id, weak.clone()).unwrap(),
        ItemState::Draft
    );
    r.record_frozen(&id, weak).unwrap();
    let ds = r.disagreements().unwrap();
    assert_eq!(ds.len(), 1);
    assert_eq!(ds[0].item, id);
    assert_eq!(ds[0].kind, DisagreementKind::WeakCheck);
}

#[test]
fn an_item_waits_for_what_it_comes_after() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let a = open_item(&mut r);
    let mut n = new_item();
    n.after = vec![a.clone()];
    let b = r.add_item(n).unwrap();
    assert_eq!(r.record_frozen(&b, frozen()).unwrap(), ItemState::Blocked);
    assert_eq!(r.item(&b).unwrap().after, vec![a.clone()]);
    let c = rusqlite::Connection::open(d.path().join("room.sqlite3")).unwrap();
    c.execute(
        "UPDATE items SET state='passed_unverified' WHERE id=?1",
        [&a.0],
    )
    .unwrap();
    assert_eq!(r.record_frozen(&b, frozen()).unwrap(), ItemState::Blocked);
    c.execute(
        "UPDATE items SET state='passed_verified' WHERE id=?1",
        [&a.0],
    )
    .unwrap();
    assert_eq!(r.record_frozen(&b, frozen()).unwrap(), ItemState::Open);
}

#[test]
fn classify_follows_section_seven() {
    let outside = check();
    let mut model_written = outside.clone();
    model_written.origin = CheckOrigin::Model;
    let red = frozen();
    let no_wrong_artifacts = Frozen {
        red_on_wrong: vec![],
        ..red.clone()
    };
    let pass = verdict(true);
    let pass_with_other_hash = Verdict {
        check_hash: "5".repeat(64),
        ..pass.clone()
    };
    let fail = verdict(false);
    assert_eq!(
        classify(&outside, &red, &pass, "codex:sol"),
        ItemState::PassedVerified
    );
    assert_eq!(
        classify(&model_written, &red, &pass, "codex:sol"),
        ItemState::PassedUnverified
    );
    assert_eq!(
        classify(&outside, &no_wrong_artifacts, &pass, "codex:sol"),
        ItemState::PassedUnverified
    );
    assert_eq!(
        classify(&outside, &red, &pass_with_other_hash, "codex:sol"),
        ItemState::Failed
    );
    assert_eq!(
        classify(&outside, &red, &fail, "codex:sol"),
        ItemState::Failed
    );
    assert_eq!(
        classify(&outside, &red, &pass, "person:fixture"),
        ItemState::PassedUnverified
    );
    let observed = CheckSpec {
        origin: CheckOrigin::ObservedFailure,
        ..outside.clone()
    };
    assert_eq!(
        classify(&observed, &red, &pass, "codex:sol"),
        ItemState::PassedVerified
    );
    for weak in [
        Frozen {
            red_on_base: false,
            ..red.clone()
        },
        Frozen {
            red_on_wrong: vec![false],
            ..red.clone()
        },
    ] {
        assert_eq!(
            classify(&outside, &weak, &pass, "codex:sol"),
            ItemState::PassedUnverified
        );
    }
    let timeout = Verdict {
        timed_out: true,
        ..pass
    };
    assert_eq!(
        classify(&outside, &red, &timeout, "codex:sol"),
        ItemState::Failed
    );
}

#[test]
fn frozen_checks_cannot_be_replaced() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = open_item(&mut r);
    let changed = Frozen {
        check_hash: "6".repeat(64),
        ..frozen()
    };
    assert!(matches!(
        r.record_frozen(&id, changed),
        Err(RoomError::Refused(_))
    ));
    assert_eq!(r.item(&id).unwrap().state, ItemState::Open);
}

#[test]
fn a_frozen_hash_cannot_carry_free_text() {
    let d = tempfile::tempdir().unwrap();
    let mut r = Room::init(d.path()).unwrap();
    let id = r.add_item(new_item()).unwrap();
    let f = Frozen {
        check_hash: "MARKER-9f3a".into(),
        ..frozen()
    };
    assert!(matches!(
        r.record_frozen(&id, f),
        Err(RoomError::Refused(_))
    ));
    assert_eq!(r.item(&id).unwrap().state, ItemState::Draft);
}
