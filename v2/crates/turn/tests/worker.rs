//! Task 8: workers. No test starts a real `claude` or `codex`: their command lines are checked as built, and
//! their runs are driven through stand-in programs that print the real sample streams.

mod common;

use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use common::{Repo, git, strings};
use room::{Step, Target, Tokens, Tool};
use turn::worker::{ClaudeWorker, CodexWorker, RULES, Seen, Worker, from_name, prompt};
use turn::{RunStatus, Sandbox, TurnError};

/// A fresh `Seen` to pass into `Worker::run`, for a turn that starts now.
fn seen() -> Seen {
    Seen {
        steps: Vec::new(),
        tokens: Tokens::none(),
        steps_seen: 0,
        started: Instant::now(),
        seal_ms: 0,
        status: None,
    }
}

/// A test's sandbox, removed by the room's own `destroy` when the test is done with it. A model worker's run
/// makes the turn's own temporary directory under `/tmp`, outside the repository's temporary directory, and it
/// would otherwise be left there after every test.
struct Made(Option<Sandbox>);

impl std::ops::Deref for Made {
    type Target = Sandbox;
    fn deref(&self) -> &Sandbox {
        self.0.as_ref().unwrap()
    }
}

impl Drop for Made {
    fn drop(&mut self) {
        if let Some(sb) = self.0.take() {
            let _ = sb.destroy();
        }
    }
}

fn sandbox(repo: &Repo) -> Made {
    Made(Some(
        Sandbox::create(
            &repo.path,
            &repo.base,
            &repo.scratch("sandbox"),
            "room/i1/1",
        )
        .unwrap(),
    ))
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
    let mut seen = seen();
    let status = from_name(&format!("script:{}", path.display()))
        .unwrap()
        .run(&sb, "t", "true", 1, &mut seen)
        .unwrap();
    assert!(status.timed_out);
    assert_ne!(status.exit_code, 0);
    // How the program ended is in what the room saw, too, and a script commits for itself.
    assert_eq!(seen.status, Some(status));
    assert_eq!(seen.seal_ms, 0);
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
    let settings = ClaudeWorker::settings(&sb).unwrap();
    let tmp = sb.worker_tmp().unwrap();
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
    // The shell writes in the clone and in the turn's own temporary directory, and nowhere else.
    assert_eq!(
        settings["sandbox"]["filesystem"]["allowWrite"],
        serde_json::json!([dir, tmp.to_str().unwrap()])
    );
    assert_eq!(
        settings["sandbox"]["network"]["allowedDomains"],
        serde_json::json!([])
    );
    assert_eq!(settings["disableAllHooks"], true);
    // The home is not readable from the shell, as a whole and first, named as an absolute path.
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
    let home = turn::jail::places().unwrap().home;
    assert_eq!(deny_read.first(), home.to_str().as_ref(), "{deny_read:?}");
}

#[test]
fn the_codex_command_is_the_plans() {
    let repo = Repo::new(&[("a.txt", "x\n")]);
    let sb = sandbox(&repo);
    let worker = CodexWorker::new("gpt-6.1-sol");
    assert_eq!(worker.program(), "codex");
    let args = worker.args(&sb).unwrap();
    // The table of what the shell may reach depends on this machine and its settings: it is compared whole in
    // `codex_is_given_a_profile_and_no_sandbox_mode`, under settings that test chose. Here, its frame.
    let table = &args[7];
    assert!(
        table.starts_with(
            "permissions.yak.filesystem={\":root\"=\"deny\", \":minimal\"=\"read\", \":slash_tmp\"=\"deny\", "
        ) && table.ends_with('}'),
        "{table}"
    );
    assert_eq!(
        args,
        strings(&[
            "exec",
            "--json",
            "-c",
            "default_permissions=\"yak\"",
            "-c",
            "permissions.yak.extends=\":workspace\"",
            "-c",
            table,
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
    // The program's closing total, and when each step was seen and answered.
    assert_eq!(seen.tokens.total(), Some(37_220));
    assert_eq!(seen.steps_seen, 3);
    for step in &seen.steps {
        assert!(
            step.seen_ms.is_some() && step.result_ms >= step.seen_ms,
            "{step:?}"
        );
    }

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
    assert_eq!(seen, ClaudeWorker::settings(&sb).unwrap());
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
    assert_eq!(seen.tokens.total(), Some(46_441 + 100));
    assert_eq!(seen.steps_seen, 3);
    for step in &seen.steps {
        assert!(
            step.seen_ms.is_some() && step.result_ms >= step.seen_ms,
            "{step:?}"
        );
    }
    let args: Vec<String> = read(&repo.scratch("args.txt"))
        .lines()
        .map(str::to_string)
        .collect();
    assert_eq!(args, worker.args(&sb).unwrap());
    assert_eq!(
        read(&repo.scratch("prompt.txt")),
        prompt("Make the greeting say bye", "grep -q bye a.txt")
    );
    assert_eq!(git(&sb.dir, &["show", "HEAD:a.txt"]), "changed");
    let message = git(&sb.dir, &["log", "-1", "--format=%B"]);
    assert!(message.contains("Made by codex:gpt-6.1-sol."), "{message}");
}

/// A stand-in that prints the lines of `fixture` a sed address list picks, changes a.txt, and then leaves the
/// clone's git directory in a state the room refuses to commit in: a link among its refs.
fn breaker(repo: &Repo, name: &str, fixture: &str, lines: &str) -> PathBuf {
    let body = format!(
        "#!/bin/sh\ncat > /dev/null\nsed -n '{lines}' '{fixture}' | sed \"s#/sandbox#$PWD#g\"\n\
         echo changed > a.txt\nln -s /tmp .git/refs/broken\n",
        fixture = data(fixture),
    );
    script(repo, name, &body)
}

#[test]
fn what_was_seen_is_kept_when_the_run_ends_in_an_error() {
    // Claude: Read a.txt and its result, the call to `ls`, and the closing total.
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let fake = breaker(&repo, "claude", "claude-stream-ids.jsonl", "1,4p;13p");
    let mut kept = seen();
    let result = ClaudeWorker::with_program("opus", fake.to_str().unwrap())
        .run(&sb, "t", "true", 60, &mut kept);
    // The room's commit for it is refused.
    assert!(matches!(result, Err(TurnError::Refused(_))), "{result:?}");
    assert_eq!(kept.steps.len(), 2);
    assert_eq!(kept.steps[0].target, tracked(&repo, "a.txt"));
    assert_eq!(kept.steps_seen, 2);
    assert_eq!(kept.tokens.total(), Some(37_220));
    // How its program ended was kept before the room's commit was tried.
    assert_eq!(
        kept.status,
        Some(RunStatus {
            exit_code: 0,
            timed_out: false,
            stopped: false,
        })
    );
    // Codex: two commands and the closing total.
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let fake = breaker(&repo, "codex", "codex-json-sample.jsonl", "1,7p;11p");
    let mut kept = seen();
    let result = CodexWorker::with_program("test", fake.to_str().unwrap())
        .run(&sb, "t", "true", 60, &mut kept);
    assert!(matches!(result, Err(TurnError::Refused(_))), "{result:?}");
    assert_eq!(oks(&kept.steps), [true, true]);
    assert_eq!(kept.steps_seen, 2);
    assert_eq!(kept.tokens.total(), Some(46_541));
    assert_eq!(
        kept.status,
        Some(RunStatus {
            exit_code: 0,
            timed_out: false,
            stopped: false,
        })
    );
}

/// A step's times count from the turn's start as the `Seen` says it, not from when the worker began: the room
/// makes the sandbox in between, and that is the turn's time too.
#[test]
fn a_steps_times_count_from_the_turns_start() {
    let earlier = |seen: &mut Seen| {
        seen.started = Instant::now()
            .checked_sub(Duration::from_secs(5))
            .expect("this machine has been up five seconds");
    };
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sample = read(Path::new(&data("claude-stream-ids.jsonl")));
    let body = format!(
        "#!/bin/sh\ncat > /dev/null\nsed \"s#/sandbox#$PWD#g\" <<'YAK_SAMPLE'\n{}\nYAK_SAMPLE\n",
        sample.trim_end()
    );
    let path = script(&repo, "steps.sh", &body);
    let script_worker = from_name(&format!("script:{}", path.display())).unwrap();
    let claude = stand_in(&repo, "claude", "claude-stream-ids.jsonl");
    let codex = stand_in(&repo, "codex", "codex-json-sample.jsonl");
    let workers: [Box<dyn Worker>; 3] = [
        script_worker,
        Box::new(ClaudeWorker::with_program("opus", claude.to_str().unwrap())),
        Box::new(CodexWorker::with_program("test", codex.to_str().unwrap())),
    ];
    for worker in workers {
        let repo = Repo::new(&[("a.txt", "hello\n")]);
        let sb = sandbox(&repo);
        let mut seen = seen();
        earlier(&mut seen);
        worker.run(&sb, "t", "true", 60, &mut seen).unwrap();
        assert!(!seen.steps.is_empty(), "{}", worker.name());
        for step in &seen.steps {
            assert!(
                step.seen_ms.unwrap() >= 5_000,
                "{}: {step:?}",
                worker.name()
            );
            if let Some(result) = step.result_ms {
                assert!(result >= 5_000, "{}: {step:?}", worker.name());
            }
        }
    }
}

/// The room's commit for a model worker is timed by the worker, apart from the program's own run. A script
/// worker commits for itself, so the room's commit takes it no time.
#[test]
fn the_rooms_commit_for_a_worker_is_timed_apart_from_its_program() {
    for family in ["claude", "codex"] {
        let repo = Repo::new(&[("a.txt", "hello\n")]);
        let sb = sandbox(&repo);
        let fake = leaver(&repo, family, ":");
        let fake = fake.to_str().unwrap();
        let worker: Box<dyn Worker> = match family {
            "codex" => Box::new(CodexWorker::with_program("test", fake)),
            _ => Box::new(ClaudeWorker::with_program("test", fake)),
        };
        let mut seen = seen();
        let began = Instant::now();
        worker.run(&sb, "t", "true", 60, &mut seen).unwrap();
        let whole = began.elapsed();
        assert_ne!(
            sb.head().unwrap(),
            repo.base,
            "{family}: nothing was committed"
        );
        // Three runs of git at least: some milliseconds, and never more than the whole run.
        assert!(seen.seal_ms > 0, "{family}");
        assert!(
            u128::from(seen.seal_ms) <= whole.as_millis(),
            "{family}: {} of {whole:?}",
            seen.seal_ms
        );
    }
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let path = script(
        &repo,
        "commits.sh",
        "#!/bin/sh\necho changed > a.txt\ngit commit -qam mine\n",
    );
    let mut seen = seen();
    from_name(&format!("script:{}", path.display()))
        .unwrap()
        .run(&sb, "t", "true", 60, &mut seen)
        .unwrap();
    assert_eq!(seen.seal_ms, 0);
}

#[test]
fn a_script_workers_stream_gives_its_tokens() {
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    // The stream goes into the script itself, which is all of this tree a jailed script is shown.
    let sample = read(Path::new(&data("claude-stream-ids.jsonl")));
    assert!(!sample.contains("YAK_SAMPLE"));
    let body = format!(
        "#!/bin/sh\ncat > /dev/null\nsed \"s#/sandbox#$PWD#g\" <<'YAK_SAMPLE'\n{}\nYAK_SAMPLE\n",
        sample.trim_end()
    );
    let path = script(&repo, "tokens.sh", &body);
    let mut seen = seen();
    from_name(&format!("script:{}", path.display()))
        .unwrap()
        .run(&sb, "t", "true", 60, &mut seen)
        .unwrap();
    assert_eq!(oks(&seen.steps), [true, true, false]);
    assert_eq!(seen.tokens.total(), Some(37_220));
    assert!(seen.tokens.complete);
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

// --- A worker that cannot commit can still say what it did -------------------------------------------------

/// A stand-in that changes a.txt, then runs `then` in the clone, and prints nothing.
fn leaver(repo: &Repo, name: &str, then: &str) -> PathBuf {
    script(
        repo,
        name,
        &format!("#!/bin/sh\ncat > /dev/null\necho changed > a.txt\n{then}\n"),
    )
}

fn last_message(sb: &Sandbox) -> String {
    git(&sb.dir, &["log", "-1", "--format=%B"])
}

fn committed(sb: &Sandbox) -> Vec<String> {
    git(&sb.dir, &["ls-tree", "-r", "--name-only", "HEAD"])
        .lines()
        .map(str::to_string)
        .collect()
}

fn message_file(sb: &Sandbox) -> Option<std::fs::Metadata> {
    std::fs::symlink_metadata(sb.dir.join(".yak-message")).ok()
}

#[test]
fn a_worker_that_cannot_commit_leaves_its_message() {
    let leave = "printf 'Make the greeting say bye\\n\\nIt said hello.\\n' > .yak-message";
    for family in ["codex", "claude"] {
        let repo = Repo::new(&[("a.txt", "hello\n")]);
        let sb = sandbox(&repo);
        let fake = leaver(&repo, family, leave);
        let fake = fake.to_str().unwrap();
        let (worker, coauthor): (Box<dyn Worker>, &str) = match family {
            "codex" => (
                Box::new(CodexWorker::with_program("test", fake)),
                "Codex <noreply@openai.com>",
            ),
            _ => (
                Box::new(ClaudeWorker::with_program("test", fake)),
                "Claude <noreply@anthropic.com>",
            ),
        };
        worker.run(&sb, "t", "true", 60, &mut seen()).unwrap();
        assert_eq!(
            last_message(&sb),
            format!(
                "Make the greeting say bye\n\nIt said hello.\n\nMade by {family}:test.\n\
                 Co-Authored-By: {coauthor}"
            )
        );
        assert_eq!(committed(&sb), ["a.txt"]);
        assert_eq!(git(&sb.dir, &["show", "HEAD:a.txt"]), "changed");
        assert!(
            message_file(&sb).is_none(),
            "the message file is still there"
        );
    }
    // At its limit it is still read.
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let fake = leaver(
        &repo,
        "codex",
        "head -c 16384 /dev/zero | tr '\\000' a > .yak-message",
    );
    CodexWorker::with_program("test", fake.to_str().unwrap())
        .run(&sb, "t", "true", 60, &mut seen())
        .unwrap();
    assert!(last_message(&sb).starts_with(&"a".repeat(16_384)));
    assert!(message_file(&sb).is_none());
    // A message and no other change: nothing to commit, and the file is gone all the same.
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let fake = script(
        &repo,
        "codex",
        "#!/bin/sh\ncat > /dev/null\necho 'Nothing needed' > .yak-message\n",
    );
    CodexWorker::with_program("test", fake.to_str().unwrap())
        .run(&sb, "t", "true", 60, &mut seen())
        .unwrap();
    assert_eq!(sb.head().unwrap(), repo.base);
    assert!(message_file(&sb).is_none());
}

#[test]
fn a_message_file_that_is_not_a_plain_file_is_not_read() {
    let fixed = "Turn by codex:test, committed by the room.\n\nMade by codex:test.\nCo-Authored-By: Codex <noreply@openai.com>";
    // A link is removed and not followed; a file the room cannot use is removed and not read. A directory or a
    // pipe there stops the room's commit: `something_at_the_message_path_that_is_not_a_file_stops_the_rooms_commit`.
    let cases = [
        (
            "a link",
            "printf 'Read through a link\\n' > ../outside && ln -s ../outside .yak-message",
        ),
        (
            "too long",
            "head -c 16385 /dev/zero | tr '\\000' a > .yak-message",
        ),
        ("empty", ": > .yak-message"),
        ("blank", "printf ' \\n\\n\\t\\n' > .yak-message"),
        ("not UTF-8", "printf 'caf\\351\\n' > .yak-message"),
        ("a NUL", "printf 'a\\000b\\n' > .yak-message"),
    ];
    for (what, leave) in cases {
        let repo = Repo::new(&[("a.txt", "hello\n")]);
        let sb = sandbox(&repo);
        let fake = leaver(&repo, "codex", leave);
        CodexWorker::with_program("test", fake.to_str().unwrap())
            .run(&sb, "t", "true", 60, &mut seen())
            .unwrap_or_else(|e| panic!("{what}: {e}"));
        assert_eq!(last_message(&sb), fixed, "{what}");
        assert_eq!(git(&sb.dir, &["show", "HEAD:a.txt"]), "changed", "{what}");
        assert!(message_file(&sb).is_none(), "{what}: something is left");
        assert!(
            !committed(&sb).iter().any(|p| p.starts_with(".yak-message")),
            "{what}"
        );
    }
    // What the link pointed at is untouched.
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let fake = leaver(
        &repo,
        "codex",
        "printf 'kept\\n' > ../outside && ln -s ../outside .yak-message",
    );
    CodexWorker::with_program("test", fake.to_str().unwrap())
        .run(&sb, "t", "true", 60, &mut seen())
        .unwrap();
    assert_eq!(read(&sb.dir.with_file_name("outside")), "kept\n");
}

/// A model worker of each family whose program is `fake`.
fn family_worker(family: &str, fake: &Path) -> Box<dyn Worker> {
    let fake = fake.to_str().unwrap();
    match family {
        "codex" => Box::new(CodexWorker::with_program("test", fake)),
        _ => Box::new(ClaudeWorker::with_program("test", fake)),
    }
}

/// A repository whose base tracks `name`, made by `make` in its tree, beside a.txt.
fn tracking(name: &str, make: impl FnOnce(&Path)) -> Repo {
    let mut repo = Repo::new(&[("a.txt", "hello\n")]);
    make(&repo.path.join(name));
    repo.base = repo.commit("tracks the message file's name");
    assert!(
        git(&repo.path, &["ls-tree", "-z", "--name-only", &repo.base])
            .split('\0')
            .any(|tracked| tracked == name),
        "{name} is not tracked"
    );
    repo
}

/// When the base already tracks something at the message file's name, in any letter case, it is the item's
/// own file: the room neither reads it nor removes it, and for that turn there is no message file. A worker that
/// leaves it as it was changes nothing, so nothing is committed, and it is still there as it was.
#[test]
fn a_message_file_the_base_tracks_is_neither_read_nor_removed() {
    // Bytes no message could be: not UTF-8, a NUL, no newline at the end.
    let bytes: &[u8] = b"tracked \xff\x00 by the item";
    for family in ["claude", "codex"] {
        // A plain file.
        let repo = tracking(".yak-message", |path| std::fs::write(path, bytes).unwrap());
        let sb = sandbox(&repo);
        let quiet = script(&repo, family, "#!/bin/sh\ncat > /dev/null\n");
        family_worker(family, &quiet)
            .run(&sb, "t", "true", 60, &mut seen())
            .unwrap();
        assert_eq!(sb.head().unwrap(), repo.base, "{family}: a file");
        assert_eq!(std::fs::read(sb.dir.join(".yak-message")).unwrap(), bytes);
        // A link, to a file of the repository.
        let repo = tracking(".yak-message", |path| {
            std::os::unix::fs::symlink("a.txt", path).unwrap()
        });
        let sb = sandbox(&repo);
        let quiet = script(&repo, family, "#!/bin/sh\ncat > /dev/null\n");
        family_worker(family, &quiet)
            .run(&sb, "t", "true", 60, &mut seen())
            .unwrap();
        assert_eq!(sb.head().unwrap(), repo.base, "{family}: a link");
        assert_eq!(
            std::fs::read_link(sb.dir.join(".yak-message")).unwrap(),
            Path::new("a.txt")
        );
        // In other letters. Where the disk does not tell capital letters from small ones, this is the file the
        // room would find at `.yak-message`.
        let repo = tracking(".Yak-Message", |path| std::fs::write(path, bytes).unwrap());
        let sb = sandbox(&repo);
        let quiet = script(&repo, family, "#!/bin/sh\ncat > /dev/null\n");
        family_worker(family, &quiet)
            .run(&sb, "t", "true", 60, &mut seen())
            .unwrap();
        assert_eq!(sb.head().unwrap(), repo.base, "{family}: other letters");
        assert_eq!(std::fs::read(sb.dir.join(".Yak-Message")).unwrap(), bytes);
    }
}

/// The same holds on a disk that tells letters apart: with the base tracking the name in other letters, a
/// `.yak-message` the worker writes is not taken as its message. It is committed with the room's fixed message
/// as any other change is (on a disk that does not tell them apart it is the tracked file, changed), and it is
/// still there afterwards.
#[test]
fn with_the_name_tracked_in_other_letters_no_message_file_is_read() {
    // The second is spelled with the Kelvin sign, which folds to a small k.
    for tracked in [".Yak-Message", ".YAK-MESSAGE", ".ya\u{212A}-message"] {
        for family in ["claude", "codex"] {
            let repo = tracking(tracked, |path| std::fs::write(path, "tracked\n").unwrap());
            let sb = sandbox(&repo);
            let fake = script(
                &repo,
                family,
                "#!/bin/sh\ncat > /dev/null\necho changed > a.txt\nprintf 'Not read\\n' > .yak-message\n",
            );
            family_worker(family, &fake)
                .run(&sb, "t", "true", 60, &mut seen())
                .unwrap();
            assert!(
                last_message(&sb).starts_with("Turn by "),
                "{tracked} {family}: {}",
                last_message(&sb)
            );
            assert!(message_file(&sb).is_some(), "{tracked} {family}: removed");
        }
    }
}

/// When the base does not track the name and something at it after the worker's run is neither a plain file
/// nor a link, the room does not commit for the worker: it says what it found, and where. Nothing of it is
/// staged, and no commit holds what was in it.
#[test]
fn something_at_the_message_path_that_is_not_a_file_stops_the_rooms_commit() {
    const MARKER: &str = "yak-marker-7f3c1a";
    let cases = [
        (
            "a directory",
            format!("mkdir .yak-message && printf '{MARKER}\\n' > .yak-message/note"),
        ),
        ("a named pipe", "mkfifo .yak-message".to_string()),
    ];
    for family in ["claude", "codex"] {
        for (what, leave) in &cases {
            let repo = Repo::new(&[("a.txt", "hello\n")]);
            let sb = sandbox(&repo);
            let fake = leaver(&repo, family, leave);
            let result = family_worker(family, &fake).run(&sb, "t", "true", 60, &mut seen());
            let path = sb.dir.join(".yak-message");
            match &result {
                Err(TurnError::Refused(why)) => {
                    assert!(why.contains(&path.display().to_string()), "{why}");
                    assert!(why.contains(&format!("is {what}")), "{why}");
                }
                other => panic!("{family} {what}: {other:?}"),
            }
            assert_eq!(sb.head().unwrap(), repo.base, "{family} {what}");
            assert_eq!(git(&sb.dir, &["diff", "--cached", "--name-only"]), "");
            let history = git(&sb.dir, &["log", "--all", "-p", "--format=%H %B"]);
            assert!(!history.contains(MARKER), "{family} {what}: {history}");
            // What was there is left there.
            assert!(message_file(&sb).is_some(), "{family} {what}");
        }
    }
}

#[test]
fn the_prompt_says_where_to_leave_a_message() {
    assert!(prompt("t", "true").contains(
        "If your tools cannot commit, leave your commit message in a file named `.yak-message` at the \
         repository's root and the room will commit for you with it."
    ));
}

// --- What a model worker's shell is shown (Task 4b) ----------------------------------------------------------

/// The inner half of the tests below, and nothing by itself. What a model worker's shell is shown is read from
/// the environment, as the room's jail reads it, and a test cannot change its own. So the outer half runs this
/// test again in a child whose environment it chose, and reads the one line the child prints: the sandbox, what
/// it hides and gives a worker, the jail's places, and both workers' settings, each as it came or as refused.
#[test]
fn inner_a_workers_reach_under_the_rooms_settings() {
    let Some(dir) = std::env::var_os("YAK_INNER_SANDBOX") else {
        return;
    };
    let repo = std::env::var_os("YAK_INNER_REPO").unwrap();
    let base = std::env::var("YAK_INNER_BASE").unwrap();
    let mut sb = Sandbox::create(Path::new(&repo), &base, Path::new(&dir), "room/i1/1").unwrap();
    if let Some(path) = std::env::var_os("YAK_INNER_HIDE") {
        sb.hide_from_worker(Path::new(&path)).unwrap();
    }
    let said = |answer: Result<serde_json::Value, TurnError>| match answer {
        Ok(value) => serde_json::json!({ "ok": value }),
        Err(e) => serde_json::json!({ "refused": e.to_string() }),
    };
    let places = turn::jail::places().map(|p| {
        serde_json::json!({ "home": p.home, "hidden": p.hidden, "shown": p.shown, "system": p.system })
    });
    let report = serde_json::json!({
        "dir": sb.dir,
        "hidden_from_worker": sb.hidden_from_worker(),
        "tmp": said(sb.worker_tmp().map(|tmp| serde_json::json!(tmp))),
        "shared": Sandbox::shared_tmp(),
        "places": said(places),
        "claude": said(ClaudeWorker::settings(&sb)),
        "codex": said(CodexWorker::new("m").args(&sb).map(|args| serde_json::json!(args))),
    });
    println!("REACH {report}");
    sb.destroy().unwrap();
}

/// What the inner half printed, with `vars` set, `without` taken out, and the room's own variables otherwise
/// taken out of the child's environment.
fn reach_without(
    repo: &Repo,
    vars: &[(&str, &std::ffi::OsStr)],
    without: &[&str],
) -> serde_json::Value {
    static SANDBOXES: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
    let n = SANDBOXES.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
    let mut child = std::process::Command::new(std::env::current_exe().unwrap());
    child
        .args([
            "--exact",
            "inner_a_workers_reach_under_the_rooms_settings",
            "--nocapture",
        ])
        .env("YAK_INNER_SANDBOX", repo.scratch(&format!("reach-{n}")))
        .env("YAK_INNER_REPO", &repo.path)
        .env("YAK_INNER_BASE", &repo.base)
        .env_remove("YAK_INNER_HIDE")
        .env_remove("YAK_JAIL_READ")
        .env_remove("CLAUDE_CONFIG_DIR")
        .env_remove("CODEX_HOME");
    for (name, value) in vars {
        child.env(name, value);
    }
    for name in without {
        child.env_remove(name);
    }
    let out = child.output().unwrap();
    let printed = String::from_utf8_lossy(&out.stdout);
    let line = printed
        .lines()
        .find_map(|line| line.strip_prefix("REACH "))
        .unwrap_or_else(|| {
            panic!(
                "the inner half did not report: {printed} {}",
                String::from_utf8_lossy(&out.stderr)
            )
        });
    serde_json::from_str(line).unwrap()
}

fn reach(repo: &Repo, vars: &[(&str, &std::ffi::OsStr)]) -> serde_json::Value {
    reach_without(repo, vars, &[])
}

/// The value the inner half got for `key`, which must not have been refused.
fn answer<'a>(report: &'a serde_json::Value, key: &str) -> &'a serde_json::Value {
    report[key]
        .get("ok")
        .unwrap_or_else(|| panic!("{key} was refused: {}", report[key]))
}

/// Why the inner half's `key` was refused; it must have been.
fn refusal<'a>(report: &'a serde_json::Value, key: &str) -> &'a str {
    report[key]["refused"]
        .as_str()
        .unwrap_or_else(|| panic!("{key} was not refused: {}", report[key]))
}

fn texts(value: &serde_json::Value) -> Vec<String> {
    value
        .as_array()
        .unwrap_or_else(|| panic!("not a list: {value}"))
        .iter()
        .map(|v| v.as_str().unwrap().to_string())
        .collect()
}

/// The real form of a path that is there, as text.
fn real(path: &Path) -> String {
    path.canonicalize().unwrap().to_str().unwrap().to_string()
}

/// A home with a place where keys are kept in it, a tool directory beside it, and room for more, all in one
/// temporary directory that is gone with it.
struct Places {
    _tmp: tempfile::TempDir,
    root: PathBuf,
    home: PathBuf,
    tool: PathBuf,
}

fn places() -> Places {
    let tmp = tempfile::tempdir().unwrap();
    let root = tmp.path().canonicalize().unwrap();
    let home = root.join("home");
    let tool = root.join("tools/bin");
    std::fs::create_dir_all(home.join(".ssh")).unwrap();
    std::fs::create_dir_all(&tool).unwrap();
    Places {
        _tmp: tmp,
        root,
        home,
        tool,
    }
}

/// The permission table among Codex's arguments, as given: the value after its `-c`.
fn table_of(args: &[String]) -> String {
    let at = args
        .iter()
        .position(|a| a.starts_with("permissions.yak.filesystem="))
        .unwrap_or_else(|| panic!("no permission table in {args:?}"));
    assert_eq!(args[at - 1], "-c", "{args:?}");
    args[at]["permissions.yak.filesystem=".len()..].to_string()
}

#[test]
fn claudes_shell_is_shown_the_sandbox_its_own_tmp_and_the_named_tools_and_not_the_home() {
    let repo = Repo::new(&[("a.txt", "x\n")]);
    let at = places();
    let added = at.root.join("added");
    std::fs::create_dir(&added).unwrap();
    let report = reach(
        &repo,
        &[
            ("HOME", at.home.as_os_str()),
            ("YAK_JAIL_READ", at.tool.as_os_str()),
            ("YAK_INNER_HIDE", added.as_os_str()),
        ],
    );
    let settings = answer(&report, "claude");
    let filesystem = &settings["sandbox"]["filesystem"];
    let dir = report["dir"].as_str().unwrap().to_string();
    let tmp = answer(&report, "tmp").as_str().unwrap().to_string();
    // The home first, then what the room hid, then the temporary directories every turn shares, then the home's
    // keys and settings, then the files of secrets wherever they are.
    let mut deny = vec![real(&at.home), real(&repo.path), real(&added)];
    let shared = texts(&report["shared"]);
    assert!(!shared.is_empty());
    deny.extend(shared);
    deny.push(real(&at.home.join(".ssh")));
    deny.extend(["**/.env".to_string(), "**/.env.*".to_string()]);
    assert_eq!(texts(&filesystem["denyRead"]), deny);
    assert_eq!(
        texts(&filesystem["allowRead"]),
        [dir.clone(), tmp.clone(), real(&at.tool)]
    );
    assert_eq!(texts(&filesystem["allowWrite"]), [dir, tmp]);
    // The rest is as it was.
    assert_eq!(settings["sandbox"]["enabled"], true);
    assert_eq!(settings["sandbox"]["failIfUnavailable"], true);
    assert_eq!(settings["sandbox"]["allowUnsandboxedCommands"], false);
    assert_eq!(
        settings["sandbox"]["network"]["allowedDomains"],
        serde_json::json!([])
    );
    assert_eq!(settings["permissions"]["defaultMode"], "dontAsk");
    assert_eq!(settings["disableAllHooks"], true);
}

#[test]
fn codex_is_given_a_profile_and_no_sandbox_mode() {
    let repo = Repo::new(&[("a.txt", "x\n")]);
    let at = places();
    let added = at.root.join("added");
    std::fs::create_dir(&added).unwrap();
    let report = reach(
        &repo,
        &[
            ("HOME", at.home.as_os_str()),
            ("YAK_JAIL_READ", at.tool.as_os_str()),
            ("YAK_INNER_HIDE", added.as_os_str()),
        ],
    );
    let args = texts(answer(&report, "codex"));
    // A sandbox mode makes Codex ignore a permission profile, so there is none, by any of its names.
    for word in ["-s", "--sandbox", "workspace-write", "read-only"] {
        assert!(!args.iter().any(|a| a == word), "{word}: {args:?}");
    }
    assert!(
        !args
            .iter()
            .any(|a| a.contains("sandbox_mode") || a.contains("workspace-write")),
        "{args:?}"
    );
    let dir = report["dir"].as_str().unwrap();
    let tmp = answer(&report, "tmp").as_str().unwrap();
    let system = texts(&answer(&report, "places")["system"]);
    assert!(system.iter().any(|dir| dir == "/usr/bin"), "{system:?}");
    // The whole table, in the plan's order: the three named places, the system, the named tools, the turn's
    // own temporary directory to write in, then what the room hid and the home's keys.
    let mut entries = vec![
        "\":root\"=\"deny\"".to_string(),
        "\":minimal\"=\"read\"".to_string(),
        "\":slash_tmp\"=\"deny\"".to_string(),
    ];
    entries.extend(system.iter().map(|dir| format!("\"{dir}\"=\"read\"")));
    entries.push(format!("\"{}\"=\"read\"", real(&at.tool)));
    entries.push(format!("\"{tmp}\"=\"write\""));
    for hidden in [real(&repo.path), real(&added), real(&at.home.join(".ssh"))] {
        entries.push(format!("\"{hidden}\"=\"deny\""));
    }
    let table = format!("{{{}}}", entries.join(", "));
    assert_eq!(
        args,
        strings(&[
            "exec",
            "--json",
            "-c",
            "default_permissions=\"yak\"",
            "-c",
            "permissions.yak.extends=\":workspace\"",
            "-c",
            &format!("permissions.yak.filesystem={table}"),
            "-C",
            dir,
            "-m",
            "m",
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

#[test]
fn a_path_with_a_quote_or_a_backslash_is_written_as_toml() {
    let repo = Repo::new(&[("a.txt", "x\n")]);
    let at = places();
    let odd = at.root.join("say \"hi\" \\ there");
    std::fs::create_dir(&odd).unwrap();
    let report = reach(
        &repo,
        &[
            ("HOME", at.home.as_os_str()),
            ("YAK_INNER_HIDE", odd.as_os_str()),
        ],
    );
    let real = real(&odd);
    let table = table_of(&texts(answer(&report, "codex")));
    let escaped = real.replace('\\', "\\\\").replace('"', "\\\"");
    assert!(
        table.contains(&format!(", \"{escaped}\"=\"deny\"")),
        "{table}"
    );
    assert!(!table.contains(&real), "written as it is: {table}");
    // Claude's settings are JSON, which is its own quoting: the path is there as it is.
    let deny = texts(&answer(&report, "claude")["sandbox"]["filesystem"]["denyRead"]);
    assert!(deny.contains(&real), "{deny:?}");
}

#[test]
fn a_path_with_a_control_character_is_refused() {
    let repo = Repo::new(&[("a.txt", "x\n")]);
    let at = places();
    // A tab, a character below it, and the one control character above the space.
    for (name, shown) in [
        ("tab\there", "tab\\there"),
        ("bell\x07", "bell\\u{7}"),
        ("delete\x7f", "delete\\u{7f}"),
    ] {
        let odd = at.root.join(name);
        std::fs::create_dir(&odd).unwrap();
        let report = reach(
            &repo,
            &[
                ("HOME", at.home.as_os_str()),
                ("YAK_INNER_HIDE", odd.as_os_str()),
            ],
        );
        for worker in ["claude", "codex"] {
            let why = refusal(&report, worker);
            // The path is named, as best it can be shown: with the character written out.
            assert!(why.contains(shown), "{worker} {name:?}: {why}");
        }
    }
}

#[test]
fn a_tool_directory_that_is_also_hidden_is_not_shown() {
    let repo = Repo::new(&[("a.txt", "x\n"), ("tools/run.sh", "#!/bin/sh\n")]);
    let at = places();
    let inside = repo.path.join("tools");
    // The item's repository named for tools, a directory inside it, and a system directory named as well. The
    // repository is also hidden a second time, by name.
    let named =
        std::env::join_paths([repo.path.as_path(), &inside, Path::new("/usr/bin")]).unwrap();
    let report = reach(
        &repo,
        &[
            ("HOME", at.home.as_os_str()),
            ("YAK_JAIL_READ", &named),
            ("YAK_INNER_HIDE", repo.path.as_os_str()),
        ],
    );
    let (repo_real, inside_real) = (real(&repo.path), real(&inside));
    let dir = report["dir"].as_str().unwrap().to_string();
    let tmp = answer(&report, "tmp").as_str().unwrap().to_string();
    let filesystem = &answer(&report, "claude")["sandbox"]["filesystem"];
    assert_eq!(
        texts(&filesystem["allowRead"]),
        [dir, tmp, "/usr/bin".to_string()]
    );
    let deny = texts(&filesystem["denyRead"]);
    assert_eq!(
        deny.iter().filter(|p| **p == repo_real).count(),
        1,
        "{deny:?}"
    );
    let table = table_of(&texts(answer(&report, "codex")));
    assert!(!table.contains(&inside_real), "{table}");
    assert!(
        !table.contains(&format!("\"{repo_real}\"=\"read\"")),
        "{table}"
    );
    assert_eq!(
        table.matches(&format!("\"{repo_real}\"")).count(),
        1,
        "{table}"
    );
    assert!(
        table.contains(&format!("\"{repo_real}\"=\"deny\"")),
        "{table}"
    );
    // No path is written twice: a system directory that is also named is shown once.
    assert_eq!(table.matches("\"/usr/bin\"").count(), 1, "{table}");

    // A system directory the room hides is not shown either.
    let report = reach(
        &repo,
        &[
            ("HOME", at.home.as_os_str()),
            ("YAK_INNER_HIDE", std::ffi::OsStr::new("/usr/bin")),
        ],
    );
    let table = table_of(&texts(answer(&report, "codex")));
    assert!(table.contains("\"/usr/bin\"=\"deny\""), "{table}");
    assert_eq!(table.matches("\"/usr/bin\"").count(), 1, "{table}");

    // Nor is a temporary directory every turn shares, named for tools: here the clock's own.
    let shared = at.root.join("shared");
    std::fs::create_dir(&shared).unwrap();
    let report = reach(
        &repo,
        &[
            ("HOME", at.home.as_os_str()),
            ("TMPDIR", shared.as_os_str()),
            ("YAK_JAIL_READ", shared.as_os_str()),
        ],
    );
    let shared_real = real(&shared);
    assert!(texts(&report["shared"]).contains(&shared_real));
    let filesystem = &answer(&report, "claude")["sandbox"]["filesystem"];
    assert!(!texts(&filesystem["allowRead"]).contains(&shared_real));
    let table = table_of(&texts(answer(&report, "codex")));
    assert!(!table.contains(&shared_real), "{table}");
}

#[test]
fn a_workers_program_is_given_its_own_tmp_and_no_global_git_settings() {
    for family in ["claude", "codex"] {
        let repo = Repo::new(&[("a.txt", "hello\n")]);
        let sb = sandbox(&repo);
        let said = repo.scratch("variables.txt");
        let body = format!(
            "#!/bin/sh\ncat > /dev/null\n\
             printf 'TMPDIR=%s\\nCLAUDE_CODE_TMPDIR=%s\\nGIT_CONFIG_GLOBAL=%s\\n' \
             \"$TMPDIR\" \"$CLAUDE_CODE_TMPDIR\" \"$GIT_CONFIG_GLOBAL\" > '{}'\n",
            said.display()
        );
        let fake = script(&repo, family, &body);
        family_worker(family, &fake)
            .run(&sb, "t", "true", 60, &mut seen())
            .unwrap();
        let tmp = sb.worker_tmp().unwrap();
        assert_eq!(
            read(&said),
            format!(
                "TMPDIR={t}\nCLAUDE_CODE_TMPDIR={t}\nGIT_CONFIG_GLOBAL=/dev/null\n",
                t = tmp.display()
            ),
            "{family}"
        );
    }
    // The control: another run in a sandbox is told none of it.
    let repo = Repo::new(&[("a.txt", "hello\n")]);
    let sb = sandbox(&repo);
    let mut lines = Vec::new();
    sb.run(
        "sh",
        &strings(&[
            "-c",
            "echo \"[${CLAUDE_CODE_TMPDIR-unset}] [${GIT_CONFIG_GLOBAL-unset}]\"",
        ]),
        "",
        30,
        &mut |line| lines.push(line.to_string()),
    )
    .unwrap();
    assert_eq!(lines, ["[unset] [unset]"]);
}

/// `jail::places` is the jail's own reading of the settings: the home, its keys and the agents' settings
/// directories that are there, the named tool directories, the system directories that are there, each as a
/// real path; and refused as the jail refuses.
#[test]
fn the_jails_places_are_its_own_reading_of_the_settings() {
    let repo = Repo::new(&[("a.txt", "x\n")]);
    let at = places();
    let agent = at.root.join("agent");
    std::fs::create_dir(&agent).unwrap();
    let never = at.root.join("never-made");
    let report = reach(
        &repo,
        &[
            ("HOME", at.home.as_os_str()),
            ("YAK_JAIL_READ", at.tool.as_os_str()),
            ("CLAUDE_CONFIG_DIR", agent.as_os_str()),
            ("CODEX_HOME", never.as_os_str()),
        ],
    );
    let places = answer(&report, "places");
    assert_eq!(places["home"], real(&at.home));
    assert_eq!(
        texts(&places["hidden"]),
        [real(&at.home.join(".ssh")), real(&agent)]
    );
    assert_eq!(texts(&places["shown"]), [real(&at.tool)]);
    let system = texts(&places["system"]);
    assert!(system.iter().any(|dir| dir == "/usr/bin"), "{system:?}");
    for dir in &system {
        assert!(Path::new(dir).exists(), "{dir} is not there");
    }
    // A tool directory that holds the home is refused, by the jail's own words, and so is every worker's reach.
    let report = reach(
        &repo,
        &[
            ("HOME", at.home.as_os_str()),
            ("YAK_JAIL_READ", at.root.as_os_str()),
        ],
    );
    assert!(
        refusal(&report, "places").contains("holds the home directory"),
        "{report}"
    );
    for worker in ["claude", "codex"] {
        assert!(refusal(&report, worker).contains("holds the home directory"));
    }
}

/// The temporary directories every turn on the machine shares: the real `/tmp`, and the clock's own `TMPDIR`
/// when that is set, is there, is a directory and is another one.
#[test]
fn the_shared_temporary_directories_are_tmp_and_the_clocks_own() {
    let repo = Repo::new(&[("a.txt", "x\n")]);
    let at = places();
    let slash_tmp = real(Path::new("/tmp"));
    let file = at.root.join("a-file");
    std::fs::write(&file, "").unwrap();
    let shared = |tmpdir: Option<&Path>| {
        let report = match tmpdir {
            Some(dir) => reach(
                &repo,
                &[("HOME", at.home.as_os_str()), ("TMPDIR", dir.as_os_str())],
            ),
            None => reach_without(&repo, &[("HOME", at.home.as_os_str())], &["TMPDIR"]),
        };
        texts(&report["shared"])
    };
    assert_eq!(shared(Some(&at.root)), [slash_tmp.clone(), real(&at.root)]);
    let alone = std::slice::from_ref(&slash_tmp);
    assert_eq!(shared(Some(&at.root.join("missing"))), alone);
    assert_eq!(shared(Some(&file)), alone);
    assert_eq!(shared(Some(Path::new("/tmp"))), alone);
    assert_eq!(shared(None), alone);
}
