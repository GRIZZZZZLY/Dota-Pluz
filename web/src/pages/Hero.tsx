import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../api/client";
import { useBuild, useHero } from "../api/hooks";
import type { BuildResponse, HeroDetail, RankBucket } from "../api/types";
import { Bar, ErrorBox, HeroChip, ItemIcon, Loading, Portrait, Segmented } from "../components/common";
import { BUCKETS, MEDALS, POSITION_NAMES, date, pct, pts } from "../lib/format";

// Russian labels for data keys and OpenDota constants; anything not listed shows as it comes.
const STAT_LABELS: Record<string, string> = {
  base_health: "Здоровье",
  base_health_regen: "Регенерация здоровья",
  base_mana: "Мана",
  base_mana_regen: "Регенерация маны",
  base_armor: "Броня",
  base_mr: "Сопротивление магии",
  base_attack_min: "Мин. урон атаки",
  base_attack_max: "Макс. урон атаки",
  base_str: "Сила",
  base_agi: "Ловкость",
  base_int: "Интеллект",
  str_gain: "Прирост силы",
  agi_gain: "Прирост ловкости",
  int_gain: "Прирост интеллекта",
  attack_range: "Дальность атаки",
  projectile_speed: "Скорость снаряда",
  attack_rate: "Интервал атаки",
  base_attack_time: "Базовое время атаки",
  attack_point: "Замах атаки",
  move_speed: "Скорость передвижения",
  turn_rate: "Скорость поворота",
  day_vision: "Обзор днём",
  night_vision: "Обзор ночью",
  gold_per_min: "GPM",
  xp_per_min: "XPM",
  kills_per_min: "Убийства в минуту",
  last_hits_per_min: "Ластхиты в минуту",
  hero_damage_per_min: "Урон по героям в минуту",
  hero_healing_per_min: "Лечение в минуту",
  tower_damage: "Урон по башням",
  stuns_per_min: "Оглушение в минуту",
  lhten: "Ластхиты к 10-й минуте",
};
const statLabel = (k: string) => STAT_LABELS[k] ?? k.replace(/_/g, " ");
const DMG_TYPES: Record<string, string> = { Magical: "магический", Physical: "физический", Pure: "чистый" };
const ATTACK_TYPES: Record<string, string> = { Melee: "Ближний бой", Ranged: "Дальний бой" };
const ROLES: Record<string, string> = {
  Carry: "Керри",
  Support: "Саппорт",
  Nuker: "Нюкер",
  Disabler: "Контроль",
  Jungler: "Лесник",
  Durable: "Живучий",
  Escape: "Побег",
  Pusher: "Пушер",
  Initiator: "Инициатор",
};

function BuildTab({ build }: { build: BuildResponse }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    const text = await api.get<string>(`/api/heroes/${build.hero.key}/build.txt`);
    await navigator.clipboard?.writeText(text);
    setCopied(true);
  };
  const talentsByLevel = [25, 20, 15, 10].map((lvl) => build.skills.talents.filter((t) => t.level === lvl));
  return (
    <div className="stack">
      {build.notes.map((n) => (
        <div key={n} className="note">
          {n}
        </div>
      ))}
      <section className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <h2>Сборка предметов</h2>
          <button className="btn" type="button" onClick={() => void copy()}>
            {copied ? "Скопировано" : "Копировать сборку текстом"}
          </button>
        </div>
        {build.items.starting[0] && (
          <>
            <h3>Стартовые предметы</h3>
            <div className="order">
              {build.items.starting[0].items.map((i, idx) => (
                <ItemIcon key={`${i.key}${idx}`} itemKey={i.key} />
              ))}
            </div>
            <p className="small muted">
              Про-матчи: {build.items.starting[0].n} из {build.pro.games}.
            </p>
          </>
        )}
        <h3>Основные предметы в порядке сборки у про-игроков</h3>
        <div className="order">
          {build.items.order.map((o) => (
            <ItemIcon key={o.key} itemKey={o.key} caption={<>{o.name}<br /><span className="gold">{o.median}</span> <span>{pct(o.share, 0)}</span></>} />
          ))}
        </div>
        <p className="source">
          Про-матчей на этом герое: {build.pro.games}
          {build.pro.since ? `, с ${date(build.pro.since)}` : ""}. Показаны медианная минута первой покупки и доля матчей, где
          предмет купили. Компоненты, которые потом собираются в предмет крупнее, не показаны.
        </p>
      </section>
      <section className="panel">
        <h2>Порядок способностей</h2>
        <div className="skill-row">
          {build.skills.by_level.slice(0, 18).map((s) => (
            <div key={s.pick} className="lv" title={`${s.name}: ${pct(s.share, 0)}, матчей: ${s.n}`}>
              {s.img ? <img src={s.img} alt={s.name} /> : <span>{s.name}</span>}
              {s.pick}
            </div>
          ))}
        </div>
        {build.skills.orders[0] && (
          <p className="small muted" style={{ marginTop: "0.5rem" }}>
            Чаще всего первые десять очков: {build.skills.orders[0].order.map((a) => a.name).join(", ")} (матчей: {build.skills.orders[0].n}
            {build.skills.orders[0].win_rate !== null ? `, побед: ${pct(build.skills.orders[0].win_rate, 0)}` : ""}).
          </p>
        )}
        <h3>Таланты</h3>
        <table>
          <tbody>
            {talentsByLevel.map((pair, i) =>
              pair.length ? (
                <tr key={i}>
                  <td className="num" style={{ width: "3rem" }}>
                    {pair[0]!.level}
                  </td>
                  {pair.map((t) => (
                    <td key={t.key} style={{ fontWeight: (t.share ?? 0) >= 0.5 ? 600 : 400 }}>
                      {t.name} <span className="muted small">{t.share === null ? "" : pct(t.share, 0)}</span>
                    </td>
                  ))}
                </tr>
              ) : null,
            )}
          </tbody>
        </table>
      </section>
      <div className="grid cols-2">
        {Object.entries(build.items.phases).map(([phase, rows]) =>
          rows.length ? (
            <section key={phase} className="panel">
              <h3>{{ start: "Куплено до горна", early: "Начало игры", mid: "Середина игры", late: "Поздняя игра" }[phase] ?? phase}</h3>
              <div className="order">
                {rows.slice(0, 8).map((r) => (
                  <ItemIcon key={r.key} itemKey={r.key} caption={<>{r.name}<br />{pct(r.share, 0)}</>} />
                ))}
              </div>
            </section>
          ) : null,
        )}
      </div>
      {Object.keys(build.items.timing_win_rates).length > 0 && (
        <section className="panel">
          <h2>Винрейт по таймингу предмета</h2>
          <table>
            <thead>
              <tr>
                <th>Предмет</th>
                <th>Винрейт, если куплен до…</th>
              </tr>
            </thead>
            <tbody>
              {Object.values(build.items.timing_win_rates)
                .sort((a, b) => b.games - a.games)
                .slice(0, 10)
                .map((t) => (
                  <tr key={t.key}>
                    <td>{t.name}</td>
                    <td className="small">
                      {t.buckets
                        .filter((b) => b.games >= 10)
                        .map((b) => `${b.label}: ${pct(b.win_rate, 0)} (${b.games})`)
                        .join("   ")}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
          <p className="source">Тайминги предметов из OpenDota (публичные матчи). Интервалы, где меньше 10 матчей, скрыты.</p>
        </section>
      )}
    </div>
  );
}

function AbilitiesTab({ hero }: { hero: HeroDetail }) {
  return (
    <section className="panel">
      {hero.abilities
        .filter((a) => !a.hidden || a.desc)
        .map((a) => (
          <div key={a.key} className="ability">
            {a.img ? <img src={a.img} alt="" loading="lazy" /> : <span />}
            <div>
              <h3 style={{ marginBottom: "0.2rem" }}>
                {a.name} {a.hidden ? <span className="tag">от Aghanim's или часть другой способности</span> : null}
              </h3>
              <p className="small">{a.desc}</p>
              <p className="small muted">
                {[a.behavior.join(", "), a.dmg_type ? `урон ${DMG_TYPES[a.dmg_type] ?? a.dmg_type}` : "", a.bkb_pierce ? "проходит сквозь иммунитет к магии" : "",
                  a.cooldown ? `перезарядка ${String(a.cooldown)}` : "", a.mana ? `мана ${String(a.mana)}` : ""]
                  .filter(Boolean)
                  .join("; ")}
              </p>
            </div>
          </div>
        ))}
      {hero.scepter?.desc && (
        <p>
          <strong>Aghanim's Scepter ({hero.scepter.skill}):</strong> {hero.scepter.desc}
        </p>
      )}
      {hero.shard?.desc && (
        <p>
          <strong>Aghanim's Shard ({hero.shard.skill}):</strong> {hero.shard.desc}
        </p>
      )}
      <h3>Особенности по тексту способностей</h3>
      <div className="row">
        {hero.traits.map((t) => (
          <span key={t.trait} className="tag" title={`Найдено в: ${t.evidence.join(", ")}`}>
            {t.label}
          </span>
        ))}
      </div>
    </section>
  );
}

function MatchupsTab({ hero }: { hero: HeroDetail }) {
  const list = (rows: { hero: number; value?: number; edge?: number }[]) => (
    <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {rows.map((r) => (
        <li key={r.hero} className="row" style={{ justifyContent: "space-between", padding: "0.2rem 0" }}>
          <HeroChip hero={r.hero} size={24} />
          <span className={(r.value ?? r.edge ?? 0) >= 0 ? "good" : "bad"}>{pts(r.value ?? r.edge ?? 0)}</span>
        </li>
      ))}
    </ul>
  );
  return (
    <div className="grid cols-3">
      <section className="panel">
        <h3>Силён против</h3>
        {list(hero.best_against)}
      </section>
      <section className="panel">
        <h3>Слаб против</h3>
        {list(hero.worst_against)}
      </section>
      <section className="panel">
        <h3>Лучше всего с</h3>
        {list(hero.best_with)}
      </section>
      <section className="panel">
        <h3>Похожие герои</h3>
        <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
          {hero.similar.map((s) => (
            <li key={s.hero} style={{ padding: "0.2rem 0" }}>
              <HeroChip hero={s.hero} size={24} />
            </li>
          ))}
        </ul>
        <p className="source">Герои, у которых победы и поражения против всех остальных больше всего похожи.</p>
      </section>
      <section className="panel" style={{ gridColumn: "span 2" }}>
        <p className="small muted">
          Перевес по винрейту в процентных пунктах против каждого героя или вместе с ним, сглаженный к собственному винрейту героя;
          пары, где меньше 50 матчей, не учитываются. Риск контрпика {hero.counterability.toFixed(1)}: средний перевес десяти самых
          сильных его контрпиков.
        </p>
      </section>
    </div>
  );
}

function NumbersTab({ hero }: { hero: HeroDetail }) {
  const brackets = hero.meta.brackets ?? {};
  const lanes = hero.lane_roles ?? {};
  const laneTotal = Object.values(lanes).reduce((s, [g]) => s + g, 0) || 1;
  return (
    <div className="grid cols-2">
      <section className="panel">
        <h3>Винрейт по медалям</h3>
        <table>
          <tbody>
            {MEDALS.map((m, i) => {
              const [p, w] = brackets[String(i + 1)] ?? [0, 0];
              return (
                <tr key={m}>
                  <td>{m}</td>
                  <td className="num">{p ? pct(w / p) : "–"}</td>
                  <td className="num muted small">матчей: {p.toLocaleString("ru-RU")}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {hero.meta.pro && (
          <p className="small muted">
            Про-матчи: пики {hero.meta.pro[0]}, баны {hero.meta.pro[2]}, побед {hero.meta.pro[0] ? pct(hero.meta.pro[1] / hero.meta.pro[0]) : "–"}.
          </p>
        )}
      </section>
      <section className="panel">
        <h3>Где играют героя</h3>
        {hero.positions && (
          <>
            {Object.entries(hero.positions.shares).map(([p, s]) => (
              <div key={p} style={{ marginBottom: "0.4rem" }}>
                <div className="small row" style={{ justifyContent: "space-between" }}>
                  <span>
                    {p}. {POSITION_NAMES[Number(p)]}
                  </span>
                  <span>{pct(s, 0)}</span>
                </div>
                <Bar value={s} label={`Позиция ${p}`} />
              </div>
            ))}
            <p className="source">
              Источник: {POSITION_SOURCES[hero.positions.source] ?? hero.positions.source}
              {hero.positions.games ? ` (матчей: ${hero.positions.games})` : ""}.
            </p>
          </>
        )}
        {Object.keys(lanes).length > 0 && (
          <p className="small muted">
            Публичные матчи по линиям:{" "}
            {Object.entries(lanes)
              .map(([lane, [g, w]]) => `${({ "1": "лёгкая", "2": "мид", "3": "сложная", "4": "лес" } as Record<string, string>)[lane] ?? lane} ${pct(g / laneTotal, 0)} (побед: ${pct(w / Math.max(g, 1), 0)})`)
              .join(", ")}
          </p>
        )}
      </section>
      {hero.benchmarks && (
        <section className="panel">
          <h3>Ориентиры (медиана и лучшие 10%)</h3>
          <table>
            <tbody>
              {Object.entries(hero.benchmarks).map(([metric, points]) => {
                const med = points.find(([p]) => p === 0.5)?.[1];
                const top = points.find(([p]) => p === 0.9)?.[1];
                return (
                  <tr key={metric}>
                    <td>{statLabel(metric)}</td>
                    <td className="num">{med?.toFixed(metric.includes("per_min") && (med ?? 0) < 10 ? 2 : 0)}</td>
                    <td className="num muted">{top?.toFixed(metric.includes("per_min") && (top ?? 0) < 10 ? 2 : 0)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>
      )}
      <section className="panel">
        <h3>Базовые характеристики</h3>
        <table>
          <tbody>
            {Object.entries(hero.stats)
              .filter(([, v]) => v !== null)
              .map(([k, v]) => (
                <tr key={k}>
                  <td>{statLabel(k)}</td>
                  <td className="num">{String(v)}</td>
                </tr>
              ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

const POSITION_SOURCES: Record<string, string> = {
  pro: "про-матчи",
  "public lanes": "линии в публичных матчах",
  "listed roles": "роли героя в игре",
};

export function HeroPage() {
  const { ref = "" } = useParams();
  const [bucket, setBucket] = useState<RankBucket | undefined>(undefined);
  const hero = useHero(ref, bucket);
  const build = useBuild(ref);
  const [tab, setTab] = useState("build");
  if (hero.error) return <ErrorBox error={hero.error} />;
  if (!hero.data) return <Loading what="героя" />;
  const h = hero.data;
  const stats = h.bucket_stats;
  return (
    <>
      <div className="hero-title">
        <Portrait hero={h.id} size={84} wide />
        <div>
          <h1>{h.name}</h1>
          <p className="muted" style={{ margin: 0 }}>
            {h.roles.map((r) => ROLES[r] ?? r).join(", ")}. {ATTACK_TYPES[h.attack_type] ?? h.attack_type}.{" "}
            {stats ? `Винрейт ${pct(stats.wr)}, рейтинговых матчей: ${stats.games.toLocaleString("ru-RU")}.` : ""}{" "}
            {h.aliases.length ? `Также называют: ${h.aliases.join(", ")}.` : ""}
          </p>
        </div>
      </div>
      <div className="tabs" role="tablist">
        {[
          ["build", "Сборка"],
          ["abilities", "Способности"],
          ["matchups", "Матчапы"],
          ["numbers", "Цифры"],
        ].map(([k, label]) => (
          <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k!)}>
            {label}
          </button>
        ))}
      </div>
      {tab === "build" && (build.data ? <BuildTab build={build.data} /> : <ErrorBox error={build.error} />)}
      {tab === "abilities" && <AbilitiesTab hero={h} />}
      {tab === "matchups" && (
        <>
          <div style={{ marginBottom: "1rem" }}>
            <Segmented label="Ранговая группа" value={(bucket ?? h.bucket) as RankBucket} options={BUCKETS.map((b) => ({ value: b.value as RankBucket, label: b.label }))} onChange={setBucket} />
          </div>
          <MatchupsTab hero={h} />
        </>
      )}
      {tab === "numbers" && <NumbersTab hero={h} />}
    </>
  );
}
