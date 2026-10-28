"""An imprint travels over the tailnet only (spec I 9, section 2 review S5): a public (Funnel) request is refused on the
request, manifest, parts and complete routes even with a valid ship key, and the same request from the tailnet works."""
from fastapi.testclient import TestClient
import pytest

from superyak_peer.identity import canonical
from superyak_peer.imprints import PART_SIZE as PART_BYTES
from imprint_support import request_doc, station
from test_imprint_confirm import confirm, row
from test_imprint_upload import allowed_with_all_parts, allowed_with_manifest, manifest_for_doc, requested_with_package

PUBLIC_CLIENT = ('203.0.113.7', 50000)
TAILNET_SHIP = ('100.70.202.124', 50000)
TAILNET_ONLY = (403, {'error': 'Imprints go to the station over the tailnet only'})


def public_ship(st, ship='voyager', client=PUBLIC_CLIENT, **headers):
    """The ship's own client (its valid key, origin and presence), from outside the tailnet."""
    return TestClient(st.app, base_url='http://testserver', client=client,
                      headers={**dict(getattr(st, ship).headers), **headers})


def tailnet_only(response):
    return (response.status_code, response.json()) == TAILNET_ONLY


@pytest.fixture
def no_lookup(monkeypatch):
    """Fails the test if a refused public request got as far as looking up its ship (which writes last_used)."""
    def watch(st):
        def fail(*args, **kwargs):
            raise AssertionError('the route looked the ship up')
        monkeypatch.setattr(st.store, 'ship_for_key', fail)
    return watch


def requests(st):
    with st.store.transaction() as db:
        return db.execute('SELECT count(*) FROM imprint_requests').fetchone()[0]


def staging(st):
    root = st.store.data_dir / 'imprints'
    return sorted(p.name for p in root.iterdir()) if root.exists() else []


def test_a_public_request_with_a_valid_ship_key_is_refused_and_the_tailnet_one_works(tmp_path, monkeypatch, no_lookup):
    st = station(tmp_path)
    doc = request_doc()
    outside = public_ship(st)
    real = st.store.ship_for_key
    no_lookup(st)
    assert tailnet_only(outside.post('/api/imprints', content=canonical(doc)))
    assert requests(st) == 0 and staging(st) == []
    monkeypatch.setattr(st.store, 'ship_for_key', real)
    made = st.voyager.post('/api/imprints', content=canonical(doc))
    assert made.status_code == 201, made.text
    assert requests(st) == 1


@pytest.mark.parametrize('client, headers', [(PUBLIC_CLIENT, {}),
                                             (TAILNET_SHIP, {'tailscale-funnel-request': '?1'})],
                         ids=['internet-address', 'funnel-header'])
def test_every_public_upload_is_refused_and_the_tailnet_one_works(tmp_path, monkeypatch, no_lookup, client, headers):
    st, made, data = allowed_with_all_parts(tmp_path)
    rid = made['id']
    outside = public_ship(st, client=client, **headers)
    real = st.store.ship_for_key
    no_lookup(st)
    assert tailnet_only(outside.post('/api/imprints', content=canonical(request_doc())))
    assert tailnet_only(outside.put(f'/api/imprints/{rid}/parts/0', content=data[:PART_BYTES]))
    assert tailnet_only(outside.post(f'/api/imprints/{rid}/complete'))
    assert row(st, rid)['status'] == 'allowed' and requests(st) == 1
    monkeypatch.setattr(st.store, 'ship_for_key', real)
    assert st.voyager.put(f'/api/imprints/{rid}/parts/0', content=data[:PART_BYTES]).status_code == 200
    assert st.voyager.post(f'/api/imprints/{rid}/complete').json()['status'] == 'received'


def test_a_public_manifest_is_refused_and_the_tailnet_one_works(tmp_path):
    st = station(tmp_path)
    made, data = requested_with_package(st)
    assert confirm(st.sam, made).status_code == 200
    manifest = canonical(manifest_for_doc(st, made, data))
    assert tailnet_only(public_ship(st).put(f"/api/imprints/{made['id']}/manifest", content=manifest))
    assert not (st.store.data_dir / 'imprints' / made['id'] / 'manifest.json').exists()
    assert st.voyager.put(f"/api/imprints/{made['id']}/manifest", content=manifest).status_code == 200


def test_a_public_part_writes_no_file(tmp_path):
    st, made, data = allowed_with_manifest(tmp_path, nbytes=PART_BYTES)
    before = sorted(p.name for p in (st.store.data_dir / 'imprints' / made['id']).iterdir())
    assert tailnet_only(public_ship(st).put(f"/api/imprints/{made['id']}/parts/0", content=data))
    assert sorted(p.name for p in (st.store.data_dir / 'imprints' / made['id']).iterdir()) == before
    assert st.voyager.get(f"/api/imprints/{made['id']}").json()['held'] == []


def test_a_tailnet_address_is_not_refused(tmp_path):
    st = station(tmp_path)
    made = public_ship(st, client=TAILNET_SHIP).post('/api/imprints', content=canonical(request_doc()))
    assert made.status_code == 201, made.text
