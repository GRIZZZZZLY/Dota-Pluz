import { useCopilotAdvice, useCopilotStatus, useDismissAdvice } from "../api/hooks";
import type { LiveSnapshot, Recommendation } from "../api/types";
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
  const shown = sortAdvice(advice ?? []);

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
          Источник: офлайн-правила{status.error ? ` · ошибка Copilot: ${status.error}` : ""}
        </p>
      )}
    </section>
  );
}
