"""The docs name what the imprint spec requires (I 15). Skipped in the standalone peer bundle."""
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not (REPO / 'CLAUDE.md').is_file() or not (REPO / 'engram' / 'CLAUDE.md').is_file(),
                                reason='needs CLAUDE.md and engram/ from the full repository')


def test_the_docs_name_what_the_spec_requires():
    api, engram_md, claude_md = ((REPO / 'peer' / 'API.md').read_text(), (REPO / 'engram' / 'CLAUDE.md').read_text(),
                                 (REPO / 'CLAUDE.md').read_text())
    for route in ('POST /api/imprints', '/api/imprints/{id}/confirm', '/api/imprints/{id}/parts/{n}',
                  '/api/imprints/{id}/withdraw', 'imprint-permission', 'imprint-receipt', 'roads_and_trails',
                  'sessions_too_large'):
        assert route in api, route
    assert '**Imprints:**' in engram_md and '| `imprint.py` |' in engram_md
    assert '| `imprint_filter.py` |' in engram_md and '| `imprint_checks.py` |' in engram_md
    approving = claude_md.split('# Approving on the station')[1]
    assert 'IMPRINT' in approving and '~/.engram/imprints/' in approving and 'imprint.py use' in approving
    assert 'other people' in approving and 'MemoryMax=512M' in engram_md
    assert 'G18' in approving and 'signed by the lighthouse' in api and 'YN1' in api
