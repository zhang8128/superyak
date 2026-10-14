"""The restore (docs/superpowers/specs/2026-10-14-station-backups-alerts-design.md, S6, S7, S16; R7-R9, R18). Every
test works in tmp_path; the restore test boots real loopback servers and stops every one of them."""
from contextlib import closing
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import pytest
from fastapi.testclient import TestClient
from superyak_peer import backups
from superyak_peer.__main__ import main as cli
from superyak_peer.app import create_app
from superyak_peer.auth import token_hash
from superyak_peer.common import Problem
from superyak_peer.db import Store
from superyak_peer.door import create_door


def test_health_answers_without_a_session(tmp_path, monkeypatch):
    """R7: 200 with exactly {"ok": true}, no session, after one database read (a failing read is the 500 handler's);
    the door answers 404."""
    app = create_app(tmp_path / 'peer', clock=lambda: 1000000.0, allowed_origins=['http://testserver'])
    reply = TestClient(app, base_url='http://testserver').get('/api/health')
    assert reply.status_code == 200 and reply.json() == {'ok': True} and 'set-cookie' not in reply.headers
    door = TestClient(create_door(tmp_path / 'peer', clock=lambda: 1000000.0), base_url='https://door.example:8443')
    assert door.get('/api/health').status_code == 404

    def broken():
        raise sqlite3.OperationalError('disk I/O error')

    monkeypatch.setattr(app.state.store, 'transaction', broken)
    reply = TestClient(app, base_url='http://testserver', raise_server_exceptions=False).get('/api/health')
    assert reply.status_code == 500 and reply.json() == {'error': 'Request could not be completed'}
