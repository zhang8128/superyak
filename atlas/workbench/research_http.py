"""Stdlib HTTP reads and writes governed by one absolute request deadline."""

from __future__ import annotations

from functools import partial
import http.client
import io
import socket
import time
from urllib.error import HTTPError
from urllib.request import HTTPHandler, HTTPRedirectHandler, HTTPSHandler, ProxyHandler, build_opener


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("HTTP request deadline expired")
    return remaining


class _DeadlineReader(io.RawIOBase):
    def __init__(self, raw, sock, deadline):
        self.raw, self._sock, self.deadline = raw, sock, deadline

    def readable(self):
        return True

    def readinto(self, buffer):
        # A socket inactivity timeout alone never expires on a slow drip.
        self._sock.settimeout(_remaining(self.deadline))
        return self.raw.readinto(buffer)

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class _DeadlineSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def makefile(self, mode):
        # Preserve the socket's makefile reference counting when urllib closes
        # its connection while the response still owns a readable body.
        raw = self.sock.makefile(mode, buffering=0)
        return io.BufferedReader(_DeadlineReader(raw, self.sock, self.deadline))


class _DeadlineConnection:
    def __init__(self, *args, deadline, **kwargs):
        self.deadline = deadline
        super().__init__(*args, **kwargs)
        self._create_connection = self._connect_socket
        self.response_class = lambda sock, **options: http.client.HTTPResponse(
            _DeadlineSocket(sock, self.deadline), **options)

    def _connect_socket(self, address, timeout=None, source_address=None):
        _remaining(self.deadline)
        # DNS cannot be interrupted portably by Python. The caller bounds this
        # worker separately; critically, a late DNS answer never starts a socket.
        addresses = socket.getaddrinfo(*address, 0, socket.SOCK_STREAM)
        _remaining(self.deadline)
        last_error = None
        for family, kind, protocol, _, target in addresses:
            _remaining(self.deadline)
            sock = socket.socket(family, kind, protocol)
            try:
                sock.settimeout(_remaining(self.deadline))
                if source_address:
                    sock.bind(source_address)
                sock.connect(target)
                # Refresh the remaining budget before a possible TLS handshake.
                sock.settimeout(_remaining(self.deadline))
                return sock
            except OSError as exc:
                sock.close()
                last_error = exc
        raise last_error or OSError("DNS returned no addresses")

    def send(self, data):
        if self.sock is None:
            self.connect()
        # This also protects proxy CONNECT and requests following slow TLS setup.
        self.sock.settimeout(_remaining(self.deadline))
        super().send(data)


class _HTTPConnection(_DeadlineConnection, http.client.HTTPConnection):
    pass


class _HTTPSConnection(_DeadlineConnection, http.client.HTTPSConnection):
    pass


class _HTTPHandler(HTTPHandler):
    def __init__(self, deadline):
        super().__init__()
        self.deadline = deadline

    def http_open(self, request):
        return self.do_open(partial(_HTTPConnection, deadline=self.deadline), request)


class _HTTPSHandler(HTTPSHandler):
    def __init__(self, deadline):
        super().__init__()
        self.deadline = deadline

    def https_open(self, request):
        return self.do_open(partial(_HTTPSConnection, deadline=self.deadline), request,
                            context=self._context)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(req.full_url, code, "Redirects are disabled", headers, fp)


def open_with_deadline(request, *, timeout, deadline, use_environment_proxy=True):
    # Local model prompts must reach their explicit endpoint directly, regardless
    # of machine-wide proxy or proxy-credential settings. Papers retain proxies.
    proxy = ProxyHandler() if use_environment_proxy else ProxyHandler({})
    opener = build_opener(proxy, _NoRedirect(), _HTTPHandler(deadline), _HTTPSHandler(deadline))
    _remaining(deadline)
    return opener.open(request, timeout=timeout)
