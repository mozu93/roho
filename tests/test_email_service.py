from types import SimpleNamespace

import pytest

from app.services import email_service


class _Response:
    def __init__(self, status_code, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


def _service(from_address=""):
    service = object.__new__(email_service.EmailService)
    service._config = SimpleNamespace(m365_from_address=from_address)
    return service


def test_proxy_sender_is_added_to_graph_message(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        email_service.requests, "post",
        lambda *_args, **kwargs: (captured.update(kwargs) or _Response(202)),
    )

    _service("info@example.com").send(
        "recipient@example.com", "件名", "本文", token="token"
    )

    assert captured["json"]["message"]["from"] == {
        "emailAddress": {"address": "info@example.com"}
    }


def test_proxy_sender_requests_shared_mail_scope():
    assert email_service.SEND_SHARED_SCOPE in _service("info@example.com")._scopes()
    assert email_service.SEND_SHARED_SCOPE not in _service()._scopes()


def test_send_retries_graph_rate_limit(monkeypatch):
    responses = [_Response(429, headers={"Retry-After": "1"}), _Response(202)]
    waits = []
    monkeypatch.setattr(email_service.requests, "post", lambda *_args, **_kwargs: responses.pop(0))
    monkeypatch.setattr(email_service.time, "sleep", waits.append)

    _service().send("recipient@example.com", "件名", "本文", token="token")

    assert waits == [1]


def test_send_rejects_oversized_attachments(tmp_path, monkeypatch):
    attachment = tmp_path / "large.pdf"
    attachment.write_bytes(b"x" * (email_service.MAX_ATTACHMENT_SIZE_BYTES + 1))
    monkeypatch.setattr(
        email_service.requests, "post",
        lambda *_args, **_kwargs: pytest.fail("Graph API must not be called"),
    )

    with pytest.raises(ValueError, match="3MB"):
        _service().send(
            "recipient@example.com", "件名", "本文",
            attachments=[{"path": str(attachment), "name": "large.pdf"}], token="token",
        )
