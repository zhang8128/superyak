//! Task 8: workers. No test starts a real `claude` or `codex`: their command lines are checked as built, and
//! their runs are driven through stand-in programs that print the real sample streams.

mod common;

use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};

use common::{Repo, git, strings};
use room::{Step, Target, Tokens, Tool};
use turn::worker::{ClaudeWorker, CodexWorker, RULES, Seen, Worker, from_name, prompt};
use turn::{Sandbox, TurnError};

/// A fresh `Seen` to pass into `Worker::run`.
fn seen() -> Seen {
    Seen {
        steps: Vec::new(),
        tokens: Tokens::none(),
        steps_seen: 0,
    }
}

fn sandbox(repo: &Repo) -> Sandbox {
    Sandbox::create(
        &repo.path,
        &repo.base,
        &repo.scratch("sandbox"),
        "room/i1/1",
    )
    .unwrap()
}

/// An executable script beside the repository.
fn script(repo: &Repo, name: &str, body: &str) -> PathBuf {
    let path = repo.scratch(name);
    std::fs::write(&path, body).unwrap();
    std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o755)).unwrap();
    path
}

fn data(name: &str) -> String {
    format!("{}/tests/data/{name}", env!("CARGO_MANIFEST_DIR"))
}

fn tracked(repo: &Repo, path: &str) -> Target {
    Target::TrackedFile {
        path: path.to_string(),
        blob: git(&repo.path, &["rev-parse", &format!("{}:{path}", repo.base)]),
    }
}

fn oks(steps: &[Step]) -> Vec<bool> {
    steps.iter().map(|s| s.ok).collect()
}

fn read(path: &Path) -> String {
    std::fs::read_to_string(path).unwrap()
}

#[test]
fn a_script_worker_can_commit_in_its_sandbox() {
    let repo = Repo::new(&[("a.txt", "broken\n")]);
    let sb = sandbox(&repo);
    let path = script(
        &repo,
        "fix.sh",
        "#!/bin/sh\necho fixed > a.txt\ngit commit -q -am fix\n",
    );
    let name = format!("script:{}", path.display());
    let worker = from_name(&name).unwrap();
    assert_eq!(worker.name(), name);
    let status = worker
        .run(&sb, "Fix a.txt", "grep -q fixed a.txt", 60, &mut seen())
        .unwrap();
    assert_eq!(status.exit_code, 0);
    assert!(!status.timed_out);
    assert_ne!(sb.head().unwrap(), repo.base);
    assert_eq!(git(&sb.dir, &["show", "HEAD:a.txt"]), "fixed");
}

#[test]
fn an_unknown_worker_name_is_refused() {
    assert!(matches!(
        from_name("gpt:x"),
        Err(TurnError::UnknownWorker(_))
    ));
    for bad in [
        "",
        "claude",
        "claude:",
        "codex:",
        "script:",
        "claude:-x",
        "claude:a b",
        ":x",
        "codex:sol;rm",
    ] {
        assert!(from_name(bad).is_err(), "{bad:?} was taken");
    }
    for good in ["claude:opus", "codex:gpt-6.1-sol", "script:/bin/true"] {
        assert_eq!(from_name(good).unwrap().name(), good);
    }
}

#[test]
fn a_script_worker_gets_the_prompt_and_its_stream_becomes_steps() {
    let repo = Repo::new(&[("src/a.txt", "source\n")]);
    let sb = sandbox(&repo);
    // A script worker runs in the jail, where its home is the scratch directory beside the sandbox. That is
    // the one place outside its clone where it can leave the prompt for this test to read.
    let mut scratch = sb.dir.file_name().unwrap().to_os_string();
    scratch.push(".scratch");
    let prompt_out = sb.dir.with_file_name(scratch).join("prompt.txt");
    // The sample stream goes into the script itself: the jail shows a script worker its own program, and not
    // the files of this source tree.
    let sample = read(Path::new(&data("claude-read-src.jsonl")));
    assert!(!sample.contains("YAK_SAMPLE"));
    let body = format!(
        "#!/bin/sh\ncat > \"$HOME/prompt.txt\"\nsed \"s#/sandbox#$PWD#g\" <<'YAK_SAMPLE'\n{}\nYAK_SAMPLE\n",
        sample.trim_end()
    );
    let path = script(&repo, "reader.sh", &body);
    let worker = from_name(&format!("script:{}", path.display())).unwrap();
    let mut seen = seen();
    let status = worker
        .run(&sb, "Read the source", "test -f src/a.txt", 60, &mut seen)
        .unwrap();
    assert_eq!(status.exit_code, 0);
    assert_eq!(seen.steps.len(), 1);
    assert_eq!(seen.steps[0].tool, Tool::Read);
    assert_eq!(seen.steps[0].target, tracked(&repo, "src/a.txt"));
    assert_eq!(
        read(&prompt_out),
        prompt("Read the source", "test -f src/a.txt")
    );
}

#[test]
fn the_prompt_is_the_item_its_check_and_the_rules() {
    let text = prompt("Make the greeting say bye", "grep -q bye a.txt");
    assert!(text.contains("Make the greeting say bye"));
    assert!(text.contains("grep -q bye a.txt"));
    assert!(text.contains(RULES));
    // Section 9's ten rules, each numbered.
    for n in 1..=10 {
        assert!(
            RULES.contains(&format!("\n{n}. ")) || RULES.starts_with(&format!("{n}. ")),
            "rule {n}"
        );
    }
}

#[test]
fn a_worker_past_its_limit_is_timed_out() {
    let repo = Repo::new(&[("a.txt", "x\n")]);
    let sb = sandbox(&repo);
    let path = script(&repo, "slow.sh", "#!/bin/sh\nsleep 600\n");
    let status = from_name(&format!("script:{}", path.display()))
        .unwrap()
        .run(&sb, "t", "true", 1, &mut seen())
        .unwrap();
    assert!(status.timed_out);
    assert_ne!(status.exit_code, 0);
}

#[test]
fn the_claude_command_is_the_plans() {
    let worker = ClaudeWorker::new("opus");
    assert_eq!(worker.program(), "claude");
    assert_eq!(
        worker.args(Path::new("/turns/a1.claude-settings.json")),
        strings(&[
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--permission-mode",
            "dontAsk",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--setting-sources",
            "project,local",
            "--settings",
            "/turns/a1.claude-settings.json",
            "--model",
            "opus",
        ])
    );
}

#[test]
fn the_claude_settings_allow_only_file_and_shell_tools_in_the_sandbox() {
    let repo = Repo::new(&[("a.txt", "x\n")]);
    let sb = sandbox(&repo);
    let settings = ClaudeWorker::settings(&sb);
    let dir = sb.dir.to_str().unwrap();
    assert_eq!(settings["permissions"]["defaultMode"], "dontAsk");
    let allow = settings["permissions"]["allow"].as_array().unwrap();
    assert!(allow.iter().any(|r| r == "Bash"));
    for rule in allow {
        let rule = rule.as_str().unwrap();
        let scoped = ["Read", "Grep", "Edit"]
            .iter()
            .any(|tool| rule == format!("{tool}(/{dir}/**)"));
        assert!(
            rule == "Bash" || scoped,
            "{rule} reaches outside the file and shell tools in the sandbox"
        );
    }
    let deny: Vec<&str> = settings["permissions"]["deny"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|r| r.as_str())
        .collect();
    for tool in ["WebFetch", "WebSearch", "NotebookEdit", "Task"] {
        assert!(deny.contains(&tool), "{tool} is not denied");
    }
    assert_eq!(settings["sandbox"]["enabled"], true);
    assert_eq!(settings["sandbox"]["allowUnsandboxedCommands"], false);
    assert_eq!(
        settings["sandbox"]["filesystem"]["allowWrite"],
        serde_json::json!([dir])
    );
    assert_eq!(
        settings["sandbox"]["network"]["allowedDomains"],
        serde_json::json!([])
    );
    assert_eq!(settings["disableAllHooks"], true);
    // Keys and accounts on this machine are not readable from the shell, named as absolute paths.
    let deny_read: Vec<&str> = settings["sandbox"]["filesystem"]["denyRead"]
        .as_array()
        .unwrap()
        .iter()
        .filter_map(|p| p.as_str())
        .collect();
    assert!(
        deny_read.iter().all(|p| !p.starts_with('~')),
        "{deny_read:?}"
    );
    if let Some(home) = std::env::var_os("HOME") {
        let ssh = Path::new(&home).join(".ssh");
        assert!(deny_read.contains(&ssh.to_str().unwrap()), "{deny_read:?}");
    }
}

#[test]
fn the_codex_command_is_the_plans() {
    let repo = Repo::new(&[("a.txt", "x\n")]);
    let sb = sandbox(&repo);
    let worker = CodexWorker::new("gpt-6.1-sol");
    assert_eq!(worker.program(), "codex");
    assert_eq!(
        worker.args(&sb),
        strings(&[
            "exec",
            "--json",
            "-s",
            "workspace-write",
            "-C",
            sb.dir.to_str().unwrap(),
            "-m",
            "gpt-6.1-sol",
            "--ephemeral",
            "--ignore-user-config",
            "-c",
            "approval_policy=\"never\"",
            "-c",
            "web_search=\"disabled\"",
            "-",
        ])
    );
}

/// A stand-in for a CLI: it keeps its arguments, its stdin and the settings file it was given, changes a.txt
/// without committing, and prints `fixture` as if it had done the work.
fn stand_in(repo: &Repo, name: &str, fixture: &str) -> PathBuf {
    let body = format!(
        "#!/bin/sh\nprintf '%s\\n' \"$@\" > '{args}'\ncat > '{prompt}'\n\
         while [ $# -gt 0 ]; do [ \"$1\" = --settings ] && cp \"$2\" '{settings}'; shift; done\n\
         echo changed > a.txt\nsed \"s#/sandbox#$PWD#g\" '{fixture}'\n",
        args = repo.scratch("args.txt").display(),
        prompt = repo.scratch("prompt.txt").display(),
        settings = repo.scratch("settings-seen.json").display(),
        fixture = data(fixture),
    );
    script(repo, name, &body)
}

#[test]
fn a_claude_worker_reads_its_stream_and_its_work_is_committed() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let fake = stand_in(&repo, "claude", "claude-stream-ids.jsonl");
    let worker = ClaudeWorker::with_program("opus", fake.to_str().unwrap());
    assert_eq!(worker.name(), "claude:opus");
    let mut seen = seen();
    let status = worker
        .run(
            &sb,
            "Make the greeting say bye",
            "grep -q bye a.txt",
            60,
            &mut seen,
        )
        .unwrap();
    assert_eq!(status.exit_code, 0);
    assert_eq!(oks(&seen.steps), [true, true, false]);
    assert_eq!(seen.steps[0].target, tracked(&repo, "a.txt"));

    let args: Vec<String> = read(&repo.scratch("args.txt"))
        .lines()
        .map(str::to_string)
        .collect();
    let settings = ClaudeWorker::settings_path(&sb);
    assert_eq!(args, worker.args(&settings));
    assert!(
        !settings.starts_with(&sb.dir),
        "the settings file is not in the clone"
    );
    assert!(
        !settings.exists(),
        "the settings file is removed after the run"
    );
    let seen: serde_json::Value =
        serde_json::from_str(&read(&repo.scratch("settings-seen.json"))).unwrap();
    assert_eq!(seen, ClaudeWorker::settings(&sb));
    assert_eq!(
        read(&repo.scratch("prompt.txt")),
        prompt("Make the greeting say bye", "grep -q bye a.txt")
    );

    // The change it left uncommitted is committed for it, on the turn's branch.
    assert_ne!(sb.head().unwrap(), repo.base);
    assert_eq!(git(&sb.dir, &["show", "HEAD:a.txt"]), "changed");
    assert_eq!(
        git(&sb.dir, &["rev-parse", "--abbrev-ref", "HEAD"]),
        "room/i1/1"
    );
    let message = git(&sb.dir, &["log", "-1", "--format=%B"]);
    assert!(message.contains("Made by claude:opus."), "{message}");
    assert_eq!(git(&sb.dir, &["status", "--porcelain"]), "");
}

#[test]
fn a_codex_worker_reads_its_stream_and_its_work_is_committed() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let fake = stand_in(&repo, "codex", "codex-json-sample.jsonl");
    let worker = CodexWorker::with_program("gpt-6.1-sol", fake.to_str().unwrap());
    assert_eq!(worker.name(), "codex:gpt-6.1-sol");
    let mut seen = seen();
    let status = worker
        .run(
            &sb,
            "Make the greeting say bye",
            "grep -q bye a.txt",
            60,
            &mut seen,
        )
        .unwrap();
    assert_eq!(status.exit_code, 0);
    assert_eq!(oks(&seen.steps), [true, true, false]);
    assert_eq!(seen.steps[0].target, tracked(&repo, "a.txt"));
    let args: Vec<String> = read(&repo.scratch("args.txt"))
        .lines()
        .map(str::to_string)
        .collect();
    assert_eq!(args, worker.args(&sb));
    assert_eq!(
        read(&repo.scratch("prompt.txt")),
        prompt("Make the greeting say bye", "grep -q bye a.txt")
    );
    assert_eq!(git(&sb.dir, &["show", "HEAD:a.txt"]), "changed");
    let message = git(&sb.dir, &["log", "-1", "--format=%B"]);
    assert!(message.contains("Made by codex:gpt-6.1-sol."), "{message}");
}

#[test]
fn an_agent_that_changed_nothing_leaves_no_commit() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let quiet = script(&repo, "claude", "#!/bin/sh\ncat > /dev/null\n");
    let mut seen = seen();
    let status = ClaudeWorker::with_program("opus", quiet.to_str().unwrap())
        .run(&sb, "t", "true", 60, &mut seen)
        .unwrap();
    assert_eq!(status.exit_code, 0);
    assert!(seen.steps.is_empty());
    assert_eq!(sb.head().unwrap(), repo.base);
}

#[test]
fn nothing_a_worker_plants_in_its_git_directory_runs_when_the_room_commits() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let marker = |n: u32| repo.scratch(&format!("ran-{n}"));
    let evil = repo.scratch("evil");
    // A filter driver, a filesystem monitor, a second config through worktreeConfig, a common directory
    // elsewhere with its own driver, a stale index lock, and another branch checked out.
    let body = format!(
        "#!/bin/sh\ncat > /dev/null\n\
         git checkout -q -b elsewhere\n\
         git config filter.evil.clean \"touch '{m1}'; cat\"\n\
         git config core.fsmonitor \"touch '{m2}'; false\"\n\
         git config core.repositoryformatversion 1\n\
         git config extensions.worktreeConfig true\n\
         printf '[filter \"evil\"]\\n\\tclean = touch {m3}; cat\\n' > .git/config.worktree\n\
         mkdir -p '{evil}' && printf '[filter \"evil\"]\\n\\tclean = touch {m4}; cat\\n' > '{evil}/config'\n\
         printf '* filter=evil\\n' > .gitattributes\n\
         echo changed > a.txt\n\
         touch .git/index.lock\n\
         printf '%s\\n' '{evil}' > .git/commondir\n",
        m1 = marker(1).display(),
        m2 = marker(2).display(),
        m3 = marker(3).display(),
        m4 = marker(4).display(),
        evil = evil.display(),
    );
    let fake = script(&repo, "claude", &body);
    let status = ClaudeWorker::with_program("opus", fake.to_str().unwrap())
        .run(&sb, "t", "true", 60, &mut seen())
        .unwrap();
    assert_eq!(status.exit_code, 0);
    for n in 1..=4 {
        assert!(!marker(n).exists(), "the room ran the worker's command {n}");
    }
    // The work itself is committed, on the turn's branch.
    assert_eq!(
        git(&sb.dir, &["rev-parse", "--abbrev-ref", "HEAD"]),
        "room/i1/1"
    );
    assert_eq!(git(&sb.dir, &["show", "room/i1/1:a.txt"]), "changed");
    assert_eq!(
        sb.head().unwrap(),
        git(&sb.dir, &["rev-parse", "room/i1/1"])
    );
}

#[test]
fn the_room_requires_plain_git_metadata_at_every_depth() {
    for name in [
        "logs/HEAD",
        "refs/heads/deep/canary",
        "objects/info/deep/canary",
    ] {
        let repo = Repo::new(&[("a.txt", "hello\n")]);
        let sb = sandbox(&repo);
        let canary = repo.scratch("canary");
        std::fs::write(&canary, "untouched\n").unwrap();
        let link = sb.dir.join(".git").join(name);
        std::fs::create_dir_all(link.parent().unwrap()).unwrap();
        if link.exists() {
            std::fs::remove_file(&link).unwrap();
        }
        std::os::unix::fs::symlink(&canary, &link).unwrap();
        let fake = script(
            &repo,
            "worker",
            "#!/bin/sh\ncat >/dev/null\necho changed >a.txt\n",
        );
        let result = CodexWorker::with_program("test", fake.to_str().unwrap()).run(
            &sb,
            "t",
            "true",
            30,
            &mut seen(),
        );
        let intact = read(&canary) == "untouched\n";
        assert!(intact, "canary changed for {name}");
        assert!(
            matches!(result, Err(TurnError::Refused(_))),
            "{name}: {result:?}"
        );
    }
}

#[test]
fn the_room_accepts_only_a_single_repository_tree() {
    for git_file in [false, true] {
        let repo = Repo::new(&[("a.txt", "hello\n")]);
        let sb = sandbox(&repo);
        let nested = sb.dir.join("nested/deep");
        std::fs::create_dir_all(&nested).unwrap();
        git(&nested, &["init", "-q"]);
        std::fs::write(nested.join(".gitattributes"), "* filter=canary\n").unwrap();
        std::fs::write(nested.join("file"), "base\n").unwrap();
        git(&nested, &["add", "."]);
        git(&nested, &["commit", "-qm", "fixture"]);
        let nested_head = git(&nested, &["rev-parse", "HEAD"]);
        git(
            &sb.dir,
            &[
                "update-index",
                "--add",
                "--cacheinfo",
                &format!("160000,{nested_head},nested/deep"),
            ],
        );
        let marker = repo.scratch("marker");
        git(
            &nested,
            &[
                "config",
                "filter.canary.clean",
                &format!("touch '{}'; cat", marker.display()),
            ],
        );
        std::fs::write(nested.join("file"), "changed\n").unwrap();
        if git_file {
            let metadata = repo.scratch("nested-metadata");
            std::fs::rename(nested.join(".git"), &metadata).unwrap();
            std::fs::write(
                nested.join(".git"),
                format!("gitdir: {}\n", metadata.display()),
            )
            .unwrap();
        }
        let fake = script(
            &repo,
            "worker",
            "#!/bin/sh\ncat >/dev/null\necho changed >a.txt\n",
        );
        let result = CodexWorker::with_program("test", fake.to_str().unwrap()).run(
            &sb,
            "t",
            "true",
            30,
            &mut seen(),
        );
        assert!(!marker.exists(), "the marker stays unwritten");
        assert!(matches!(result, Err(TurnError::Refused(_))), "{result:?}");
    }
}

#[test]
fn the_room_requires_an_index_without_gitlinks() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    git(
        &sb.dir,
        &[
            "update-index",
            "--add",
            "--cacheinfo",
            &format!("160000,{},nested", repo.base),
        ],
    );
    let fake = script(&repo, "worker", "#!/bin/sh\ncat >/dev/null\n");
    let result = CodexWorker::with_program("test", fake.to_str().unwrap()).run(
        &sb,
        "t",
        "true",
        30,
        &mut seen(),
    );
    assert!(matches!(result, Err(TurnError::Refused(_))), "{result:?}");
}

#[test]
fn room_commits_leave_no_reflogs() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let head = sb.dir.join(".git/logs/HEAD");
    let branch = sb.dir.join(".git/logs/refs/heads/room/i1/1");
    std::fs::create_dir_all(branch.parent().unwrap()).unwrap();
    std::fs::write(&head, "fixture\n").unwrap();
    std::fs::write(&branch, "fixture\n").unwrap();
    let fake = script(
        &repo,
        "worker",
        "#!/bin/sh\ncat >/dev/null\necho changed >a.txt\n",
    );
    CodexWorker::with_program("test", fake.to_str().unwrap())
        .run(&sb, "t", "true", 30, &mut seen())
        .unwrap();
    assert!(!head.exists());
    assert!(!branch.exists());
}
