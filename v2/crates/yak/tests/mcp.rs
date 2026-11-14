//! Real stdio MCP clients: no transport mocks and no writable MCP operations.
use std::fs;
use std::io::{BufRead, BufReader, Write};
use std::os::unix::fs::PermissionsExt;
use std::path::Path;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, Receiver};
use std::thread;
use std::time::{Duration, Instant};

use room::{CheckOrigin, CheckSpec, Frozen, NewItem, Room};
use serde_json::{Value, json};

struct Process(Child);
impl Drop for Process {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

fn command(room: &Path) -> Command {
    let mut cmd = Command::new(assert_cmd::cargo::cargo_bin!("yak"));
    cmd.arg("--room").arg(room).env_remove("YAK_JAIL_READ");
    cmd
}

struct Client {
    _child: Process,
    input: ChildStdin,
    output: Receiver<Value>,
    next: u32,
}
impl Client {
    fn new(room: &Path) -> Self {
        let mut child = command(room)
            .arg("mcp")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .spawn()
            .unwrap();
        let input = child.stdin.take().unwrap();
        let stdout = child.stdout.take().unwrap();
        let (tx, output) = mpsc::channel();
        thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                let value = serde_json::from_str(&line.unwrap()).expect("only MCP JSON on stdout");
                if tx.send(value).is_err() {
                    break;
                }
            }
        });
        let mut client = Self {
            _child: Process(child),
            input,
            output,
            next: 1,
        };
        let reply = client.request("initialize", json!({"protocolVersion":"2024-11-05", "capabilities":{}, "clientInfo":{"name":"test", "version":"1"}}));
        assert!(reply.get("result").is_some(), "{reply}");
        client.send(json!({"jsonrpc":"2.0", "method":"notifications/initialized"}));
        client
    }

    fn send(&mut self, request: Value) {
        writeln!(self.input, "{request}").unwrap();
        self.input.flush().unwrap();
    }

    fn request(&mut self, method: &str, params: Value) -> Value {
        let id = self.next;
        self.next += 1;
        self.send(json!({"jsonrpc":"2.0", "id":id, "method":method, "params":params}));
        loop {
            let reply = self
                .output
                .recv_timeout(Duration::from_secs(5))
                .expect("MCP response");
            if reply["id"] == id {
                return reply;
            }
        }
    }

    fn call(&mut self, name: &str, arguments: Value) -> Value {
        self.request("tools/call", json!({"name":name, "arguments":arguments}))
    }
}

fn value(reply: &Value) -> Value {
    assert!(reply.get("error").is_none(), "{reply}");
    assert_ne!(reply["result"]["isError"], true, "{reply}");
    serde_json::from_str(
        reply["result"]["content"][0]["text"]
            .as_str()
            .expect("JSON tool text"),
    )
    .unwrap()
}

fn cli_json(room: &Path, args: &[&str]) -> Value {
    let out = command(room).args(args).output().unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    serde_json::from_slice(&out.stdout).unwrap()
}

#[test]
fn the_mcp_server_lists_exactly_four_tools() {
    let tmp = tempfile::tempdir().unwrap();
    drop(Room::init(tmp.path()).unwrap());
    let mut client = Client::new(tmp.path());
    let listed = client.request("tools/list", json!({}));
    let mut names: Vec<&str> = listed["result"]["tools"]
        .as_array()
        .unwrap()
        .iter()
        .map(|tool| tool["name"].as_str().unwrap())
        .collect();
    names.sort();
    assert_eq!(
        names,
        ["disagreements", "item_list", "item_show", "room_status"]
    );
    for tool in listed["result"]["tools"].as_array().unwrap() {
        assert_eq!(tool["annotations"]["readOnlyHint"], true);
        assert_eq!(tool["inputSchema"]["additionalProperties"], false);
        if tool["name"] == "item_show" {
            assert_eq!(tool["inputSchema"]["required"], json!(["id"]));
            assert_eq!(tool["inputSchema"]["properties"]["id"]["type"], "string");
        } else {
            assert_eq!(tool["inputSchema"]["properties"], json!({}));
        }
    }
}

#[test]
fn room_status_over_mcp_equals_status_json() {
    let tmp = tempfile::tempdir().unwrap();
    drop(Room::init(tmp.path()).unwrap());
    let mut client = Client::new(tmp.path());
    assert_eq!(
        value(&client.call("room_status", json!({}))),
        cli_json(tmp.path(), &["status", "--json"])
    );
    assert_eq!(value(&client.call("item_list", json!({}))), json!([]));
    assert_eq!(value(&client.call("disagreements", json!({}))), json!([]));
    fs::write(tmp.path().join("STOP"), []).unwrap();
    assert_eq!(
        value(&client.call("room_status", json!({})))["stopped"],
        true
    );
    let unknown = client.call("item_show", json!({"id":"missing"}));
    assert_eq!(unknown["result"]["isError"], true);
}

#[test]
fn the_mcp_server_cannot_write() {
    let tmp = tempfile::tempdir().unwrap();
    let dir = tmp.path().join("room");
    let mut room = Room::init(&dir).unwrap();
    let id = room
        .add_item(NewItem {
            title: "fixture".into(),
            repo: tmp.path().into(),
            base_commit: "a".repeat(40),
            after: vec![],
            check: CheckSpec {
                command: "false".into(),
                files: vec![],
                timeout_secs: 1,
                origin: CheckOrigin::Outside,
                wrong_artifacts: vec!["b".repeat(40)],
                written_by: "script:fixture".into(),
            },
        })
        .unwrap();
    room.record_frozen(
        &id,
        Frozen {
            check_hash: "c".repeat(64),
            red_on_base: true,
            red_on_wrong: vec![true],
        },
    )
    .unwrap();
    drop(room);
    let script = tmp.path().join("worker.sh");
    fs::write(&script, "#!/bin/sh\nexit 0\n").unwrap();
    fs::set_permissions(&script, fs::Permissions::from_mode(0o755)).unwrap();
    let mut clock = Process(
        command(&dir)
            .args(["clock", "run", "--worker"])
            .arg(format!("script:{}", script.display()))
            .args(["--daily-turns", "13"])
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::inherit())
            .spawn()
            .unwrap(),
    );
    let deadline = Instant::now() + Duration::from_secs(5);
    loop {
        assert!(
            clock.0.try_wait().unwrap().is_none(),
            "clock must stay alive"
        );
        if cli_json(&dir, &["status", "--json"])["daily_ceiling"] == 13 {
            break;
        }
        assert!(Instant::now() < deadline);
        thread::sleep(Duration::from_millis(20));
    }
    assert!(matches!(Room::open(&dir), Err(room::RoomError::Locked)));
    let snapshot =
        || ["room.sqlite3", "room.sqlite3-wal"].map(|name| fs::read(dir.join(name)).ok());
    let before = snapshot();
    let mut client = Client::new(&dir);
    for (tool, args, cli) in [
        ("room_status", json!({}), vec!["status", "--json"]),
        ("item_list", json!({}), vec!["item", "list", "--json"]),
        (
            "item_show",
            json!({"id":id.0}),
            vec!["item", "show", id.0.as_str(), "--json"],
        ),
        ("disagreements", json!({}), vec!["disagreements", "--json"]),
    ] {
        assert_eq!(value(&client.call(tool, args)), cli_json(&dir, &cli));
    }
    for tool in ["item_add", "item_erase", "stop", "resume", "clock_run"] {
        let reply = client.call(tool, json!({"id":id.0}));
        assert!(
            reply.get("error").is_some() || reply["result"]["isError"] == true,
            "{reply}"
        );
        assert_eq!(client.call(tool, json!({}))["error"]["code"], -32601);
    }
    for (tool, args) in [
        ("item_show", json!({})),
        ("item_show", json!({"id":12})),
        ("item_show", json!({"id":id.0,"erase":true})),
        ("room_status", json!({"stop":true})),
    ] {
        let reply = client.call(tool, args);
        assert_eq!(reply["error"]["code"], -32602, "{reply}");
    }
    assert_eq!(
        snapshot(),
        before,
        "MCP calls leave database and WAL bytes unchanged"
    );
    assert!(!dir.join("STOP").exists());
    fs::write(dir.join("STOP"), "").unwrap();
    assert!(clock.0.wait().unwrap().success());
}
