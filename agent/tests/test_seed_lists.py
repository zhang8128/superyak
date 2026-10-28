"""Checklists: the seed (spec, Seeding), and the ways ships really push (Review Focus 1)."""
import re
from pathlib import Path
import pytest
from superyak_agent import checklists as cl

REPO = Path(__file__).resolve().parents[2]
SEED = REPO / '.superyak' / 'checklists'
TABLE = {
    'why-we-build': 'start; every 3h', 'each-hour': 'every 1h', 'reflect': 'every 3h',
    'before-push': 'command git push; command push origin; command push -u origin; command push https://',
    'merging-to-main': ('command git push origin main; command push origin main; '
                        'command push https://github.com/zhang8128/superyak.git main; command systemctl --user restart superyak-'),
    'before-work': 'claim', 'session-start': 'start',
    'live-station-act': '; '.join(f'command make station-{t}' for t in
                                  ('approve', 'deny', 'bridge', 'unbridge', 'add-ship', 'moderate', 'unmoderate')),
}


def seed(list_id):
    return cl.parse(f'{list_id}.md', (SEED / f'{list_id}.md').read_bytes(), own=False)


def matches(list_id, command):
    return any(m.kind == 'command' and cl.command_matches(m.words, command) for m in seed(list_id).moments)


def slug(heading):
    return re.sub(r'[^\w\- ]', '', heading.strip().lower()).replace(' ', '-')


def test_the_seed_is_the_spec_s_table():
    assert sorted(p.stem for p in SEED.glob('*.md')) == sorted(TABLE)
    for list_id, when in TABLE.items():
        assert (SEED / f'{list_id}.md').read_text().split('\n')[3] == f'when: {when}' and seed(list_id).version == 1
    assert seed('why-we-build').read and seed('reflect').post == cl.ALL_HANDS
    assert any('checklists report' in item for item in seed('reflect').items)          # plan review M5
    assert seed('merging-to-main').items[-1] == 'Reflect is run once the merge is announced.'


def test_every_see_points_at_a_heading_in_docs_checklists():
    headings = {slug(line[3:]) for line in (REPO / 'docs' / 'checklists.md').read_text().splitlines() if line.startswith('## ')}
    for list_id in TABLE:
        path, anchor = seed(list_id).see.split('#')
        assert path == 'docs/checklists.md' and anchor in headings, list_id


@pytest.mark.parametrize('command', ['git push origin feature', 'cd /x && git push',
                                     "git -c 'credential.helper=!gh auth git-credential' push https://github.com/zhang8128/superyak.git feature",
                                     'git -C /Users/kairos/Projects/superyak/.worktrees/x push origin feature',
                                     'git -C /x push -u origin feature'])
def test_before_any_push_holds_the_ways_ships_really_push(command):                    # Review Focus 1
    assert matches('before-push', command)


def test_merging_to_main_fires_at_the_main_push_or_the_units_restart_and_not_at_a_merge():
    for command in ('git push origin main', 'git -C /x push origin main', 'systemctl --user restart superyak-peer.service',
                    "ssh andy@smart '… && systemctl --user restart superyak-peer'",
                    "git -c 'credential.helper=!gh auth git-credential' push https://github.com/zhang8128/superyak.git main"):
        assert matches('merging-to-main', command), command
    # The plan's message was "git push origin main", but Ruling 27's literal `push origin main` matches its " push"
    # after a space (the spec's rule); a quote right before the words still keeps a message from matching.
    for command in ('git merge main', 'git merge-base --is-ancestor 60dd851 HEAD', 'git push origin feature',
                    'git commit -m "push origin main"'):
        assert not matches('merging-to-main', command), command


def test_a_live_station_act_fires_at_each_make_target_over_ssh_too_and_not_at_a_read():
    for target in ('approve', 'deny', 'bridge', 'unbridge', 'add-ship', 'moderate', 'unmoderate'):
        assert matches('live-station-act', f'make station-{target} ID=abc')
    assert matches('live-station-act', "ssh andy@smart 'cd ~/superyak && make station-approve ID=abc'")   # plan review M1
    assert not matches('live-station-act', 'make station-rooms') and not matches('live-station-act', 'make station-pending')


def test_docs_checklists_points_to_each_file_and_ticks_nothing_twice():
    text = (REPO / 'docs' / 'checklists.md').read_text()
    for list_id in TABLE:
        assert f'.superyak/checklists/{list_id}.md' in text
    sections = re.split(r'\n## ', text)
    seeded = [s for s in sections if any(f'.superyak/checklists/{i}.md' in s for i in TABLE)]
    assert len(seeded) == len(TABLE) and not any('- [ ] ' in s for s in seeded)
