"""Unit tests for crawler.domain.dedup.

Pure-function tests. No I/O, no fixtures beyond stdlib.
"""

from crawler.domain.dedup import dedup_key, is_duplicate


def test_dedup_key_lowercases_and_strips_punctuation() -> None:
    assert dedup_key("Hello, World!  ") == "hello world"


def test_dedup_key_collapses_whitespace() -> None:
    assert dedup_key("foo   bar\tbaz") == "foo bar baz"


def test_is_duplicate_identical_titles_returns_true() -> None:
    assert is_duplicate("OpenAI releases GPT-5", "OpenAI releases GPT-5") is True


def test_is_duplicate_minor_punctuation_diff_returns_true() -> None:
    assert is_duplicate("OpenAI releases GPT-5!", "OpenAI releases GPT-5.") is True


def test_is_duplicate_word_reorder_returns_true() -> None:
    # token_set_ratio is order-insensitive — same token bag, different order.
    assert is_duplicate(
        "releases new model GPT-5 OpenAI",
        "OpenAI releases GPT-5 new model",
    ) is True


def test_is_duplicate_unrelated_titles_returns_false() -> None:
    assert is_duplicate(
        "Apple announces M5 chip",
        "Russia invades neighboring country",
    ) is False


def test_is_duplicate_threshold_boundary() -> None:
    # This pair scores ~83 on token_set_ratio (empirically verified).
    # It must cross cleanly across the 85 boundary in both directions.
    new_title = "Tesla launches Cybertruck successor"
    existing_title = "Tesla launches new Cybertruck variant"

    # Default threshold (85) — score is below, so NOT a duplicate.
    assert is_duplicate(new_title, existing_title) is False
    # Stricter threshold (90) — still not a duplicate.
    assert is_duplicate(new_title, existing_title, threshold=90) is False
    # Looser threshold (80) — now considered a duplicate.
    assert is_duplicate(new_title, existing_title, threshold=80) is True
