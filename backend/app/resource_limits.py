"""Single-process admission and bounded body buffering before multipart creates temp files."""
from starlette.responses import JSONResponse
from . import config
from .rate_limits import operation_groups


class ResourceLimitsMiddleware:
    def __init__(self, app):
        self.app = app
        self.active = 0
        self.owners = set()

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        groups = operation_groups(scope)
        path = scope["path"].rstrip("/")
        if config.PUBLIC_DEMO and ("collection" in groups or path.endswith("/ai-summary")
                                   or "/jobs/" in path or path.endswith("/jobs")):
            return await JSONResponse(
                {"detail": "This feature is unavailable in the hosted showcase."}, status_code=404,
            )(scope, receive, send)
        expensive = (scope['method'] in {'POST', 'PUT', 'PATCH', 'DELETE'}
                     or bool(set(groups) & {'export', 'ai'}))
        principal = scope.get('state', {}).get('principal')
        owner = principal.owner_id if principal is not None else None
        if expensive and (self.active >= config.MAX_EXPENSIVE_REQUESTS or owner in self.owners):
            return await JSONResponse({'detail': 'The server is busy. Please retry shortly.'},
                                      status_code=429, headers={'Retry-After': '5'})(scope, receive, send)
        if expensive:
            self.active += 1
            if owner is not None:
                self.owners.add(owner)
        try:
            headers = dict(scope.get('headers', []))
            if headers.get(b'content-encoding', b'identity').lower() != b'identity':
                return await JSONResponse({'detail': 'Compressed request bodies are not supported.'}, 415)(scope, receive, send)
            try:
                declared = int(headers.get(b'content-length', b'0'))
                if declared < 0:
                    raise ValueError
            except ValueError:
                return await JSONResponse({'detail': 'Invalid request length.'}, 400)(scope, receive, send)
            if declared > config.MAX_REQUEST_BYTES:
                return await JSONResponse({'detail': 'The request exceeds the body-size limit.'}, 413)(scope, receive, send)
            body = bytearray()
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                chunk = message.get('body', b'')
                if len(body) + len(chunk) > config.MAX_REQUEST_BYTES:
                    return await JSONResponse({'detail': 'The request exceeds the body-size limit.'}, 413)(scope, receive, send)
                body.extend(chunk)
                if not message.get('more_body', False):
                    break
            delivered = False
            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                return await receive()
            await self.app(scope, replay, send)
        finally:
            if expensive:
                self.active -= 1
                self.owners.discard(owner)
