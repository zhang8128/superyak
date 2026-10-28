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


@pytest.mark.parametrize('body, says', [
    (lesson_body() + '\n', 'final newline'),
    (lesson_body().replace('\n', '\r\n'), '\\r'),
    (lesson_body().replace('lesson\n', 'Lesson\n', 1), 'only lessons and retractions'),
    (lesson_body(command=()), 'at least one error, command or file'),
    (lesson_body(command=('x', 'x')), 'repeats a command value'),
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
    ('lesson\nclaim: c\nship: tardis\nwhy: w\ncommand: x\nlearned from: own', 'out of order'),
    ('lesson\nship: tardis\nclaim: c\nwhy: w\nfile: f\nerror: e\nlearned from: own', 'out of order'),
    (lesson_body() + '\nlearned from: own', 'out of order or repeated'),
    ('lesson\nship: tardis\nclaim: c\nwhy: w\ncommand: x', 'one learned from line'),
    ('x' * 4097, '4,096 bytes'),
])
def test_a_refusal_says_which_rule_and_never_the_value(body, says):
    with pytest.raises(lessons.LessonRefused) as refused:
        lessons.parse_post(body)
    assert says in refused.value.message and refused.value.status == 422
    assert 'padded' not in refused.value.message and 'tab' not in refused.value.message


def test_values_at_their_bounds_and_a_body_at_4096_bytes_pass():
    body = lesson_body(claim='c' * 160, why='w' * 300, error=tuple(f'{i}' + 'e' * 119 for i in range(8)),
                       command=tuple(f'{i}' + 'c' * 119 for i in range(8)), file=tuple(f'{i}' + 'f' * 119 for i in range(8)))
    assert len(body.encode()) <= 4096 and len(lessons.parse_post(body).file) == 8


def test_a_retraction_names_the_full_id():
    key = f'{PEER}:{"b" * 64}'
    assert lessons.parse_post('retract ' + key) == lessons.Retraction(key)
    for wrong in ('retract ' + lessons.short_lesson_id(key), 'retract ' + key + '\n', 'Retract ' + key):
        with pytest.raises(lessons.LessonRefused):
            lessons.parse_post(wrong)


def test_one_text_on_one_peer_is_one_id_whatever_learned_from_says():
    own, owner = lessons.parse_post(lesson_body(learned='own')), lessons.parse_post(lesson_body(learned='owner'))
    assert lessons.lesson_id(PEER, own) == lessons.lesson_id(PEER, owner) != lessons.lesson_id('c' * 64, own)
