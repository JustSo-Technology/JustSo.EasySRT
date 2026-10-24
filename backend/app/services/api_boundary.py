"""Authentication transport boundary, bounded bodies and secret-free API errors."""
import logging
import re
from uuid import uuid4
from fastapi import Request
from sqlalchemy.exc import OperationalError
from fastapi.responses import JSONResponse
from app.core.settings import settings

logger = logging.getLogger(__name__)


class ApiAccessLogFilter(logging.Filter):
    def filter(self, record):
        # Uvicorn access arguments contain the raw URL, even for rejected auth.
        # Do not preserve query strings or bearer-shaped path data in access logs.
        if isinstance(record.args, tuple) and len(record.args) == 5:
            values = list(record.args)
            values[2] = re.sub(r'esrt_[A-Za-z0-9_-]+', '[redacted]', str(values[2]).split('?', 1)[0])
            record.args = tuple(values)
        return True


def install_access_log_filter():
    access = logging.getLogger('uvicorn.access')
    if not any(isinstance(f, ApiAccessLogFilter) for f in access.filters):
        access.addFilter(ApiAccessLogFilter())


def api_error(code, message, request_id, headers=None):
    return JSONResponse(status_code=code, content={'code': {400: 'invalid_authentication_mode', 401: 'invalid_token',
        403: 'insufficient_scope', 404: 'not_found', 409: 'conflict', 413: 'payload_too_large',
        422: 'invalid_payload', 428: 'precondition_required', 429: 'rate_limited', 503: 'unavailable'}.get(code, 'request_failed'),
        'detail': message, 'request_id': request_id}, headers={**(headers or {}), 'Cache-Control': 'no-store', 'X-Request-ID': request_id, 'X-Content-Type-Options': 'nosniff', 'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer'})


async def boundary(request: Request, call_next):
    path = request.url.path
    bearer = request.headers.get('Authorization')
    versioned = path == '/api/v1' or path.startswith('/api/v1/')
    request.state.api_request_id = uuid4().hex
    request_id = request.state.api_request_id
    if bearer:
        if request.cookies.get(settings.session_cookie_name):
            return api_error(400, 'Do not combine browser sessions and API tokens', request_id)
        if not versioned or path.startswith('/api/v1/tokens') or path == '/api/v1/token-catalogue':
            return api_error(401, 'This route does not accept integration credentials', request_id, {'WWW-Authenticate': 'Bearer'})
    if versioned:
        if any(key.lower() in {'token', 'access_token', 'api_key', 'authorization'} for key in request.query_params):
            return api_error(400, 'Credentials must not be supplied in query parameters', request_id)
        # uvicorn supplies scheme only after its trusted-proxy policy. Never trust
        # an arbitrary X-Forwarded-Proto header here.
        if request.url.scheme != 'https':
            return api_error(400, 'The API requires HTTPS, including token administration', request_id)
        if request.method in {'POST', 'PUT', 'PATCH'}:
            body = bytearray()
            async for chunk in request.stream():
                if len(body) + len(chunk) > 1_048_576:
                    return api_error(413, 'API payload exceeds 1 MiB', request_id)
                body.extend(chunk)
            request._body = bytes(body)  # Starlette's cached Request is replayed by call_next.
    try:
        response = await call_next(request)
    except Exception as exc:
        if not versioned:
            raise
        # Never log exception repr/SQL parameters/validation inputs containing a secret.
        logger.error('API request failed request_id=%s exception_type=%s', request_id, type(exc).__name__)
        response = api_error(503 if isinstance(exc, OperationalError) else 500, 'API operation failed; reconcile status using the request ID', request_id)
    if versioned:
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Request-ID'] = request_id
        if response.status_code >= 400 and getattr(request.state, 'api_token_id', None) and getattr(request.state, 'api_actor_id', None):
            from sqlmodel import Session
            from app.core.db import get_engine
            from app.services.api_tokens import audit
            try:
                with Session(get_engine()) as session:
                    audit(session, request.state.api_actor_id, 'api:denied' if response.status_code in {403, 404} else 'api:error',
                          token_id=request.state.api_token_id, outcome=str(response.status_code), request_id=request_id)
                    session.commit()
            except OperationalError:
                logger.error('API audit storage unavailable request_id=%s', request_id)
    return response
