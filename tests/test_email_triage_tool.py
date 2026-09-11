import contextlib
from unittest.mock import MagicMock, patch


def _msg(from_, subject, text):
    m = MagicMock()
    m.from_ = from_
    m.subject = subject
    m.text = text
    m.html = ""
    m.date_str = "Fri, 03 Jul 2026"
    return m


def _fake_imap(msgs):
    @contextlib.contextmanager
    def _cm(acc):
        mb = MagicMock()
        mb.fetch.return_value = iter(msgs)
        yield mb
    return _cm


TRIAGE_OUT = [
    {"urgency": "low", "category": "newsletter", "spam": False,
     "summary": "Weekly digest.", "draft": ""},
    {"urgency": "high", "category": "work", "spam": False,
     "summary": "Contract needs sign-off today.", "draft": "Hi Jane, signing now."},
]


def test_triage_inbox_ranks_and_drafts():
    import modules.email_tools as et
    msgs = [
        _msg("News <news@list.com>", "Digest", "links"),
        _msg("Jane <jane@co.com>", "Contract sign-off", "Need SOW signed today."),
    ]
    acc = {"name": "work", "provider": "generic"}
    with patch.object(et, "_resolve", return_value=acc), \
         patch("agents.email_client.imap_connection", _fake_imap(msgs)), \
         patch("agents.email_triage.triage_messages", return_value=TRIAGE_OUT):
        out = et.triage_inbox()
    # high email ranked before low
    assert out.index("Contract sign-off") < out.index("Digest")
    assert "[HIGH]" in out and "[LOW]" in out
    assert "work" in out
    assert "Draft:" in out                       # draft rendered for the high email
    assert "Hi Jane, signing now." in out


def test_triage_inbox_no_account():
    import modules.email_tools as et
    with patch.object(et, "_resolve", return_value=None):
        out = et.triage_inbox()
    assert out == et._NO_ACCOUNTS


def test_triage_inbox_empty():
    import modules.email_tools as et
    acc = {"name": "work", "provider": "generic"}
    with patch.object(et, "_resolve", return_value=acc), \
         patch("agents.email_client.imap_connection", _fake_imap([])):
        out = et.triage_inbox()
    assert "empty" in out.lower()


def test_triage_inbox_auth_error():
    import modules.email_tools as et
    acc = {"name": "work", "provider": "generic"}

    @contextlib.contextmanager
    def _boom(acc):
        raise RuntimeError("not authorized")
        yield  # pragma: no cover

    with patch.object(et, "_resolve", return_value=acc), \
         patch("agents.email_client.imap_connection", _boom):
        out = et.triage_inbox()
    assert "authentication failed" in out.lower()


def test_triage_inbox_connection_error():
    import modules.email_tools as et
    acc = {"name": "work", "provider": "generic"}

    @contextlib.contextmanager
    def _boom(acc):
        raise ValueError("network down")
        yield  # pragma: no cover

    with patch.object(et, "_resolve", return_value=acc), \
         patch("agents.email_client.imap_connection", _boom):
        out = et.triage_inbox()
    assert "could not connect" in out.lower()


def test_triage_inbox_registered(reset_registry):
    import sys
    from core.registry import set_loading_module, list_tools

    # Remove module from cache if present, so we can import it fresh
    if "modules.email_tools" in sys.modules:
        del sys.modules["modules.email_tools"]

    set_loading_module("email_tools")
    try:
        import modules.email_tools  # noqa: F401
    finally:
        set_loading_module("")

    assert "triage_inbox" in list_tools()
