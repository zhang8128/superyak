"""Spec lesson-holds-on-tool-calls (docs/superpowers/specs/2026-10-30-lesson-holds-on-tool-calls-design.md), item 3 on
the peer's side: a held tool's name holds only that tool's call, and matches by words at no other event (a Bash hold, a
prompt, a failed command, a session start); no other value holds a tool call."""
import time

from superyak_peer import lessons

POST = 'mcp__station__station_post'


def item(**values):
    return {'id': 'a' * 64 + ':' + 'b' * 64, 'author': 'author-tardis', 'ship': 'tardis', 'learned_from': 'own',
            'claim': 'A claim.', 'why': 'A why.', 'chain_time': None, 'vector': None,
            'error': list(values.get('error', ())), 'command': list(values.get('command', ())),
            'file': list(values.get('file', ()))}


def test_a_held_tools_name_holds_its_own_call_and_no_bash_command():
    assert lessons.holding([POST], POST) == [POST]
    assert lessons.holding([POST], f'rg {POST} agent/') == []  # S5: a grep of the name spends nothing


def test_no_other_value_holds_a_tool_call_and_bash_is_unchanged():
    assert lessons.holding(['station', 'station_post'], POST) == []  # N4: a short value can't hold every post
    assert lessons.holding(['git push'], 'git push origin main') == ['git push']


def test_a_failed_command_naming_the_tool_does_not_match_it_by_words():
    """R1: the failure event's query counts any contained value; a held tool's name isn't one of them."""
    request = {'command': f'grep -n {POST} agent/superyak_agent/hook.py', 'error': f'exit 1 {POST}', 'cwd': '/repo',
               'words_only': False}
    assert lessons.words(item(command=[POST], error=[POST], file=[POST]), request) == (0, None)
    assert lessons.words(item(command=['grep -n']), request) == (1, 'grep -n')  # an ordinary value still matches


def test_a_prompt_naming_the_tool_does_not_surface_its_lesson():
    index = {'ships': {'serenity': 'author-serenity'}, 'lessons': [item(command=[POST]), item(command=['dock --lessons'])],
             'model': None, 'dimension': None}
    index['lessons'][1]['id'] = 'c' * 64 + ':' + 'd' * 64
    request = {'ship': 'serenity', 'prompt': f'Review the hold for {POST} and dock --lessons please', 'limit': 3,
               'seen': [], 'budget_ms': None}
    answer = lessons.prompt_answer(request, index, 0, None, None, time.monotonic)
    assert [entry['id'] for entry in answer['lessons']] == [lessons.short_lesson_id('c' * 64 + ':' + 'd' * 64)]
