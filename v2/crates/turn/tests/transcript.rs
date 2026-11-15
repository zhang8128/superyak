//! Task 8: a worker's event stream to `Step`s.

mod common;

use std::process::Command;

use common::{Repo, git};
use room::{Step, Target, Tool};
use turn::Sandbox;
use turn::sandbox::MAX_LINE_BYTES;
use turn::transcript::{ClaudeParser, CodexParser, claude_steps, codex_steps};

/// A repository holding `a.txt`, `b.txt` and `src/a.txt`, and a sandbox of it.
fn sandbox() -> (Repo, Sandbox) {
    let repo = Repo::new(&[
        ("a.txt", "hello\n"),
        ("b.txt", "other\n"),
        ("src/a.txt", "source\n"),
    ]);
    let sb = Sandbox::create(
        &repo.path,
        &repo.base,
        &repo.scratch("sandbox"),
        "room/i1/1",
    )
    .unwrap();
    (repo, sb)
}

/// A fixture's lines, with the `/sandbox` the samples were captured in replaced by this sandbox.
fn fixture(name: &str, sb: &Sandbox) -> Vec<String> {
    let path = format!("{}/tests/data/{name}", env!("CARGO_MANIFEST_DIR"));
    let text = std::fs::read_to_string(path).unwrap();
    let dir = sb.dir.to_str().unwrap();
    text.lines().map(|l| l.replace("/sandbox", dir)).collect()
}

fn blob(repo: &Repo, path: &str) -> String {
    git(&repo.path, &["rev-parse", &format!("{}:{path}", repo.base)])
}

fn tracked(repo: &Repo, path: &str) -> Target {
    Target::TrackedFile {
        path: path.to_string(),
        blob: blob(repo, path),
    }
}

fn tools(steps: &[Step]) -> Vec<Tool> {
    steps.iter().map(|s| s.tool).collect()
}

fn targets(steps: &[Step]) -> Vec<Target> {
    steps.iter().map(|s| s.target.clone()).collect()
}

fn oks(steps: &[Step]) -> Vec<bool> {
    steps.iter().map(|s| s.ok).collect()
}

#[test]
fn a_read_of_a_tracked_file_is_a_tracked_step() {
    let (repo, sb) = sandbox();
    let steps = claude_steps(fixture("claude-read-src.jsonl", &sb).into_iter(), &sb);
    assert_eq!(
        steps,
        [Step {
            seq: 0,
            tool: Tool::Read,
            target: tracked(&repo, "src/a.txt"),
            ok: true,
            tokens_in: Some(3 + 100 + 1000),
            tokens_out: Some(20),
            named: Vec::new(),
            seen_ms: None,
            result_ms: None,
        }]
    );
}

#[test]
fn a_failed_tool_call_is_recorded_as_not_ok() {
    let (_repo, sb) = sandbox();
    // The real sample with its ids told apart: the Read of a.txt, then `ls` and the Read of missing.txt, whose
    // results came back in the other order.
    let claude = claude_steps(fixture("claude-stream-ids.jsonl", &sb).into_iter(), &sb);
    assert_eq!(oks(&claude), [true, true, false]);
    let codex = codex_steps(fixture("codex-json-sample.jsonl", &sb).into_iter(), &sb);
    assert_eq!(oks(&codex), [true, true, false]);
    // A call whose result never came (the run was ended) is not ok either.
    let mut cut = fixture("claude-read-src.jsonl", &sb);
    cut.truncate(2);
    assert_eq!(oks(&claude_steps(cut.into_iter(), &sb)), [false]);
    let mut cut = fixture("codex-json-sample.jsonl", &sb);
    cut.truncate(4); // up to the start of `cat a.txt`
    assert_eq!(oks(&codex_steps(cut.into_iter(), &sb)), [false]);
}

#[test]
fn anything_outside_the_repository_is_outside() {
    let (_repo, sb) = sandbox();
    let steps = claude_steps(fixture("claude-outside.jsonl", &sb).into_iter(), &sb);
    // /etc/hosts, a web fetch, a path that climbs out of the sandbox, an untracked file, a directory, a shell
    // command on /etc/hosts, a web search, and a relative path that climbs out.
    assert_eq!(
        tools(&steps),
        [
            Tool::Read,
            Tool::Read,
            Tool::Read,
            Tool::Read,
            Tool::Search,
            Tool::Shell,
            Tool::Search,
            Tool::Read
        ]
    );
    assert!(
        steps.iter().all(|s| s.target == Target::Outside),
        "{steps:?}"
    );
    assert_eq!(oks(&steps), [true; 8]);
    assert_eq!(
        steps.iter().map(|s| s.seq).collect::<Vec<_>>(),
        (0..8).collect::<Vec<_>>()
    );
}

#[test]
fn no_text_from_the_stream_survives() {
    let (repo, sb) = sandbox();
    let marker = "MARKER-9f3a";
    let claude = claude_steps(fixture("claude-marker.jsonl", &sb).into_iter(), &sb);
    let codex = codex_steps(fixture("codex-marker.jsonl", &sb).into_iter(), &sb);
    assert_eq!(claude.len(), 4, "{claude:?}");
    assert_eq!(codex.len(), 5, "{codex:?}");
    for step in claude.iter().chain(&codex) {
        let shown = format!("{step:?}");
        assert!(!shown.contains(marker), "{shown}");
        assert!(!shown.contains("9f3a"), "{shown}");
    }
    // What is kept is the shape: tools, tracked files and whether each call worked.
    assert_eq!(
        tools(&claude),
        [Tool::Shell, Tool::Read, Tool::Search, Tool::Other]
    );
    assert_eq!(oks(&claude), [true, true, true, false]);
    assert_eq!(claude[2].target, tracked(&repo, "src/a.txt"));
    assert_eq!(
        tools(&codex),
        [
            Tool::Shell,
            Tool::Write,
            Tool::Edit,
            Tool::Search,
            Tool::Other
        ]
    );
    assert_eq!(codex[2].target, tracked(&repo, "src/a.txt"));
}

#[test]
fn the_real_samples_give_the_steps_they_show() {
    let (repo, sb) = sandbox();
    // The lead's samples as captured. Their tool ids were all scrubbed to one value, so which result answers
    // which call is not in the Claude sample: only the calls themselves and their cost are checked here.
    let claude = claude_steps(fixture("claude-stream-sample.jsonl", &sb).into_iter(), &sb);
    assert_eq!(tools(&claude), [Tool::Read, Tool::Shell, Tool::Read]);
    assert_eq!(
        targets(&claude),
        [tracked(&repo, "a.txt"), Target::Outside, Target::Outside]
    );
    // One message made all three calls; its cost is counted once, on the first.
    assert_eq!(
        (claude[0].tokens_in, claude[0].tokens_out),
        (Some(2 + 6903 + 11370), Some(16))
    );
    assert_eq!((claude[1].tokens_in, claude[2].tokens_in), (None, None));
    let codex = codex_steps(fixture("codex-json-sample.jsonl", &sb).into_iter(), &sb);
    assert_eq!(tools(&codex), [Tool::Shell, Tool::Shell, Tool::Shell]);
    assert_eq!(
        targets(&codex),
        [tracked(&repo, "a.txt"), Target::Outside, Target::Outside]
    );
    assert_eq!(oks(&codex), [true, true, false]);
    assert!(
        codex
            .iter()
            .all(|s| s.tokens_in.is_none() && s.tokens_out.is_none())
    );
}

/// One Bash call per command, each with its result.
fn bash_stream(commands: &[&str]) -> Vec<String> {
    let mut lines = Vec::new();
    for (i, command) in commands.iter().enumerate() {
        let input = serde_json::json!({ "command": command });
        lines.push(
            serde_json::json!({"type": "assistant", "message": {"id": format!("msg_{i}"), "content": [
                {"type": "tool_use", "id": format!("toolu_{i}"), "name": "Bash", "input": input}]}})
            .to_string(),
        );
        lines.push(
            serde_json::json!({"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": format!("toolu_{i}"), "content": "x"}]}})
            .to_string(),
        );
    }
    lines
}

#[test]
fn a_shell_step_names_a_tracked_file_only_when_it_names_exactly_one() {
    let (repo, sb) = sandbox();
    let commands = [
        "cat src/a.txt",
        "cat \"src/a.txt\"",
        "grep -n hello a.txt | head -1",
        "bash -c 'cat src/a.txt'",
        "cat a.txt b.txt",
        "cat a.txt a.txt",
        "ls",
        "cat untracked.txt",
        "cat ../repo/a.txt",
        "echo src/a.txt > /dev/null && cat b.txt",
    ];
    // Paths that look like tracked ones and are not: one climbs out of the sandbox and names a.txt there, one
    // only begins with the sandbox's own path.
    let climbs_out = "cat ../a.txt".to_string();
    let next_door = format!("cat {}a.txt", sb.dir.display());
    let commands: Vec<&str> = commands
        .iter()
        .copied()
        .chain([climbs_out.as_str(), next_door.as_str()])
        .collect();
    let steps = claude_steps(bash_stream(&commands).into_iter(), &sb);
    let a = tracked(&repo, "a.txt");
    let src = tracked(&repo, "src/a.txt");
    assert_eq!(
        targets(&steps),
        [
            src.clone(),
            src.clone(),
            a.clone(),
            src,
            Target::Outside,
            a,
            Target::Outside,
            Target::Outside,
            Target::Outside,
            Target::Outside,
            Target::Outside,
            Target::Outside,
        ]
    );
    assert!(steps.iter().all(|s| s.tool == Tool::Shell));
}

#[test]
fn a_codex_item_is_settled_once_and_by_its_exit() {
    let (repo, sb) = sandbox();
    let command = |id: &str, status: &str, exit: Option<i64>| {
        serde_json::json!({"type": "item.completed", "item": {"id": id, "type": "command_execution",
            "command": "cat a.txt", "status": status, "exit_code": exit, "aggregated_output": ""}})
        .to_string()
    };
    let lines = vec![
        command("item_1", "completed", Some(0)),
        // The same item again, and an item that says it completed with a failing exit.
        command("item_1", "completed", Some(0)),
        command("item_2", "completed", Some(2)),
        command("item_3", "declined", None),
    ];
    let steps = codex_steps(lines.into_iter(), &sb);
    assert_eq!(oks(&steps), [true, false, false]);
    assert_eq!(steps[0].target, tracked(&repo, "a.txt"));
}

#[test]
fn each_message_is_counted_once() {
    let (_repo, sb) = sandbox();
    let usage =
        serde_json::json!({"input_tokens": 10, "cache_read_input_tokens": 5, "output_tokens": 3});
    let call = |id: &str, msg: &str| {
        serde_json::json!({"type": "assistant", "message": {"id": msg, "usage": usage, "content": [
            {"type": "tool_use", "id": id, "name": "Read", "input": {"file_path": "a.txt"}}]}})
        .to_string()
    };
    let two_in_one = serde_json::json!({"type": "assistant", "message": {"id": "msg_c", "usage": usage, "content": [
        {"type": "tool_use", "id": "t3", "name": "Read", "input": {"file_path": "a.txt"}},
        {"type": "tool_use", "id": "t4", "name": "Read", "input": {"file_path": "b.txt"}}]}})
    .to_string();
    let lines = vec![
        call("t1", "msg_a"),
        call("t2", "msg_a"),
        two_in_one,
        call("t5", "msg_d"),
    ];
    let steps = claude_steps(lines.into_iter(), &sb);
    let cost: Vec<_> = steps.iter().map(|s| (s.tokens_in, s.tokens_out)).collect();
    assert_eq!(
        cost,
        [
            (Some(15), Some(3)),
            (None, None),
            (Some(15), Some(3)),
            (None, None),
            (Some(15), Some(3))
        ]
    );
}

#[test]
fn lines_that_are_not_json_are_passed_over() {
    let (repo, sb) = sandbox();
    let mut lines = vec![
        "not json".to_string(),
        "{\"type\":".to_string(),
        String::new(),
        "[1,2]".to_string(),
    ];
    lines.extend(fixture("claude-read-src.jsonl", &sb));
    let steps = claude_steps(lines.into_iter(), &sb);
    assert_eq!(targets(&steps), [tracked(&repo, "src/a.txt")]);
    let steps = codex_steps(["oops".to_string(), "null".to_string()].into_iter(), &sb);
    assert!(steps.is_empty());
}

#[test]
fn odd_lines_are_passed_over_without_a_panic() {
    let (_repo, sb) = sandbox();
    let deep = format!("{}{}", "[".repeat(10_000), "]".repeat(10_000));
    let claude = [
        r#"{"type":"assistant","message":{"content":"just text"}}"#.to_string(),
        r#"{"type":"assistant","message":{"content":[{"type":"tool_use","id":5,"name":7,"input":"x"}]}}"#.to_string(),
        r#"{"type":"assistant","message":{"id":["m"],"usage":{"input_tokens":1e30,"output_tokens":-4},"content":[{"type":"tool_use","id":"t1","name":"Read","input":{"file_path":"\ud800"}}]}}"#.to_string(),
        r#"{"type":"assistant","message":{"usage":"x","content":[{"type":"tool_use","id":"t2","name":"Read","input":{"file_path":["a.txt"]}}]}}"#.to_string(),
        r#"{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":["t2"],"is_error":"yes"}]}}"#.to_string(),
        r#"{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t2","is_error":"yes"}]}}"#.to_string(),
        r#"{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"never-called"}]}}"#.to_string(),
        r#"{"type":"user","message":null,"tool_":1}"#.to_string(),
        format!(r#"{{"type":"assistant","tool_":{deep}}}"#),
        r#"{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Bash","input":{"command":"cat 'unterminated"}}]}}"#
            .to_string(),
    ];
    let steps = claude_steps(claude.into_iter(), &sb);
    // A call with no name, t2 (a path that is not a string, then a result whose is_error is not a boolean), and
    // the unterminated command; the call with the lone surrogate is not JSON at all.
    assert_eq!(
        tools(&steps),
        [Tool::Other, Tool::Read, Tool::Shell],
        "{steps:?}"
    );
    assert!(steps.iter().all(|s| s.target == Target::Outside));
    assert_eq!(oks(&steps), [false, true, false]);
    let codex = [
        r#"{"type":"item.completed","item":"x"}"#,
        r#"{"type":"item.started","item":{"id":"i1","type":"file_change","changes":"x"}}"#,
        r#"{"type":"item.completed","item":{"id":"i2","type":"command_execution","command":5,"exit_code":"0","status":"completed"}}"#,
        r#"{"type":"item.completed","item":{"id":"i3","type":"file_change","changes":[{"kind":7,"path":null},"x"]}}"#,
        r#"{"type":"item.","item":{"type":"web_search"}}"#,
        r#"{"type":7,"item":{}}"#,
    ];
    let steps = codex_steps(codex.iter().map(|s| s.to_string()), &sb);
    assert!(
        steps.iter().all(|s| s.target == Target::Outside),
        "{steps:?}"
    );
    assert_eq!(
        tools(&steps),
        [
            Tool::Edit,
            Tool::Shell,
            Tool::Edit,
            Tool::Edit,
            Tool::Search
        ]
    );
}

#[test]
fn parsers_retain_at_most_one_hundred_thousand_steps_and_keep_counting() {
    let (_repo, sb) = sandbox();
    let mut claude = ClaudeParser::new(&sb);
    let mut codex = CodexParser::new(&sb);
    for n in 0..100_005 {
        claude.line(&format!(r#"{{"type":"assistant","message":{{"id":"m{n}","content":[{{"type":"tool_use","id":"t{n}","name":"Read","input":{{"file_path":"a.txt"}}}}]}}}}"#));
        codex.line(&format!(r#"{{"type":"item.completed","item":{{"id":"i{n}","type":"command_execution","command":"cat a.txt","status":"completed","exit_code":0}}}}"#));
    }
    for n in [0, 99_999] {
        claude.line(&format!(r#"{{"type":"user","message":{{"content":[{{"type":"tool_result","tool_use_id":"t{n}"}}]}}}}"#));
    }
    codex.line(r#"{"type":"item.started","item":{"id":"last","type":"command_execution","command":"cat a.txt"}}"#);
    codex.line(r#"{"type":"item.completed","item":{"id":"last","type":"command_execution","command":"cat a.txt","status":"completed","exit_code":0}}"#);
    codex.line(r#"{"type":"item.completed","item":{"id":"i0","type":"command_execution","status":"completed","exit_code":0}}"#);
    assert_eq!(claude.total_steps(), 100_005);
    assert_eq!(codex.total_steps(), 100_006);
    let claude = claude.finish();
    let codex = codex.finish();
    assert_eq!(claude.len(), 100_000);
    assert_eq!(codex.len(), 100_000);
    assert!(claude[0].ok && claude[99_999].ok);
    assert!(codex.iter().all(|step| step.ok));
    assert_eq!(claude.last().unwrap().seq, 99_999);
    assert_eq!(codex.last().unwrap().seq, 99_999);
}

// --- Memory --------------------------------------------------------------------------------------------------

const MB: u64 = 1 << 20;

/// Runs `rss_probe` in a child process over a generated stream of about `bytes` and returns its peak memory.
fn peak_of_a_parse(bytes: u64) -> u64 {
    #[cfg(target_os = "macos")]
    let mut command = {
        let mut command = Command::new("/usr/bin/time");
        command.arg("-l").arg(std::env::current_exe().unwrap());
        command
    };
    #[cfg(not(target_os = "macos"))]
    let mut command = Command::new(std::env::current_exe().unwrap());
    let out = command
        .args([
            "rss_probe",
            "--exact",
            "--ignored",
            "--nocapture",
            "--test-threads=1",
        ])
        .env("TURN_RSS_BYTES", bytes.to_string())
        .output()
        .unwrap();
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(
        out.status.success(),
        "the probe failed: {stdout}{}",
        String::from_utf8_lossy(&out.stderr)
    );
    #[cfg(target_os = "macos")]
    return String::from_utf8_lossy(&out.stderr)
        .lines()
        .find(|line| line.contains("maximum resident set size"))
        .and_then(|line| line.split_whitespace().next()?.parse().ok())
        .unwrap_or_else(|| {
            panic!(
                "time gave no peak: {}",
                String::from_utf8_lossy(&out.stderr)
            )
        });
    #[cfg(not(target_os = "macos"))]
    stdout
        .lines()
        // The harness may print the test's name on the same line.
        .find_map(|l| l.split("PEAK_BYTES=").nth(1))
        .and_then(|n| n.split_whitespace().next()?.parse().ok())
        .unwrap_or_else(|| panic!("the probe gave no peak: {stdout}"))
}

#[test]
fn a_stream_of_two_hundred_megabytes_is_read_in_bounded_memory() {
    let small = peak_of_a_parse(MB);
    let big = peak_of_a_parse(200 * MB);
    let growth = big.saturating_sub(small);
    assert!(
        growth < 64 * MB,
        "peak grew by {} MB ({small} to {big} bytes)",
        growth / MB
    );
}

#[test]
#[ignore = "run in a child process by a_stream_of_two_hundred_megabytes_is_read_in_bounded_memory"]
fn rss_probe() {
    let Some(bytes) = std::env::var("TURN_RSS_BYTES")
        .ok()
        .and_then(|b| b.parse::<u64>().ok())
    else {
        return;
    };
    let (_repo, sb) = sandbox();
    let generator = r#"
        my $bytes = shift;
        my $made = 0;
        $| = 1;
        if ($bytes >= 64*1024*1024) {
            my $chunk = "x" x (64*1024);
            for (1..1024) { print $chunk; }
            print "\n";
            $made += 64*1024*1024 + 1;
        }
        my $filler = "x" x (16*1024);
        my $n = 0;
        while ($made < $bytes) {
            my $call = '{"type":"assistant","message":{"id":"m'.$n.'","content":[{"type":"tool_use","id":"t'.$n.'","name":"Read","input":{"file_path":"src/a.txt"}}]}}';
            my $result = '{"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"t'.$n.'","content":"'.$filler.'"}]}}';
            print $call, "\n", $result, "\n";
            $made += length($call) + length($result) + 2;
            $n++;
        }
        print "STREAM_PAIRS=$n\n";
    "#;
    let mut parser = ClaudeParser::new(&sb);
    let mut pairs = None;
    let mut longest = 0;
    let status = sb
        .run(
            "perl",
            &["-e".into(), generator.into(), bytes.to_string()],
            "",
            60,
            &mut |line| {
                longest = longest.max(line.len());
                if let Some(n) = line.strip_prefix("STREAM_PAIRS=") {
                    pairs = Some(n.parse::<usize>().unwrap());
                }
                parser.line(line);
            },
        )
        .unwrap();
    assert_eq!(status.exit_code, 0);
    assert!(!status.timed_out);
    assert_eq!(parser.finish().len(), pairs.unwrap());
    if bytes >= 64 * MB {
        assert_eq!(longest, MAX_LINE_BYTES);
    }
    #[cfg(not(target_os = "macos"))]
    println!("PEAK_BYTES={}", own_peak());
}

/// This process's peak memory, from the kernel's own count.
#[cfg(not(target_os = "macos"))]
fn own_peak() -> u64 {
    if let Ok(status) = std::fs::read_to_string("/proc/self/status") {
        let kb = status
            .lines()
            .find_map(|l| l.strip_prefix("VmHWM:"))
            .and_then(|v| v.trim().trim_end_matches("kB").trim().parse::<u64>().ok())
            .expect("VmHWM in /proc/self/status");
        return kb * 1024;
    }
    panic!("no kernel peak memory counter");
}
