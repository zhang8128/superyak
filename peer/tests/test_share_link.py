import importlib.util
import io
import json
from pathlib import Path


def load():
    path = Path(__file__).resolve().parents[1] / 'scripts' / 'share_link.py'
    spec = importlib.util.spec_from_file_location('share_link', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_creates_one_reusable_invite_for_the_device_and_saves_it_privately(tmp_path):
    share = load()
    seen = {}

    def opener(request, timeout):
        seen.update(url=request.full_url, auth=request.get_header('Authorization'), body=json.loads(request.data))
        return Response(json.dumps([{'inviteUrl': 'https://login.tailscale.com/admin/invite/abc'}]).encode())
    url = share.create_link('tskey-api-x', 'nDEVICE', opener=opener)
    assert url == 'https://login.tailscale.com/admin/invite/abc'
    assert seen == {'url': 'https://api.tailscale.com/api/v2/device/nDEVICE/device-invites', 'auth': 'Bearer tskey-api-x',
                    'body': [{'multiUse': True, 'allowExitNode': False}]}
    out = tmp_path / 'cfg' / 'tailscale-share-url'
    share.write_private(out, url)
    assert out.read_text() == url + '\n' and out.stat().st_mode & 0o777 == 0o600
