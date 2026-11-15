//! The cases under "How we know part 0 is done" (the stage 2 experiment, part 0), each for a stand-in of each
//! worker program, run by the real clock from the command line.
//!
//! A stand-in is a script named `claude` or `codex`, first on the clock's search path. It prints a stream
//! captured from that program and then does what the case says: fixes the item, leaves it, waits past the
//! turn's limit, ends itself. No model is run. What each test asks is what the turn's record says afterwards.
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::Output;
use std::thread;
use std::time::{Duration, Instant};

use assert_cmd::Command;
use room::limits::MAX_ATTEMPTS;
use room::{Change, ChangedFile, Ended, ItemId, Measured, Room, Tool, TurnView};

/// One worker program, and what is known of the stream captured from it.
struct Program {
    name: &'static str,
    stream: &'static str,
    /// A stream of the same program whose every text holds `MARKER`.
    marked: &'static str,
    /// What marks the line that is its closing total.
    closing: &'static str,
    /// The closing total's parts: fresh input, written to the program's memory, read from it, output.
    parts: (u64, u64, u64, u64),
    /// The words by which a line is a tool's call or its result.
    tool_words: &'static [&'static str],
    /// The captured command that names no file: its id and its text, and those of a copy of it that names
    /// two tracked files.
    names_none: (&'static str, &'static str),
    names_two: (&'static str, &'static str),
}

const PROGRAMS: [Program; 2] = [
    Program {
        name: "claude",
        // Its messages arrive more than once, as the program sends them; the closing total counts each once.
        stream: "claude-stream-ids.jsonl",
        marked: "claude-marker.jsonl",
        closing: "\"type\":\"result\"",
        parts: (4, 7_287, 29_643, 286),
        tool_words: &["\"tool_use\"", "\"tool_result\""],
        names_none: ("toolu_ls", "\"command\":\"ls\""),
        names_two: ("toolu_two", "\"command\":\"cat check.sh a.txt\""),
    },
    Program {
        name: "codex",
        stream: "codex-json-sample.jsonl",
        marked: "codex-marker.jsonl",
        closing: "\"type\":\"turn.completed\"",
        parts: (11_113, 0, 35_328, 100),
        tool_words: &["command_execution"],
        names_none: ("item_2", "/bin/zsh -lc ls"),
        names_two: ("item_9", "/bin/zsh -lc 'cat check.sh a.txt'"),
    },
];

/// The word the marked streams carry in every text of theirs.
const MARKER: &str = "MARKER-9f3a";

/// The lines of a stream captured from a program.
fn captured(name: &str) -> Vec<String> {
    let path = format!("{}/../turn/tests/data/{name}", env!("CARGO_MANIFEST_DIR"));
    fs::read_to_string(path)
        .unwrap()
        .lines()
        .map(str::to_owned)
        .collect()
}

impl Program {
    fn total(&self) -> u64 {
        self.parts.0 + self.parts.1 + self.parts.2 + self.parts.3
    }

    /// Its captured stream, whole. The closing total is its last line, and only that.
    fn whole(&self) -> Vec<String> {
        let lines = captured(self.stream);
        let closing: Vec<usize> = (0..lines.len())
            .filter(|at| lines[*at].contains(self.closing))
            .collect();
        assert_eq!(closing, [lines.len() - 1], "{}", self.stream);
        lines
    }

    /// All but the calls of tools and their results.
    fn no_tool_call(&self) -> Vec<String> {
        let whole = self.whole();
        let kept: Vec<String> = whole
            .iter()
            .filter(|line| !self.tool_words.iter().any(|word| line.contains(word)))
            .cloned()
            .collect();
        // The control: there were such lines, and the closing total is not one of them.
        assert!(kept.len() < whole.len() && kept.last() == whole.last());
        kept
    }

    /// All but the closing total: what a program has printed when it is ended before its end.
    fn no_closing_total(&self) -> Vec<String> {
        let mut lines = self.whole();
        lines.pop();
        lines
    }

    /// The whole stream, and before its closing total one more command: a copy of the captured one that
    /// names no file, made to name two tracked files, the later in the alphabet first.
    fn naming_two_files(&self) -> Vec<String> {
        let mut lines = self.whole();
        let closing = lines.pop().unwrap();
        let copies: Vec<String> = lines
            .iter()
            .filter(|line| line.contains(self.names_none.0))
            .map(|line| {
                line.replace(self.names_none.0, self.names_two.0)
                    .replace(self.names_none.1, self.names_two.1)
            })
            .collect();
        // The call and its result, and the call now holds the other command.
        assert_eq!(copies.len(), 2, "{}", self.stream);
        assert!(copies.iter().any(|line| line.contains(self.names_two.1)));
        lines.extend(copies);
        lines.push(closing);
        lines
    }
}

fn yak(room: &Path) -> Command {
    let mut cmd = Command::new(assert_cmd::cargo::cargo_bin!("yak"));
    cmd.arg("--room").arg(room).env_remove("YAK_JAIL_READ");
    for name in ["YAK_JAIL", "YAK_SUPERVISION"] {
        if let Some(value) = std::env::var_os(name) {
            cmd.env(name, value);
        } else {
            cmd.env_remove(name);
        }
    }
    cmd.timeout(Duration::from_secs(120));
    cmd
}

fn git(repo: &Path, args: &[&str]) -> String {
    let out = turn::sandbox::safe_git()
        .arg("-C")
        .arg(repo)
        .args([
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "-c",
            "commit.gpgsign=false",
        ])
        .args(args)
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "{}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8(out.stdout).unwrap().trim().to_owned()
}

/// A room with one item, "make the answer green", in a repository that also tracks the file the captured
/// streams read; and a directory for the stand-in.
struct Case {
    /// Kept, and its place said, if what the case started could not be ended when the case is dropped.
    tmp: Option<tempfile::TempDir>,
    room: PathBuf,
    bin: PathBuf,
    id: String,
}

/// Nothing a case started outlives it, whatever became of its test. The clock a test runs is ended by the
/// test's own limit on it, and that ends the clock alone: its worker is in a process group of its own. So a
/// run that a clock left is ended here from the record the room keeps of it, as a clock that starts again
/// would end it, before the directory that holds the record is removed.
impl Drop for Case {
    fn drop(&mut self) {
        let left = end_what_a_room_left(&self.room);
        if !left.is_empty()
            && let Some(tmp) = self.tmp.take()
        {
            eprintln!(
                "a case could not be cleaned, and is kept in {}: {left:?}",
                tmp.keep().display()
            );
        }
    }
}

/// Stops the room at `room` and ends every run it has a record of, each only if it is still the process its
/// record describes. Says everything that could not be stopped, looked at or ended: a place that cannot be
/// listed is not taken for a place with nothing in it. A room with no turns' directory has had no run.
fn end_what_a_room_left(room: &Path) -> Vec<String> {
    let mut left = Vec::new();
    if let Err(e) = fs::write(room.join("STOP"), []) {
        left.push(format!("{}: could not be stopped: {e}", room.display()));
    }
    let turns = room.join("turns");
    let entries = match fs::read_dir(&turns) {
        Ok(entries) => entries,
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => return left,
        Err(e) => {
            left.push(format!("{}: could not be listed: {e}", turns.display()));
            return left;
        }
    };
    for entry in entries {
        match entry {
            Err(e) => left.push(format!(
                "{}: an entry could not be read: {e}",
                turns.display()
            )),
            Ok(entry) => {
                let path = entry.path();
                if path.extension().is_some_and(|ext| ext == "pid")
                    && let Err(e) = turn::Sandbox::end_stale(&path)
                {
                    left.push(format!("{}: {e}", path.display()));
                }
            }
        }
    }
    left
}

impl Case {
    fn new() -> Case {
        Case::with_check("grep -qx green answer\n")
    }

    /// A case whose item is judged by this check, a shell script's text.
    fn with_check(check: &str) -> Case {
        let tmp = tempfile::tempdir().unwrap();
        let (room, repo, bin) = (
            tmp.path().join("room"),
            tmp.path().join("repo"),
            tmp.path().join("bin"),
        );
        fs::create_dir(&repo).unwrap();
        fs::create_dir(&bin).unwrap();
        git(&repo, &["init", "-q", "-b", "main"]);
        fs::write(repo.join("a.txt"), "hello\n").unwrap();
        fs::write(repo.join("answer"), "red\n").unwrap();
        fs::write(repo.join("check.sh"), check).unwrap();
        git(&repo, &["add", "."]);
        git(&repo, &["commit", "-qm", "base"]);
        let base = git(&repo, &["rev-parse", "HEAD"]);
        let made = yak(&room).arg("init").output().unwrap();
        assert!(made.status.success());
        let added = yak(&room)
            .args(["item", "add", "--title", "Make answer green", "--repo"])
            .arg(&repo)
            .args([
                "--base",
                "main",
                "--check",
                "sh check.sh",
                "--file",
                "check.sh",
                "--wrong",
                &base,
                "--origin",
                "outside",
                "--by",
                "person:test",
            ])
            .output()
            .unwrap();
        assert!(
            added.status.success(),
            "{}",
            String::from_utf8_lossy(&added.stderr)
        );
        let id = String::from_utf8(added.stdout).unwrap().trim().to_owned();
        Case {
            tmp: Some(tmp),
            room,
            bin,
            id,
        }
    }

    /// The case's own directory, where its room, its repository and its stand-in are.
    fn dir(&self) -> &Path {
        self.tmp.as_ref().expect("the case's directory").path()
    }

    /// Puts the stand-in for `program` first on the search path the clock will be given: it takes its prompt,
    /// prints `lines` as if from its sandbox, and then runs `then`.
    fn stand_in(&self, program: &Program, lines: Vec<String>, then: &str) {
        let stream = self.dir().join("stream.jsonl");
        fs::write(&stream, lines.join("\n") + "\n").unwrap();
        let body = format!(
            "#!/bin/sh\ncat > /dev/null\nsed \"s#/sandbox#$PWD#g\" '{}'\n{then}\n",
            stream.display()
        );
        let path = self.bin.join(program.name);
        fs::write(&path, body).unwrap();
        fs::set_permissions(&path, fs::Permissions::from_mode(0o755)).unwrap();
    }

    /// The search path the clock is given: the stand-in's directory first.
    fn path(&self) -> String {
        format!(
            "{}:{}",
            self.bin.display(),
            std::env::var("PATH").unwrap_or_default()
        )
    }

    /// The clock, once through, with one worker of `program` and the stand-in's directory first on its path.
    /// It is ended by the test after two minutes if it has not ended by itself, and that ends the clock alone.
    fn clock(&self, program: &Program, more: &[&str]) -> Output {
        yak(&self.room)
            .args(["clock", "run", "--once-through", "--worker"])
            .arg(format!("{}:test", program.name))
            .args(more)
            .env("PATH", self.path())
            .output()
            .unwrap()
    }

    /// Every turn at the item, with its record.
    fn turns(&self) -> Vec<TurnView> {
        Room::open_read_only(&self.room)
            .unwrap()
            .turns(&ItemId(self.id.clone()))
            .unwrap()
    }

    /// The one turn there was, and its record. `out` is what the clock printed, said when there is not one.
    fn the_turn(&self, program: &Program, out: &Output) -> (TurnView, Measured) {
        let mut turns = self.turns();
        assert_eq!(
            turns.len(),
            1,
            "{}: {} {}",
            program.name,
            String::from_utf8_lossy(&out.stdout),
            String::from_utf8_lossy(&out.stderr)
        );
        let turn = turns.remove(0);
        let measured = turn
            .measured
            .clone()
            .unwrap_or_else(|| panic!("{}: the turn has no record", program.name));
        (turn, measured)
    }
}

/// A turn's parts add up to its active time, and it has a sandbox's time and a worker's.
fn whole(program: &Program, m: &Measured) {
    assert_eq!(
        m.active_ms,
        m.sandbox_ms + m.worker_ms + m.seal_ms + m.bring_ms + m.check_ms.unwrap_or(0),
        "{}: {m:?}",
        program.name
    );
    assert!(
        m.sandbox_ms > 0 && m.worker_ms > 0,
        "{}: {m:?}",
        program.name
    );
}

/// The token cost is the program's own closing total, in its parts: fresh input, what was written to the
/// program's memory and what was read from it are three numbers, beside the output.
fn closing_total(program: &Program, m: &Measured) {
    assert!(m.tokens.complete, "{}: {m:?}", program.name);
    let (fresh, written, read, output) = program.parts;
    assert_eq!(
        (
            m.tokens.fresh_in,
            m.tokens.cache_write,
            m.tokens.cache_read,
            m.tokens.output
        ),
        (Some(fresh), Some(written), Some(read), Some(output)),
        "{}: {m:?}",
        program.name
    );
    assert_eq!(
        m.tokens.total(),
        Some(program.total()),
        "{}: {m:?}",
        program.name
    );
}

/// No closing total came, and none is made up: the cost is marked as not whole, and has no total.
fn no_total(program: &Program, m: &Measured) {
    assert!(!m.tokens.complete, "{}: {m:?}", program.name);
    assert_eq!(m.tokens.total(), None, "{}: {m:?}", program.name);
}

/// One turn only: the clock is given a day's ceiling of one.
const ONE_TURN: [&str; 2] = ["--daily-turns", "1"];

/// One turn, ended after five seconds. A stand-in prints its stream at once and then waits; five seconds is
/// for a busy machine to have handed all of that to the room before the limit comes.
const AT_ITS_LIMIT: [&str; 4] = ["--daily-turns", "1", "--turn-secs", "5"];

#[test]
fn a_turn_that_ends_normally_has_its_programs_closing_total_and_what_it_changed() {
    for program in &PROGRAMS {
        let case = Case::new();
        case.stand_in(program, program.whole(), "echo green > answer");
        let out = case.clock(program, &ONE_TURN);
        let (turn, m) = case.the_turn(program, &out);
        assert_eq!(turn.passed, Some(true), "{}", program.name);
        assert_eq!(turn.worker, format!("{}:test", program.name));
        assert_eq!(
            (m.ended, m.exit_code),
            (Ended::Exited, Some(0)),
            "{}",
            program.name
        );
        closing_total(program, &m);
        whole(program, &m);
        // The room committed for the worker, which is timed apart from the worker; and the check ran.
        assert!(
            m.seal_ms > 0 && m.check_ms.is_some(),
            "{}: {m:?}",
            program.name
        );
        // Its steps are kept, and one of them names the tracked file its stream read.
        assert!(
            turn.steps > 0 && turn.steps_with_a_name > 0 && m.steps_seen > 0,
            "{}: {turn:?}",
            program.name
        );
        // What it changed is taken from the difference between its base and its commit: the stream shows no
        // step that wrote the answer, which a shell command did.
        assert_eq!(
            turn.changes,
            [ChangedFile {
                path: "answer".to_string(),
                change: Change::Changed
            }],
            "{}",
            program.name
        );
        assert_eq!(m.unknown_changes, 0, "{}", program.name);
    }
}

#[test]
fn a_turn_with_no_tool_call_has_a_record_with_its_cost() {
    for program in &PROGRAMS {
        let case = Case::new();
        case.stand_in(program, program.no_tool_call(), "echo green > answer");
        let out = case.clock(program, &ONE_TURN);
        let (turn, m) = case.the_turn(program, &out);
        assert_eq!(turn.passed, Some(true), "{}", program.name);
        assert_eq!((turn.steps, m.steps_seen), (0, 0), "{}", program.name);
        closing_total(program, &m);
        whole(program, &m);
    }
}

#[test]
fn a_turn_that_fails_its_check_and_one_that_hands_in_nothing_each_have_a_record() {
    for program in &PROGRAMS {
        // A wrong answer: handed in, and judged.
        let case = Case::new();
        case.stand_in(program, program.whole(), "echo blue > answer");
        let out = case.clock(program, &ONE_TURN);
        let (turn, m) = case.the_turn(program, &out);
        assert_eq!(turn.passed, Some(false), "{}", program.name);
        assert_eq!(m.ended, Ended::Exited, "{}", program.name);
        assert!(m.check_ms.is_some(), "{}: {m:?}", program.name);
        closing_total(program, &m);
        whole(program, &m);
        // Nothing changed: nothing of the worker's is handed in.
        let case = Case::new();
        case.stand_in(program, program.whole(), ":");
        let out = case.clock(program, &ONE_TURN);
        let (turn, m) = case.the_turn(program, &out);
        assert_ne!(turn.passed, Some(true), "{}", program.name);
        assert!(turn.changes.is_empty(), "{}: {turn:?}", program.name);
        assert_eq!(m.ended, Ended::Exited, "{}", program.name);
        closing_total(program, &m);
        whole(program, &m);
    }
}

#[test]
fn a_turn_ended_at_its_limit_has_a_record_and_a_cost_as_whole_as_its_program_left_it() {
    for program in &PROGRAMS {
        // Ended before its closing total, as a program is that was still at work.
        let case = Case::new();
        case.stand_in(program, program.no_closing_total(), "sleep 600");
        let out = case.clock(program, &AT_ITS_LIMIT);
        let (turn, m) = case.the_turn(program, &out);
        assert_eq!(m.ended, Ended::TimedOut, "{}: {m:?}", program.name);
        no_total(program, &m);
        whole(program, &m);
        assert!(m.worker_ms >= 5000, "{}: {m:?}", program.name);
        // What it did before it was ended is kept.
        assert!(
            turn.steps > 0 && m.steps_seen > 0,
            "{}: {turn:?}",
            program.name
        );
        // Ended after its closing total had come: the cost is whole, because the program said so.
        let case = Case::new();
        case.stand_in(program, program.whole(), "sleep 600");
        let out = case.clock(program, &AT_ITS_LIMIT);
        let (_, m) = case.the_turn(program, &out);
        assert_eq!(m.ended, Ended::TimedOut, "{}: {m:?}", program.name);
        closing_total(program, &m);
        whole(program, &m);
    }
}

#[test]
fn a_turn_whose_program_crashes_has_a_record() {
    for program in &PROGRAMS {
        let case = Case::new();
        case.stand_in(program, program.no_closing_total(), "kill -KILL $$");
        let out = case.clock(program, &ONE_TURN);
        let (turn, m) = case.the_turn(program, &out);
        // Ended by a signal that the room did not send: the record says so, and keeps the code a shell gives
        // for it (128 and the signal's number).
        assert_eq!(
            (m.ended, m.exit_code),
            (Ended::Signalled, Some(128 + 9)),
            "{}: {m:?}",
            program.name
        );
        no_total(program, &m);
        whole(program, &m);
        assert!(turn.steps > 0, "{}: {turn:?}", program.name);
    }
}

#[test]
fn a_turn_that_is_killed_has_a_record() {
    for program in &PROGRAMS {
        let case = Case::new();
        // The stand-in says when it is running, and the room is stopped then: not before its program began.
        let running = case.dir().join("running");
        case.stand_in(
            program,
            program.no_closing_total(),
            &format!(": > '{}'\nsleep 600", running.display()),
        );
        let stop = case.room.join("STOP");
        let stopper = thread::spawn(move || {
            let deadline = Instant::now() + Duration::from_secs(60);
            while !running.exists() && Instant::now() < deadline {
                thread::sleep(Duration::from_millis(50));
            }
            let seen = running.exists();
            // Stopped whether or not the program was seen, so that the clock does not wait out its worker.
            fs::write(stop, []).unwrap();
            seen
        });
        let out = case.clock(program, &ONE_TURN);
        assert!(
            stopper.join().unwrap(),
            "{}: its program was never seen running",
            program.name
        );
        let (turn, m) = case.the_turn(program, &out);
        assert_eq!(m.ended, Ended::Stopped, "{}: {m:?}", program.name);
        no_total(program, &m);
        whole(program, &m);
        assert!(turn.steps > 0, "{}: {turn:?}", program.name);
    }
}

/// A run is an item's turns until it passes or is given up. Its cost is nowhere but in its turns: every one of
/// them has a record, the failed ones too, and the sum is over those.
#[test]
fn a_runs_cost_is_the_sum_over_its_turns() {
    for program in &PROGRAMS {
        let case = Case::new();
        case.stand_in(program, program.whole(), "echo blue > answer");
        let _ = case.clock(program, &[]);
        let turns = case.turns();
        assert_eq!(turns.len(), MAX_ATTEMPTS as usize, "{}", program.name);
        let mut tokens = 0;
        let mut active = 0;
        for (at, turn) in turns.iter().enumerate() {
            assert_eq!(turn.lease_no as usize, at + 1, "{}", program.name);
            assert_eq!(turn.passed, Some(false), "{}", program.name);
            let m = turn
                .measured
                .as_ref()
                .unwrap_or_else(|| panic!("{}: turn {} has no record", program.name, at + 1));
            closing_total(program, m);
            whole(program, m);
            tokens += m.tokens.total().unwrap();
            active += m.active_ms;
        }
        assert_eq!(
            tokens,
            u64::from(MAX_ATTEMPTS) * program.total(),
            "{}",
            program.name
        );
        assert!(active > 0, "{}", program.name);
    }
}

/// A command that names several tracked files keeps all of them, in the order named. One that names none is a
/// step all the same, and is counted among those the record cannot name.
#[test]
fn a_command_naming_several_files_keeps_them_in_order_and_one_naming_none_is_counted() {
    for program in &PROGRAMS {
        let case = Case::new();
        case.stand_in(program, program.naming_two_files(), "echo green > answer");
        let out = case.clock(program, &ONE_TURN);
        let (turn, m) = case.the_turn(program, &out);
        let walk = Room::open_read_only(&case.room)
            .unwrap()
            .walk(&turn.attempt)
            .unwrap();
        // Every step of the stream, in its order: its tool, the tracked files it named in the order named,
        // and whether it went well. The captured streams read a.txt, run `ls`, and fail to read a file that
        // is not there; the added command comes last. The command that names nothing is the second.
        let first = if program.name == "claude" {
            Tool::Read
        } else {
            Tool::Shell
        };
        let expected: [(Tool, &[&str], bool); 4] = [
            (first, &["a.txt"], true),
            (Tool::Shell, &[], true),
            (first, &[], false),
            (Tool::Shell, &["check.sh", "a.txt"], true),
        ];
        let kept: Vec<(Tool, Vec<&str>, bool)> = walk
            .iter()
            .map(|step| {
                let named = step.named.iter().map(|file| file.path.as_str()).collect();
                (step.tool, named, step.ok)
            })
            .collect();
        assert_eq!(kept.len(), expected.len(), "{}: {kept:?}", program.name);
        for (at, (kept, expected)) in kept.iter().zip(expected).enumerate() {
            assert_eq!(
                (kept.0, kept.1.as_slice(), kept.2),
                expected,
                "{}: step {}",
                program.name,
                at + 1
            );
        }
        // Four seen and four kept; the two that name no tracked file are counted as such, and not left out.
        assert_eq!(
            (
                m.steps_seen,
                m.unknown_steps,
                turn.steps,
                turn.steps_with_a_name
            ),
            (4, 2, 4, 2),
            "{}",
            program.name
        );
        whole(program, &m);
    }
}

/// Every file under a directory, as bytes.
fn files_under(dir: &Path) -> Vec<(PathBuf, Vec<u8>)> {
    let mut found = Vec::new();
    let mut left = vec![dir.to_path_buf()];
    while let Some(dir) = left.pop() {
        for entry in fs::read_dir(&dir).unwrap() {
            let path = entry.unwrap().path();
            let meta = fs::symlink_metadata(&path).unwrap();
            if meta.is_dir() {
                left.push(path);
            } else if meta.is_file() {
                let bytes = fs::read(&path).unwrap();
                found.push((path, bytes));
            }
        }
    }
    found
}

fn holds(bytes: &[u8], words: &str) -> bool {
    bytes.windows(words.len()).any(|w| w == words.as_bytes())
}

/// No text of a turn is kept by the room: not in its store, not in any other file under its directory, and
/// not in what the clock prints. Each program's stream here holds one word in every text it carries.
#[test]
fn no_text_of_a_turn_is_kept_by_the_room() {
    for program in &PROGRAMS {
        let case = Case::new();
        let lines = captured(program.marked);
        // The control: the stream does carry the word, in more than one line.
        assert!(
            lines.iter().filter(|line| line.contains(MARKER)).count() > 1,
            "{}",
            program.marked
        );
        case.stand_in(program, lines, "echo green > answer");
        let out = case.clock(program, &ONE_TURN);
        // The stream was read: the turn has steps from it.
        let (turn, m) = case.the_turn(program, &out);
        assert!(turn.steps > 0, "{}: {turn:?}", program.name);
        whole(program, &m);
        let kept = files_under(&case.room);
        // The control: the scan finds text the store does keep.
        assert!(
            kept.iter()
                .any(|(_, bytes)| holds(bytes, "Make answer green")),
            "{}: the item's title was found in none of {:?}",
            program.name,
            kept.iter().map(|(path, _)| path).collect::<Vec<_>>()
        );
        for (path, bytes) in &kept {
            assert!(
                !holds(bytes, MARKER),
                "{}: {} holds text of the turn",
                program.name,
                path.display()
            );
        }
        for printed in [&out.stdout, &out.stderr] {
            assert!(
                !holds(printed, MARKER),
                "{}: the clock printed text of the turn",
                program.name
            );
        }
    }
}

/// A turn's parts adding up does not show that nothing was left out of all of them. So here the check is
/// made to take a time that is known, and that time must be in the check's part and in the turn's active
/// time: for a commit that is handed in, and for a turn that hands in nothing, whose base is checked.
#[test]
fn a_checks_time_is_in_its_part_and_in_the_turns_active_time() {
    for program in &PROGRAMS {
        for (then, passes) in [("echo green > answer", Some(true)), (":", None)] {
            let case = Case::with_check("sleep 2\ngrep -qx green answer\n");
            case.stand_in(program, program.whole(), then);
            let out = case.clock(program, &ONE_TURN);
            let (turn, m) = case.the_turn(program, &out);
            if let Some(passes) = passes {
                assert_eq!(turn.passed, Some(passes), "{}", program.name);
            } else {
                assert_ne!(turn.passed, Some(true), "{}", program.name);
            }
            let check = m.check_ms.unwrap_or(0);
            assert!(check >= 2000, "{} ({then}): {m:?}", program.name);
            assert!(
                m.active_ms >= check + m.worker_ms,
                "{} ({then}): {m:?}",
                program.name
            );
            whole(program, &m);
        }
    }
}

/// How many processes run with exactly this command line. The listing is shown to be one that can say so:
/// the command that made it ended well, and is itself in it, found the same way.
fn running(command: &str) -> usize {
    let listed = std::process::Command::new("ps")
        .args(["-Ao", "command="])
        .output()
        .unwrap();
    assert!(
        listed.status.success(),
        "the processes could not be listed: {}",
        String::from_utf8_lossy(&listed.stderr)
    );
    let listed = String::from_utf8_lossy(&listed.stdout);
    assert!(
        listed.lines().any(|line| line.trim() == "ps -Ao command="),
        "the list of processes does not hold the command that made it"
    );
    listed.lines().filter(|line| line.trim() == command).count()
}

/// A clock a test holds in its own hands: ended and waited for when the test lets go of it, however it ends.
struct Held(std::process::Child);

impl Drop for Held {
    fn drop(&mut self) {
        let _ = self.0.kill();
        let _ = self.0.wait();
    }
}

/// The case's own guard. Ending a clock ends the clock alone, and a worker it had started is then nobody's:
/// seen here alive after its clock is gone. Dropping the case ends it, from the room's record of it.
#[test]
fn a_case_ends_the_worker_that_a_clock_it_ended_left_running() {
    for program in &PROGRAMS {
        let case = Case::new();
        // Named by this test's own process and by the program, so that no other test's sleeper is taken for
        // it; and long, so that it does not end by itself while the test looks for it.
        let sleeper = format!(
            "sleep 3{}1.{}",
            if program.name == "claude" { 1 } else { 2 },
            std::process::id()
        );
        let running_at = case.dir().join("running");
        let scratch_at = case.dir().join("scratch");
        case.stand_in(
            program,
            program.no_closing_total(),
            &format!(
                "printf '%s' \"$TMPDIR\" > '{}'\n: > '{}'\n{sleeper}",
                scratch_at.display(),
                running_at.display()
            ),
        );
        // The clock as the other tests start it, but held here, so that it can be ended once its worker runs.
        let mut clock = std::process::Command::new(assert_cmd::cargo::cargo_bin!("yak"));
        clock
            .arg("--room")
            .arg(&case.room)
            .args(["clock", "run", "--once-through", "--daily-turns", "1"])
            .arg("--worker")
            .arg(format!("{}:test", program.name))
            .env("PATH", case.path())
            .env_remove("YAK_JAIL_READ")
            .stdin(std::process::Stdio::null())
            .stdout(std::process::Stdio::null())
            .stderr(std::process::Stdio::null());
        let clock = Held(clock.spawn().unwrap());
        let deadline = Instant::now() + Duration::from_secs(60);
        while !(running_at.exists() && running(&sleeper) == 1) && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(100));
        }
        let was_running = running(&sleeper);
        // The clock is ended as a test's limit ends one: the clock, and nothing it started.
        drop(clock);
        assert_eq!(was_running, 1, "{}: the worker never ran", program.name);
        assert_eq!(
            running(&sleeper),
            1,
            "{}: the worker went with its clock, so there is nothing for the case to end",
            program.name
        );
        // What the clock would have removed with the turn: the turn's own temporary directory. A clock that is
        // killed leaves it, and so would every run of this test. Its place is taken from the worker itself and
        // removed only if it is what the room makes: a directory named yak- and sixteen hex digits, in /tmp.
        let scratch = PathBuf::from(fs::read_to_string(&scratch_at).unwrap());
        drop(case);
        let deadline = Instant::now() + Duration::from_secs(20);
        while running(&sleeper) > 0 && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(100));
        }
        assert_eq!(
            running(&sleeper),
            0,
            "{}: `{sleeper}` outlived its case",
            program.name
        );
        let name = scratch
            .file_name()
            .and_then(|name| name.to_str())
            .unwrap_or_default();
        let the_rooms = scratch.parent() == fs::canonicalize("/tmp").ok().as_deref()
            && name.len() == 20
            && name.starts_with("yak-")
            && name[4..].bytes().all(|b| b.is_ascii_hexdigit())
            && fs::symlink_metadata(&scratch).is_ok_and(|meta| meta.is_dir());
        assert!(
            the_rooms,
            "{}: {} is not a turn's own temporary directory",
            program.name,
            scratch.display()
        );
        fs::remove_dir_all(&scratch).unwrap();
    }
}

/// The guard says what it could not look at or end, and a case it could not clean is kept for a person.
#[test]
fn a_case_that_cannot_be_cleaned_says_why_and_is_kept() {
    let tmp = tempfile::tempdir().unwrap();
    let room = tmp.path().join("room");
    fs::create_dir(&room).unwrap();
    // No turns' directory: there has been no run, and nothing is wrong.
    assert_eq!(end_what_a_room_left(&room), Vec::<String>::new());
    // A record that cannot be read: said, with its place.
    let turns = room.join("turns");
    fs::create_dir(&turns).unwrap();
    let record = turns.join("a000000000000.pid");
    fs::create_dir(&record).unwrap();
    let left = end_what_a_room_left(&room);
    assert_eq!(left.len(), 1, "{left:?}");
    assert!(
        left[0].starts_with(&format!("{}: ", record.display())),
        "{left:?}"
    );
    // A file that is no record is not asked about.
    fs::remove_dir(&record).unwrap();
    fs::write(turns.join("notes.txt"), "not a record").unwrap();
    assert_eq!(end_what_a_room_left(&room), Vec::<String>::new());
    // The turns' place cannot be listed: that is said, and is not taken for a place with nothing in it.
    fs::remove_file(turns.join("notes.txt")).unwrap();
    fs::remove_dir(&turns).unwrap();
    fs::write(&turns, "not a directory").unwrap();
    let left = end_what_a_room_left(&room);
    assert_eq!(left.len(), 1, "{left:?}");
    assert!(
        left[0].starts_with(&format!("{}: could not be listed: ", turns.display())),
        "{left:?}"
    );
    // A room that cannot be stopped: said too.
    let left = end_what_a_room_left(&tmp.path().join("no-room"));
    assert_eq!(left.len(), 1, "{left:?}");
    assert!(left[0].contains("could not be stopped"), "{left:?}");
    // A whole case in such a state is kept when it is dropped; one with nothing wrong is removed.
    for broken in [true, false] {
        let case = Case::new();
        let dir = case.dir().to_path_buf();
        if broken {
            let turns = case.room.join("turns");
            if turns.is_dir() {
                fs::remove_dir_all(&turns).unwrap();
            }
            fs::write(&turns, "not a directory").unwrap();
        }
        drop(case);
        assert_eq!(dir.is_dir(), broken, "{}", dir.display());
        if broken {
            fs::remove_dir_all(&dir).unwrap();
        }
    }
}
