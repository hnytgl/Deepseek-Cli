from __future__ import annotations

import io
import urllib.error
from email.message import Message

import pytest

from deepseek_cli.api import DeepSeekAPIError, DeepSeekClient


class FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self.body


def http_error(code: int, *, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        "https://api.deepseek.com/chat/completions",
        code,
        "error",
        headers,
        io.BytesIO(b'{"error":"temporary"}'),
    )


def test_chat_retries_retryable_http_error(monkeypatch) -> None:
    attempts = [http_error(429, retry_after="0"), FakeResponse(b'{"choices":[]}')]
    sleeps: list[float] = []

    def open_next(*_args, **_kwargs):
        result = attempts.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr("deepseek_cli.api.urllib.request.urlopen", open_next)
    monkeypatch.setattr("deepseek_cli.api.time.sleep", sleeps.append)
    client = DeepSeekClient("key", max_retries=1)

    assert client.chat({"messages": []}) == {"choices": []}
    assert sleeps == [0.0]


def test_chat_does_not_retry_non_retryable_http_error(monkeypatch) -> None:
    monkeypatch.setattr(
        "deepseek_cli.api.urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(http_error(400)),
    )
    client = DeepSeekClient("key", max_retries=3, retry_base_delay=0)

    with pytest.raises(DeepSeekAPIError, match="HTTP 400"):
        client.chat({"messages": []})


def test_chat_retries_network_error_then_reports_failure(monkeypatch) -> None:
    attempts = 0

    def fail(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        raise urllib.error.URLError("offline")

    monkeypatch.setattr("deepseek_cli.api.urllib.request.urlopen", fail)
    monkeypatch.setattr("deepseek_cli.api.time.sleep", lambda _delay: None)
    client = DeepSeekClient("key", max_retries=2, retry_base_delay=0)

    with pytest.raises(DeepSeekAPIError, match="offline"):
        client.chat({"messages": []})
    assert attempts == 3
