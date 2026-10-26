"""External responses use allowlists; URL credentials are never ordinary config."""
import re
from urllib.parse import urlsplit, urlunsplit
from fastapi import HTTPException


def safe_url(value):
    try:
        p = urlsplit(value)
        if not p.scheme:
            return value
        host = p.hostname or ''
        if ':' in host:
            host = '[' + host + ']'
        if p.port:
            host += ':' + str(p.port)
        return urlunsplit((p.scheme, host, '/[redacted]' if p.path else '', '', ''))
    except (ValueError, TypeError):
        return '[redacted]'


def has_secret(value):
    return isinstance(value, str) and safe_url(value) != value


def redact(value):
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items() if k.lower() not in {
            'password', 'passphrase', 'secret', 'authorization', 'ffmpeg_args', 'ffmpeg_command',
            'stderr_tail', 'sender_env_path', 'last_command', 'token_hash', 'secret_hash'}}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'\b(?:esrt|ntfy)_[A-Za-z0-9_-]+', '[redacted]', value)
        value = re.sub(r'(?:https?|srt|rtsp|rtmp|udp|rtp|file)://[^\s"<>]+', lambda m: safe_url(m[0]), value)
        return re.sub(r'(?i)(password|passphrase|token|secret|authorization)(\s*[=:]\s*)[^\s,;]+', r'\1\2[redacted]', value)
    return value


def source_view(source, principal, kind, resource_id):
    result = source.copy()
    if 'url' in result and has_secret(result['url']) and not principal.allows('secrets:read', kind, resource_id):
        result['url'] = safe_url(result['url'])
        result['url_has_secret'] = True
    return result


def merge_source(incoming, old, principal, kind, resource_id):
    if not isinstance(incoming, dict):
        raise HTTPException(422, "Source settings must be an object")
    incoming = incoming.copy()
    incoming.pop('url_has_secret', None)
    clear = incoming.pop('clear_url_secret', False)
    if type(clear) is not bool:
        raise HTTPException(422, 'clear_url_secret must be a boolean')
    if clear:
        principal.require('secrets:update', kind, resource_id)
    if 'url' not in incoming and old:
        incoming['url'] = old['url']
    elif not clear and old and has_secret(old.get('url')) and incoming.get('url') == safe_url(old['url']):
        # An unchanged redacted projection preserves credentials, never clears them.
        incoming['url'] = old['url']
    changed = not old or incoming.get('url') != old.get('url')
    if changed and (has_secret(incoming.get('url')) or (old and has_secret(old.get('url')))):
        principal.require('secrets:update', kind, resource_id)
    return incoming
