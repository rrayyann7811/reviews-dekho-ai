"""Explicit multipart lifecycle, including unfinished parts not present in FormData."""
from fastapi.routing import APIRoute
from starlette.formparsers import MultiPartParser, MultiPartException
from .errors import AppError
from . import config


class CompleteMultipartParser(MultiPartParser):
    complete = False

    def on_end(self):
        self.complete = True
        super().on_end()


class UploadRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            if not request.headers.get('content-type', '').lower().startswith('multipart/form-data'):
                return await original(request)
            parser = CompleteMultipartParser(request.headers, request.stream(), max_files=1, max_fields=8,
                                             max_part_size=config.MAX_FORM_FIELD_BYTES)
            try:
                try:
                    form = await parser.parse()
                except MultiPartException:
                    raise AppError('The multipart upload is invalid or exceeds its part limits.') from None
                if not parser.complete:
                    raise AppError('The multipart upload is incomplete.')
                # FastAPI reuses Starlette's cached form instead of parsing the stream twice.
                request._form = form
                return await original(request)
            finally:
                # Starlette's FormData omits unfinished file parts. Track the parser's handles too.
                # This private integration is covered by truncated/cancellation regression tests.
                for file in parser._files_to_close_on_error:
                    file.close()

        return handler
