"""Bounded OCR text cache shared by the API and the PDF worker through Redis."""
from functools import lru_cache
import json
import logging
import time

from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings
from app.services.pdf_layout_service import OCRText
from app.utils.text_quality import is_readable_text


logger = logging.getLogger(__name__)
# Bump the namespace when recognition or heading selection rules change.
CACHE_KEY = "digital-scientist:ocr:v1:pages"
CACHE_ORDER_KEY = "digital-scientist:ocr:v1:order"
MAX_ENTRIES = 256
MAX_ENTRY_BYTES = 128 * 1024
TTL_SECONDS = 24 * 60 * 60
CACHE_ERROR_COOLDOWN_SECONDS = 30
_unavailable_until = 0.0
STORE_SCRIPT = """
if redis.call('HSET', KEYS[1], ARGV[1], ARGV[2]) == 1 then
    redis.call('LPUSH', KEYS[2], ARGV[1])
end
while redis.call('LLEN', KEYS[2]) > tonumber(ARGV[3]) do
    local oldest = redis.call('RPOP', KEYS[2])
    redis.call('HDEL', KEYS[1], oldest)
end
redis.call('EXPIRE', KEYS[1], ARGV[4])
redis.call('EXPIRE', KEYS[2], ARGV[4])
return 1
"""


@lru_cache(maxsize=1)
def _client() -> Redis:
    return Redis.from_url(
        settings.celery_broker_url,
        decode_responses=True,
        socket_connect_timeout=0.2,
        socket_timeout=0.2,
    )


def get_cached_ocr(key: str) -> OCRText | None:
    global _unavailable_until
    if not settings.pdf_ocr_cache_enabled or time.monotonic() < _unavailable_until:
        return None
    try:
        payload = _client().hget(CACHE_KEY, key)
    except (RedisError, OSError):
        # Avoid paying a network timeout for every page of a long PDF when
        # Redis is down. Other extraction paths continue without the cache.
        _unavailable_until = time.monotonic() + CACHE_ERROR_COOLDOWN_SECONDS
        logger.debug("OCR cache read unavailable", exc_info=True)
        return None
    try:
        if not payload:
            return None
        value = json.loads(payload)
        text, title = value["text"], value.get("layout_title")
        if isinstance(text, str) and (title is None or isinstance(title, str)) and is_readable_text(text):
            return OCRText(text, title)
    except (ValueError, KeyError, TypeError):
        logger.debug("Invalid OCR cache entry", exc_info=True)
    return None


def store_cached_ocr(key: str, text: str) -> None:
    global _unavailable_until
    if (not settings.pdf_ocr_cache_enabled or time.monotonic() < _unavailable_until
            or not is_readable_text(text)):
        return
    payload = json.dumps({"text": str(text), "layout_title": getattr(text, "layout_title", None)}, ensure_ascii=False)
    if len(payload.encode("utf-8")) > MAX_ENTRY_BYTES:
        return
    try:
        _client().eval(STORE_SCRIPT, 2, CACHE_KEY, CACHE_ORDER_KEY, key, payload, MAX_ENTRIES, TTL_SECONDS)
    except (RedisError, OSError):
        _unavailable_until = time.monotonic() + CACHE_ERROR_COOLDOWN_SECONDS
        logger.debug("OCR cache write unavailable", exc_info=True)
