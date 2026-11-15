//! A worker's event stream to `Step`s: what the stream shows was called, in order. It is not proof of what was
//! read.
//!
//! Nothing from the stream survives as text (spec rule 9). A step keeps its kind of tool, whether the call
//! worked, its cost, when it was called and answered, its target (a file tracked at the sandbox's base commit,
//! with that file's blob id, or `Outside`, with no name), and every tracked file it named. The parsers take one
//! line at a time and keep only the steps, the calls still waiting for their results, and the program's closing
//! total for the whole turn.

use std::collections::{HashMap, HashSet, VecDeque};
use std::time::Instant;

use room::{Named, Step, Target, Tokens, Tool};
use serde_json::Value;

use crate::Sandbox;
use crate::sandbox::git;

/// How deep `sh -c '...'` is unwrapped inside a shell command.
const SHELL_DEPTH: u32 = 3;

/// Maximum steps retained from one turn. Later calls are counted without retaining their data.
pub const MAX_STEPS: usize = 100_000;

/// The Claude stream's steps (`claude -p --output-format stream-json --verbose`).
pub fn claude_steps(lines: impl Iterator<Item = String>, sandbox: &Sandbox) -> Vec<Step> {
    let mut parser = ClaudeParser::new(sandbox, Instant::now());
    for line in lines {
        parser.line(&line);
    }
    parser.finish()
}

/// The Codex stream's steps (`codex exec --json`).
pub fn codex_steps(lines: impl Iterator<Item = String>, sandbox: &Sandbox) -> Vec<Step> {
    let mut parser = CodexParser::new(sandbox, Instant::now());
    for line in lines {
        parser.line(&line);
    }
    parser.finish()
}

/// The files tracked at a sandbox's base commit, by path, with their blob ids; and where the sandbox is.
pub struct Tracked {
    roots: Vec<String>,
    files: HashMap<String, String>,
}

impl Tracked {
    /// Reads the base commit's tree. A tree that cannot be read leaves every target `Outside`.
    pub fn of(sandbox: &Sandbox) -> Tracked {
        let mut files = HashMap::new();
        if let Ok(listing) = git(
            &sandbox.dir,
            &["ls-tree", "-r", "-z", "--full-tree", sandbox.base()],
        ) {
            for entry in listing.split(|&b| b == 0) {
                // "<mode> <type> <object>\t<path>": regular files only, not links or submodules.
                let Some(tab) = entry.iter().position(|&b| b == b'\t') else {
                    continue;
                };
                let (Ok(meta), Ok(path)) = (
                    std::str::from_utf8(&entry[..tab]),
                    std::str::from_utf8(&entry[tab + 1..]),
                ) else {
                    continue;
                };
                let mut parts = meta.split(' ');
                if let (Some("100644" | "100755"), Some("blob"), Some(object)) =
                    (parts.next(), parts.next(), parts.next())
                {
                    files.insert(path.to_string(), object.to_string());
                }
            }
        }
        let root = sandbox.dir.to_string_lossy().into_owned();
        let mut roots = vec![root.clone()];
        // macOS shows /private/var and /private/tmp also as /var and /tmp.
        if let Some(short) = root.strip_prefix("/private")
            && (short.starts_with("/var/") || short.starts_with("/tmp/"))
        {
            roots.push(short.to_string());
        }
        Tracked { roots, files }
    }

    /// What `raw`, a path from the stream, names: absolute, or relative to the sandbox, where a worker starts.
    pub fn target(&self, raw: &str) -> Target {
        match self.resolve(raw) {
            Some((path, blob)) => Target::TrackedFile {
                path: path.to_string(),
                blob: blob.to_string(),
            },
            None => Target::Outside,
        }
    }

    /// A shell command is a `TrackedFile` step only when its words name exactly one tracked file.
    pub fn shell_target(&self, command: &str) -> Target {
        self.words_target(&command_words(command))
    }

    /// Every tracked file the words name, in the order named, each once, at its first place.
    fn words_named(&self, words: &[String]) -> Vec<Named> {
        let mut seen = HashSet::new();
        let mut named = Vec::new();
        for word in words {
            if let Some((path, blob)) = self.resolve(word)
                && seen.insert(path)
            {
                named.push(Named {
                    path: path.to_string(),
                    blob: blob.to_string(),
                });
            }
        }
        named
    }

    /// What a shell command given as one string touched: its target, and every tracked file it named.
    fn shell(&self, command: &str) -> (Target, Vec<Named>) {
        let words = command_words(command);
        (self.words_target(&words), self.words_named(&words))
    }

    fn words_target(&self, words: &[String]) -> Target {
        let mut found: Option<(&str, &str)> = None;
        for word in words {
            if let Some(hit) = self.resolve(word) {
                match found {
                    Some(seen) if seen.0 != hit.0 => return Target::Outside,
                    _ => found = Some(hit),
                }
            }
        }
        match found {
            Some((path, blob)) => Target::TrackedFile {
                path: path.to_string(),
                blob: blob.to_string(),
            },
            None => Target::Outside,
        }
    }

    fn resolve(&self, raw: &str) -> Option<(&str, &str)> {
        if raw.is_empty() || raw.contains(['\0', '\n', '\r']) {
            return None;
        }
        let relative = if raw.starts_with('/') {
            self.roots.iter().find_map(|root| {
                raw.strip_prefix(root.as_str())
                    .filter(|rest| rest.is_empty() || rest.starts_with('/'))
            })?
        } else {
            raw
        };
        let mut parts: Vec<&str> = Vec::new();
        for part in relative.split('/') {
            match part {
                "" | "." => {}
                // A path that climbs out of the sandbox names nothing in it, even if it climbs back.
                ".." => {
                    parts.pop()?;
                }
                part => parts.push(part),
            }
        }
        let path = parts.join("/");
        self.files
            .get_key_value(path.as_str())
            .map(|(path, blob)| (path.as_str(), blob.as_str()))
    }
}

/// The words of a shell command, with each `sh -c '<script>'` (or bash, zsh, `-lc` and the like) also split into
/// the script's words.
fn command_words(command: &str) -> Vec<String> {
    let mut words = Vec::new();
    expand(split_words(command), 0, &mut words);
    words
}

/// `words` into `out`, each script that a shell is given with `-c` followed at once by the script's own words, so
/// that the words come in the order the command names things in.
fn expand(words: Vec<String>, depth: u32, out: &mut Vec<String>) {
    let script: Vec<bool> = (0..words.len())
        .map(|i| {
            let shell = i >= 2
                && words[i - 2]
                    .rsplit('/')
                    .next()
                    .is_some_and(|n| matches!(n, "sh" | "bash" | "zsh" | "dash" | "ksh"));
            let flag = i >= 1 && {
                let f = &words[i - 1];
                f.starts_with('-') && !f.starts_with("--") && f.contains('c')
            };
            shell && flag && depth < SHELL_DEPTH
        })
        .collect();
    for (word, script) in words.into_iter().zip(script) {
        if script {
            let inner = split_words(&word);
            out.push(word);
            expand(inner, depth + 1, out);
        } else {
            out.push(word);
        }
    }
}

/// A file tool's names: the one file it was given, when that is tracked.
fn named_of(target: &Target) -> Vec<Named> {
    match target {
        Target::TrackedFile { path, blob } => vec![Named {
            path: path.clone(),
            blob: blob.clone(),
        }],
        Target::Outside => Vec::new(),
    }
}

/// Milliseconds from the turn's start to `at`: 0 for a moment before the start, and at most what a step holds.
fn ms(start: Instant, at: Instant) -> u32 {
    clamp(u64::try_from(at.saturating_duration_since(start).as_millis()).unwrap_or(u64::MAX))
}

/// A count in a closing total: a whole number a program could report, or nothing.
fn count(usage: &Value, key: &str) -> Option<u64> {
    usage.get(key).and_then(Value::as_u64)
}

/// Claude's closing total, the `usage` of its `result` line. Its input is three parts, none inside another:
/// fresh input (`input_tokens`), cache writes and cache reads. Thinking is a part of the output, and is kept as
/// the reasoning part.
fn claude_total(usage: &Value) -> Tokens {
    Tokens {
        fresh_in: count(usage, "input_tokens"),
        cache_write: count(usage, "cache_creation_input_tokens"),
        cache_read: count(usage, "cache_read_input_tokens"),
        output: count(usage, "output_tokens"),
        reasoning: usage
            .get("output_tokens_details")
            .and_then(|d| count(d, "thinking_tokens")),
        complete: true,
    }
}

/// Codex's closing total, the `usage` of its `turn.completed` line. Its `input_tokens` is the whole input, and
/// holds the cached part (see `the_closing_total_is_the_turns_tokens` in the tests for the measurement that
/// shows it). The fresh part is what is left: input - cached - cache write. Where a cache write falls is not
/// established, since every capture has it 0, so the fresh part is known only when the cache write was given
/// and is 0; it is unknown unless all three were given, and when the cached part comes to more than the whole,
/// the reading is wrong for that line, and the fresh part is unknown rather than a guess. Reasoning is a part of
/// the output.
fn codex_total(usage: &Value) -> Tokens {
    let input = count(usage, "input_tokens");
    let cache_read = count(usage, "cached_input_tokens");
    let cache_write = count(usage, "cache_write_input_tokens");
    let fresh_in = match (input, cache_read, cache_write) {
        (Some(input), Some(read), Some(0)) => input.checked_sub(read),
        _ => None,
    };
    Tokens {
        fresh_in,
        cache_write,
        cache_read,
        output: count(usage, "output_tokens"),
        reasoning: count(usage, "reasoning_output_tokens"),
        complete: true,
    }
}

/// The `usage` of a closing line, when it has one that can hold counts.
fn usage(event: &Value) -> Option<&Value> {
    event.get("usage").filter(|u| u.is_object())
}

/// Splits like a POSIX shell, roughly: quotes and backslashes are honoured, and `|&;<>()` end a word.
fn split_words(text: &str) -> Vec<String> {
    let mut words = Vec::new();
    let mut word = String::new();
    let mut started = false;
    let mut chars = text.chars();
    while let Some(c) = chars.next() {
        match c {
            '\'' => {
                started = true;
                for c in chars.by_ref() {
                    if c == '\'' {
                        break;
                    }
                    word.push(c);
                }
            }
            '"' => {
                started = true;
                let mut escaped = false;
                for c in chars.by_ref() {
                    match c {
                        '"' if !escaped => break,
                        '\\' if !escaped => escaped = true,
                        c => {
                            if escaped && !matches!(c, '"' | '\\' | '$' | '`') {
                                word.push('\\');
                            }
                            escaped = false;
                            word.push(c);
                        }
                    }
                }
            }
            '\\' => {
                started = true;
                if let Some(next) = chars.next()
                    && next != '\n'
                {
                    word.push(next);
                }
            }
            c if c.is_whitespace() || "|&;<>()".contains(c) => {
                if started {
                    words.push(std::mem::take(&mut word));
                    started = false;
                }
            }
            c => {
                started = true;
                word.push(c);
            }
        }
    }
    if started {
        words.push(word);
    }
    words
}

fn clamp(n: u64) -> u32 {
    u32::try_from(n).unwrap_or(u32::MAX)
}

fn text<'a>(value: &'a Value, key: &str) -> Option<&'a str> {
    value.get(key).and_then(Value::as_str)
}

/// The steps found so far.
#[derive(Default)]
struct Steps {
    items: Vec<Step>,
    total: u64,
}

impl Steps {
    fn full(&self) -> bool {
        self.items.len() >= MAX_STEPS
    }

    fn count(&mut self, count: usize) {
        self.total = self.total.saturating_add(count as u64);
    }

    fn push(
        &mut self,
        tool: Tool,
        (target, named): (Target, Vec<Named>),
        tokens: (Option<u32>, Option<u32>),
        seen_ms: u32,
    ) -> Option<usize> {
        self.count(1);
        if self.full() {
            return None;
        }
        let index = self.items.len();
        self.items.push(Step {
            seq: clamp(index as u64),
            tool,
            target,
            // Not ok until a result says it was.
            ok: false,
            tokens_in: tokens.0,
            tokens_out: tokens.1,
            named,
            seen_ms: Some(seen_ms),
            result_ms: None,
        });
        Some(index)
    }

    /// The step at `index` was answered at `result_ms`, and worked or not.
    fn settle(&mut self, index: usize, ok: bool, result_ms: u32) {
        let step = &mut self.items[index];
        step.ok = ok;
        step.result_ms = Some(result_ms);
    }
}

/// Claude's stream, a line at a time. Results are matched to calls by id, the oldest waiting call first; a call
/// whose result never comes is not ok.
pub struct ClaudeParser {
    tracked: Tracked,
    start: Instant,
    steps: Steps,
    waiting: HashMap<String, VecDeque<usize>>,
    counted: HashSet<String>,
    tokens: Tokens,
}

impl ClaudeParser {
    /// A parser for a turn that started at `start`: each step's times are counted from it.
    pub fn new(sandbox: &Sandbox, start: Instant) -> ClaudeParser {
        ClaudeParser {
            tracked: Tracked::of(sandbox),
            start,
            steps: Steps::default(),
            waiting: HashMap::new(),
            counted: HashSet::new(),
            tokens: Tokens::none(),
        }
    }

    /// The program's closing total for the whole turn, the last one it gave, and `Tokens::none()` if it gave
    /// none: what each message cost on the way is not summed in its place.
    pub fn tokens(&self) -> Tokens {
        self.tokens.clone()
    }

    /// One line of the stream, as it arrives.
    pub fn line(&mut self, line: &str) {
        self.line_at(line, Instant::now());
    }

    /// One line of the stream, which arrived at `at`.
    pub fn line_at(&mut self, line: &str, at: Instant) {
        // Every line that matters carries a tool_use block, a tool_result, or is the closing `result`; most of a
        // long stream is none of them.
        if !line.contains("tool_") && !line.contains("\"result\"") {
            return;
        }
        let Ok(event) = serde_json::from_str::<Value>(line) else {
            return;
        };
        let message = event.get("message").unwrap_or(&Value::Null);
        let at = ms(self.start, at);
        match text(&event, "type") {
            Some("assistant") => self.calls(message, at),
            Some("user") => self.results(message, at),
            Some("result") => {
                if let Some(usage) = usage(&event) {
                    self.tokens = claude_total(usage);
                }
            }
            _ => {}
        }
    }

    /// Number of observed tool calls, including calls beyond the retained-step limit.
    pub fn total_steps(&self) -> u64 {
        self.steps.total
    }

    pub fn finish(self) -> Vec<Step> {
        self.steps.items
    }

    /// The steps so far, taken out: for the worker, which hands them on however its run ends.
    pub(crate) fn take_steps(&mut self) -> Vec<Step> {
        std::mem::take(&mut self.steps.items)
    }

    fn calls(&mut self, message: &Value, at: u32) {
        let Some(blocks) = message.get("content").and_then(Value::as_array) else {
            return;
        };
        let mut first = true;
        for block in blocks
            .iter()
            .filter(|b| text(b, "type") == Some("tool_use"))
        {
            if self.steps.full() {
                self.steps.count(1);
                continue;
            }
            let input = block.get("input").unwrap_or(&Value::Null);
            let (tool, touched) =
                claude_call(text(block, "name").unwrap_or(""), input, &self.tracked);
            let cost = if first {
                self.cost(message)
            } else {
                (None, None)
            };
            first = false;
            let index = self.steps.push(tool, touched, cost, at);
            if let (Some(id), Some(index)) = (text(block, "id"), index) {
                self.waiting
                    .entry(id.to_string())
                    .or_default()
                    .push_back(index);
            }
        }
    }

    /// A message's tokens, the first time one of its calls is seen: Claude Code writes a message holding several
    /// calls as several lines, each repeating the message's usage. Tokens in count the cache as well.
    fn cost(&mut self, message: &Value) -> (Option<u32>, Option<u32>) {
        if let Some(id) = text(message, "id")
            && !self.counted.insert(id.to_string())
        {
            return (None, None);
        }
        let Some(usage) = message.get("usage") else {
            return (None, None);
        };
        let n = |key: &str| usage.get(key).and_then(Value::as_u64);
        let input = [
            n("input_tokens"),
            n("cache_creation_input_tokens"),
            n("cache_read_input_tokens"),
        ];
        let tokens_in = input
            .iter()
            .any(Option::is_some)
            .then(|| clamp(input.iter().flatten().sum()));
        (tokens_in, n("output_tokens").map(clamp))
    }

    fn results(&mut self, message: &Value, at: u32) {
        let Some(blocks) = message.get("content").and_then(Value::as_array) else {
            return;
        };
        for block in blocks
            .iter()
            .filter(|b| text(b, "type") == Some("tool_result"))
        {
            let Some(id) = text(block, "tool_use_id") else {
                continue;
            };
            let Some(queue) = self.waiting.get_mut(id) else {
                continue;
            };
            let index = queue.pop_front();
            if queue.is_empty() {
                self.waiting.remove(id);
            }
            if let Some(index) = index {
                let ok = block.get("is_error").and_then(Value::as_bool) != Some(true);
                self.steps.settle(index, ok, at);
            }
        }
    }
}

/// A Claude tool call's kind, its target and the tracked files it named.
fn claude_call(name: &str, input: &Value, tracked: &Tracked) -> (Tool, (Target, Vec<Named>)) {
    let path = |key: &str| text(input, key).map_or(Target::Outside, |p| tracked.target(p));
    let (tool, target) = match name {
        "Read" => (Tool::Read, path("file_path")),
        "NotebookRead" => (Tool::Read, path("notebook_path")),
        "Edit" | "MultiEdit" => (Tool::Edit, path("file_path")),
        "NotebookEdit" => (Tool::Edit, path("notebook_path")),
        "Write" => (Tool::Write, path("file_path")),
        "Grep" => (Tool::Search, path("path")),
        "Glob" | "LS" => (Tool::Search, Target::Outside),
        "Bash" => {
            let touched =
                text(input, "command").map_or((Target::Outside, Vec::new()), |c| tracked.shell(c));
            return (Tool::Shell, touched);
        }
        "WebFetch" => (Tool::Read, Target::Outside),
        "WebSearch" => (Tool::Search, Target::Outside),
        _ => (Tool::Other, Target::Outside),
    };
    let named = named_of(&target);
    (tool, (target, named))
}

/// Codex's stream, a line at a time. An item becomes its steps when first seen and is settled when completed.
/// Codex gives tokens only for a whole turn, so its steps carry none.
pub struct CodexParser {
    tracked: Tracked,
    start: Instant,
    steps: Steps,
    open: HashMap<String, Vec<usize>>,
    closed: HashSet<String>,
    tokens: Tokens,
}

impl CodexParser {
    /// A parser for a turn that started at `start`: each step's times are counted from it.
    pub fn new(sandbox: &Sandbox, start: Instant) -> CodexParser {
        CodexParser {
            tracked: Tracked::of(sandbox),
            start,
            steps: Steps::default(),
            open: HashMap::new(),
            closed: HashSet::new(),
            tokens: Tokens::none(),
        }
    }

    /// The program's closing total for the whole turn, the last one it gave, and `Tokens::none()` if it gave
    /// none.
    pub fn tokens(&self) -> Tokens {
        self.tokens.clone()
    }

    /// One line of the stream, as it arrives.
    pub fn line(&mut self, line: &str) {
        self.line_at(line, Instant::now());
    }

    /// One line of the stream, which arrived at `at`.
    pub fn line_at(&mut self, line: &str, at: Instant) {
        if !line.contains("\"item") && !line.contains("turn.completed") {
            return;
        }
        let Ok(event) = serde_json::from_str::<Value>(line) else {
            return;
        };
        if text(&event, "type") == Some("turn.completed") {
            if let Some(usage) = usage(&event) {
                self.tokens = codex_total(usage);
            }
            return;
        }
        let at = ms(self.start, at);
        let Some(kind) = text(&event, "type").and_then(|t| t.strip_prefix("item.")) else {
            return;
        };
        let Some(item) = event.get("item").filter(|i| i.is_object()) else {
            return;
        };
        let what = text(item, "type").unwrap_or("");
        if matches!(what, "agent_message" | "reasoning" | "todo_list" | "error") {
            return;
        }
        let id = text(item, "id");
        if self.steps.full()
            && id.is_none_or(|id| !self.open.contains_key(id) && !self.closed.contains(id))
        {
            if kind == "completed" {
                let count = if what == "file_change" {
                    item.get("changes")
                        .and_then(Value::as_array)
                        .map_or(1, |v| v.len().max(1))
                } else {
                    1
                };
                self.steps.count(count);
            }
            return;
        }
        let Some(id) = id.map(str::to_string) else {
            // An item with no id cannot be told from the next one: each such event is its own step.
            let indices = self.start(what, item, at);
            if kind == "completed" {
                let ok = codex_ok(what, item);
                for index in indices {
                    self.steps.settle(index, ok, at);
                }
            }
            return;
        };
        if self.closed.contains(&id) {
            return;
        }
        let indices = match self.open.get(&id) {
            Some(indices) => indices.clone(),
            None => {
                let indices = self.start(what, item, at);
                self.open.insert(id.clone(), indices.clone());
                indices
            }
        };
        if kind == "completed" {
            let ok = codex_ok(what, item);
            for index in indices {
                self.steps.settle(index, ok, at);
            }
            self.open.remove(&id);
            self.closed.insert(id);
        }
    }

    /// Retained calls plus completed steps observed after the retained-step limit.
    pub fn total_steps(&self) -> u64 {
        self.steps.total
    }

    pub fn finish(self) -> Vec<Step> {
        self.steps.items
    }

    /// The steps so far, taken out: for the worker, which hands them on however its run ends.
    pub(crate) fn take_steps(&mut self) -> Vec<Step> {
        std::mem::take(&mut self.steps.items)
    }

    /// An item's steps, first seen at `at`.
    fn start(&mut self, what: &str, item: &Value, at: u32) -> Vec<usize> {
        let none = (None, None);
        let nothing = || (Target::Outside, Vec::new());
        match what {
            "command_execution" => {
                let touched = match item.get("command") {
                    Some(Value::String(command)) => self.tracked.shell(command),
                    Some(Value::Array(argv)) => {
                        let words: Vec<String> = argv
                            .iter()
                            .filter_map(Value::as_str)
                            .map(str::to_string)
                            .collect();
                        // Its target is read from the words as given, as it always was; what it named also
                        // from any script among them.
                        let target = self.tracked.words_target(&words);
                        let mut expanded = Vec::new();
                        expand(words, 0, &mut expanded);
                        (target, self.tracked.words_named(&expanded))
                    }
                    _ => nothing(),
                };
                self.steps
                    .push(Tool::Shell, touched, none, at)
                    .into_iter()
                    .collect()
            }
            "file_change" => {
                let changes = item
                    .get("changes")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default();
                if changes.is_empty() {
                    return self
                        .steps
                        .push(Tool::Edit, nothing(), none, at)
                        .into_iter()
                        .collect();
                }
                changes
                    .iter()
                    .filter_map(|change| {
                        let tool = if text(change, "kind") == Some("add") {
                            Tool::Write
                        } else {
                            Tool::Edit
                        };
                        let target = text(change, "path")
                            .map_or(Target::Outside, |p| self.tracked.target(p));
                        let named = named_of(&target);
                        self.steps.push(tool, (target, named), none, at)
                    })
                    .collect()
            }
            "web_search" => self
                .steps
                .push(Tool::Search, nothing(), none, at)
                .into_iter()
                .collect(),
            _ => self
                .steps
                .push(Tool::Other, nothing(), none, at)
                .into_iter()
                .collect(),
        }
    }
}

fn codex_ok(what: &str, item: &Value) -> bool {
    let status = text(item, "status");
    match what {
        "command_execution" => {
            status == Some("completed") && item.get("exit_code").and_then(Value::as_i64) == Some(0)
        }
        _ => {
            status.is_none_or(|s| s == "completed") && item.get("error").is_none_or(Value::is_null)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn words_follow_quotes_escapes_and_operators() {
        assert_eq!(
            split_words(r#"cat 'a b' "c \"d\"" e\ f|g;h>i"#),
            ["cat", "a b", "c \"d\"", "e f", "g", "h", "i"]
        );
        assert_eq!(split_words(r#"echo "a\nb" ''"#), ["echo", "a\\nb", ""]);
        // A script's words follow it at once, so the words keep the order the command names things in.
        assert_eq!(
            command_words("/bin/zsh -lc 'cat a.txt'"),
            ["/bin/zsh", "-lc", "cat a.txt", "cat", "a.txt"]
        );
        assert_eq!(
            command_words("cat a && sh -c 'cat b; bash -c \"cat c\"' d"),
            [
                "cat",
                "a",
                "sh",
                "-c",
                "cat b; bash -c \"cat c\"",
                "cat",
                "b",
                "bash",
                "-c",
                "cat c",
                "cat",
                "c",
                "d"
            ]
        );
    }
}
