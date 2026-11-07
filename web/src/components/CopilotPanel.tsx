import { useCopilotAdvice, useCopilotStatus, useDismissAdvice } from "../api/hooks";
import type { LiveSnapshot, Providers, Recommendation } from "../api/types";
import { adviceLabel, dataState, quickbuyHint, sortAdvice } from "../lib/copilot";
import { clock, gold } from "../lib/format";
import { useItemMap } from "./common";

/** The Copilot's current advice: what to level and buy next, why, and how fresh the data is. */
export function CopilotPanel({ snap }: { snap: LiveSnapshot }) {
  const { data: status } = useCopilotStatus();
  const { data: advice } = useCopilotAdvice();
  const dismiss = useDismissAdvice();
  const items = useItemMap();
  const state = dataState(status);
  const abilityName = new Map((snap.skills?.abilities ?? []).map((a) => [a.key, a.name]));
  // Cloud models' opinions sit under the rules' advice of the same kind, not as cards of their own.
  const shown = sortAdvice((advice ?? []).filter((r) => r.source === "baseline"));
  const opinions = new Map(
    (advice ?? []).filter((r) => r.source !== "baseline").map((r) => [`${r.type}:${r.category ?? ""}`, r]),
  );

  function title(rec: Recommendation): string {
    if (rec.type === "SKILL_LEVEL") return abilityName.get(rec.candidate_id) ?? rec.candidate_id;
    if (rec.type === "ITEM_BUYBACK_GUARD") return "Оставьте золото на выкуп";
    if (rec.type === "TALENT") return "Выбор таланта";
    return items.get(rec.candidate_id)?.name ?? rec.candidate_id.replace(/_/g, " ");
  }

  return (
    <section className="copilot stack" aria-label="Copilot">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <strong>Copilot</strong>
        <span className={`tag${state.warn ? " warn" : ""}`}>{state.text}</span>
      </div>
      {!shown.length && <p className="muted small">Сейчас советов нет: они появляются, когда в игре что-то меняется.</p>}
      {shown.map((rec) => {
        const live = rec.type === "ITEM_NEXT" ? snap.next_items?.find((i) => i.item === rec.candidate_id) : undefined;
        const name = title(rec);
        return (
          <article className="advice" key={rec.id}>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <span className="muted small">{adviceLabel(rec)}</span>
              <button className="btn small" onClick={() => dismiss.mutate(rec.id)} aria-label={`Скрыть совет: ${name}`}>
                Скрыть
              </button>
            </div>
            <div>
              <strong>{name}</strong>
              {live && (
                <span className="gold">
                  {" "}
                  · {live.remaining > 0 ? `не хватает ${gold(live.remaining)}` : "хватает золота"}
                  {live.eta_seconds ? ` · ≈${clock(live.eta_seconds)} при текущем GPM (ориентир)` : ""}
                </span>
              )}
            </div>
            <p className="small">{rec.reason_ru}</p>
            <Opinion rec={rec} opinion={opinions.get(`${rec.type}:${rec.category ?? ""}`)} name={title} />
            {rec.type.startsWith("ITEM_") && rec.type !== "ITEM_BUYBACK_GUARD" && (
              <details className="small muted">
                <summary>Как купить</summary>
                {quickbuyHint(name)}
              </details>
            )}
          </article>
        );
      })}
      {status && (
        <p className="muted small">
          Источник: офлайн-правила{cloudLine(status.providers)}
          {status.error ? ` · ошибка Copilot: ${status.error}` : ""}
        </p>
      )}
    </section>
  );
}

/** What a cloud model thinks of the rules' advice: agreement, or its pick with the advisor's reason. */
function Opinion({ rec, opinion, name }: { rec: Recommendation; opinion?: Recommendation; name: (r: Recommendation) => string }) {
  if (!opinion) return null;
  const who = opinion.source === "hybrid" ? "Jev + DeepSeek" : "Jev";
  const conf = opinion.confidence != null ? `, уверенность модели ${Math.round(opinion.confidence * 100)}%` : "";
  if (opinion.candidate_id === rec.candidate_id && opinion.source === "jev") {
    return <p className="small muted">✓ {who} согласен{conf}</p>;
  }
  return (
    <p className="small opinion">
      <strong>{who}:</strong> {opinion.candidate_id === rec.candidate_id ? "лучше этот вариант" : `альтернатива — ${name(opinion)}`}. {opinion.source === "hybrid" ? opinion.reason_ru : ""}
      <span className="muted">{conf}. Это оценка модели, не вероятность победы.</span>
    </p>
  );
}

function cloudLine(p: Providers | undefined): string {
  if (!p || p.mode === "baseline") return "";
  const on = [p.jev.configured && "Jev", p.mode === "hybrid" && p.advisor.configured && "DeepSeek"].filter(Boolean);
  if (!on.length) return " · облачные модели выключены: нет ключей в .env";
  const down = [p.jev, p.advisor].find((x) => x.configured && x.online === false);
  return ` + ${on.join(", ")}${down ? ` (ошибка: ${down.error})` : ""}`;
}
