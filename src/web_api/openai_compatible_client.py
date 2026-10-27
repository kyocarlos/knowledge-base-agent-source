"""OpenAI-compatible chat client for gateways such as Sub2API."""

from __future__ import annotations

import json
import logging
import os
from types import SimpleNamespace
from typing import Any, Callable

import requests

logger = logging.getLogger(__name__)


class _Completions:
    def __init__(self, client: "OpenAICompatibleClient") -> None:
        self._client = client

    def create(self, *, model: str | None = None, messages: list[dict[str, Any]],
               temperature: float = 0.3, on_delta: Callable[[str], None] | None = None, **kwargs: Any) -> Any:
        if on_delta is not None:
            return self._client._complete_streaming(model=model or self._client.model, messages=messages, temperature=temperature, on_delta=on_delta, **kwargs)
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
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=message.get("tool_calls") or []),
                finish_reason=data["choices"][0].get("finish_reason"),
            )],
            usage=data.get("usage"),
        )

    def _complete_streaming(self, *, model: str, messages: list[dict[str, Any]], temperature: float = 0.3,
                            on_delta: Callable[[str], None], **kwargs: Any) -> Any:
        """Same result object as ``_complete`` (the whole message), but ``on_delta`` gets each piece of text as it arrives.

        A stream that fails before the first chunk falls back to one ordinary request; a failure after text was delivered is raised,
        because the caller has already shown part of the answer.
        """
        payload: dict[str, Any] = {"model": model, "messages": messages, "temperature": temperature,
                                   "max_tokens": kwargs.pop("max_tokens", self.max_tokens), "stream": True}
        payload.update(kwargs)
        content: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        finish, response_id, delivered = None, None, False
        try:
            with requests.post(f"{self.base_url}/chat/completions", headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                               json=payload, timeout=self.timeout, stream=True) as response:
                response.raise_for_status()
                for raw in response.iter_lines():
                    line = raw.decode("utf-8", "replace").strip() if isinstance(raw, bytes) else str(raw).strip()
                    if not line.startswith("data:"):
                        continue
                    body = line[5:].strip()
                    if body == "[DONE]":
                        break
                    chunk = json.loads(body)
                    response_id = response_id or chunk.get("id")
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("content"):
                            content.append(delta["content"])
                            delivered = True
                            on_delta(delta["content"])
                        for part in delta.get("tool_calls") or []:
                            slot = calls.setdefault(int(part.get("index", 0)), {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                            slot["id"] = part.get("id") or slot["id"]
                            fn = part.get("function") or {}
                            slot["function"]["name"] += fn.get("name") or ""
                            slot["function"]["arguments"] += fn.get("arguments") or ""
                        finish = choice.get("finish_reason") or finish
        except (requests.RequestException, ValueError) as exc:
            if delivered:
                logger.error("OpenAI-compatible stream broke after text was delivered: %s", type(exc).__name__)
                raise RuntimeError("OpenAI-compatible LLM stream was interrupted") from exc
            logger.warning("OpenAI-compatible stream failed before any text (%s); retrying without streaming", type(exc).__name__)
            return self._complete(model=model, messages=messages, temperature=temperature, **{k: v for k, v in payload.items() if k not in ("model", "messages", "temperature", "stream")})
        return SimpleNamespace(id=response_id, model=model, choices=[SimpleNamespace(
            message=SimpleNamespace(content="".join(content), tool_calls=[calls[i] for i in sorted(calls)]), finish_reason=finish)], usage=None)

    def generate(self, prompt: str, temperature: float = 0.3) -> str:
        return self.chat([{"role": "user", "content": prompt}], temperature=temperature)
