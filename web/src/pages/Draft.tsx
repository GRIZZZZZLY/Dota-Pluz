import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { useCopilotStatus, useDraft, useHeroes, useSettings } from "../api/hooks";
import type { DraftRequest, DraftResponse, HeroListRow, LiveSnapshot, RankBucket, Side, Suggestion, TeamReport } from "../api/types";
import { ErrorBox, HeroChip, ItemIcon, Portrait, Segmented, WinSplit, useHeroMap } from "../components/common";
import { HeroPicker } from "../components/HeroPicker";
import { BUCKETS, POSITION_NAMES, pct, pts } from "../lib/format";
import { useHotkeys } from "../lib/hotkeys";
import { mergeGameDraft, type BoardState } from "../lib/liveDraft";

type Target = "us" | "them" | "ban";

type DraftState = BoardState;

const EMPTY: DraftState = { us: [], them: [], bans: [], side: "radiant" };
const STORE = "d2bg.draft";

function load(): DraftState {
  try {
    const raw = localStorage.getItem(STORE);
    return raw ? { ...EMPTY, ...(JSON.parse(raw) as DraftState) } : EMPTY;
  } catch {
    return EMPTY;
  }
}

function Slots({ heroes, side, ours, positions, selected, onSelect, onRemove }: {
  heroes: number[];
  side: Side;
  ours: boolean;
  positions: Record<string, number> | undefined;
  selected: boolean;
  onSelect: () => void;
  onRemove: (h: number) => void;
}) {
  const heroMap = useHeroMap();
  return (
    <section className={`team ${side}${selected ? " selected" : ""}`} aria-label={side === "radiant" ? "Пики Света" : "Пики Тьмы"}>
      <header>
        <h2 className={side}>{side === "radiant" ? "Свет" : "Тьма"}</h2>
        <button type="button" className="btn small" onClick={onSelect} aria-pressed={selected}>
          {ours ? "Ваша команда" : "Вражеская команда"}
          {selected ? ", добавляем сюда" : ""}
        </button>
      </header>
      <div className="slots">
        {Array.from({ length: 5 }, (_, i) => {
          const h = heroes[i];
          return h ? (
            <button key={h} type="button" className="slot filled" onClick={() => onRemove(h)} title="Убрать">
              <Portrait hero={h} size={40} wide />
              <span>{heroMap.get(h)?.name}</span>
              {positions?.[String(h)] ? <span className="pos">поз. {positions[String(h)]}</span> : null}
            </button>
          ) : (
            <button key={`empty${i}`} type="button" className="slot" onClick={onSelect}>
              <span className="muted small">{selected && i === heroes.length ? "Следующий пик сюда" : "Пусто"}</span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function Why({ s }: { s: Suggestion }) {
  const heroMap = useHeroMap();
  const parts = [
    ...s.why.good_against.map((g) => `сильнее ${heroMap.get(g.hero)?.name ?? g.hero} ${pts(g.value)}`),
    ...s.why.with.map((g) => `вместе с ${heroMap.get(g.hero)?.name ?? g.hero} ${pts(g.value)}`),
    ...s.why.bad_against.slice(0, 1).map((g) => `слаб против ${heroMap.get(g.hero)?.name ?? g.hero} ${pts(g.value)}`),
  ];
  return <>{parts.join(", ") || "Пока нет данных о матчапах против этих пиков"}</>;
}

function SuggestionTable({ rows, onCompare, compare }: { rows: Suggestion[]; onCompare: (h: number) => void; compare: number[] }) {
  if (!rows.length) return <p className="muted">Под эти фильтры ничего не подходит.</p>;
  return (
    <table className="suggest">
      <thead>
        <tr>
          <th>Герой</th>
          <th className="num">Оценка</th>
          <th>Позиции</th>
          <th>Почему</th>
          <th className="num" title="Насколько сильно героя бьют его лучшие контрпики. Чем выше, тем позже его стоит брать.">Риск контрпика</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((s) => (
          <tr key={s.hero}>
            <td>
              <HeroChip hero={s.hero} size={26} />
            </td>
            <td className={`num ${s.score >= 0 ? "good" : "bad"}`}>{pts(s.score, 2)}</td>
            <td className="small">{s.positions.join(", ")}</td>
            <td className="why">
              <Why s={s} />
            </td>
            <td className="num small">{s.counterability.toFixed(1)}</td>
            <td>
              <button type="button" className="btn small" disabled={compare.includes(s.hero) || compare.length >= 3} onClick={() => onCompare(s.hero)}>
                Сравнить
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TeamPanel({ title, report }: { title: string; report: TeamReport }) {
  if (!report.heroes.length) return null;
  return (
    <div>
      <h3>{title}</h3>
      {report.warnings.length ? (
        <ul className="small" style={{ paddingLeft: "1.1rem", margin: "0 0 0.5rem" }}>
          {report.warnings.map((w) => (
            <li key={w} className="bad">
              {w}
            </li>
          ))}
        </ul>
      ) : (
        <p className="small good">Слабых мест не найдено.</p>
      )}
      <p className="small muted">
        Урон: магический {report.damage.magic}, физический {report.damage.physical}, чистый {report.damage.pure}. Ближний бой:{" "}
        {report.melee}, дальний: {report.ranged}. Контроль: {report.disablers.length ? report.disablers.join(", ") : "ни у кого"}.
      </p>
      <div className="row">
        {Object.entries(report.traits).map(([key, t]) => (
          <span key={key} className="tag" title={t.heroes.join(", ")}>
            {t.label} {t.heroes.length}
          </span>
        ))}
      </div>
    </div>
  );
}

function Results({ res, state, onCompare, compare, removeCompare }: {
  res: DraftResponse;
  state: DraftState;
  onCompare: (h: number) => void;
  compare: number[];
  removeCompare: (h: number) => void;
}) {
  const [tab, setTab] = useState("all");
  const heroMap = useHeroMap();
  const rows = tab === "all" ? res.suggestions : (res.by_position[tab] ?? []);
  const usLeft = state.side === "radiant";
  return (
    <div className="stack" style={{ marginTop: "1rem" }}>
      {res.win && (
        <section className="panel win-meter">
          <div className="labels">
            <span className={usLeft ? "radiant" : "dire"}>{usLeft ? `Мы ${pct(res.win.us)}` : `Они ${pct(res.win.them)}`}</span>
            <span className={usLeft ? "dire" : "radiant"}>{usLeft ? `Они ${pct(res.win.them)}` : `Мы ${pct(res.win.us)}`}</span>
          </div>
          <WinSplit left={usLeft ? res.win.us : res.win.them} label="Оценка шанса на победу" />
          <p className="source">
            Оценка модели только по драфту: на проверочных матчах она угадывала победителя в {pct(res.win.held_out_accuracy)} случаев.
            Умение и исполнение решают куда больше, чем это число.
          </p>
        </section>
      )}
      {res.notes.map((n) => (
        <div key={n} className="note">
          {n}
        </div>
      ))}
      <section className="panel">
        <h2>Пики для вас</h2>
          <div className="tabs" role="tablist">
            {["all", "1", "2", "3", "4", "5"].map((t) => (
              <button key={t} type="button" role="tab" aria-selected={tab === t} onClick={() => setTab(t)} title={t === "all" ? "" : POSITION_NAMES[Number(t)]}>
                {t === "all" ? "Любая позиция" : `Поз. ${t}`}
              </button>
            ))}
          </div>
          <SuggestionTable rows={rows} onCompare={onCompare} compare={compare} />
          <p className="source">
            Оценка = средний перевес по винрейту против их пиков плюс вес синергии, умноженный на перевес с вашими пиками, в процентных
            пунктах. Рейтинговых матчей: {res.sample_matches.toLocaleString("ru-RU")}, {res.source_week}, {BUCKETS.find((b) => b.value === res.bucket)?.label}.
          </p>
      </section>
      <div className="grid cols-2">
        <section className="panel">
          <h2>Баны</h2>
          <ul className="small" style={{ listStyle: "none", padding: 0, margin: 0 }}>
            {res.bans.slice(0, 8).map((b) => (
              <li key={b.hero} className="row" style={{ justifyContent: "space-between", padding: "0.2rem 0" }}>
                <HeroChip hero={b.hero} size={24} />
                <span className="muted">
                  {b.beats.length ? `сильнее ${b.beats.map((x) => heroMap.get(x.hero)?.name).join(", ")}, ` : ""}
                  винрейт {pct(b.wr)}
                </span>
              </li>
            ))}
          </ul>
          {res.hot_counters.length > 0 && (
            <>
              <h3 style={{ marginTop: "1rem" }}>Контрпики к двум и более их героям</h3>
              <div className="row">
                {res.hot_counters.slice(0, 8).map((h) => (
                  <HeroChip key={h.hero} hero={h.hero} size={24} extra={<span className="muted small">×{h.enemies.length}</span>} />
                ))}
              </div>
            </>
          )}
        </section>
        {Object.keys(res.counters).length > 0 && (
          <section className="panel">
            <h2>Контрпики к каждому врагу</h2>
            {Object.entries(res.counters).map(([enemy, list]) => (
              <div key={enemy} style={{ marginBottom: "0.6rem" }}>
                <HeroChip hero={Number(enemy)} size={26} />
                <div className="row small" style={{ marginTop: "0.3rem" }}>
                  {list.slice(0, 5).map((c) => (
                    <span key={c.hero} className="tag" title={`${pts(c.edge)} п. п.`}>
                      {heroMap.get(c.hero)?.name}
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </section>
        )}
      </div>
      {compare.length > 0 && (
        <section className="panel">
          <h2>Сравнение</h2>
          <table>
            <thead>
              <tr>
                <th>Герой</th>
                <th className="num">Оценка</th>
                <th>Почему</th>
                <th className="num">Риск контрпика</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {res.compare.map((s) => (
                <tr key={s.hero}>
                  <td>
                    <HeroChip hero={s.hero} size={26} />
                  </td>
                  <td className="num">{pts(s.score, 2)}</td>
                  <td className="small muted">
                    <Why s={s} />
                  </td>
                  <td className="num">{s.counterability.toFixed(1)}</td>
                  <td>
                    <button type="button" className="btn small" onClick={() => removeCompare(s.hero)}>
                      Убрать
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
      <div className="grid cols-2">
        <section className="panel">
          <TeamPanel title="Ваша команда" report={res.ours} />
          <div style={{ height: "1rem" }} />
          <TeamPanel title="Их команда" report={res.theirs} />
          {!res.ours.heroes.length && !res.theirs.heroes.length && <p className="muted">Выберите героев, чтобы увидеть слабые места команд.</p>}
        </section>
        <section className="panel">
          <h2>Линии</h2>
          {res.lanes.length ? (
            <table>
              <thead>
                <tr>
                  <th>Ваша линия</th>
                  <th>Мы</th>
                  <th>Они</th>
                  <th className="num">Перевес</th>
                </tr>
              </thead>
              <tbody>
                {res.lanes.map((l) => (
                  <tr key={l.lane}>
                    <td>{l.lane === "safe" ? "Лёгкая линия" : l.lane === "mid" ? "Мид" : "Сложная линия"}</td>
                    <td className="small">{l.ours.map((h) => heroMap.get(h)?.name).join(", ") || "–"}</td>
                    <td className="small">{l.theirs.map((h) => heroMap.get(h)?.name).join(", ") || "–"}</td>
                    <td className={`num ${l.advantage >= 0 ? "good" : "bad"}`} title={`Данные есть для ${l.pairs_known} из ${l.pairs_total} пар`}>
                      {pts(l.advantage)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">Добавьте героев в обе команды, чтобы увидеть линии. Позиции угаданы по про-матчам, цифры примерные.</p>
          )}
        </section>
      </div>
      {res.items.length > 0 && (
        <section className="panel">
          <h2>Предметы против их драфта</h2>
          <div className="grid cols-2">
            {res.items.map((rule) => (
              <div key={rule.id}>
                <p className="small" style={{ marginBottom: "0.3rem" }}>
                  <strong>{rule.reason_ru || rule.reason}</strong> <span className="muted">({rule.heroes.join(", ")})</span>
                </p>
                <div className="order">
                  {rule.items.map((i) => (
                    <ItemIcon key={i.key} itemKey={i.key} />
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

/** Says what came from the game so far, and plainly what Dota does not send a player. */
function GameStatus({ live }: { live: LiveSnapshot | null }) {
  const { data: copilot } = useCopilotStatus();
  const draft = live?.draft;
  if (!live || !draft || !live.connection.connected) {
    return (
      <p className="note" style={{ marginBottom: "1rem" }}>
        Сейчас данных из игры нет. Во время игры ваш герой, ваша команда и баны заполнятся здесь сами. Dota не передаёт игроку
        остальные пики во время драфта, поэтому введите их вручную.
      </p>
    );
  }
  const found = Object.values(draft.sources ?? {});
  return (
    <section className="panel" style={{ marginBottom: "1rem" }} aria-label="Из игры">
      <p className="small" style={{ margin: 0 }}>
        <span className="dot on" />
        Из игры{live.demo ? " (демо)" : ""}: {found.length ? found.join("; ") : "пока ничего; ваш герой появится, когда вы его выберете"}.
      </p>
      {draft.note && (
        <p className="small muted" style={{ margin: "0.4rem 0 0" }}>
          {draft.note}
        </p>
      )}
      <p className="small muted" style={{ margin: "0.4rem 0 0" }}>
        {copilot?.screen_reader?.running
          ? "Чтение экрана драфта работает: пики врагов и союзников добавятся сами."
          : "Чтение экрана драфта не запущено. Чтобы пики заполнялись сами, запустите run-cv.cmd в папке приложения."}
      </p>
      {!!draft.screen?.unknown && (
        <p className="note" style={{ margin: "0.4rem 0 0" }}>
          {"? ".repeat(draft.screen.unknown).trim()}: не распознано с экрана {draft.screen.unknown}. Добавьте этих героев вручную, приложение
          не угадывает.
        </p>
      )}
    </section>
  );
}

export function DraftPage({ live }: { live: LiveSnapshot | null }) {
  const { data: heroes } = useHeroes();
  const { data: settings } = useSettings();
  const [state, setState] = useState<DraftState>(load);
  // Whatever the game sends (his hero and team, the bans, and after loading the minimap's heroes) fills
  // the board by itself; his own edits stay. Synced while rendering, React's pattern for outside data.
  const liveDraft = live?.draft;
  const liveKey = liveDraft
    ? JSON.stringify([live?.match_id, liveDraft.allies, liveDraft.enemies, liveDraft.bans, liveDraft.side])
    : null;
  const [syncedKey, setSyncedKey] = useState<string | null>(null);
  if (liveDraft && liveKey !== syncedKey) {
    setSyncedKey(liveKey);
    setState((s) => mergeGameDraft(s, liveDraft, live?.match_id ?? null));
  }
  const [history, setHistory] = useState<DraftState[]>([]);
  const [target, setTarget] = useState<Target>("them");
  const [bucket, setBucket] = useState<RankBucket | null>(null);
  const [weight, setWeight] = useState<number | null>(null);
  const [compare, setCompare] = useState<number[]>([]);
  const [paste, setPaste] = useState("");
  const [pasteMsg, setPasteMsg] = useState("");
  const search = useRef<HTMLInputElement>(null);

  useEffect(() => {
    try {
      localStorage.setItem(STORE, JSON.stringify(state));
    } catch {
      // the draft just won't survive a reload
    }
  }, [state]);

  // During a match his board is the correction the Copilot uses: heroes he removed stop counting.
  const liveMatch = live?.match_id ?? null;
  useEffect(() => {
    if (!state.edited || !state.matchId || state.matchId !== liveMatch) return;
    const onBoard = new Set([...state.us, ...state.them, ...state.bans]);
    // Only heroes this board saw from the game and he took off: a hero reported since is not removed.
    const removed = (state.fromGame ?? []).filter((h) => !onBoard.has(h));
    const timer = setTimeout(() => {
      api
        .post("/api/copilot/draft/manual", { match_id: state.matchId, allies: state.us, enemies: state.them, bans: state.bans, removed })
        .catch(() => undefined); // the board still works without the Copilot
    }, 400);
    return () => clearTimeout(timer);
  }, [state.edited, state.matchId, state.us, state.them, state.bans, state.fromGame, liveMatch]);

  const update = (next: DraftState) => {
    setHistory((h) => [...h.slice(-30), state]);
    setState({ ...next, edited: true });
  };
  const taken = useMemo(() => new Set([...state.us, ...state.them, ...state.bans]), [state]);

  const add = (h: HeroListRow) => {
    if (taken.has(h.id)) return;
    if (target === "ban") update({ ...state, bans: [...state.bans, h.id] });
    else if (target === "us" && state.us.length < 5) update({ ...state, us: [...state.us, h.id] });
    else if (target === "them" && state.them.length < 5) update({ ...state, them: [...state.them, h.id] });
  };
  const remove = (h: number) =>
    update({ ...state, us: state.us.filter((x) => x !== h), them: state.them.filter((x) => x !== h), bans: state.bans.filter((x) => x !== h) });

  const keys = useMemo(
    () => ({
      "/": () => search.current?.focus(),
      Tab: () => setTarget((t) => (t === "us" ? "them" : "us")),
      b: () => setTarget("ban"),
      Backspace: () => {
        const last = history[history.length - 1];
        if (!last) return;
        setState(last);
        setHistory(history.slice(0, -1));
      },
    }),
    [history],
  );
  useHotkeys(keys);

  const canFill = !!liveDraft && (liveDraft.allies.length > 0 || liveDraft.enemies.length > 0 || liveDraft.bans.length > 0);
  const fillFromGame = () => {
    if (!liveDraft) return;
    update(mergeGameDraft({ ...EMPTY }, liveDraft, live?.match_id ?? null));
  };

  const req: DraftRequest = {
    allies: state.us,
    enemies: state.them,
    bans: state.bans,
    side: state.side,
    rank_bucket: bucket ?? settings?.rank_bucket ?? "all",
    synergy_weight: weight ?? settings?.synergy_weight ?? 0.5,
    compare,
    n: 15,
  };
  const { data, error, isFetching } = useDraft(req, !!heroes);

  const copyText = () => {
    const name = (id: number) => heroes?.find((h) => h.id === id)?.name ?? String(id);
    const text = `Мы: ${state.us.map(name).join(", ")}\nОни: ${state.them.map(name).join(", ")}${state.bans.length ? `\nБаны: ${state.bans.map(name).join(", ")}` : ""}`;
    void navigator.clipboard?.writeText(text);
  };
  const applyPaste = async () => {
    const res = await api.post<{ heroes: HeroListRow[]; unknown: string[] }>("/api/heroes/parse", { text: paste });
    const ids = res.heroes.map((h) => h.id).filter((id) => !taken.has(id));
    if (target === "ban") update({ ...state, bans: [...state.bans, ...ids] });
    else if (target === "us") update({ ...state, us: [...state.us, ...ids].slice(0, 5) });
    else update({ ...state, them: [...state.them, ...ids].slice(0, 5) });
    setPasteMsg(res.unknown.length ? `Не распознано: ${res.unknown.join(", ")}` : `Добавлено: ${ids.length}`);
    setPaste("");
  };

  const ourSide = state.side;
  const radiantIsUs = ourSide === "radiant";
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Драфт</h1>
          <p>Ваш герой, ваша команда и баны заполняются из игры сами. Остальные пики вводите по ходу драфта.</p>
        </div>
        <div className="row">
          {canFill && (
            <button className="btn primary" type="button" onClick={fillFromGame}>
              Сбросить на драфт из игры
            </button>
          )}
          <button className="btn" type="button" onClick={() => update({ ...state, side: radiantIsUs ? "dire" : "radiant" })}>
            Поменять стороны
          </button>
          <button className="btn" type="button" onClick={copyText}>
            Копировать текстом
          </button>
          <button className="btn danger" type="button" onClick={() => update(EMPTY)}>
            Очистить
          </button>
        </div>
      </div>
      <GameStatus live={live} />

      <div className="board">
        <Slots
          heroes={radiantIsUs ? state.us : state.them}
          side="radiant"
          ours={radiantIsUs}
          positions={radiantIsUs ? data?.positions.ours : data?.positions.theirs}
          selected={target === (radiantIsUs ? "us" : "them")}
          onSelect={() => setTarget(radiantIsUs ? "us" : "them")}
          onRemove={remove}
        />
        <div className="river" aria-hidden="true" />
        <Slots
          heroes={radiantIsUs ? state.them : state.us}
          side="dire"
          ours={!radiantIsUs}
          positions={radiantIsUs ? data?.positions.theirs : data?.positions.ours}
          selected={target === (radiantIsUs ? "them" : "us")}
          onSelect={() => setTarget(radiantIsUs ? "them" : "us")}
          onRemove={remove}
        />
      </div>
      <div className="bans" aria-label="Баны">
        <button type="button" className="btn small" aria-pressed={target === "ban"} onClick={() => setTarget("ban")}>
          {target === "ban" ? "Добавляем баны" : "Добавить баны"}
        </button>
        {state.bans.map((b) => (
          <button key={b} type="button" className="ban" onClick={() => remove(b)} title="Убрать бан">
            <Portrait hero={b} size={30} />
          </button>
        ))}
      </div>

      <div className="row" style={{ marginTop: "1rem", justifyContent: "space-between" }}>
        <Segmented
          label="Ранговая группа"
          value={(bucket ?? settings?.rank_bucket ?? "all") as RankBucket}
          options={BUCKETS.map((b) => ({ value: b.value as RankBucket, label: b.label }))}
          onChange={setBucket}
        />
        <label className="row small">
          Вес синергии
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={weight ?? settings?.synergy_weight ?? 0.5}
            onChange={(e) => setWeight(Number(e.target.value))}
          />
          {(weight ?? settings?.synergy_weight ?? 0.5).toFixed(2)}
        </label>
      </div>

      {heroes && (
        <HeroPicker
          ref={search}
          heroes={heroes}
          taken={taken}
          onPick={add}
          onTab={() => setTarget((t) => (t === "us" ? "them" : "us"))}
          placeholder={`Добавить в ${target === "ban" ? "баны" : target === "us" ? "вашу команду" : "вражескую команду"}: введите am, qop, pudge… и Enter (/ — к поиску, Tab — сменить команду)`}
        />
      )}
      <details style={{ marginTop: "0.75rem" }}>
        <summary className="small muted">Вставить список героев</summary>
        <div className="row" style={{ marginTop: "0.5rem" }}>
          <textarea className="input" rows={2} value={paste} onChange={(e) => setPaste(e.target.value)} placeholder="am, lion, cm" />
          <button className="btn" type="button" onClick={() => void applyPaste()} disabled={!paste.trim()}>
            Добавить в {target === "ban" ? "баны" : target === "us" ? "вашу команду" : "вражескую команду"}
          </button>
          <span className="small muted">{pasteMsg}</span>
        </div>
      </details>

      <ErrorBox error={error} />
      {isFetching && !data ? <p className="muted">Считаем подсказки…</p> : null}
      {data && (
        <Results
          res={data}
          state={state}
          compare={compare}
          onCompare={(h) => setCompare((c) => (c.includes(h) ? c : [...c, h].slice(0, 3)))}
          removeCompare={(h) => setCompare((c) => c.filter((x) => x !== h))}
        />
      )}
    </>
  );
}
