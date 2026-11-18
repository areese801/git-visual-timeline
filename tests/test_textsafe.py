"""Tests for making repo-controlled text safe to show in a terminal."""

from gvt.textsafe import safe_text


def test_plain_text_unchanged():
    assert safe_text("Fix the parser (#12)\ttabs stay\nnewlines stay") == (
        "Fix the parser (#12)\ttabs stay\nnewlines stay"
    )


def test_escape_sequences_become_visible():
    assert safe_text("a\x1b]0;PWNED\x07b") == "a\\x1b]0;PWNED\\x07b"
    assert safe_text("\x1b[2J") == "\\x1b[2J"


def test_c1_and_del_controls_become_visible():
    assert safe_text("x\x9by\x7fz") == "x\\x9by\\x7fz"


def test_crlf_line_endings_are_normalized():
    assert safe_text("one\r\ntwo\r\n") == "one\ntwo\n"
    assert safe_text("trailing\r") == "trailing"


def test_lone_carriage_return_is_visible():
    assert safe_text("overwrite\rme") == "overwrite\\x0dme"


def test_bidi_controls_become_visible():
    # "Trojan Source": bidi overrides reorder what the terminal displays
    assert safe_text("access‮level") == "access\\u202elevel"
    assert safe_text("⁦x⁩") == "\\u2066x\\u2069"


def test_unicode_text_unchanged():
    assert safe_text("café — naïve 日本") == "café — naïve 日本"
