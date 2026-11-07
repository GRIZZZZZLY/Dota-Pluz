import { useNavigate, useParams } from "react-router-dom";
import { useAnalyzeMatch, useCoachReview, useGoals, useJournalMatches, useRebuildReview } from "../api/hooks";
import type { AiReview, Certainty, CoachReport, JournalMatch } from "../api/types";
import { ErrorBox, Loading, Portrait } from "../components/common";
import { clock } from "../lib/format";

const CERTAINTY: Record<Certainty, { label: string; cls: string }> = {
  verified: { label: "проверено", cls: "tag" },
  likely: { label: "вероятно", cls: "tag warn" },
  insufficient_data: { label: "мало данных", cls: "tag muted" },
};

function when(ts: number): string {
  return new Date(ts * 1000).toLocaleString("ru-RU", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function show(v: unknown): string {
  return v === null || v === undefined ? "—" : String(v);
}

/** Post-match coach: his games from the Copilot journal, the measured findings, and the analyst's reading. */
export function ReviewPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const matches = useJournalMatches();
  const goals = useGoals();
  const list = (matches.data ?? []).filter((m) => m.source === "game" || m.source === "replay");
  const selected = id ?? list[0]?.match_id ?? null;
  return (
    <>
      <h1>Разбор матчей</h1>
      <p className="muted small">
        Только факты из ваших игр: журнал Copilot, запись GSI и OpenDota, если матч там есть. Каждая находка говорит, с чем
        сравнивали и насколько уверена; одна находка не объясняет, почему игра выиграна или проиграна.
      </p>
      {goals.data && (goals.data.goals.length > 0 || goals.data.recurring.length > 0) && (
        <section className="panel stack">
          <h3>Цели на следующие игры</h3>
          <ul>
            {[...new Map(goals.data.goals.map((g) => [g.text, g])).values()].slice(0, 5).map((g) => (
              <li key={g.text}>
                {g.text} <span className="muted small">({g.source === "ai" ? "DeepSeek" : "тренер"})</span>
              </li>
            ))}
          </ul>
          {goals.data.recurring.length > 0 && (
            <>
              <h3>Повторяется</h3>
              <ul className="small">
                {goals.data.recurring.map((r) => (
                  <li key={r.metric}>
                    {r.title} — в {r.matches} из {r.of} последних разборов
                  </li>
                ))}
              </ul>
            </>
          )}
        </section>
      )}
      <div className="grid cols-2">
        <section className="panel stack" aria-label="Матчи">
          <h3>Ваши матчи</h3>
          {matches.isLoading && <Loading what="матчи" />}
          {matches.error && <ErrorBox error={matches.error} />}
          {!list.length && !matches.isLoading && <p className="muted">Пока нет игр в журнале: запустите приложение и сыграйте.</p>}
          {list.map((m: JournalMatch) => (
            <button
              key={m.match_id}
              type="button"
              className={`row match-row${m.match_id === selected ? " active" : ""}`}
              onClick={() => navigate(`/review/${m.match_id}`)}
            >
              <Portrait hero={m.hero_id} size={28} />
              <span>
                <strong>{m.hero ?? "Герой ?"}</strong> · {when(m.last_seen_at)}
                <span className="muted small">
                  {" "}
                  · {m.last_game_time_s ? clock(m.last_game_time_s) : "?"}
                  {m.reports.includes("ai") ? " · разобран DeepSeek" : m.reports.includes("facts") ? " · разобран" : ""}
                </span>
              </span>
            </button>
          ))}
        </section>
        {selected ? <MatchReview matchId={selected} /> : <section className="panel muted">Выберите матч слева.</section>}
      </div>
    </>
  );
}

function MatchReview({ matchId }: { matchId: string }) {
  const review = useCoachReview(matchId);
  const rebuild = useRebuildReview();
  const analyze = useAnalyzeMatch();
  if (review.isLoading) return <Loading what="разбор" />;
  if (review.error) return <ErrorBox error={review.error} />;
  if (!review.data) return null;
  const r: CoachReport = review.data.facts;
  return (
    <section className="panel stack" aria-label="Разбор матча">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3>
          {r.hero ?? "Герой ?"} · {r.mode === "turbo" ? "Turbo" : r.mode === "normal" ? "обычная игра" : "режим не определён"}
          {r.duration_s ? ` · ${clock(r.duration_s)}` : ""}
          {r.won === true ? " · победа" : r.won === false ? " · поражение" : ""}
        </h3>
        <button className="btn small" type="button" disabled={rebuild.isPending} onClick={() => rebuild.mutate(matchId)}>
          {rebuild.isPending ? "Обновляю…" : "Обновить (OpenDota)"}
        </button>
      </div>
      {r.stats && (
        <p className="small">
          {r.stats.kills}/{r.stats.deaths}/{r.stats.assists} · добивания {r.stats.last_hits} · GPM {r.stats.gpm} · XPM {r.stats.xpm}
          {r.stats.level ? ` · уровень ${r.stats.level}` : ""}
        </p>
      )}

      <h3>Что разобрать</h3>
      {!r.findings.length && <p className="muted small">Заметных ошибок по измеряемым правилам не найдено.</p>}
      {r.findings.map((f) => (
        <article className="advice" key={f.id}>
          <div className="row" style={{ justifyContent: "space-between" }}>
            <strong>{f.title}</strong>
            <span className={CERTAINTY[f.certainty].cls}>{CERTAINTY[f.certainty].label}</span>
          </div>
          {(f.actual !== null || f.baseline !== null) && (
            <p className="small">
              У вас: {show(f.actual)} · ориентир: {show(f.baseline)} <span className="muted">({f.comparison_group})</span>
            </p>
          )}
          {f.review_anchor && <p className="small muted">Пересмотреть: {f.review_anchor}</p>}
          {f.recommendation && <p className="small">{f.recommendation}</p>}
        </article>
      ))}

      {r.strengths.length > 0 && (
        <>
          <h3>Получилось</h3>
          <ul className="small">
            {r.strengths.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
        </>
      )}

      <AiBlock ai={review.data.ai} pending={analyze.isPending} error={analyze.error} onRun={() => analyze.mutate(matchId)} />

      <h3>Советы Copilot в этой игре</h3>
      <p className="small">
        Всего {r.advice.total}
        {Object.entries(r.advice.by_status).map(([k, v]) => ` · ${k}: ${v}`)}
        {r.advice.models.total ? ` · мнений моделей: ${r.advice.models.total}, совпали с правилами: ${r.advice.models.agreed}` : ""}
      </p>
      <table className="table small">
        <tbody>
          {(r.advice.outcomes ?? []).map((a) => (
            <tr key={a.evidence}>
              <td>{a.first_t}</td>
              <td>{a.name}</td>
              <td>{a.outcome}</td>
              <td className="muted">{a.times_shown > 1 ? `показан ${a.times_shown} раз` : ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="small muted">Невыполненный совет — не обязательно ошибка: решение в игре остаётся за вами.</p>
      <details className="small">
        <summary>Все записи журнала по времени</summary>
        <table className="table">
          <tbody>
            {r.advice.items.map((a) => (
              <tr key={a.id}>
                <td>{a.t !== null ? clock(a.t) : "?"}</td>
                <td>{a.name}</td>
                <td className="muted">{a.source === "baseline" ? "правила" : a.source === "jev" ? "Jev" : "Jev + DeepSeek"}</td>
                <td>{a.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>

      {r.timeline.length > 0 && (
        <details className="small">
          <summary>Смерти и крупные предметы</summary>
          <ul>
            {r.timeline.map((e) => (
              <li key={e.id + e.text}>
                {e.t !== null ? clock(e.t) : "?"} — {e.kind === "death" ? "смерть" : e.text}
              </li>
            ))}
          </ul>
        </details>
      )}

      {r.missing.length > 0 && (
        <div className="small muted">
          <strong>Чего не хватило:</strong>
          <ul>
            {r.missing.map((m) => (
              <li key={m}>{m}</li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function AiBlock({ ai, pending, error, onRun }: { ai: AiReview | null; pending: boolean; error: unknown; onRun: () => void }) {
  return (
    <div className="stack opinion">
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h3>Разбор DeepSeek</h3>
        <button className="btn small" type="button" disabled={pending} onClick={onRun}>
          {pending ? "Разбираю… (до двух минут)" : ai ? "Разобрать заново" : "Разобрать"}
        </button>
      </div>
      {error ? <ErrorBox error={error} /> : null}
      {!ai && !pending && (
        <p className="small muted">
          Модель читает только находки и журнал советов выше и пишет короткий вывод и цели. Стоит доли рубля; нужен ключ
          ForgetAPI в .env.
        </p>
      )}
      {ai && (
        <>
          <p>{ai.summary}</p>
          {ai.findings.map((f) => (
            <p className="small" key={f.text}>
              <span className={CERTAINTY[f.certainty].cls}>{CERTAINTY[f.certainty].label}</span> {f.text}
            </p>
          ))}
          {ai.practice_goals.length > 0 && (
            <ul className="small">
              {ai.practice_goals.map((g) => (
                <li key={g}>Цель: {g}</li>
              ))}
            </ul>
          )}
          {ai.unknowns.length > 0 && <p className="small muted">Неизвестно: {ai.unknowns.join("; ")}</p>}
          <p className="small muted">
            Модель: {ai.model_version}
            {ai.blocked_findings ? ` · отброшено находок без доказательств: ${ai.blocked_findings}` : ""}. Это мнение модели, не
            проверенный факт.
          </p>
        </>
      )}
    </div>
  );
}
