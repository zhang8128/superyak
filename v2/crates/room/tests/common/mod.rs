#![allow(dead_code)]

use room::*;

pub fn check() -> CheckSpec {
    CheckSpec {
        command: "test -f fixed".into(),
        files: vec!["check.sh".into()],
        timeout_secs: 900,
        origin: CheckOrigin::Outside,
        wrong_artifacts: vec!["2".repeat(40)],
        written_by: "person:fixture".into(),
    }
}

pub fn new_item() -> NewItem {
    NewItem {
        title: "Fix fixture".into(),
        repo: std::path::PathBuf::from("/fixture"),
        base_commit: "0".repeat(40),
        after: vec![],
        check: check(),
    }
}

pub fn frozen() -> Frozen {
    Frozen {
        check_hash: "1".repeat(64),
        red_on_base: true,
        red_on_wrong: vec![true],
    }
}

pub fn verdict(passed: bool) -> Verdict {
    Verdict {
        passed,
        exit_code: if passed { 0 } else { 1 },
        timed_out: false,
        commit: "3".repeat(40),
        check_hash: "1".repeat(64),
        output_sha256: "4".repeat(64),
    }
}

pub fn open_item(room: &mut Room) -> ItemId {
    let id = room.add_item(new_item()).unwrap();
    assert_eq!(room.record_frozen(&id, frozen()).unwrap(), ItemState::Open);
    id
}
