mod common;

use common::*;
use yak::history::{self, Measure, Plan, PlanItem};

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn actual_turn_output_is_in_no_export_store_or_log() {
    let mut world = World::new(1);
    let marker = "TURN_OUTPUT_ONLY_7fe23a9";
    let worker = world.script(
        "history-worker",
        &format!("{}\nprintf '%s\\n' '{marker}'\n", FIX),
    );
    let (result, events) = world.run(&[&worker], yak::clock::Mode::OnceThrough, NEVER, 30);
    result.unwrap();
    assert!(events.iter().any(|event| matches!(
        event,
        yak::clock::Event::Ended {
            outcome: yak::clock::Outcome::Judged {
                state: room::ItemState::PassedVerified,
                ..
            },
            ..
        }
    )));
    let item = &world.items[0];
    let walks = history::item_walks(&world.room_dir, item, None).unwrap();
    assert!(!String::from_utf8_lossy(&walks).contains(marker));
    let plan = Plan {
        items: vec![PlanItem {
            room: world.room_dir.clone(),
            item: item.clone(),
        }],
    };
    let out = world.scratch("history");
    history::make(&plan, Measure::parse("share:1").unwrap(), &out).unwrap();
    history::check(&plan, &out.join("history.json"), &out).unwrap();
    fn scan(dir: &std::path::Path, marker: &str) {
        for entry in std::fs::read_dir(dir).unwrap() {
            let path = entry.unwrap().path();
            if path.is_dir() {
                scan(&path, marker);
            } else {
                assert!(
                    !String::from_utf8_lossy(&std::fs::read(&path).unwrap()).contains(marker),
                    "{}",
                    path.display()
                );
            }
        }
    }
    scan(&world.room_dir, marker);
    scan(&out, marker);
    assert!(!format!("{events:?}").contains(marker));
}
