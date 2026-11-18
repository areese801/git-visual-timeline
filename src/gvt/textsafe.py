"""
Make repository-controlled text safe to print in a terminal.

Commit messages, author names and file contents come from whoever made the
repo. Raw control characters in them would reach the terminal as escape
sequences, and bidi controls can reorder what is displayed, so anything shown
from a repo passes through safe_text() first.
"""

from __future__ import annotations

import re

# C0 controls except tab and newline, DEL, C1 controls, and bidi
# embedding/override/isolate characters
_UNSAFE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f‪-‮⁦-⁩]")


def _visible(match: re.Match[str]) -> str:
    code = ord(match.group())
    return f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}"


def safe_text(text: str) -> str:
    """
    Replace control and bidi characters with visible escapes like "\\x1b".

    Tabs and newlines are kept, and CRLF line endings become plain newlines.
    """
    text = text.replace("\r\n", "\n")
    if text.endswith("\r"):
        text = text[:-1]
    return _UNSAFE.sub(_visible, text)
