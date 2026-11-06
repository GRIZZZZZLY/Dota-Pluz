import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useMatch, usePostGame } from "../api/hooks";
import type { MatchReview, ReviewRow } from "../api/types";
import { Bar, ErrorBox, HeroChip, Loading } from "../components/common";
import { dateTime, gold, percentileText } from "../lib/format";

function Team({ rows, won, side }: { rows: ReviewRow[]; won: boolean; side: "radiant" | "dire" }) {
  return (
    <section className="panel">
      <h3 className={side}>
        {side === "radiant" ? "Свет" : "Тьма"}: {won ? "победа" : "поражение"}
      </h3>
      <table>
        <thead>
          <tr>
            <th>Герой</th>
            <th className="num">K/D/A</th>
            <th className="num">ЛХ/ДН</th>
            <th className="num">GPM</th>
            <th className="num">Нетворс</th>
            <th className="num">Урон</th>
            <th>Предметы</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.hero}${r.account_id}`}>
              <td>
                <HeroChip hero={r.hero} size={24} extra={r.name ? <span className="muted small">{r.name}</span> : null} />
              </td>
              <td className="num">
                {r.kills}/{r.deaths}/{r.assists}
              </td>
              <td className="num">
                {r.last_hits}/{r.denies}
              </td>
              <td className="num">{r.gpm}</td>
              <td className="num gold">{gold(r.net_worth)}</td>
              <td className="num">{gold(r.hero_damage)}</td>
              <td className="small muted">{r.items.map((i) => i.name).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Review({ m }: { m: MatchReview }) {
  const [parse, setParse] = useState("");
  const requestParse = async () => {
    try {
      await api.post(`/api/matches/${m.match_id}/parse`);
      setParse("Обработка запрошена. Обычно OpenDota справляется за несколько минут, потом обновите страницу.");
    } catch (e) {
      setParse(e instanceof Error ? e.message : String(e));
    }
  };
  return (
    <div className="stack">
      <p className="muted">
        Матч {m.match_id}, {dateTime(m.start_time)}, {m.duration_text}. Счёт{" "}
        <span className="radiant">{m.score.radiant}</span> : <span className="dire">{m.score.dire}</span>.
      </p>
      {!m.parsed && (
        <div className="note">
          OpenDota ещё не обработал эту запись, поэтому таймингов предметов и цифр по линии нет.{" "}
          <button className="btn small" type="button" onClick={() => void requestParse()}>
            Запросить обработку
          </button>{" "}
          {parse}
        </div>
      )}
      {m.me && (
        <section className="panel">
          <h2>
            Ваша игра: <span className={m.me.won ? "good" : "bad"}>{m.me.won ? "победа" : "поражение"}</span> на {m.me.row.hero_name}
          </h2>
          {m.notes.length > 0 && (
            <ul>
              {m.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
          <div className="grid cols-2">
            <div>
              <h3>В сравнении с другими игроками на {m.me.row.hero_name}</h3>
              {m.me.benchmarks.length ? (
                m.me.benchmarks.map((b) => (
                  <div key={b.metric} style={{ marginBottom: "0.45rem" }}>
                    <div className="small row" style={{ justifyContent: "space-between" }}>
                      <span>
                        {b.label}: {b.value}
                      </span>
                      <span className="muted">{percentileText(b.percentile)}</span>
                    </div>
                    <Bar value={b.percentile} label={b.label} />
                  </div>
                ))
              ) : (
                <p className="small muted">Ориентиров нет, пока запись не обработана.</p>
              )}
            </div>
            <div>
              <h3>Тайминги предметов в сравнении с медианой про-игроков</h3>
              {m.me.item_timings.length ? (
                <table>
                  <tbody>
                    {m.me.item_timings.map((t) => (
                      <tr key={t.item}>
                        <td>{t.name}</td>
                        <td className="num">{t.you}</td>
                        <td className="num muted">про: {t.pro_median}</td>
                        <td className={`num ${t.delta_seconds > 0 ? "bad" : "good"}`}>{t.delta_seconds > 0 ? `+${t.delta}` : t.delta}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="small muted">Таймингов нет: запись не обработана или ваших предметов нет в данных о сборках про-игроков.</p>
              )}
            </div>
          </div>
        </section>
      )}
      <Team rows={m.radiant} won={m.radiant_win} side="radiant" />
      <Team rows={m.dire} won={!m.radiant_win} side="dire" />
    </div>
  );
}

export function MatchPage() {
  const params = useParams();
  const navigate = useNavigate();
  const id = params.id ? Number(params.id) : null;
  const [input, setInput] = useState(params.id ?? "");
  const { data, error, isFetching } = useMatch(id);
  const { data: jobs } = usePostGame();
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Матчи</h1>
          <p>Разбор любого матча из OpenDota: таблица итогов, ваши цифры в сравнении с другими игроками на этом герое, тайминги предметов в сравнении с про-игроками.</p>
        </div>
      </div>
      <div className="row" style={{ marginBottom: "1rem" }}>
        <input className="input" value={input} onChange={(e) => setInput(e.target.value.replace(/\D/g, ""))} onKeyDown={(e) => e.key === "Enter" && input && navigate(`/match/${input}`)} placeholder="ID матча" aria-label="ID матча" />
        <button className="btn primary" type="button" disabled={!input} onClick={() => navigate(`/match/${input}`)}>
          Открыть матч
        </button>
      </div>
      {jobs && jobs.length > 0 && (
        <section className="panel" style={{ marginBottom: "1rem" }}>
          <h3>После последних игр</h3>
          {jobs.map((j) => (
            <p key={j.match_id} className="small" style={{ margin: "0.2rem 0" }}>
              Матч {j.match_id}:{" "}
              {j.status === "ready" ? <Link to={`/match/${j.match_id}`}>готов к разбору</Link> : j.status === "waiting" ? `ждём OpenDota (проверка ${j.attempts})` : "OpenDota так и не получил матч, попробуйте этот ID позже"}
              {j.parse_requested ? ", обработка запрошена" : ""}
            </p>
          ))}
        </section>
      )}
      <ErrorBox error={error} />
      {id && isFetching && !data && <Loading what={`матча ${id}`} />}
      {data && <Review m={data} />}
    </>
  );
}
