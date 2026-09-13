"""Session-authorized optional assistance and explicit source interchange."""
from fastapi import Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from .app import actor, body
from .common import Problem, text
from .interchange import Interchange


def install(app):
    store = app.state.store
    sources = app.state.interchange = Interchange(store, app.state.federation.identity.peer_id)

    @app.get('/api/assistant')
    def assistant_status(request: Request):
        actor(request)
        return app.state.assistant.status()

    @app.post('/api/assistant')
    async def assist(request: Request):
        who, data = actor(request), await body(request)
        if set(data) - {'text', 'layer_id', 'version'}:
            raise Problem(400, 'Unknown assistant field')
        draft = None
        if data.get('layer_id') is not None:
            text(data['layer_id'], 'layer ID', 100)
            draft = store.get_layer(who, data['layer_id'])
            if type(data.get('version')) is not int or data['version'] != draft['version']:
                raise Problem(409, 'Selected saved draft changed; review its version again')
        elif 'version' in data:
            raise Problem(400, 'Choose a saved draft for this version')
        result = await run_in_threadpool(app.state.assistant.suggest, data.get('text'), draft)
        return {**result, 'layer_id': draft['id'] if draft else None, 'version': draft['version'] if draft else None}

    @app.get('/api/sources')
    def source_list(request: Request):
        return sources.sources(actor(request))

    @app.post('/api/interchange/export')
    async def source_export(request: Request):
        who, data = actor(request), await body(request)
        return sources.export(who, data)

    @app.post('/api/interchange/import', status_code=201)
    async def source_import(request: Request):
        who, data = actor(request), await body(request)
        return sources.import_document(who, data)

    @app.get('/api/interchange/adna/{key}')
    def source_adna(key: str, request: Request):
        result = sources.adna(actor(request), key)
        return Response(result, media_type='application/octet-stream', headers={'Content-Disposition': 'attachment; filename="selected-source.md"'})
