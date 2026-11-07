"""The hybrid policy (stage 4). The local rules answer first, at once. Then, in the background, Jev
re-ranks the same candidates; when it disagrees with the rules, the advisor model picks between the
two and says why, in Russian. No model can add a candidate the rules did not produce, every pick goes
through the rules' validator, and a failing or slow provider only means the rules answer alone.

Limits per match (20 Jev, 5 advisor calls by default) and the provider_calls journal keep the spend
visible. Demo matches and replays call nobody unless he turns that on.
"""

from __future__ import annotations

import hashlib
import json
import queue
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import httpx

from d2bg import apikeys
from d2bg.context import AppContext
from d2bg.copilot import baseline
from d2bg.copilot.models import GameContext, Recommendation
from d2bg.copilot.providers import AdvisorClient, Call, ChoiceAnswer, JevClient, ProviderError
from d2bg.copilot.store import CopilotStore

if TYPE_CHECKING:
    from d2bg.copilot.pipeline import Copilot

SUPPORTED = ("ITEM_NEXT", "ITEM_SITUATIONAL", "TALENT")
HINT_GROUP = {"ITEM_NEXT": "items", "ITEM_SITUATIONAL": "items", "TALENT": "skills"}
# A disagreement weaker than this is noted but not worth the advisor's time (live: Jev at 28-30% on
# starting items was a coin toss).
CONFLICT_CONFIDENCE = 0.5
# After these errors a provider rests: for the session (a bad key, no money) or a minute.
REST_S = {"auth": float("inf"), "payment": float("inf"), "rate": 60.0, "server": 60.0, "timeout": 60.0}
ADVISOR_SYSTEM = (
    "Ты тренер по Dota 2. Игрок выбирает между вариантами из options. Выбери один id из options и "
    "по-русски, одним-двумя короткими предложениями (до 250 символов), объясни, почему он лучше в этой ситуации. "
    "Опирайся только на факты из запроса, не придумывай предметы, героев и события. "
    'Ответ — только JSON: {"choice": "<id из options>", "reason_ru": "<объяснение>"}.'
)


@dataclass
class Job:
    key: str  # the Copilot's "TYPE:category" slot of the advice
    rec: Recommendation
    context: GameContext
    source: str  # game, demo or replay


def facts(c: GameContext, app: AppContext, mode: str | None) -> dict[str, Any]:
    """What a model is told about the game: no ids, no names of people, nothing the player cannot see."""
    hero, item = app.data.heroes.name, app.data.items.name
    t = int(c.time_s or 0)
    return {
        "game": "Dota 2",
        "mode": {"turbo": "Turbo", "normal": "normal (All Pick)"}.get(mode or "", "unknown"),
        "game_time": f"{'-' if t < 0 else ''}{abs(t) // 60}:{abs(t) % 60:02d}",
        "hero": hero(c.hero_id) if c.hero_id else None,
        "level": c.level,
        "position": c.position,
        "gold": c.gold,
        "items": [item(k) for k in c.owned],
        "allies": [hero(h) for h in c.allies if h != c.hero_id],
        "enemies_seen": [hero(h) for h in c.enemies_visible],
    }


def options(rec: Recommendation, c: GameContext, app: AppContext) -> dict[str, str]:
    """The rules' candidate and alternatives that are still legal, id -> what the model reads."""
    ids = list(dict.fromkeys([rec.candidate_id, *rec.alternatives]))
    if rec.type == "TALENT":
        hero = app.data.heroes.get(c.hero_id) if c.hero_id else None
        names = {t.key: t.name for t in hero.talents} if hero else {}
        return {k: names[k] for k in ids if k in names}
    items = app.data.items
    return {
        k: f"{items.name(k)} ({items.cost(k)} gold)"
        for k in ids
        if items.get(k) is not None and k not in c.owned
    }


class Hybrid:
    def __init__(
        self,
        app: AppContext,
        store: CopilotStore,
        mode_of: Callable[[], str | None] = lambda: None,
        clock: Callable[[], float] = time.time,
        http: httpx.Client | None = None,
    ) -> None:
        self.app, self.store, self.mode_of, self._clock = app, store, mode_of, clock
        self.http = http or httpx.Client()
        self.copilot: Copilot | None = None
        self._queue: queue.Queue[Job] = queue.Queue()
        self._cache: OrderedDict[str, ChoiceAnswer] = OrderedDict()
        # provider -> {"ok": last call worked, "error": last error kind, "rest_until": time}
        self.health: dict[str, dict[str, Any]] = {
            p: {"ok": None, "error": None, "rest_until": 0.0} for p in ("jev", "advisor")
        }
        self.last_error: str | None = None

    # ── plumbing ───────────────────────────────────────────────────

    def submit(self, job: Job) -> None:
        if job.rec.type in SUPPORTED:
            self._queue.put(job)

    def drain(self) -> None:
        """Process queued jobs on this thread (tests, and the worker loop)."""
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                return
            self._safe(job)

    def start(self) -> None:  # pragma: no cover - a daemon thread around drain()
        def loop() -> None:
            while True:
                self._safe(self._queue.get())

        threading.Thread(target=loop, name="copilot-hybrid", daemon=True).start()

    def _safe(self, job: Job) -> None:
        try:
            self.process(job)
        except Exception as exc:  # a model must never break the Copilot
            self.last_error = f"{type(exc).__name__}: {exc}"

    def _jev(self) -> JevClient | None:
        k = apikeys.key(apikeys.JEV_KEY)
        return JevClient(k, self.app.settings.get().providers.jev_model, http=self.http) if k else None

    def _advisor(self) -> AdvisorClient | None:
        k = apikeys.key(apikeys.ADVISOR_KEY)
        p = self.app.settings.get().providers
        return (
            AdvisorClient(
                k, p.advisor_base_url, p.advisor_model, http=self.http, reasoning=p.advisor_reasoning
            )
            if k
            else None
        )

    def _ready(self, provider: str, match_id: str, limit: int) -> bool:
        if self.health[provider]["rest_until"] > self._clock():
            return False
        used = self.store.provider_usage(match_id).get(provider, {}).get("calls", 0)
        return bool(used < limit)

    def _record(
        self, match_id: str | None, call: Call, purpose: str, error: ProviderError | None = None
    ) -> None:
        h = self.health["jev" if call.provider == "jev" else "advisor"]
        if error is None:
            h.update(ok=True, error=None, rest_until=0.0)
        else:
            call.status, call.error = error.kind, str(error)[:200]
            h.update(ok=False, error=error.kind, rest_until=self._clock() + REST_S.get(error.kind, 0.0))
        self.store.add_provider_call(match_id, self._clock(), call.as_row(purpose))

    # ── the policy ─────────────────────────────────────────────────

    def process(self, job: Job) -> None:
        prefs = self.app.settings.get().providers
        copilot = self.copilot
        jev = self._jev()
        if copilot is None or jev is None or prefs.mode == "baseline":
            return
        if job.source != "game" and not prefs.in_demo:
            return
        if HINT_GROUP.get(job.rec.type) in self.app.settings.get().hidden_hints:
            return  # he switched this kind of hint off: no money spent on it
        rec, match = job.rec, job.rec.match_id
        if not copilot.is_current(job.key, rec.id):
            return  # the game moved on before the queue reached this advice
        opts = options(rec, copilot.context, self.app)
        if len(opts) < 2 or rec.candidate_id not in opts:
            return
        state = facts(copilot.context, self.app, self.mode_of())
        hero = state["hero"] or "hero"
        question = (
            f"Which talent should {hero} take now"
            if rec.type == "TALENT"
            else f"Which item should the player's hero ({hero}) buy next in this situation"
        )
        cache_key = hashlib.sha256(json.dumps([rec.type, opts, state], sort_keys=True).encode()).hexdigest()
        answer = self._cache.get(cache_key)
        if answer is None:
            if not self._ready("jev", match, prefs.jev_per_match):
                return
            try:
                answer, call = jev.choice(state, question, opts)
            except ProviderError as exc:
                self._record(match, exc.call or Call("jev", jev.model), "rerank", exc)
                return
            self._record(match, call, "rerank")
            self._cache[cache_key] = answer
            while len(self._cache) > 256:
                self._cache.popitem(last=False)
        pick = answer.choice
        conf = f"{answer.confidence:.0%}" if answer.confidence is not None else "?"
        opinion = rec.model_copy(
            update={
                "id": hashlib.sha256(f"{rec.id}|jev|{pick}".encode()).hexdigest()[:20],
                "candidate_id": pick,
                "alternatives": [k for k in opts if k != pick],
                "source": "jev",
                "confidence": answer.confidence,
                "confidence_kind": "unverified_model_score",
                "model_version": jev.model,
                "reason_ru": (
                    f"Jev согласен с правилами (уверенность {conf})."
                    if pick == rec.candidate_id
                    else f"Jev выбирает {opts[pick].split(' (')[0]} вместо {opts[rec.candidate_id].split(' (')[0]} "
                    f"(уверенность {conf})."
                ),
            }
        )
        why = baseline.rejection(opinion, copilot.context, self.app)
        if why is not None:
            copilot.rejected.append({"type": rec.type, "candidate": pick, "reason": f"Jev: {why}"})
            return
        if not copilot.adopt(job.key, rec.id, opinion):
            return
        advisor = self._advisor()
        weak = answer.confidence is None or answer.confidence < CONFLICT_CONFIDENCE
        if pick == rec.candidate_id or weak or prefs.mode != "hybrid" or advisor is None:
            return
        if not self._ready("advisor", match, prefs.advisor_per_match):
            return
        pair = {k: opts[k] for k in (rec.candidate_id, pick)}
        try:
            verdict, call = advisor.advise(
                ADVISOR_SYSTEM,
                {
                    **state,
                    "rules_pick": rec.candidate_id,
                    "jev_pick": pick,
                    "jev_confidence": answer.confidence,
                },
                pair,
            )
        except ProviderError as exc:
            self._record(match, exc.call or Call("advisor", advisor.model), "explain", exc)
            return
        self._record(match, call, "explain")
        final = opinion.model_copy(update={"candidate_id": verdict.choice, "reason_ru": verdict.reason_ru})
        if baseline.rejection(final, copilot.context, self.app) is None:
            copilot.revise(job.key, opinion.id, verdict.choice, verdict.reason_ru)

    # ── status and the test button ─────────────────────────────────

    def status(self, match_id: str | None) -> dict[str, Any]:
        prefs = self.app.settings.get().providers
        usage = self.store.provider_usage(match_id) if match_id else {}
        total = self.store.provider_usage()

        def one(provider: str, key: str, model: str, limit: int) -> dict[str, Any]:
            h = self.health[provider]
            return {
                "configured": apikeys.configured(key),
                "model": model,
                "online": h["ok"],
                "error": h["error"],
                "calls_this_match": usage.get(provider, {}).get("calls", 0),
                "limit_per_match": limit,
                "cost_usd_total": round(total.get(provider, {}).get("cost_usd", 0.0), 6),
            }

        return {
            "mode": prefs.mode,
            "baseline": {"configured": True, "online": True},
            "jev": one("jev", apikeys.JEV_KEY, prefs.jev_model, prefs.jev_per_match),
            "advisor": one("advisor", apikeys.ADVISOR_KEY, prefs.advisor_model, prefs.advisor_per_match),
        }

    def test(self) -> dict[str, Any]:
        """One tiny real call to each configured provider, only when he presses the button."""
        out: dict[str, Any] = {}
        for h in self.health.values():  # he may have fixed a key or topped up: try again
            h["rest_until"] = 0.0
        jev, advisor = self._jev(), self._advisor()
        tests: list[tuple[str, Callable[[], tuple[Any, Call]]]] = []
        if jev:
            tests.append(
                (
                    "jev",
                    lambda: jev.choice(
                        {"test": "connection check"}, "Is this a test", {"yes": "Yes", "no": "No"}
                    ),
                )
            )
        if advisor:
            tests.append(
                ("advisor", lambda: advisor.advise("Ответь JSON.", {"test": True}, {"ok": "Связь есть"}))
            )
        for name, run in tests:
            try:
                _, call = run()
            except ProviderError as exc:
                self._record(None, exc.call or Call(name, ""), "test", exc)
                out[name] = {"ok": False, "error": exc.kind, "message": str(exc)}
                continue
            self._record(None, call, "test")
            out[name] = {"ok": True, "latency_ms": call.latency_ms, "model": call.model}
        for name, key in (("jev", apikeys.JEV_KEY), ("advisor", apikeys.ADVISOR_KEY)):
            out.setdefault(
                name, {"ok": False, "error": "not_configured", "message": f"Нет ключа {key} в .env"}
            )
        return out
