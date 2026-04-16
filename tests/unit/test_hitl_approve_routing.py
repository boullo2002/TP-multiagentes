from __future__ import annotations

from graph.edges import is_approve_reply


def test_is_approve_reply_variants() -> None:
    assert is_approve_reply("APPROVE") is True
    assert is_approve_reply("approve") is True
    assert is_approve_reply("**APPROVE**") is True
    assert is_approve_reply("no") is False
