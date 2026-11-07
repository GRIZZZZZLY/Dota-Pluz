"""The post-match analyst (stage 5, AI part): DeepSeek reads the deterministic report and writes a short
human summary, strengths, findings and up to three practice goals.

It gets selected facts only (the findings, the advice journal, deaths and big items), never the raw
recording. Its answer is validated against a schema; a finding that cites an evidence id the report does
not have is dropped and counted, never shown.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from d2bg.copilot.coach import mmss
from d2bg.copilot.providers import AdvisorClient, Call

ANALYST_VERSION = "analyst-1"
SYSTEM = (
    "Ты тренер по Dota 2 и разбираешь одну игру игрока по фактам из запроса. Пиши по-русски, коротко и "
    "по делу, обращайся на «вы». Опирайся только на факты из запроса: не придумывай события, героев, "
    "предметы и цифры. Каждая находка ссылается на evidence_ids только из списка allowed_evidence_ids. "
    "Не утверждай, что что-то решило исход игры: одна корреляция — не причина. Если данных мало, скажи это "
    "в unknowns. certainty: verified — факт из данных, likely — вероятная интерпретация, insufficient_data — "
    "данных не хватает. Ответ — только JSON вида "
    '{"summary": "...", "strengths": ["..."], "findings": [{"text": "...", "evidence_ids": ["..."], '
    '"certainty": "likely"}], "practice_goals": ["..."], "unknowns": ["..."]}. '
    "practice_goals — от одной до трёх конкретных и измеримых целей на следующие игры: это навыки игры "
    "(смерти, золото, тайминги, добивания), а не послушание советам приложения. copilot_advice — советы "
    "приложения и что с ними стало; невыполненный совет не обязательно ошибка игрока. Время пиши как "
    "м:сс, а не в секундах."
)


class AiFinding(BaseModel):
    text: str = Field(min_length=3, max_length=500)
    evidence_ids: list[str] = Field(min_length=1, max_length=10)
    certainty: Literal["verified", "likely", "insufficient_data"]


class AiReport(BaseModel):
    summary: str = Field(min_length=3, max_length=900)
    strengths: list[str] = Field(default_factory=list, max_length=6)
    findings: list[AiFinding] = Field(default_factory=list, max_length=8)
    practice_goals: list[str] = Field(default_factory=list, max_length=3)
    unknowns: list[str] = Field(default_factory=list, max_length=8)


def facts(report: dict[str, Any]) -> dict[str, Any]:
    """What the analyst is told: the report's findings and advice, without raw data or ids of people."""
    advice = report.get("advice") or {}
    return {
        "hero": report.get("hero"),
        "mode": report.get("mode") or "unknown",
        "duration": report.get("duration_s"),
        "won": report.get("won"),
        "stats": report.get("stats"),
        "findings": [
            {
                k: f.get(k)
                for k in (
                    "id",
                    "title",
                    "metric",
                    "actual",
                    "baseline",
                    "comparison_group",
                    "certainty",
                    "evidence_ids",
                )
            }
            for f in report.get("findings") or []
        ],
        "strengths_measured": report.get("strengths") or [],
        # One line per piece of advice and what became of it (the journal repeats advice as the game moves).
        "copilot_advice": advice.get("outcomes") or [],
        "timeline": [{**x, "t": mmss(x.get("t"))} for x in report.get("timeline") or []],
        "missing_data": report.get("missing") or [],
        "allowed_evidence_ids": report.get("evidence_ids") or [],
    }


def analyze(report: dict[str, Any], client: AdvisorClient) -> tuple[dict[str, Any], Call]:
    """The analyst's reading of ``report``; findings with unknown evidence are dropped and counted."""
    answer, call = client.ask_json(SYSTEM, facts(report), AiReport, max_tokens=2500)
    allowed = set(report.get("evidence_ids") or [])
    kept = [f for f in answer.findings if set(f.evidence_ids) <= allowed]
    return (
        {
            "summary": answer.summary,
            "strengths": answer.strengths,
            "findings": [f.model_dump() for f in kept],
            "practice_goals": answer.practice_goals,
            "unknowns": answer.unknowns,
            "blocked_findings": len(answer.findings) - len(kept),
            "model_version": f"{ANALYST_VERSION}/{call.model}",
        },
        call,
    )
