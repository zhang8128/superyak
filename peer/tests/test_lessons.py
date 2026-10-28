"""First rail, the pure parts: the wire format (section 2), person data (section 6), angles and the embedder's socket
(sections 1 and 5). docs/superpowers/specs/2026-10-27-first-rail-lessons-design.md."""
import hashlib
import json
import math
import random
from pathlib import Path
import pytest
from superyak_peer import lessons
from conftest import lesson_body

PEER = 'a' * 64
ILLUSTRATION = ('lesson\nship: tardis\n'
                "claim: In zsh, quote a glob in a git pathspec or in grep's --include, or the shell expands it first.\n"
                'why: Each unquoted glob failed before git or grep ran, and cost a rerun.\n'
                'error: no matches found\ncommand: --include=*\nlearned from: own')


# Task 1: the wire format
def test_the_spec_illustration_parses_and_its_id_is_the_digest_of_the_embedded_text():
    got = lessons.parse_post(ILLUSTRATION)
    assert got == lessons.Lesson('tardis', "In zsh, quote a glob in a git pathspec or in grep's --include, or the shell expands it first.",
                                 'Each unquoted glob failed before git or grep ran, and cost a rerun.',
                                 ('no matches found',), ('--include=*',), (), 'own')
    text = lessons.embedded_text(got)
    assert text == got.claim + '\n' + got.why + '\nApplies to: no matches found; --include=*'
    digest = hashlib.sha256(text.encode()).hexdigest()
    assert lessons.lesson_id(PEER, got) == f'{PEER}:{digest}'
    assert lessons.short_lesson_id(f'{PEER}:{digest}') == f'aaaaaaaa-{digest[:8]}'


def echoable(body):
    """Everything in `body` a refusal must never echo: each field's value, and the key and value (or the whole) of a
    line that is no field. The wire format's own words (the header `lesson`, learned from's `own` and `owner`) are
    the rules' vocabulary, so a message may name them."""
    found = []
    for line in body.split('\n'):
        key, sep, value = line.rstrip('\r').partition(': ')
        found += [value] if sep and key in lessons.LIMITS else [key, value] if sep else [key]
    return [v for v in found if v and v not in ('lesson', 'own', 'owner')]


@pytest.mark.parametrize('body, says', [
    (lesson_body() + '\n', 'final newline'),
    (lesson_body().replace('\n', '\r\n'), '\\r'),
    (lesson_body().replace('lesson\n', 'Lesson\n', 1), 'only lessons and retractions'),
    (lesson_body(command=()), 'at least one error, command or file'),
    (lesson_body(command=('dup-value', 'dup-value')), 'repeats a command value'),
    (lesson_body(command=tuple(f'c{i}' for i in range(9))), 'at most 8'),
    (lesson_body(claim='x' * 161), '1 to 160 bytes'),
    (lesson_body(why='é' * 151), '1 to 300 bytes'),
    (lesson_body(error=('e' * 121,)), '1 to 120 bytes'),
    (lesson_body(claim=' padded'), 'leading or trailing space'),
    (lesson_body(claim='tab\there'), 'control or format'),
    (lesson_body(claim='bidi \u202e here'), 'control or format'),
    (lesson_body(claim='zero\u200bwidth'), 'control or format'),
    (lesson_body(ship='Tardis'), 'ship: is a ship name'),
    (lesson_body(learned='Owner'), 'learned from: is own, owner'),
    (lesson_body().replace('\nwhy:', '\n\nwhy:'), 'blank line'),
    ('lesson\nclaim: Claim before ship.\nship: tardis\nwhy: Why third.\ncommand: cmd-x\nlearned from: own', 'out of order'),
    ('lesson\nship: tardis\nclaim: File before error.\nwhy: Why third.\nfile: file-f\nerror: error-e\nlearned from: own',
     'out of order'),
    (lesson_body() + '\nlearned from: own', 'out of order or repeated'),
    ('lesson\nship: tardis\nclaim: Claim without a source.\nwhy: Why third.\ncommand: cmd-x', 'one learned from line'),
    ('x' * 4097, '4,096 bytes'),
    (lesson_body(claim='lone \ud800 surrogate'), 'UTF-8'),
    (lesson_body().replace('\nwhy:', '\nmood: Sunny today.\nwhy:'), 'not one of the fields'),
])
def test_a_refusal_says_which_rule_and_never_the_value(body, says):
    with pytest.raises(lessons.LessonRefused) as refused:
        lessons.parse_post(body)
    assert says in refused.value.message and refused.value.status == 422
    assert [value for value in echoable(body) if value in refused.value.message] == []
    assert 'padded' not in refused.value.message and 'tab' not in refused.value.message


def test_values_at_their_bounds_and_a_body_at_4096_bytes_pass():
    body = lesson_body(claim='c' * 160, why='w' * 300, error=tuple(f'{i}' + 'e' * 119 for i in range(8)),
                       command=tuple(f'{i}' + 'c' * 119 for i in range(8)), file=tuple(f'{i}' + 'f' * 119 for i in range(8)))
    assert len(body.encode()) <= 4096 and len(lessons.parse_post(body).file) == 8


def test_a_retraction_names_the_full_id():
    key = f'{PEER}:{"b" * 64}'
    assert lessons.parse_post('retract ' + key) == lessons.Retraction(key)
    for wrong in ('retract ' + lessons.short_lesson_id(key), 'retract ' + key + '\n', 'Retract ' + key):
        with pytest.raises(lessons.LessonRefused) as refused:
            lessons.parse_post(wrong)
        assert 'aaaaaaaa' not in refused.value.message and 'bbbbbbbb' not in refused.value.message  # nor any id


def test_one_text_on_one_peer_is_one_id_whatever_learned_from_says():
    own, owner = lessons.parse_post(lesson_body(learned='own')), lessons.parse_post(lesson_body(learned='owner'))
    assert lessons.lesson_id(PEER, own) == lessons.lesson_id(PEER, owner) != lessons.lesson_id('c' * 64, own)


# Task 2: person data
NAMES = lessons.names_pattern(['test', 'Test Account', 'andy', 'Andy Example'])


@pytest.mark.parametrize('value', ['2026-10-27', '2026-10-27T10:30:45Z', 'v1.62.0', 'Python 3.11.2', '192.168.1.10',
                                   '100.64.0.1:7437', 'port 7435', 'pid 48213', 'pytest -k test_cli', '~/superyak/peer',
                                   'GitHub over SSH', 'x' * 120 + ' ' + 'y' * 300])
def test_dates_versions_addresses_ports_and_pids_pass(value):
    assert not lessons.holds_person_data(value, NAMES)


@pytest.mark.parametrize('value', ['git@github.com', 'mail a@b.org', '+1 415 555 0100', '(415) 555-0100', '415.555.0100',
                                   'make test', 'ask Andy', 'ANDY EXAMPLE said', 'andy\texample', '/home/andy/superyak'])
def test_an_account_name_an_email_or_a_phone_number_refuses(value):
    assert lessons.holds_person_data(value, NAMES)


def test_names_fold_case_short_ones_are_ignored_and_field_names_are_never_read():
    pattern = lessons.names_pattern(['José Ruiz', 'al', None, 'file'])
    assert lessons.holds_person_data('JOSÉ RUIZ wrote it', pattern)
    assert not lessons.holds_person_data('al fresco', pattern)
    assert lessons.names_pattern(['ab']) is None
    lesson = lessons.parse_post(lesson_body(file=('peer/README.md',)))
    assert 'file' not in lessons.lesson_values(lesson).split('\n')
    assert not lessons.holds_person_data(lessons.lesson_values(lesson), lessons.names_pattern(['file', 'error']))


# Task 3: angles and the embedder
def test_kahans_angle_is_symmetric_bounded_exact_at_the_ends_and_keeps_the_triangle_inequality():
    rnd = random.Random(42)
    def sample():
        return lessons.unit([rnd.gauss(0, 1) for _ in range(768)])
    for _ in range(300):
        a, b, c = sample(), sample(), sample()
        assert lessons.angle(a, a) == 0.0
        assert abs(lessons.angle(a, b) - lessons.angle(b, a)) < 1e-12
        assert 0 <= lessons.angle(a, b) <= math.pi
        assert lessons.angle(a, c) <= lessons.angle(a, b) + lessons.angle(b, c) + 1e-12
    a = sample()
    assert 0 < lessons.angle(a, lessons.unit([x + 1e-9 * (i % 3) for i, x in enumerate(a)])) < 1e-6
    assert abs(lessons.angle(a, [-x for x in a]) - math.pi) < 1e-12
    assert lessons.unit([0.0, 0.0]) is None


def test_embed_speaks_the_protocol_and_returns_unit_vectors(fake_embedder):
    fake_embedder.vectors['x'] = [3.0, 4.0, 0.0, 0.0]
    assert lessons.embed(fake_embedder.path, ['x'], 'search_query', 105.0, lambda: 100.0) == ('fake-model', [[0.6, 0.8, 0.0, 0.0]])
    assert fake_embedder.requests[-1]['prefix'] == 'search_query' and fake_embedder.requests[-1]['texts'] == ['x']
    assert lessons.embedder_model(fake_embedder.path, 105.0, lambda: 100.0) == 'fake-model'


def test_embed_is_unavailable_past_its_deadline_without_a_socket_or_with_bad_vectors(fake_embedder):
    with pytest.raises(lessons.EmbedderUnavailable):
        lessons.embed(fake_embedder.path, ['x'], 'search_query', 100.0, lambda: 100.0)
    with pytest.raises(lessons.EmbedderUnavailable):
        lessons.embed(fake_embedder.path.with_name('missing'), ['x'], 'search_query', 105.0, lambda: 100.0)
    fake_embedder.delay = 0.5  # answers after the socket's 0.2 s: the query never waits past its deadline
    with pytest.raises(lessons.EmbedderUnavailable):
        lessons.embed(fake_embedder.path, ['x'], 'search_query', 100.2, lambda: 100.0)
    fake_embedder.delay, fake_embedder.dimension = 0.0, 3  # the vectors don't have the dimension it claims
    with pytest.raises(lessons.EmbedderUnavailable):
        lessons.embed(fake_embedder.path, ['x'], 'search_query', 105.0, lambda: 100.0)


def test_runtime_json_names_the_socket(tmp_path):
    config = tmp_path / 'runtime.json'
    assert lessons.embedder_socket(config) is None
    config.write_text(json.dumps({'embedder_socket': '/run/user/1000/superyak/embedder.sock', 'memory_home': '/m'}))
    assert lessons.embedder_socket(config) == Path('/run/user/1000/superyak/embedder.sock')
    for value in ('relative.sock', 7, None):
        config.write_text(json.dumps({'embedder_socket': value}))
        assert lessons.embedder_socket(config) is None
    config.write_text('{not json')
    assert lessons.embedder_socket(config) is None
