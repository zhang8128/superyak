"""A lesson verb never makes a peer where none is (board fix:lessons-verbs-make-a-store).

`make lessons-where` on a machine with no peer used to create `peer.sqlite3` at the default path and then say "No lessons room is
recorded on this peer", and `make lesson-receipts` said "No receipts yet". Both were true of a store made a moment before, and
two ships nearly read that as a measure of the rail (2026-11-04)."""
import pytest

from superyak_peer.db import Store
from superyak_peer.lessons import VERBS, main

OPENING = sorted(name for name, (_, _, _, opens) in VERBS.items() if opens)


def argv(verb, data_dir):
    """The verb with just enough arguments to reach its store: every required flag and every positional, filled in."""
    args = [verb, '--data-dir', str(data_dir)]
    for flag, options in VERBS[verb][1]:
        if not flag.startswith('-'):
            args.append('1' if options.get('type') is int else 'x')
        elif options.get('required'):
            args += [flag, '1' if options.get('type') is int else 'x']
    return args


def test_the_list_of_verbs_is_real():
    assert {'where', 'receipts', 'list', 'index', 'ship', 'room', 'repeats', 'outcomes'} <= set(OPENING)
    assert 'query' not in OPENING, 'the hook path opens a store only behind an index file, so it never makes one'


@pytest.mark.parametrize('verb', OPENING)
@pytest.mark.parametrize('made', [False, True], ids=['no directory', 'an empty directory'])
def test_every_verb_that_opens_a_store_refuses_where_none_is_and_makes_nothing(tmp_path, capsys, verb, made):
    data_dir = tmp_path / 'nowhere'
    if made:
        data_dir.mkdir()
    with pytest.raises(SystemExit) as stopped:
        main(argv(verb, data_dir))
    assert stopped.value.code == 1
    err = capsys.readouterr().err
    assert 'no peer' in err and str(data_dir) in err and 'LESSONS_DATA' in err
    assert not (data_dir / 'peer.sqlite3').exists()
    assert not (data_dir / 'dispatch.lock').exists()
    assert data_dir.exists() is made, 'it makes no directory either'


def test_a_real_store_still_answers(tmp_path, capsys):
    Store(tmp_path / 'peer', signing=False)
    main(['where', '--data-dir', str(tmp_path / 'peer')])
    assert 'No lessons room is recorded on this peer.' in capsys.readouterr().out


def test_a_directory_named_like_the_store_isnt_one(tmp_path, capsys):
    (tmp_path / 'peer' / 'peer.sqlite3').mkdir(parents=True)
    with pytest.raises(SystemExit) as stopped:
        main(['where', '--data-dir', str(tmp_path / 'peer')])
    assert stopped.value.code == 1 and 'no peer' in capsys.readouterr().err
