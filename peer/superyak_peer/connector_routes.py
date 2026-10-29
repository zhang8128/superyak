"""The remote connector's routes, installed only with `serve --public-origin` (connector plan, Task 3). Each answers 404
on any other origin, needs no session, and checks what it needs itself; none sends CORS headers. The routes the
later tasks build answer 501 until then. An async route here runs every identity check and store call in the
threadpool, never on the event loop (fix:actor-off-the-event-loop); a sync one runs there anyway."""
import json
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool

from .common import Problem
from .connector import (REGISTER_BODY_MAX, OAuthError, RedirectError, check_callback, issuer_metadata,
                        resource_metadata)

NOT_YET = 'Not built yet'
# /authorize's page for a request whose client or redirect can't be trusted, so it can't be sent back (spec "Validate
# first"). It repeats nothing the request carried.
REFUSED_PAGE = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
                'content="width=device-width, initial-scale=1"><title>This connection can\'t be used</title></head>'
                '<body><main><h1>This connection can\'t be used</h1><p>The request to connect to this home isn\'t '
                'one it can check, so nothing was shared. Go back to Claude and connect again.</p></main></body></html>')


def install(app, public_origin, callback):
    callback = check_callback(callback)
    app.state.public_origin, app.state.connector_callback = public_origin, callback
    store = app.state.store
    # On the app itself, not an APIRouter: PublicRoute's allow-list matches the app's own route objects, and an included
    # router is one object to it, so every route in it would stay closed to public requests.

    def on_public_origin(request: Request):
        """The request reached the configured public origin. Nothing else is derived from the Host header."""
        return f'{request.url.scheme}://{request.url.netloc}'.lower() == public_origin

    def answer(request, value, status=200):
        if not on_public_origin(request):
            return JSONResponse({'error': 'Not found'}, 404)
        return JSONResponse(value, status)

    @app.get('/.well-known/oauth-protected-resource')
    def protected_resource(request: Request):
        return answer(request, resource_metadata(public_origin))

    @app.get('/.well-known/oauth-protected-resource/mcp')
    def protected_resource_mcp(request: Request):
        return answer(request, resource_metadata(public_origin))

    @app.get('/.well-known/oauth-authorization-server')
    def authorization_server(request: Request):
        return answer(request, issuer_metadata(public_origin))

    @app.post('/register')
    async def register(request: Request):
        """RFC 7591, bounded and stateless (spec revision 4, D18): an 8 KB body in bytes, then the store's checks.
        Nothing is written."""
        if not on_public_origin(request):
            return JSONResponse({'error': 'Not found'}, 404)
        raw = await request.body()
        if len(raw) > REGISTER_BODY_MAX:
            return JSONResponse({'error': 'invalid_client_metadata'}, 413)
        try:
            metadata = json.loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError):
            return JSONResponse({'error': 'invalid_client_metadata'}, 400)
        try:
            made = await run_in_threadpool(store.register_client, metadata, callback)
        except OAuthError as refused:
            return JSONResponse({'error': refused.error}, refused.status)
        return JSONResponse(made, 201)

    @app.get('/authorize')
    def authorize(request: Request):
        """Spec revision 4, "The authorization request": the client and the redirect first, a refusal shown as a page;
        then the rest, a refusal sent back to the redirect with `error`, `state` and `iss`; then the consent page, the
        request signed into its fragment. It writes nothing (D18). A parameter sent twice is refused (RFC 6749 3.1)."""
        if not on_public_origin(request):
            return JSONResponse({'error': 'Not found'}, 404)
        items = request.query_params.multi_items()
        names, params = [name for name, _ in items], dict(items)
        if names.count('client_id') > 1 or names.count('redirect_uri') > 1:
            return HTMLResponse(REFUSED_PAGE, 400)
        try:
            store.check_client(params.get('client_id'), params.get('redirect_uri'), callback)
        except OAuthError:
            return HTMLResponse(REFUSED_PAGE, 400)

        def back(error):
            answer = {'error': error} | ({'state': params['state']} if params.get('state') is not None else {})
            return RedirectResponse(callback + '?' + urlencode(answer | {'iss': public_origin}), 303)
        if len(names) != len(set(names)):
            return back('invalid_request')
        try:
            fragment = store.sign_pending(params, public_origin, public_origin + '/mcp')
        except RedirectError as refused:
            return back(refused.error)
        return RedirectResponse(public_origin + '/assets/consent.html#' + fragment, 303)

    @app.post('/authorize/signin')
    async def signin(request: Request):
        """The consent page's first post: {request, username, password}. Its identity is in its body (the signed
        request and the password), so it can't refuse before reading it; the event-loop guard lists it as ANONYMOUS
        for that reason. The request is checked off the lane, so a forged one takes no sign-in slot and counts no
        attempt; the password is checked in the lane /api/login uses, counted as it counts."""
        if not on_public_origin(request):
            return JSONResponse({'error': 'Not found'}, 404)
        raw = await request.body()
        if len(raw) > REGISTER_BODY_MAX:
            return JSONResponse({'error': 'invalid_request'}, 413)
        try:
            data = json.loads(raw)
        except (ValueError, UnicodeDecodeError, RecursionError):
            data = None
        if not isinstance(data, dict):
            return JSONResponse({'error': 'invalid_request'}, 400)
        try:
            pending = await run_in_threadpool(store.pending_request, data.get('request'), callback, public_origin + '/mcp')
            username = data.get('username')
            lane, public, device = await request.app.state.sign_in_lane(request, username)
            view = await lane.run(store.pending_sign_in, pending, username, data.get('password'),
                                  request.client.host if request.client else 'unknown', public=public, device=device)
        except OAuthError as refused:
            return JSONResponse({'error': refused.error}, refused.status)
        except Problem as refused:  # the lane full, or a username that isn't text
            return JSONResponse({'error': 'too_many_attempts' if refused.status == 429 else 'invalid_request'},
                                429 if refused.status == 429 else 400)
        return JSONResponse(view)

    def not_yet(request: Request):
        return answer(request, {'error': NOT_YET}, 501)

    for path, methods in (('/authorize/decision', ['POST']), ('/token', ['POST']),
                          ('/mcp', ['GET', 'POST', 'DELETE'])):
        app.add_api_route(path, not_yet, methods=methods)
