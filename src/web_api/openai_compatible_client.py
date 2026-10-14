"""OpenAI-compatible chat client for gateways such as Sub2API."""

from __future__ import annotations

import logging
import os
from types import SimpleNamespace
from typing import Any

import requests

logger = logging.getLogger(__name__)


class _Completions:
    def __init__(self, client: "OpenAICompatibleClient") -> None:
        self._client = client

    def create(self, *, model: str | None = None, messages: list[dict[str, Any]],
               temperature: float = 0.3, **kwargs: Any) -> Any:
        return self._client._complete(
            model=model or self._client.model,
            messages=messages,
            temperature=temperature,
            **kwargs,
        )


class _ChatFacade:
    """Support both the KM ``chat(messages)`` and SDK-style calls."""

    def __init__(self, client: "OpenAICompatibleClient") -> None:
        self._client = client
        self.completions = _Completions(client)

    def __call__(self, messages: list[dict[str, Any]], temperature: float = 0.3) -> str:
        response = self.completions.create(messages=messages, temperature=temperature)
        return response.choices[0].message.content or ""


class OpenAICompatibleClient:
    """Non-streaming client for OpenAI-compatible ``/chat/completions`` APIs."""

    def __init__(
        self,
        model: str,
        base_url: str,
        timeout: float = 300,
        max_tokens: int = 4096,
        api_key_env: str = "SUB2API_API_KEY",
    ) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.max_tokens = int(max_tokens)
        self.api_key = os.getenv(api_key_env, "")
        if not self.api_key:
            raise RuntimeError(f"Missing OpenAI-compatible API credential: {api_key_env}")
        self.chat = _ChatFacade(self)

    def _complete(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> Any:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": kwargs.pop("max_tokens", self.max_tokens),
        }
        payload.update(kwargs)
        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            logger.error(
                "OpenAI-compatible request failed: endpoint=%s status=%s error=%s",
                f"{self.base_url}/chat/completions",
                getattr(getattr(exc, "response", None), "status_code", None),
                type(exc).__name__,
            )
            raise RuntimeError("OpenAI-compatible LLM request failed") from exc
        except (TypeError, ValueError) as exc:
            logger.error("OpenAI-compatible response was invalid: %s", type(exc).__name__)
            raise RuntimeError("OpenAI-compatible LLM response was invalid") from exc

        try:
            message = data["choices"][0]["message"]
            content = message.get("content", "")
        except (KeyError, IndexError, TypeError) as exc:
            logger.error("OpenAI-compatible response schema was invalid")
            raise RuntimeError("OpenAI-compatible LLM response schema was invalid") from exc

        return SimpleNamespace(
            id=data.get("id"),
            model=data.get("model", model),
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
            usage=data.get("usage"),
        )

    def generate(self, prompt: str, temperature: float = 0.3) -> str:
        return self.chat([{"role": "user", "content": prompt}], temperature=temperature)
