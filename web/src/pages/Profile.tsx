import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { usePeers, useProfile, useSettings } from "../api/hooks";
import { ErrorBox, HeroChip, Loading } from "../components/common";
import { clock, date, dateTime, pct } from "../lib/format";

function PlayerSearch({ onPick }: { onPick: (id: number) => void }) {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<{ account_id: number; name: string | null }[]>([]);
  const [error, setError] = useState<unknown>(null);
  const run = async () => {
    try {
      setError(null);
      setRows(await api.get(`/api/players/search?q=${encodeURIComponent(q)}`));
    } catch (e) {
      setError(e);
    }
  };
  return (
    <div>
      <div className="row">
        <input className="input" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && void run()} placeholder="ID аккаунта или имя игрока" aria-label="Найти игрока" />
        <button className="btn" type="button" onClick={() => void run()} disabled={q.trim().length < 2}>
          Найти игрока
        </button>
      </div>
      <ErrorBox error={error} />
      <ul className="small" style={{ listStyle: "none", padding: 0 }}>
        {rows.map((r) => (
          <li key={r.account_id}>
            <button className="btn small" type="button" onClick={() => onPick(r.account_id)} style={{ margin: "0.15rem 0" }}>
              {r.name ?? r.account_id}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function ProfilePage() {
  const { data: settings } = useSettings();
  const [other, setOther] = useState<number | null>(null);
  const account = other ?? settings?.account_id ?? null;
  const { data: p, error, isFetching } = useProfile(account);
  const peers = usePeers(account);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{other ? "Игрок" : "Ваш профиль"}</h1>
          <p>По публичным данным матчей из OpenDota. В настройках Dota должна быть включена опция «Expose public match data».</p>
        </div>
        {other && (
          <button className="btn" type="button" onClick={() => setOther(null)}>
            Назад к вашему профилю
          </button>
        )}
      </div>
      {!account && (
        <div className="empty">
          <h2>Аккаунт не указан</h2>
          <p>
            Укажите ID аккаунта Steam в разделе <Link to="/settings">Настройки</Link> или сыграйте одну игру с включённым GSI, и он
            заполнится сам. Ниже можно найти любого игрока.
          </p>
        </div>
      )}
      <section className="panel" style={{ margin: "1rem 0" }}>
        <PlayerSearch onPick={setOther} />
      </section>
      <ErrorBox error={error} />
      {account && !p && isFetching && <Loading what="профиля (по одному запросу к OpenDota на раздел)" />}
      {p && (
        <div className="stack">
          <section className="panel">
            <div className="hero-head">
              {p.avatar ? <img src={p.avatar} alt="" width={64} height={64} style={{ borderRadius: 4 }} /> : null}
              <div>
                <h2>{p.name ?? `Аккаунт ${p.account_id}`}</h2>
                <span className="muted">
                  {p.rank ?? "Без ранга или ранг скрыт"}
                  {p.profile_url ? (
                    <>
                      {", "}
                      <a href={p.profile_url} target="_blank" rel="noreferrer">
                        профиль Steam
                      </a>
                    </>
                  ) : null}
                </span>
              </div>
            </div>
            <div className="readouts" style={{ marginTop: "1rem" }}>
              <div className="readout">
                <b>{pct(p.summary.win_rate)}</b>
                <span>
                  Винрейт за последние матчи: {p.summary.games}
                </span>
              </div>
              <div className="readout">
                <b>
                  {p.summary.recent_20.wins}-{p.summary.recent_20.games - p.summary.recent_20.wins}
                </b>
                <span>Последние 20</span>
              </div>
              <div className="readout">
                <b className={p.streaks.current_kind === "win" ? "good" : "bad"}>
                  {p.streaks.current} {p.streaks.current_kind === "win" ? "В" : "П"}
                </b>
                <span>Текущая серия</span>
              </div>
              <div className="readout">
                <b>{pct(p.ranked_summary.win_rate)}</b>
                <span>Рейтинговые ({p.ranked_summary.games})</span>
              </div>
              <div className="readout">
                <b>{p.summary.avg_kda ?? "–"}</b>
                <span>Средний KDA</span>
              </div>
            </div>
            {p.streaks.current_kind === "loss" && p.streaks.current >= 3 && (
              <div className="note" style={{ marginTop: "1rem" }}>
                Поражений подряд: {p.streaks.current}. Самая длинная серия поражений в этих матчах: {p.streaks.longest_loss}.
              </div>
            )}
          </section>
          <div className="grid cols-2">
            <section className="panel">
              <h3>Сессии</h3>
              {p.sessions.map((s) => (
                <div key={s.start} className="row" style={{ justifyContent: "space-between", marginBottom: "0.4rem" }}>
                  <span className="small">{dateTime(s.start)}</span>
                  <span className="results-strip" aria-label={`Побед: ${s.wins}, поражений: ${s.games - s.wins}`}>
                    {s.results.map((r, i) => (
                      <i key={i} className={r === "W" ? "w" : ""} />
                    ))}
                  </span>
                </div>
              ))}
              <p className="source">Матчи с перерывом меньше двух часов считаются одной сессией.</p>
            </section>
            <section className="panel">
              <h3>Винрейт по часу начала матча</h3>
              <div className="hours">
                {Array.from({ length: 24 }, (_, h) => {
                  const row = p.by_hour.find((r) => r.hour === h);
                  return <i key={h} title={row ? `${h}:00, матчей: ${row.games}, ${pct(row.win_rate, 0)}` : `${h}:00, матчей нет`} style={{ height: `${row ? Math.max(row.win_rate * 100, 3) : 0}%`, opacity: row ? Math.min(0.35 + row.games / 15, 1) : 0 }} />;
                })}
              </div>
              <p className="source">Высота столбца — винрейт; чем бледнее столбец, тем меньше матчей. Время — в часовом поясе этого компьютера.</p>
            </section>
          </div>
          <section className="panel">
            <h3>Пул героев</h3>
            <table>
              <thead>
                <tr>
                  <th>Герой</th>
                  <th className="num">Матчи</th>
                  <th className="num">Винрейт</th>
                  <th className="num" title="Нижняя граница 95%: винрейт, на который можно положиться с учётом числа матчей">Надёжная оценка</th>
                  <th className="num">KDA</th>
                  <th className="num">Последняя игра</th>
                </tr>
              </thead>
              <tbody>
                {p.hero_pool.slice(0, 20).map((h) => (
                  <tr key={h.hero}>
                    <td>
                      <HeroChip hero={h.hero} size={24} />
                    </td>
                    <td className="num">{h.games}</td>
                    <td className="num">{pct(h.win_rate, 0)}</td>
                    <td className="num muted">{pct(h.wilson_lower, 0)}</td>
                    <td className="num">{h.kda}</td>
                    <td className="num muted small">{date(h.last_played)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {p.worth_adding.length > 0 && (
              <p className="small" style={{ marginTop: "0.75rem" }}>
                Похожие герои, которых стоит добавить в пул:{" "}
                {p.worth_adding.map((w) => `${w.name} (как ${w.similar_to.join(", ")})`).join("; ")}.
              </p>
            )}
          </section>
          <div className="grid cols-2">
            <section className="panel">
              <h3>Последние матчи</h3>
              <table>
                <tbody>
                  {p.recent.slice(0, 15).map((m) => (
                    <tr key={m.match_id ?? m.start_time}>
                      <td className={m.won ? "good" : "bad"}>{m.won ? "Победа" : "Поражение"}</td>
                      <td>
                        <HeroChip hero={m.hero_id} size={22} />
                      </td>
                      <td className="num">
                        {m.kills}/{m.deaths}/{m.assists}
                      </td>
                      <td className="num muted small">{clock(m.duration)}</td>
                      <td>{m.match_id ? <Link to={`/match/${m.match_id}`}>Разбор</Link> : null}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
            <section className="panel">
              <h3>С кем вы играете</h3>
              <ErrorBox error={peers.error} />
              <table>
                <tbody>
                  {(peers.data ?? []).slice(0, 12).map((pe) => (
                    <tr key={pe.account_id}>
                      <td>
                        <button className="btn small" type="button" onClick={() => setOther(pe.account_id)}>
                          {pe.name ?? pe.account_id}
                        </button>
                      </td>
                      <td className="num">матчей вместе: {pe.with_games}</td>
                      <td className="num">побед: {pct(pe.with_win_rate, 0)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          </div>
          <p className="source">Учтено матчей: {p.matches_considered} (только «значимые» матчи OpenDota).</p>
        </div>
      )}
    </>
  );
}
