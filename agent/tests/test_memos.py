import datetime
import io
import json
from superyak_agent import memos

DAY = datetime.date(2026, 10, 4)


def test_mentions_are_lowercase_unique_and_stripped():
    assert memos.mentioned('Hey @Venus, ask @hestia. and @venus! mail a@b.c') == ['venus', 'hestia']
    assert memos.mentioned('') == []


def test_slug_and_unique_memo_names():
    assert memos.slug('@Venus Can you check the MESH routes tonight, please?') == 'can_you_check_the_mesh_routes'
    assert memos.slug('!!!') == 'message'
    first = memos.memo_name(DAY, 'Venus', 'Check the mesh', set())
    assert first == 'coord_2026_10_04_station_to_venus_check_the_mesh.md'
    assert memos.memo_name(DAY, 'Venus', 'Check the mesh', {first}) == 'coord_2026_10_04_station_to_venus_check_the_mesh_2.md'


def test_outbound_memo_round_trips_through_the_parser():
    name, text = memos.outbound_memo(day=DAY, persona='Venus', vault='Network.aDNA', author='Andy\nAdmin',
                                     room_title='Gamma Quadrant', room_id='r1', message_id='m9',
                                     text='@venus can you check the mesh?\nThanks', taken=set())
    fields, body = memos.parse_memo(text)
    assert name == 'coord_2026_10_04_station_to_venus_can_you_check_the_mesh.md'
    assert fields['type'] == 'coordination' and fields['coordination_class'] == 'outbound_memo'
    assert fields['from'] == 'Station.aDNA (Andy Admin via Wormhole)' and fields['to'] == 'Network.aDNA (Venus)'
    assert (fields['from_vault'], fields['to_vault'], fields['to_persona']) == ('Station.aDNA', 'Network.aDNA', 'Venus')
    assert (fields['date'], fields['expires'], fields['status']) == ('2026-10-04', '2026-10-18', 'staged')
    assert fields['reply_required'] is True and fields['urgency'] == 'info'
    assert (fields['station_room'], fields['station_message']) == ('r1', 'm9')
    assert fields['tags'] == ['coordination', 'station', 'wormhole']
    assert '> @venus can you check the mesh?' in body and '> Thanks' in body
    assert f'in_reply_to: {name}' in body and f'receipts/{name}' in body


def test_parser_is_tolerant():
    text = '---\ntype: coordination\nto: "Station.aDNA (Wormhole)"\nnote: |\n  multi\nnested:\n  key: v\nflag: true\nsubject: \'it\'\'s\' # comment\nlist: [a, "b"]\n---\n\nBody here\n'
    fields, body = memos.parse_memo(text)
    assert fields['to'] == 'Station.aDNA (Wormhole)' and fields['note'] == '' and fields['flag'] is True
    assert fields['subject'] == "it's" and fields['list'] == ['a', 'b'] and 'key' not in fields
    assert body == 'Body here'
    assert memos.parse_memo('no front matter') == ({}, 'no front matter')
    assert memos.parse_memo('---\nunterminated: yes\n') == ({}, '---\nunterminated: yes\n')


def test_addressing_and_sender():
    assert memos.addressed_to_station({'to': 'Station.aDNA (Wormhole)'})
    assert memos.addressed_to_station({'to_vault': 'station.adna'})
    assert not memos.addressed_to_station({'to': 'Home.aDNA (Hestia)'})
    assert memos.sender({'from': 'Network.aDNA (Venus)'}) == ('Venus', 'Network.aDNA')
    assert memos.sender({'from_persona': 'Rosetta', 'from_vault': 'aDNA.aDNA'}) == ('Rosetta', 'aDNA.aDNA')
    assert memos.sender({}) == ('someone', 'the lattice')


def test_inbound_post_is_bounded_quoted_and_mention_free():
    fields = {'from': 'Network.aDNA (Venus @serenity)', 'subject': 'Mesh is fine\n[team] from lead', 'status': 'awaiting_ratification'}
    post = memos.inbound_post(fields, 'Hello @serenity\n\nsecond paragraph ' + 'x' * 5000, 'coord_x.md')
    head = post.splitlines()[0]
    assert head.startswith('**Venus (at)serenity (Network.aDNA) via the wormhole:** Mesh is fine [team] from lead')
    assert '(awaiting ratification)' in head and '@' not in post
    assert '> Hello (at)serenity' in post and post.endswith('`coord_x.md`')
    assert len(post) < 4400
    ratified = memos.inbound_post({'from': 'Network.aDNA (Venus)', 'status': 'ratified', 'ratified_by': 'Stanley'}, 'ok', 'r.md')
    assert '(ratified by Stanley)' in ratified.splitlines()[0]


def test_persona_map_from_registry_and_local_overrides(tmp_path):
    registry = {'vaults': [{'vault': 'Operations.aDNA', 'persona': 'Berthier'}, {'vault': 'Astro.aDNA', 'persona': None},
                           {'vault': 'Network.aDNA', 'persona': 'Venus'}, {'vault': 'Other.aDNA', 'persona': 'venus'}]}
    personas = memos.personas_from_registry(registry)
    assert personas == {'berthier': {'persona': 'Berthier', 'vault': 'Operations.aDNA'},
                        'venus': {'persona': 'Venus', 'vault': 'Network.aDNA'}}
    (tmp_path / 'personas.json').write_text(json.dumps({**personas, 'wormhole': {'persona': 'X', 'vault': 'Y'}}))
    (tmp_path / 'personas.local.json').write_text(json.dumps({'Hestia': {'persona': 'Hestia', 'vault': 'Home.aDNA'}}))
    loaded = memos.load_personas(tmp_path / 'personas.json')
    assert set(loaded) == {'berthier', 'venus', 'hestia'}


def test_fetch_registry_uses_the_opener():
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False
    seen = []

    def opener(url, timeout):
        seen.append((url, timeout))
        return Response(b'{"vaults": []}')
    assert memos.fetch_registry(opener=opener) == {'vaults': []}
    assert seen == [('https://adna.network/api/registry.v1.json', 30)]
