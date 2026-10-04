import json
import os
import shlex
import pytest
from superyak_agent import vault_git
from superyak_agent.__main__ import main

REPO_NAME = 'aDNA/Station.aDNA.git'


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / REPO_NAME
    path.mkdir(parents=True)
    return path


@pytest.mark.parametrize('command', [
    "git-upload-pack '{repo}'", "git-receive-pack '{repo}'", "git-upload-pack '~/aDNA/Station.aDNA.git'",
    "git-upload-pack 'aDNA/Station.aDNA.git'", 'git-upload-pack {repo}'])
def test_allowed_git_commands_on_the_vault(repo, tmp_path, monkeypatch, command):
    monkeypatch.setenv('HOME', str(tmp_path))
    verb, path = vault_git.allowed(command.format(repo=repo), repo, home=tmp_path)
    assert verb in vault_git.VERBS and path == str(repo.resolve())


@pytest.mark.parametrize('command', [
    '', 'bash', 'git-upload-pack', "git-upload-pack '/etc'", "git-upload-pack '{repo}/../other.git'",
    "git-upload-pack '{repo}'; rm -rf ~", "git-upload-pack '{repo}' extra", "git-upload-archive '{repo}'",
    "scp -t '{repo}'", "git-upload-pack '{repo}", 'git-upload-pack $(id)'])
def test_everything_else_is_refused(repo, tmp_path, command):
    assert vault_git.allowed(command.format(repo=repo), repo, home=tmp_path) is None


def test_serve_executes_allowed_commands_and_logs_refusals(repo, tmp_path, capsys):
    ran, logged = [], []
    vault_git.serve(repo, environ={'SSH_ORIGINAL_COMMAND': f"git-receive-pack '{repo}'"}, execvp=lambda v, a: ran.append(a))
    assert ran == [['git-receive-pack', str(repo.resolve())]]
    code = vault_git.serve(repo, environ={'SSH_ORIGINAL_COMMAND': 'cat ~/.ssh/id_ed25519'}, execvp=lambda v, a: ran.append(a),
                           log=logged.append)
    assert code == 1 and len(ran) == 1 and 'refused' in logged[0]
    assert 'only fetch and push the station vault' in capsys.readouterr().err


def test_serve_marks_the_push_as_the_lattice_whatever_the_caller_had_set(repo):
    # The bare repository's gate applies its drop-box rules to every pusher except `bridge`.
    for inherited in ({}, {'STATION_VAULT_PUSHER': 'bridge'}, {'STATION_VAULT_PUSHER': ''}):
        environ = {**inherited, 'SSH_ORIGINAL_COMMAND': f"git-receive-pack '{repo}'"}
        seen = []
        vault_git.serve(repo, environ=environ, execvp=lambda v, a: seen.append(dict(environ)))
        assert seen[0]['STATION_VAULT_PUSHER'] == 'lattice' and environ['STATION_VAULT_PUSHER'] == 'lattice'


def test_a_refused_command_leaves_the_environment_alone(repo):
    environ = {'SSH_ORIGINAL_COMMAND': 'bash', 'STATION_VAULT_PUSHER': 'bridge'}
    assert vault_git.serve(repo, environ=environ, execvp=lambda v, a: pytest.fail('executed'), log=lambda m: None) == 1
    assert environ['STATION_VAULT_PUSHER'] == 'bridge'


def test_install_key_adds_one_restricted_line_and_keeps_the_rest(repo, tmp_path):
    keys = tmp_path / '.ssh' / 'authorized_keys'
    keys.parent.mkdir()
    keys.write_text('ssh-ed25519 AAAAexisting lattice-master-to-andy\n')
    key = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIStanleySync stanley-sync'
    assert vault_git.install_key(key, repo, '/usr/bin/python3', '/r/agent/run_agent.py', keys) is True
    lines = keys.read_text().splitlines()
    assert lines[0] == 'ssh-ed25519 AAAAexisting lattice-master-to-andy'
    assert lines[1] == f'restrict,command="/usr/bin/python3 /r/agent/run_agent.py vault-git --repo {repo.resolve()}" {key}'
    assert keys.stat().st_mode & 0o777 == 0o600 and keys.with_name('authorized_keys.bak-wormhole').exists()
    assert vault_git.install_key(key, repo, '/usr/bin/python3', '/r/agent/run_agent.py', keys) is False
    for bad in ('not a key', 'ssh-ed25519 AAAA\nssh-ed25519 BBBB evil', 'ssh-ed25519 AAAA"; rm'):
        with pytest.raises(ValueError):
            vault_git.install_key(bad, repo, '/usr/bin/python3', '/r/agent/run_agent.py', keys)


# Characters that str.splitlines() treats as line ends but sshd does not: one more key line to nobody's knowledge.
LINE_BREAKS = ['\u2028', '\u2029', '\x1c', '\x1d', '\x1e', '\x0b', '\x0c', '\x85', '\r', '\t', '\x00', '\x7f', '\u00e9']


@pytest.mark.parametrize('char', LINE_BREAKS)
def test_install_key_refuses_a_comment_that_hides_a_second_key_line(repo, tmp_path, char):
    keys = tmp_path / 'authorized_keys'
    evil = f'ssh-ed25519 AAAAsync stanley{char}ssh-ed25519 AAAAevil evil'
    with pytest.raises(ValueError):
        vault_git.install_key(evil, repo, '/usr/bin/python3', '/r/agent/run_agent.py', keys)
    assert not keys.exists()


def test_install_key_keeps_existing_lines_byte_for_byte_even_with_odd_characters(repo, tmp_path):
    keys = tmp_path / 'authorized_keys'
    odd = 'ssh-ed25519 AAAAold odd\u2028comment\x1cssh-ed25519 AAAAhidden x'.encode()
    original = b'# a comment\n' + odd + b'\n\xff\xfe not utf-8\n\n'
    keys.write_bytes(original)
    keys.chmod(0o644)
    old_umask = os.umask(0)
    try:
        assert vault_git.install_key('ssh-ed25519 AAAAone one', repo, '/usr/bin/python3', '/r/run.py', keys) is True
        assert vault_git.install_key('ssh-ed25519 AAAAtwo two', repo, '/usr/bin/python3', '/r/run.py', keys) is True
    finally:
        os.umask(old_umask)
    data = keys.read_bytes()
    assert data.startswith(original) and data.count(b'\n') == original.count(b'\n') + 2
    assert [line for line in data.split(b'\n') if b'AAAAhidden' in line] == [odd]  # never split into its own line
    assert data.endswith(b' ssh-ed25519 AAAAtwo two\n')
    assert vault_git.install_key('ssh-ed25519 AAAAhidden again', repo, '/usr/bin/python3', '/r/run.py', keys) is False
    assert keys.stat().st_mode & 0o777 == 0o600
    backup = keys.with_name('authorized_keys.bak-wormhole')
    assert backup.stat().st_mode & 0o777 == 0o600 and backup.read_bytes().startswith(original)  # even with umask 0
    assert sorted(p.name for p in tmp_path.iterdir() if p.name.startswith('.') or p.name.startswith('authorized')) == [
        'authorized_keys', 'authorized_keys.bak-wormhole']


def test_install_key_adds_the_missing_newline_before_its_line(repo, tmp_path):
    keys = tmp_path / 'authorized_keys'
    keys.write_text('ssh-ed25519 AAAAold old')
    assert vault_git.install_key('ssh-ed25519 AAAAone one', repo, '/usr/bin/python3', '/r/run.py', keys) is True
    assert keys.read_text().splitlines()[0] == 'ssh-ed25519 AAAAold old' and keys.read_text().count('\n') == 2


def test_the_forced_command_is_shell_quoted(tmp_path):
    spaced = tmp_path / 'my vault $HOME' / 'Station.aDNA.git'
    spaced.mkdir(parents=True)
    keys = tmp_path / 'authorized_keys'
    assert vault_git.install_key('ssh-ed25519 AAAAone one', spaced, '/opt/my python/bin/python3', '/r/run agent.py', keys)
    line = keys.read_text().splitlines()[0]
    command = line[len('restrict,command="'):line.index('" ssh-ed25519')]
    assert shlex.split(command) == ['/opt/my python/bin/python3', '/r/run agent.py', 'vault-git', '--repo', str(spaced.resolve())]
    assert "'" in command and '"' not in command
    for python, run_agent in (("/it's/python", '/r/run.py'), ('/usr/bin/python3', '/r/"run".py')):
        with pytest.raises(ValueError):  # a quote or backslash cannot sit inside authorized_keys' command="…"
            vault_git.install_key('ssh-ed25519 AAAAtwo two', spaced, python, run_agent, keys)


# --- the CLI commands ---------------------------------------------------------------------------------

def test_wormhole_key_command_authorizes_once(repo, tmp_path, capsys):
    keys = tmp_path / 'authorized_keys'
    argv = ['wormhole-key', '--key', 'ssh-ed25519 AAAAsync stanley-sync', '--repo', str(repo), '--authorized-keys', str(keys)]
    assert main(argv) == 0
    assert 'Key authorized: it can only fetch and push the station vault.' in capsys.readouterr().out
    assert keys.read_text().startswith('restrict,command="') and keys.read_text().count('\n') == 1
    assert main(argv) == 0
    assert 'already in authorized_keys; nothing changed' in capsys.readouterr().out
    assert keys.read_text().count('\n') == 1


def test_vault_git_command_refuses_other_commands_with_status_1(repo, monkeypatch, capsys):
    logged = []
    monkeypatch.setattr(vault_git, '_syslog', logged.append)
    monkeypatch.setenv('SSH_ORIGINAL_COMMAND', "git-upload-pack '/etc'")
    assert main(['vault-git', '--repo', str(repo)]) == 1
    assert 'only fetch and push the station vault' in capsys.readouterr().err and 'refused' in logged[0]


def test_wormhole_init_and_personas_commands(tmp_path, capsys):
    bare, clone = tmp_path / 'aDNA' / 'Station.aDNA.git', tmp_path / 'wormhole' / 'Station.aDNA'
    assert main(['wormhole-init', '--bare', str(bare), '--clone', str(clone)]) == 0
    assert (clone / 'who' / 'coordination' / 'inbox' / 'README.md').exists() and 'Station.aDNA created' in capsys.readouterr().out
    registry = tmp_path / 'registry.json'
    registry.write_text(json.dumps({'vaults': [{'vault': 'Network.aDNA', 'persona': 'Venus'}, {'vault': 'x'}]}))
    out = tmp_path / 'wormhole' / 'personas.json'
    assert main(['wormhole-personas', '--out', str(out), '--registry', registry.as_uri()]) == 0
    assert json.loads(out.read_text()) == {'venus': {'persona': 'Venus', 'vault': 'Network.aDNA'}}
    assert '1 personas written' in capsys.readouterr().out


def key_args(keys, repo, *extra):
    return ['wormhole-key', '--repo', str(repo), '--authorized-keys', str(keys), *extra]


def test_wormhole_key_command_reports_a_bad_key_in_one_line(repo, tmp_path, capsys):
    keys = tmp_path / 'authorized_keys'
    assert main(key_args(keys, repo, '--key', 'ssh-ed25519 AAAA\nssh-ed25519 BBBB evil')) == 2
    captured = capsys.readouterr()
    assert captured.out == '' and captured.err.count('\n') == 1 and 'Give one SSH public key line' in captured.err
    assert not keys.exists()


@pytest.mark.parametrize('text', ['ssh-ed25519 AAAAsync stanley-sync', 'ssh-ed25519 AAAAsync stanley-sync\n'])
def test_wormhole_key_command_reads_the_key_from_a_file(repo, tmp_path, capsys, text):
    keys, pub = tmp_path / 'authorized_keys', tmp_path / 'stanley.pub'
    pub.write_text(text)
    assert main(key_args(keys, repo, '--key-file', str(pub))) == 0
    assert 'Key authorized' in capsys.readouterr().out
    assert keys.read_text().splitlines()[0].endswith(' ssh-ed25519 AAAAsync stanley-sync') and keys.read_text().count('\n') == 1


@pytest.mark.parametrize('text', ['ssh-ed25519 AAAAone a\nssh-ed25519 AAAAtwo b\n', 'ssh-ed25519 AAAAone a\n\n', 'ssh-ed25519 AAAAone a\r\n',
                                  '', '\n', 'garbage'])
def test_wormhole_key_command_refuses_a_key_file_that_is_not_exactly_one_key_line(repo, tmp_path, capsys, text):
    keys, pub = tmp_path / 'authorized_keys', tmp_path / 'stanley.pub'
    pub.write_text(text)
    assert main(key_args(keys, repo, '--key-file', str(pub))) == 2
    assert capsys.readouterr().err.count('\n') == 1 and not keys.exists()


def test_wormhole_key_command_reports_a_missing_key_file(repo, tmp_path, capsys):
    assert main(key_args(tmp_path / 'authorized_keys', repo, '--key-file', str(tmp_path / 'nothing.pub'))) == 2
    assert 'nothing.pub' in capsys.readouterr().err


def test_wormhole_key_command_needs_exactly_one_of_key_and_key_file(repo, tmp_path):
    keys = tmp_path / 'authorized_keys'
    (tmp_path / 'a.pub').write_text('ssh-ed25519 AAAAone a\n')
    for extra in ([], ['--key', 'ssh-ed25519 AAAAone a', '--key-file', str(tmp_path / 'a.pub')]):
        with pytest.raises(SystemExit) as exit_info:
            main(key_args(keys, repo, *extra))
        assert exit_info.value.code == 2
    assert not keys.exists()
