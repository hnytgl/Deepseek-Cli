from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from typing import Any


DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"

# Known providers and their default base URLs
PROVIDERS = {
    "deepseek": "https://api.deepseek.com",
    "ollama": "http://localhost:11434/v1",
    "lmstudio": "http://localhost:1234/v1",
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "anthropic": "https://api.anthropic.com/v1",
}

# Providers that don't require an API key
LOCAL_PROVIDERS = {"ollama", "lmstudio"}


class DeepSeekAPIError(RuntimeError):
    """Raised when the DeepSeek API returns an error or malformed response."""


@dataclass(frozen=True)
class DeepSeekClient:
    api_key: str = field(repr=False)
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = 120
    max_retries: int = 3
    retry_base_delay: float = 1.0

    @classmethod
    def from_env(
        cls,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 120,
        max_retries: int = 3,
        provider: str | None = None,
    ) -> "DeepSeekClient":
        # Resolve provider → base_url mapping
        resolved_provider = provider or os.getenv("DEEPSEEK_PROVIDER", "deepseek")
        if base_url is None:
            base_url = os.getenv("DEEPSEEK_BASE_URL") or PROVIDERS.get(resolved_provider, "")
        if not base_url:
            base_url = os.getenv("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL

        # Local providers (ollama, lmstudio) don't require an API key
        resolved_key = api_key or os.getenv("DEEPSEEK_API_KEY") or ""
        if not resolved_key and resolved_provider not in LOCAL_PROVIDERS:
            # Check if base_url points to a known local provider
            is_local = any(base_url.rstrip("/").startswith(url.rstrip("/")) for url in
                          (PROVIDERS["ollama"], PROVIDERS["lmstudio"]))
            if not is_local:
                raise DeepSeekAPIError(
                    "DEEPSEEK_API_KEY is not set. Export it or pass --api-key.\n"
                    "For local models (Ollama/LMStudio), use --provider ollama or set base_url."
                )
        if not resolved_key:
            resolved_key = "not-needed"  # placeholder for local providers

        return cls(
            api_key=resolved_key,
            base_url=base_url.rstrip("/"),
            model=model or os.getenv("DEEPSEEK_MODEL") or DEFAULT_MODEL,
            timeout=timeout,
            max_retries=max_retries,
        )

    def _retry_delay(self, attempt: int, exc: urllib.error.HTTPError | None = None) -> float:
        if exc is not None:
            retry_after = exc.headers.get("Retry-After")
            if retry_after:
                try:
                    return max(0.0, float(retry_after))
                except ValueError:
                    try:
                        target = parsedate_to_datetime(retry_after).timestamp()
                        return max(0.0, target - time.time())
                    except (TypeError, ValueError, OverflowError):
                        pass
        return self.retry_base_delay * (2**attempt)

    def _retryable(self, exc: urllib.error.HTTPError | urllib.error.URLError) -> bool:
        return isinstance(exc, urllib.error.URLError) or exc.code == 429 or 500 <= exc.code <= 599

    def _open(self, request: urllib.request.Request):
        for attempt in range(self.max_retries + 1):
            try:
                return urllib.request.urlopen(request, timeout=self.timeout)
            except (urllib.error.HTTPError, urllib.error.URLError) as exc:
                if attempt >= self.max_retries or not self._retryable(exc):
                    raise
                time.sleep(self._retry_delay(attempt, exc if isinstance(exc, urllib.error.HTTPError) else None))
        raise AssertionError("unreachable")

    def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = {
            "model": self.model,
            **payload,
        }
        body = json.dumps(request_payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        try:
            with self._open(request) as response:
                data = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DeepSeekAPIError(f"DeepSeek API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise DeepSeekAPIError(f"DeepSeek API request failed: {exc.reason}") from exc

        try:
            return json.loads(data)
        except json.JSONDecodeError as exc:
            raise DeepSeekAPIError("DeepSeek API returned invalid JSON.") from exc

    def chat_stream(self, payload: dict[str, Any]):
        request_payload = {
            "model": self.model,
            "stream": True,
            **payload,
            "stream_options": {"include_usage": True, **payload.get("stream_options", {})},
        }
        body = json.dumps(request_payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
        )

        try:
            with self._open(request) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    try:
                        yield json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise DeepSeekAPIError("DeepSeek API stream returned invalid JSON.") from exc
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise DeepSeekAPIError(f"DeepSeek API HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise DeepSeekAPIError(f"DeepSeek API request failed: {exc.reason}") from exc
