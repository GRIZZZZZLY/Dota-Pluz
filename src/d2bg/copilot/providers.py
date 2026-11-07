"""Clients for the optional cloud models: Jev (TypeSafe's System One API) picks among candidates, and an
OpenAI-compatible chat model (DeepSeek through ForgetAPI by default) explains a disagreement in Russian.

Both only ever see compact game facts and the candidate ids the local rules produced. Every failure
becomes a ProviderError with a kind the caller can act on (auth, payment, rate, server, timeout,
bad_response); its message never carries a key.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, Field, ValidationError

M = TypeVar("M", bound=BaseModel)

JEV_URL = "https://api.typesafe.ai/v1/systemone"
# USD per million tokens (input, output), as published on 2026-11-07. Edit here when prices change.
PRICES = {
    "jev": (0.042, 0.0),
    "deepseek-v4-flash": (0.078, 0.156),
    "deepseek-v4-pro": (0.53, 1.1),
}


class ProviderError(Exception):
    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.call: Call | None = None  # what the failed request cost, for the journal


@dataclass
class Call:
    """One request, as the journal keeps it."""

    provider: str
    model: str
    status: str = "ok"
    latency_ms: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    error: str | None = None

    @property
    def cost_usd(self) -> float:
        price_in, price_out = PRICES.get("jev" if self.provider == "jev" else self.model, (0.0, 0.0))
        return round((self.input_tokens * price_in + self.output_tokens * price_out) / 1e6, 8)

    def as_row(self, purpose: str) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "purpose": purpose,
            "model": self.model,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cost_usd": self.cost_usd,
            "error": self.error,
        }


@dataclass
class ChoiceAnswer:
    choice: str
    confidence: float | None
    probabilities: dict[str, float] = field(default_factory=dict)


class AdvisorAnswer(BaseModel):
    choice: str
    reason_ru: str = Field(min_length=3, max_length=800)


def _error_for(response: httpx.Response, secret: str) -> ProviderError:
    status = response.status_code
    kind = (
        "auth"
        if status in (401, 403)
        else "payment"
        if status == 402
        else "rate"
        if status == 429
        else "server"
        if status >= 500
        else "bad_request"
    )
    text = response.text[:200].replace(secret, "***") if secret else response.text[:200]
    return ProviderError(kind, f"HTTP {status}: {text}")


def _post(
    http: httpx.Client, url: str, secret: str, body: dict[str, Any], timeout: float, call: Call
) -> dict[str, Any]:
    start = time.perf_counter()
    try:
        response = http.post(url, headers={"Authorization": f"Bearer {secret}"}, json=body, timeout=timeout)
    except httpx.TimeoutException as exc:
        raise ProviderError("timeout", f"нет ответа за {timeout:g} с") from exc
    except httpx.HTTPError as exc:
        raise ProviderError("server", type(exc).__name__) from exc
    finally:
        call.latency_ms = round((time.perf_counter() - start) * 1000)
    if response.status_code != 200:
        raise _error_for(response, secret)
    try:
        doc: dict[str, Any] = response.json()
    except ValueError as exc:
        raise ProviderError("bad_response", "ответ не JSON") from exc
    return doc


class JevClient:
    def __init__(
        self, key: str, model: str = "jev-latest", timeout: float = 8.0, http: httpx.Client | None = None
    ):
        self.key, self.model, self.timeout = key, model, timeout
        self.http = http or httpx.Client()

    def choice(
        self, state: dict[str, Any], instructions: str, options: dict[str, str]
    ) -> tuple[ChoiceAnswer, Call]:
        """Jev picks one of ``options`` (id -> description) for ``state``. The pick is checked to be
        one of the ids; anything else is a bad response."""
        call = Call("jev", self.model)
        body = {
            "model": self.model,
            "state": state,
            "questions": {"pick": {"type": "choice", "instructions": instructions, "criteria": options}},
        }
        try:
            doc = _post(self.http, JEV_URL, self.key, body, self.timeout, call)
        except ProviderError as exc:
            exc.call = call
            raise
        usage = doc.get("usage") or {}
        call.model = str(doc.get("model") or self.model)
        call.input_tokens, call.output_tokens = (
            int(usage.get("input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
        )
        answer = (doc.get("answers") or {}).get("pick") or {}
        if answer.get("choice") not in options:
            error = ProviderError(
                "bad_response", f"Jev выбрал вариант не из списка: {answer.get('choice')!r}"
            )
            error.call = call
            raise error
        return (
            ChoiceAnswer(
                choice=answer["choice"],
                confidence=answer.get("confidence"),
                probabilities={k: float(v) for k, v in (answer.get("probabilities") or {}).items()},
            ),
            call,
        )


class AdvisorClient:
    """An OpenAI-compatible chat model asked for a JSON answer: which candidate, and why, in Russian."""

    def __init__(
        self,
        key: str,
        base_url: str,
        model: str,
        timeout: float = 40.0,
        http: httpx.Client | None = None,
        reasoning: bool = False,
    ):
        self.key, self.url, self.model, self.timeout = (
            key,
            base_url.rstrip("/") + "/chat/completions",
            model,
            timeout,
        )
        self.http = http or httpx.Client()
        # DeepSeek V4 on ForgetAPI thinks at length by default (24,000 characters before a 2,600-character
        # answer, measured) and runs out of tokens; switched off unless asked for.
        self.extra: dict[str, Any] = {} if reasoning else {"reasoning": {"enabled": False}}

    def advise(
        self, system: str, facts: dict[str, Any], options: dict[str, str]
    ) -> tuple[AdvisorAnswer, Call]:
        def check(answer: AdvisorAnswer) -> str | None:
            return None if answer.choice in options else f"choice должен быть одним из {list(options)}"

        return self.ask_json(system, {**facts, "options": options}, AdvisorAnswer, check)

    def ask_json(
        self,
        system: str,
        payload: dict[str, Any],
        schema: type[M],
        check: Callable[[M], str | None] = lambda _: None,
        max_tokens: int = 1200,
    ) -> tuple[M, Call]:
        """Ask for a JSON answer matching ``schema`` and passing ``check``; one controlled retry that
        tells the model what was wrong. Anything else is a bad_response."""
        call = Call("advisor", self.model)
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        problem = ""
        for _ in range(2):
            if problem:
                messages.append(
                    {"role": "user", "content": f"Ответ не подошёл: {problem}. Ответь только JSON."}
                )
            body = {
                "model": self.model,
                "messages": messages,
                "response_format": {"type": "json_object"},
                "max_tokens": max_tokens,
                **self.extra,
            }
            try:
                doc = _post(self.http, self.url, self.key, body, self.timeout, call)
            except ProviderError as exc:
                exc.call = call
                raise
            usage = doc.get("usage") or {}
            call.input_tokens += int(usage.get("prompt_tokens", 0))
            call.output_tokens += int(usage.get("completion_tokens", 0))
            content = ((doc.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            try:
                answer = schema.model_validate_json(content)
            except ValidationError as exc:
                problem = f"JSON не по схеме: {exc.errors()[0].get('loc')} {exc.errors()[0].get('msg')}"
                messages.append({"role": "assistant", "content": content[:500]})
                continue
            why = check(answer)
            if why:
                problem = why
                messages.append({"role": "assistant", "content": content[:500]})
                continue
            return answer, call
        error = ProviderError("bad_response", problem or "пустой ответ")
        error.call = call
        raise error
