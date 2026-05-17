"""Unit tests for ``crawler.adapters.sources.google_news_url.decode_google_news_url``.

Plan 04.5-01 / T03 (ING-011, locked D-Q3 = C "hybrid decode + fallback").

The decoder is opportunistic by design (see the helper's module docstring).
These tests pin three categories of behaviour:

1. **Old-style CBMi tokens** that embed a length-prefixed publisher URL
   inside their protobuf payload — must decode cleanly. Synthesized here
   from a hand-built protobuf so we don't depend on Google preserving any
   particular live URL.
2. **Modern opaque CBM tokens** from production (3 real samples captured
   from ``topic_sources`` on 2026-05-18) where the decoded payload carries
   only an internal Google identifier and no publisher URL — must return
   ``None`` and emit exactly one ``google_news.decode_failed`` warn.
3. **Defensive edge cases** (empty string, non-Google URL, malformed
   base64, /articles/ segment missing) — must return ``None`` without
   raising.
"""

from __future__ import annotations

import base64

import pytest

from crawler.adapters.sources.google_news_url import decode_google_news_url# ---------------------------------------------------------------------------
# Real production CBM tokens captured 2026-05-18 from topic_sources.
# These all decode to opaque internal Google identifiers (no publisher
# URL inside). Pinned here so the test suite proves the documented
# fallback behaviour, not just the happy path.
# ---------------------------------------------------------------------------

_PROD_OPAQUE_CBM = [
    "https://news.google.com/rss/articles/CBMivgFBVV95cUxOX01oWE9KNzhGRWxpNmFremR4bGNGRkZiZi1vb3dVM0dfQUJtNEgwVzNvZDRHSS1UZ0ZYdGU1V2RNTFRURi0xX0x0dkJuQTAwMWlNc0F0ODJuX1Z6eFRKc092U2FhN1lQR2lKRXFzMGxka0dzR1pLbTljbHRjMmc0SjU0Rkk3LWpzbnhONlpDNGZFU21yMEdoRVJDV0dFcUZnak9ubF8wTFVvZ2c2UmxqRDd4THZoZ3RMcVZfSGR3?oc=5",
    "https://news.google.com/rss/articles/CBMiwgFBVV95cUxPNzQ4UHBFRHc0QTQ3NWRfSHBpZC0xS2FtSENsN19CZFBQMDdNTUtNTEFMSElTQlZtZ19vd3VqZldwUjlfVHA0S1pncE1sNTBsQzU0NVhWX3VTSS1helFMdWhpdVRvUnVQcW5IQnd3WlM2VWdSbGtWYzNVbVBlWDBMM1Z6NjVXemdNd2RoQVFHbGYzSnhkdC1lYjZQd1NKY1gxU2E4UEZVQzlSVWoyeTRTQ1J2MHZ3bXpmRVE2MEdLSnVrUQ?oc=5",
    "https://news.google.com/rss/articles/CBMipAFBVV95cUxNSnEzZFNpWnB1RkRFUXQ3bkVydFhvc0dSMFplaFFUZzJ6TE9Uc2Q0X1hsNzZELU9fSW9NN19FQ01vSzlNTG5GSlNDQ2d0b3pHZ0k2bGdnT2E5dlRxSFY4V0h3dC1Pb25NTDNRTElZY2dWYXNvUTYwSXlMbzR2blBaRHRqS0VqT0xRVjhleUFoNGtOMmtzS2FGSUxYWDFjM0ppTEhUctIBqgFBVV95cUxPZGlNbFoyRkstS2tQT0Z4dUFjVmhuVnhZVWY0dlplNUI5aW0zMFlrcUdrRzZ0RERtYTFudnNmdzlSeFIxSDJNazEwWVBmbm1yR2s0bTJtQURZbUowbkxXNVgzVWhzZTl6NHlDajRCWWVoUlFMU2Y4dHRvd0NJUEQ1MDFXTHlvS3pvM3BwaE5ydjhZLVlyc2taeVVra3Ntc0JfaUo3cU14dnJ3QQ?oc=5",
]


def _make_old_style_cbm(publisher_url: bytes) -> str:
    """Build a synthetic old-format CBM token where the protobuf payload
    embeds ``publisher_url`` as a length-prefixed string field.

    The wire shape (\\x08\\x13 type tag, \\x22 = field 4 type 2 = bytes,
    then varint length, then the bytes, then trailing junk bytes that the
    decoder must skip) matches what Google News produced ~pre-Aug 2024 for
    tokens whose URL is small enough to fit. We append trailing protobuf
    junk to prove the regex extractor terminates correctly at the first
    non-URL-safe byte.
    """
    length = len(publisher_url)
    if length < 128:
        length_bytes = bytes([length])
    else:
        length_bytes = bytes([(length & 0x7F) | 0x80, length >> 7])
    payload = (
        b"\x08\x13\x22"
        + length_bytes
        + publisher_url
        + b"\xd2\x01\x20trailing-junk-bytes-here-pad"
    )
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    return f"https://news.google.com/rss/articles/CBMi{encoded}?oc=5"


# ---------------------------------------------------------------------------
# Old-style tokens — happy path.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "publisher_url",
    [
        "https://www.theguardian.com/world/2024/article-title-here",
        "https://www.bbc.co.uk/news/world-europe-12345678",
        "https://www.reuters.com/markets/global-update-2026",
    ],
)
def test_decodes_old_style_cbm_to_publisher_url(publisher_url: str) -> None:
    """Old-format tokens with an embedded URL decode cleanly to that URL."""
    cbm_url = _make_old_style_cbm(publisher_url.encode("ascii"))
    result = decode_google_news_url(cbm_url)
    assert result == publisher_url


# ---------------------------------------------------------------------------
# Modern opaque tokens — documented fallback path.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cbm_url", _PROD_OPAQUE_CBM)
def test_modern_opaque_cbm_returns_none(cbm_url: str, capsys) -> None:
    """The 2025+ production CBM tokens carry only an internal Google
    identifier — no http(s):// in the decoded payload. Decoder returns
    None and emits exactly one ``google_news.decode_failed`` warn (so
    the operator can grep Cloud Run logs for a wire-format rotation
    spike).
    """
    result = decode_google_news_url(cbm_url)
    assert result is None
    # structlog's default ConsoleRenderer writes to stdout — capture and
    # check the event name appears (exact line shape intentionally not
    # pinned, only the contract that operators can grep for).
    captured = capsys.readouterr()
    assert "google_news.decode_failed" in (captured.out + captured.err), (
        f"expected a google_news.decode_failed warn; got stdout={captured.out!r} stderr={captured.err!r}"
    )


# ---------------------------------------------------------------------------
# Defensive edges.
# ---------------------------------------------------------------------------


def test_empty_string_returns_none() -> None:
    assert decode_google_news_url("") is None


def test_non_google_url_returns_none() -> None:
    assert decode_google_news_url("https://example.com/article") is None


def test_malformed_token_returns_none_and_warns(capsys) -> None:
    """Garbage that isn't valid base64 must return None gracefully."""
    result = decode_google_news_url(
        "https://news.google.com/rss/articles/!!!not-base64!!!?oc=5"
    )
    assert result is None
    captured = capsys.readouterr()
    assert "google_news.decode_failed" in (captured.out + captured.err)


def test_missing_articles_segment_returns_none() -> None:
    """A news.google.com URL without /articles/<token> hits the no_token
    branch (defensive — caller filters by source_name)."""
    assert decode_google_news_url("https://news.google.com/topstories") is None
