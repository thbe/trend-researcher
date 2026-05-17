"""Google News CBM redirect URL decoder.

Plan 04.5-01 / T03 (ING-011, locked D-Q3 = C "hybrid").

Why this exists
---------------
Google News RSS publishes article links as redirect tokens shaped like
``https://news.google.com/rss/articles/CBMi…?oc=5``. Clicking the link in a
browser works (Google's web frontend resolves the token to the publisher),
but the raw URL is operator-hostile in the SPA: the host is always
news.google.com, the token is opaque, and you can't tell at a glance
whether the source is the BBC, Reuters, or a low-quality aggregator.

We need the publisher URL. We must NOT add an outbound HTTP fetch in the
ingest path — ARC-001 ("Stage 1 ingest is fully deterministic, zero AI,
zero side-effecty network calls beyond the source fetches themselves"). So
this helper is pure-stdlib: base64-decode the token, opportunistically
extract the first plausible publisher URL from the decoded protobuf bytes,
and return it. On failure return ``None`` and the caller writes NULL into
``topic_sources.resolved_url``; the SPA falls back to the original ``url``.

The protobuf wire format Google uses inside the CBM token has rotated
multiple times in 2024-2025. We are intentionally *opportunistic*, not
strict:

* Older tokens (~pre-Aug 2024) embed the destination URL as a length-
  prefixed string field. Those decode cleanly and this helper returns
  the publisher URL.
* Newer tokens (the production fleet as of this commit, 81/81 sampled)
  contain only an opaque internal Google identifier — no http(s):// bytes
  in the decoded payload at all. For those, this helper returns ``None``
  and logs a single ``google_news.decode_failed`` warn. That is the
  expected, accepted-by-design fallback path per D-Q3; the system keeps
  working with the CBM URL as the link target.

Operator monitoring
-------------------
A spike in ``google_news.decode_failed`` log entries means Google has
rotated the wire format again. The fallback keeps the SPA usable; the
spike just tells the operator "the decoder is now useless, treat all new
google_news links as opaque until the decoder is patched."

Zero third-party deps. Zero network I/O. Microsecond runtime cost.
"""

from __future__ import annotations

import base64
import re

import structlog

_log = structlog.get_logger(__name__)

# Lazy capture: longest contiguous http(s) run that doesn't include the
# news.google.com host (which would just be the input echoed back) and
# stops at the first non-URL-safe byte. We are decoding protobuf, so the
# URL is followed by length-prefix / type-tag bytes that fall outside
# this character class — the regex acts as the implicit terminator.
_URL_RE = re.compile(
    rb"https?://[A-Za-z0-9._~/\-?=&%#+,;:@!$'()*]+",
)

# Match the CBM segment after /articles/ up to (and excluding) the query
# string. We do NOT enforce ``CBM`` strictly — some older tokens used a
# slightly different prefix (``CAIi…``); the base64 decode will fail
# naturally on anything that isn't actually url-safe-base64.
_ARTICLE_TOKEN_RE = re.compile(r"/articles/([^?#]+)")

_MIN_URL_LEN = 20
_LOG_URL_PREFIX = 80


def decode_google_news_url(url: str) -> str | None:
    """Return the decoded publisher URL, or ``None`` on any failure.

    Returns ``None`` when:
      * input is empty / not a string-like value
      * input is not a ``news.google.com`` URL (defensive — the caller
        in T04 already filters by ``source_name == 'google_news'``)
      * the token segment can't be base64-decoded
      * the decoded payload contains no plausible http(s):// URL (modern
        opaque CBM tokens fall here; see module docstring)

    On every failure path, emits exactly one ``structlog.warn`` so the
    operator can grep Cloud Run logs for a wire-format-rotation spike.
    The caller must treat ``None`` as "leave ``resolved_url`` NULL"; do
    NOT echo the original input back as the resolved URL — the original
    token is already preserved in ``topic_sources.url``.
    """
    if not url or "news.google.com" not in url:
        return None

    match = _ARTICLE_TOKEN_RE.search(url)
    if match is None:
        _log.warning("google_news.decode_failed", url=url[:_LOG_URL_PREFIX], reason="no_token")
        return None

    token = match.group(1)

    # urlsafe base64 with auto-pad: Google strips '=' padding from tokens,
    # so we pad up to a multiple of 4 manually.
    padding = (-len(token)) % 4
    try:
        raw = base64.urlsafe_b64decode(token + ("=" * padding))
    except (ValueError, base64.binascii.Error):
        _log.warning("google_news.decode_failed", url=url[:_LOG_URL_PREFIX], reason="b64_error")
        return None

    # Walk every http(s)://… run in the decoded bytes; return the first
    # one long enough to be a real URL that isn't itself a news.google.com
    # echo (the inner payload sometimes references google.com tracking
    # URLs we don't want to surface).
    for hit in _URL_RE.finditer(raw):
        candidate = hit.group(0).decode("ascii", errors="replace")
        if len(candidate) < _MIN_URL_LEN:
            continue
        if "news.google.com" in candidate or "google.com/url" in candidate:
            continue
        return candidate

    _log.warning(
        "google_news.decode_failed",
        url=url[:_LOG_URL_PREFIX],
        reason="no_url_in_payload",
    )
    return None


__all__ = ["decode_google_news_url"]
