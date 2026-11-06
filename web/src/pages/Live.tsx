import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useSettings } from "../api/hooks";
import type { LiveSnapshot } from "../api/types";
import { ClockRail } from "../components/ClockRail";
import { Bar, ErrorBox, HeroChip, ItemIcon, LineChart, Portrait } from "../components/common";
import { clock, gold, pct, percentileText } from "../lib/format";
import { useHotkeys } from "../lib/hotkeys";
import { setVoice, useSpeakAlerts, voiceUnlocked } from "../lib/voice";

export interface LiveState {
  snap: LiveSnapshot | null;
  online: boolean;
}

const PHASES: Record<string, string> = {
  waiting: "Ждём Dota",
  menu: "В меню",
  loading: "Загрузка",
  hero_selection: "Выбор героев",
  strategy: "Время стратегии",
  showcase: "Показ героев",
  pre_game: "Перед стартом",
  in_game: "Идёт игра",
  post_game: "Игра окончена",
};

export function NoGame({ online }: { online: boolean }) {
  const [error, setError] = useState<unknown>(null);
  const start = async () => {
    try {
      await api.post("/api/demo", { hero: "juggernaut", speed: 8 });
    } catch (e) {
      setError(e);
    }
  };
  return (
    <div className="empty">
      <h2>Игры пока нет</h2>
      {online ? (
        <p>
          Когда Dota 2 пришлёт первое обновление GSI (Game State Integration), страница заполнится: таймеры, следующий
          предмет, подсказки по способностям и драфт врагов. Если конфиг GSI ещё не установлен, сделайте это на странице{" "}
          <Link to="/setup">«Подключение»</Link>.
        </p>
      ) : (
        <p>Сервер приложения не отвечает. Запустите его командой <code>.\run.cmd</code>, и страница переподключится сама.</p>
      )}
      <div className="row">
        <button className="btn primary" type="button" onClick={start} disabled={!online}>
          Запустить демо-матч
        </button>
        <Link className="btn" to="/setup">
          Настроить GSI
        </Link>
      </div>
      <p className="small muted" style={{ marginTop: "0.75rem" }}>
        Демо проигрывает выдуманный матч на скорости 8×, чтобы показать все функции страницы «Матч».
      </p>
      <ErrorBox error={error} />
    </div>
  );
}

function Marks({ snap }: { snap: LiveSnapshot }) {
  const mark = (what: string) => api.post("/api/live/mark", { what });
  const keys = useMemo(() => ({ r: () => void mark("roshan"), t: () => void mark("tormentor"), a: () => void mark("aegis") }), []);
  useHotkeys(keys);
  return (
    <div className="row" style={{ marginTop: "1rem" }}>
      <button className="btn" type="button" onClick={() => mark("roshan")} title="Клавиша R">
        Рошан убит
      </button>
      <button className="btn" type="button" onClick={() => mark("aegis")} title="Клавиша A">
        Аегис взят
      </button>
      <button className="btn" type="button" onClick={() => mark("tormentor")} title="Клавиша T">
        Tormentor убит
      </button>
      {snap.timers?.some((t) => t.id === "roshan" && t.status !== "alive") && (
        <button className="btn" type="button" onClick={() => mark("clear_roshan")}>
          Сбросить таймер Рошана
        </button>
      )}
    </div>
  );
}

export function TimerColumn({ snap, compact = false }: { snap: LiveSnapshot; compact?: boolean }) {
  return (
    <div>
      <div className="clockface">
        <span className="time" aria-label="Игровое время">
          {clock(snap.clock)}
        </span>
        <span className="muted">
          {PHASES[snap.phase] ?? snap.phase}
          {snap.daytime === true ? ", день" : snap.daytime === false ? ", ночь" : ""}
          {snap.paused ? ", пауза" : ""}
        </span>
      </div>
      {snap.score && (snap.score.radiant !== null || snap.score.dire !== null) && (
        <p className="small" style={{ margin: "0.35rem 0 0" }}>
          <span className="radiant">Свет {snap.score.radiant ?? 0}</span>
          {"  "}
          <span className="dire">Тьма {snap.score.dire ?? 0}</span>
          {snap.team ? <span className="muted"> (вы за {snap.team === "radiant" ? "Свет" : "Тьму"})</span> : null}
        </p>
      )}
      {snap.clock !== null && snap.clock !== undefined && <ClockRail timers={snap.timers ?? []} now={snap.clock} />}
      {!compact && <Marks snap={snap} />}
      <p className="source">Правила таймеров для патча {snap.timer_patch}, по патчноутам Valve. Наведите на таймер, чтобы увидеть источник.</p>
    </div>
  );
}

export function NextItems({ snap }: { snap: LiveSnapshot }) {
  const items = snap.next_items ?? [];
  if (!items.length) return <p className="muted small">Для этого героя пока нет данных о сборке.</p>;
  return (
    <div>
      {items.map((i, idx) => (
        <div className="next-item" key={i.item}>
          <ItemIcon itemKey={i.item} caption={idx === 0 ? "Следующий" : i.name} />
          <div>
            <div className="row" style={{ justifyContent: "space-between" }}>
              <strong>{i.name}</strong>
              <span className="gold">{i.remaining > 0 ? `не хватает ${gold(i.remaining)} золота` : "Можно купить"}</span>
            </div>
            <Bar value={i.progress} gold label={`${i.name}: прогресс`} />
            <div className="meta">
              {i.eta_seconds ? `Примерно ${clock(i.eta_seconds)} при вашем GPM. ` : ""}
              {i.pro_median ? `Про-игроки собирают его к ${i.pro_median} (медиана).` : ""}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function AlertList({ snap, limit = 30 }: { snap: LiveSnapshot; limit?: number }) {
  const alerts = (snap.alerts ?? []).slice(0, limit);
  if (!alerts.length) return <p className="muted small">Здесь появляются подсказки; если голос включён, они зачитываются вслух.</p>;
  return (
    <ul className="alerts" aria-live="polite">
      {alerts.map((a) => (
        <li key={a.id} className={a.kind}>
          <span className="t">{a.clock_text ?? ""}</span>
          <span className="x">{a.text}</span>
        </li>
      ))}
    </ul>
  );
}

function VoiceToggle() {
  const [on, setOn] = useState(voiceUnlocked());
  return (
    <button
      className="btn"
      type="button"
      aria-pressed={on}
      onClick={() => {
        setVoice(!on);
        setOn(!on);
      }}
    >
      {on ? "Голос включён" : "Включить голос"}
    </button>
  );
}

function HeroPanel({ snap }: { snap: LiveSnapshot }) {
  const h = snap.hero!;
  const s = snap.stats!;
  return (
    <section className="panel">
      <div className="hero-head">
        <Portrait hero={h.id} size={64} wide />
        <div>
          <h2>{h.name}</h2>
          <span className="muted">
            Уровень {h.level ?? "–"}
            {h.alive === false ? <span className="bad">, убит, возрождение через {h.respawn_seconds ?? "?"} с</span> : null}
            {h.scepter ? ", Aghanim's Scepter" : ""}
            {h.shard ? ", Aghanim's Shard" : ""}
          </span>
        </div>
      </div>
      <div className="readouts" style={{ marginTop: "1rem" }}>
        <div className="readout">
          <b>
            {s.kills}/{s.deaths}/{s.assists}
          </b>
          <span>K/D/A{s.kill_participation !== null ? `, участие в убийствах ${pct(s.kill_participation, 0)}` : ""}</span>
        </div>
        <div className="readout">
          <b>
            {s.last_hits}/{s.denies}
          </b>
          <span>Ластхиты / денаи</span>
        </div>
        <div className="readout">
          <b>{s.gpm}</b>
          <span>GPM ({s.xpm} XPM)</span>
        </div>
        <div className="readout">
          <b className="gold">{gold(s.gold)}</b>
          <span>Золото (надёжное: {gold(s.gold_reliable)})</span>
        </div>
        <div className="readout">
          <b>{gold(s.net_worth)}</b>
          <span>Нетворс</span>
        </div>
        <div className="readout">
          <b className={s.buyback_cost && s.gold >= s.buyback_cost ? "good" : "bad"}>{gold(s.buyback_cost)}</b>
          <span>Выкуп{s.buyback_cooldown ? `, перезарядка ${clock(s.buyback_cooldown)}` : ""}</span>
        </div>
      </div>
      {snap.items && (
        <div className="order" style={{ marginTop: "1rem" }}>
          {[...snap.items.inventory, ...snap.items.backpack].map((i) => (
            <ItemIcon key={i.slot} itemKey={i.key} />
          ))}
          {snap.items.neutral ? <ItemIcon itemKey={snap.items.neutral} /> : null}
        </div>
      )}
    </section>
  );
}

function Pace({ snap }: { snap: LiveSnapshot }) {
  if (!snap.benchmarks?.length) return null;
  return (
    <section className="panel">
      <h3>Темп в сравнении с публичными играми на этом герое</h3>
      {snap.lh_target && (
        <p>
          Ластхиты: <strong>{snap.lh_target.you}</strong>; у медианного игрока к этому моменту около {snap.lh_target.now}, а к
          10:00 — {snap.lh_target.at_10}.
        </p>
      )}
      {snap.benchmarks.map((b) => (
        <div key={b.metric} style={{ marginBottom: "0.5rem" }}>
          <div className="row small" style={{ justifyContent: "space-between" }}>
            <span>
              {b.label}: {b.value}
            </span>
            <span className="muted">{percentileText(b.percentile)}</span>
          </div>
          <Bar value={b.percentile ?? 0} label={`${b.label}: перцентиль`} />
        </div>
      ))}
      <p className="source">Перцентили по данным OpenDota для этого героя.</p>
    </section>
  );
}

function EnemyPanel({ snap }: { snap: LiveSnapshot }) {
  const enemies = snap.draft?.enemies ?? [];
  if (!enemies.length)
    return (
      <section className="panel">
        <h3>Драфт врагов</h3>
        <p className="muted small">
          Врагов пока не видно. Во время драфта Dota не сообщает игроку пики врагов; после загрузки каждый враг появится здесь,
          как только вы увидите его на миникарте. Чтобы спланировать заранее, введите их на странице{" "}
          <Link to="/draft">«Драфт»</Link>.
        </p>
      </section>
    );
  return (
    <section className="panel">
      <h3>Драфт врагов и что против него купить</h3>
      <div className="row" style={{ marginBottom: "0.75rem" }}>
        {enemies.map((e) => (
          <HeroChip key={e} hero={e} size={24} />
        ))}
      </div>
      {(snap.situational_items ?? []).map((rule) => (
        <div key={rule.id} style={{ marginBottom: "0.75rem" }}>
          <div className="small">
            <strong>{rule.reason_ru || rule.reason}</strong> <span className="muted">({rule.heroes.join(", ")})</span>
          </div>
          <div className="order">
            {rule.items.map((i) => (
              <ItemIcon key={i.key} itemKey={i.key} owned={i.owned} />
            ))}
          </div>
        </div>
      ))}
    </section>
  );
}

function Spectating({ snap }: { snap: LiveSnapshot }) {
  if (!snap.players?.length) return null;
  return (
    <section className="panel">
      <h3>Все игроки (режим зрителя)</h3>
      <table>
        <thead>
          <tr>
            <th>Герой</th>
            <th className="num">K/D/A</th>
            <th className="num" title="Ластхиты">LH</th>
            <th className="num">GPM</th>
            <th className="num">Нетворс</th>
            <th>Предметы</th>
          </tr>
        </thead>
        <tbody>
          {snap.players.map((p) => (
            <tr key={`${p.team}${p.slot}`}>
              <td className={p.team}>{p.hero ? <HeroChip hero={p.hero} size={22} /> : p.name}</td>
              <td className="num">
                {p.kills}/{p.deaths}/{p.assists}
              </td>
              <td className="num">{p.last_hits}</td>
              <td className="num">{p.gpm}</td>
              <td className="num">{gold(p.net_worth)}</td>
              <td className="small muted">{p.items.map((i) => i.name).join(", ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

export function LivePage({ live }: { live: LiveState }) {
  const { snap, online } = live;
  const { data: settings } = useSettings();
  useSpeakAlerts(snap?.alerts, settings?.timers.voice ?? true);

  if (!snap || snap.phase === "waiting") {
    return (
      <>
        <div className="page-head">
          <h1>Матч</h1>
        </div>
        <NoGame online={online} />
      </>
    );
  }
  return (
    <>
      <div className="page-head">
        <h1>Матч</h1>
        <div className="row">
          {snap.demo && <span className="tag">Демо-матч, выдуманные цифры</span>}
          {snap.connection.source === "replay" && <span className="tag">Воспроизводится запись</span>}
          <VoiceToggle />
          {snap.connection.source !== "game" && (
            <button className="btn" type="button" onClick={() => api.post("/api/live/reset")}>
              Остановить
            </button>
          )}
        </div>
      </div>
      <div className="live">
        <aside className="panel">
          <TimerColumn snap={snap} />
        </aside>
        <div className="stack">
          {snap.hero && snap.stats && <HeroPanel snap={snap} />}
          {snap.buyback_warning && <div className="note">{snap.buyback_warning}</div>}
          {snap.next_items && (
            <section className="panel">
              <h3>Следующие предметы</h3>
              <NextItems snap={snap} />
            </section>
          )}
          {snap.skills?.next && (snap.skills.unspent ?? 0) > 0 && (
            <div className="note">
              Нераспределённые очки способностей: {snap.skills.unspent}. Про-игроки здесь обычно берут{" "}
              <strong>{snap.skills.next.name}</strong> ({pct(snap.skills.next.share, 0)} про-матчей).
            </div>
          )}
          <div className="grid cols-2">
            <Pace snap={snap} />
            <EnemyPanel snap={snap} />
          </div>
          <section className="panel">
            <h3>Подсказки</h3>
            <AlertList snap={snap} />
          </section>
          {(snap.series?.length ?? 0) > 1 && (
            <section className="panel">
              <h3>
                <span className="gold">Золото</span> и <span style={{ color: "var(--river)" }}>ластхиты</span> по ходу игры
              </h3>
              <LineChart points={snap.series ?? []} series={[{ key: "gold", className: "gold" }, { key: "last_hits", className: "lh" }]} />
            </section>
          )}
          <Spectating snap={snap} />
        </div>
      </div>
    </>
  );
}
