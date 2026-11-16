mod common;

use common::*;
use yak::history::{self, Measure, Plan, PlanItem};

#[test]
#[ignore = "needs the room: a list of processes and a jail"]
fn actual_turn_output_is_in_no_export_store_or_log() {
    let mut world = World::new(1);
    let marker = "TURN_OUTPUT_ONLY_7fe23a9";
    // The marker goes where the room does read: in a tool's command and in that tool's result, as well as on
    // a bare line. So its absence below is shown against lines the room parsed, and not against nothing.
    let asked = serde_json::json!({"type":"assistant","message":{"content":[
        {"type":"tool_use","id":"t2","name":"Bash","input":{"command":format!("echo {marker}")}}]}});
    let told = serde_json::json!({"type":"user","message":{"content":[
        {"type":"tool_result","tool_use_id":"t2","content":marker}]}});
    let worker = world.script(
        "history-worker",
        &format!(
            "{}\nprintf '%s\\n' '{asked}'\nprintf '%s\\n' '{told}'\nprintf '%s\\n' '{marker}'\n",
            FIX
        ),
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
    // The room parsed this worker's lines: the walk names the file the worker read, and holds the shell
    // step whose command and result carried the marker.
    let walk: serde_json::Value =
        serde_json::from_slice(walks.split(|byte| *byte == b'\n').next().unwrap()).unwrap();
    let steps = walk["steps"].as_array().unwrap();
    assert!(steps.iter().any(|step| {
        step["tool"] == "read"
            && step["named"]
                .as_array()
                .unwrap()
                .iter()
                .any(|named| named[0] == "answer1.txt")
    }));
    assert!(steps.iter().any(|step| step["tool"] == "shell"));
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
