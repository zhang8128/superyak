//! A worker's event stream to `Step`s: what the stream shows was called, in order. It is not proof of what was
//! read.
//!
//! Nothing from the stream survives as text (spec rule 9). A step keeps its kind of tool, whether the call
//! worked, its cost, and one name at most: a file tracked at the sandbox's base commit, with that file's blob
//! id. Any other target is `Outside`, with no name. The parsers take one line at a time and keep only the steps
//! and the calls still waiting for their results.

use std::collections::{HashMap, HashSet, VecDeque};

use room::{Step, Target, Tool};
use serde_json::Value;

use crate::Sandbox;
use crate::sandbox::git;

/// How deep `sh -c '...'` is unwrapped inside a shell command.
const SHELL_DEPTH: u32 = 3;

/// The Claude stream's steps (`claude -p --output-format stream-json --verbose`).
pub fn claude_steps(lines: impl Iterator<Item = String>, sandbox: &Sandbox) -> Vec<Step> {
    let mut parser = ClaudeParser::new(sandbox);
    for line in lines {
        parser.line(&line);
    }
    parser.finish()
}

/// The Codex stream's steps (`codex exec --json`).
pub fn codex_steps(lines: impl Iterator<Item = String>, sandbox: &Sandbox) -> Vec<Step> {
    let mut parser = CodexParser::new(sandbox);
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
    expand(command, 0, &mut words);
    words
}

fn expand(command: &str, depth: u32, out: &mut Vec<String>) {
    let words = split_words(command);
    for (i, word) in words.iter().enumerate() {
        let shell = word
            .rsplit('/')
            .next()
            .is_some_and(|n| matches!(n, "sh" | "bash" | "zsh" | "dash" | "ksh"));
        let flag = words
            .get(i + 1)
            .is_some_and(|f| f.starts_with('-') && !f.starts_with("--") && f.contains('c'));
        if shell
            && flag
            && depth < SHELL_DEPTH
            && let Some(script) = words.get(i + 2)
        {
            expand(script, depth + 1, out);
        }
    }
    out.extend(words);
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
struct Steps(Vec<Step>);

impl Steps {
    fn push(&mut self, tool: Tool, target: Target, tokens: (Option<u32>, Option<u32>)) -> usize {
        let index = self.0.len();
        self.0.push(Step {
            seq: clamp(index as u64),
            tool,
            target,
            // Not ok until a result says it was.
            ok: false,
            tokens_in: tokens.0,
            tokens_out: tokens.1,
        });
        index
    }
}

/// Claude's stream, a line at a time. Results are matched to calls by id, the oldest waiting call first; a call
/// whose result never comes is not ok.
pub struct ClaudeParser {
    tracked: Tracked,
    steps: Steps,
    waiting: HashMap<String, VecDeque<usize>>,
    counted: HashSet<String>,
}

impl ClaudeParser {
    pub fn new(sandbox: &Sandbox) -> ClaudeParser {
        ClaudeParser {
            tracked: Tracked::of(sandbox),
            steps: Steps(Vec::new()),
            waiting: HashMap::new(),
            counted: HashSet::new(),
        }
    }

    pub fn line(&mut self, line: &str) {
        // Every line that matters carries a tool_use block or a tool_result; most of a long stream does not.
        if !line.contains("tool_") {
            return;
        }
        let Ok(event) = serde_json::from_str::<Value>(line) else {
            return;
        };
        let message = event.get("message").unwrap_or(&Value::Null);
        match text(&event, "type") {
            Some("assistant") => self.calls(message),
            Some("user") => self.results(message),
            _ => {}
        }
    }

    pub fn finish(self) -> Vec<Step> {
        self.steps.0
    }

    fn calls(&mut self, message: &Value) {
        let Some(blocks) = message.get("content").and_then(Value::as_array) else {
            return;
        };
        let mut first = true;
        for block in blocks
            .iter()
            .filter(|b| text(b, "type") == Some("tool_use"))
        {
            let input = block.get("input").unwrap_or(&Value::Null);
            let (tool, target) =
                claude_call(text(block, "name").unwrap_or(""), input, &self.tracked);
            let cost = if first {
                self.cost(message)
            } else {
                (None, None)
            };
            first = false;
            let index = self.steps.push(tool, target, cost);
            if let Some(id) = text(block, "id") {
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

    fn results(&mut self, message: &Value) {
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
                self.steps.0[index].ok =
                    block.get("is_error").and_then(Value::as_bool) != Some(true);
            }
        }
    }
}

fn claude_call(name: &str, input: &Value, tracked: &Tracked) -> (Tool, Target) {
    let path = |key: &str| text(input, key).map_or(Target::Outside, |p| tracked.target(p));
    match name {
        "Read" => (Tool::Read, path("file_path")),
        "NotebookRead" => (Tool::Read, path("notebook_path")),
        "Edit" | "MultiEdit" => (Tool::Edit, path("file_path")),
        "NotebookEdit" => (Tool::Edit, path("notebook_path")),
        "Write" => (Tool::Write, path("file_path")),
        "Grep" => (Tool::Search, path("path")),
        "Glob" | "LS" => (Tool::Search, Target::Outside),
        "Bash" => (
            Tool::Shell,
            text(input, "command").map_or(Target::Outside, |c| tracked.shell_target(c)),
        ),
        "WebFetch" => (Tool::Read, Target::Outside),
        "WebSearch" => (Tool::Search, Target::Outside),
        _ => (Tool::Other, Target::Outside),
    }
}

/// Codex's stream, a line at a time. An item becomes its steps when first seen and is settled when completed.
/// Codex gives tokens only for a whole turn, so its steps carry none.
pub struct CodexParser {
    tracked: Tracked,
    steps: Steps,
    open: HashMap<String, Vec<usize>>,
    closed: HashSet<String>,
}

impl CodexParser {
    pub fn new(sandbox: &Sandbox) -> CodexParser {
        CodexParser {
            tracked: Tracked::of(sandbox),
            steps: Steps(Vec::new()),
            open: HashMap::new(),
            closed: HashSet::new(),
        }
    }

    pub fn line(&mut self, line: &str) {
        if !line.contains("\"item") {
            return;
        }
        let Ok(event) = serde_json::from_str::<Value>(line) else {
            return;
        };
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
        let Some(id) = text(item, "id").map(str::to_string) else {
            // An item with no id cannot be told from the next one: each such event is its own step.
            let indices = self.start(what, item);
            let ok = kind == "completed" && codex_ok(what, item);
            for index in indices {
                self.steps.0[index].ok = ok;
            }
            return;
        };
        if self.closed.contains(&id) {
            return;
        }
        let indices = match self.open.get(&id) {
            Some(indices) => indices.clone(),
            None => {
                let indices = self.start(what, item);
                self.open.insert(id.clone(), indices.clone());
                indices
            }
        };
        if kind == "completed" {
            let ok = codex_ok(what, item);
            for index in indices {
                self.steps.0[index].ok = ok;
            }
            self.open.remove(&id);
            self.closed.insert(id);
        }
    }

    pub fn finish(self) -> Vec<Step> {
        self.steps.0
    }

    fn start(&mut self, what: &str, item: &Value) -> Vec<usize> {
        let none = (None, None);
        match what {
            "command_execution" => {
                let target = match item.get("command") {
                    Some(Value::String(command)) => self.tracked.shell_target(command),
                    Some(Value::Array(argv)) => {
                        let words: Vec<String> = argv
                            .iter()
                            .filter_map(Value::as_str)
                            .map(str::to_string)
                            .collect();
                        self.tracked.words_target(&words)
                    }
                    _ => Target::Outside,
                };
                vec![self.steps.push(Tool::Shell, target, none)]
            }
            "file_change" => {
                let changes = item
                    .get("changes")
                    .and_then(Value::as_array)
                    .cloned()
                    .unwrap_or_default();
                if changes.is_empty() {
                    return vec![self.steps.push(Tool::Edit, Target::Outside, none)];
                }
                changes
                    .iter()
                    .map(|change| {
                        let tool = if text(change, "kind") == Some("add") {
                            Tool::Write
                        } else {
                            Tool::Edit
                        };
                        let target = text(change, "path")
                            .map_or(Target::Outside, |p| self.tracked.target(p));
                        self.steps.push(tool, target, none)
                    })
                    .collect()
            }
            "web_search" => vec![self.steps.push(Tool::Search, Target::Outside, none)],
            _ => vec![self.steps.push(Tool::Other, Target::Outside, none)],
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
        assert_eq!(
            command_words("/bin/zsh -lc 'cat a.txt'"),
            ["cat", "a.txt", "/bin/zsh", "-lc", "cat a.txt"]
        );
    }
}
