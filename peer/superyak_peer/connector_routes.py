"""The remote connector's routes, installed only with `serve --public-origin` (connector plan, Task 3). Each answers 404
on any other origin, needs no session, and checks what it needs itself; none sends CORS headers. The routes the
later tasks build answer 501 until then."""
from fastapi import Request
from fastapi.responses import JSONResponse

from .connector import issuer_metadata, resource_metadata

NOT_YET = 'Not built yet'


def install(app, public_origin, callback):
    app.state.public_origin, app.state.connector_callback = public_origin, callback
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

    def not_yet(request: Request):
        return answer(request, {'error': NOT_YET}, 501)

    for path, methods in (('/register', ['POST']), ('/authorize', ['GET']), ('/authorize/request', ['POST']),
                          ('/authorize/signin', ['POST']), ('/authorize/decision', ['POST']), ('/token', ['POST']),
                          ('/mcp', ['GET', 'POST', 'DELETE'])):
        app.add_api_route(path, not_yet, methods=methods)
