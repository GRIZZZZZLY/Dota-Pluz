import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import { useDataStatus, useGsiStatus, useRecordings, useSettings } from "../api/hooks";
import type { LiveSnapshot } from "../api/types";
import { Bar, ErrorBox, Loading } from "../components/common";
import { dateTime } from "../lib/format";

function Gsi({ live }: { live: LiveSnapshot | null }) {
  const [path, setPath] = useState("");
  const { data: st, refetch } = useGsiStatus(path || undefined);
  const { data: settings } = useSettings();
  const [msg, setMsg] = useState<string>("");
  const [error, setError] = useState<unknown>(null);
  const act = async (what: "install" | "remove") => {
    setError(null);
    try {
      const res = await api.post<{ path?: string; removed?: boolean }>(`/api/gsi/${what}`, { path: path || null });
      setMsg(what === "install" ? `Записано в ${res.path}. Если Dota 2 открыта, перезапустите её.` : res.removed ? "Удалено." : "Удалять было нечего.");
      void refetch();
    } catch (e) {
      setError(e);
    }
  };
  const gotPackets = (st?.connection.packets ?? 0) > 0 && st?.connection.source === "game";
  return (
    <section className="panel">
      <h2>Подключение Dota 2</h2>
      {!st ? (
        <Loading what="состояния подключения" />
      ) : (
        <ol className="steps">
          <li className={st.dota_found ? "done" : ""}>
            <h3>Найти Dota 2</h3>
            {st.dota_found ? (
              <p className="small">Найдена: {st.dota_path}.</p>
            ) : (
              <p className="small">В списке библиотек Steam не найдена. Вставьте путь к папке «dota 2 beta»:</p>
            )}
            <input className="input" style={{ width: "100%" }} value={path} onChange={(e) => setPath(e.target.value)} placeholder="D:\SteamLibrary\steamapps\common\dota 2 beta" aria-label="Папка Dota 2" />
          </li>
          <li className={st.installed && st.current ? "done" : ""}>
            <h3>Установить конфиг GSI (Game State Integration)</h3>
            <p className="small">
              Записывается один файл, <code>gamestate_integration_d2bg.cfg</code>, в папку Dota{" "}
              <code>cfg\gamestate_integration</code>. Это штатный способ Valve дать программе слушать игру; больше ничего не меняется. Подробнее в{" "}
              <a href="https://github.com/Tajaddin/dota2-build-generator/blob/main/docs/SAFETY.md" target="_blank" rel="noreferrer">
                SAFETY.md
              </a>
              .
            </p>
            <div className="row">
              <button className="btn primary" type="button" disabled={!st.dota_found && !path} onClick={() => void act("install")}>
                {st.installed ? (st.current ? "Переустановить" : "Обновить конфиг") : "Установить"}
              </button>
              {st.installed && (
                <button className="btn danger" type="button" onClick={() => void act("remove")}>
                  Удалить
                </button>
              )}
              <span className="small muted">{msg}</span>
            </div>
            <ErrorBox error={error} />
          </li>
          <li className={gotPackets ? "done" : ""}>
            <h3>Запустить Dota 2 и дождаться первого обновления</h3>
            {gotPackets ? (
              <p className="small good">Данные приходят, обновлений получено: {st.connection.packets}. Всё готово.</p>
            ) : (
              <p className="small">
                Пока ничего не получено. Обновления начнут приходить, когда Dota запущена. Если через минуту ничего нет, сами
                добавьте <code>{st.launch_option_hint}</code> в параметры запуска Dota в Steam (Библиотека, Dota 2, Свойства,
                Параметры запуска). Приложение никогда не меняет параметры запуска.
              </p>
            )}
          </li>
          <li className={settings?.account_id ? "done" : ""}>
            <h3>Ваш аккаунт</h3>
            <p className="small">
              {settings?.account_id ? (
                <>Аккаунт {settings.account_id}. Он используется для профиля и разборов после игры.</>
              ) : (
                <>
                  Заполнится после первой игры, или введите его в <Link to="/settings">настройках</Link>.
                </>
              )}
            </p>
          </li>
        </ol>
      )}
      {live?.connection.blocks.length ? (
        <p className="source">Блоки данных, которые прислала игра: {live.connection.blocks.join(", ")}.</p>
      ) : null}
    </section>
  );
}

function Data() {
  const [poll, setPoll] = useState(false);
  const { data, refetch } = useDataStatus(poll);
  const [error, setError] = useState<unknown>(null);
  const running = data?.refresh.running ?? false;
  if (poll && data && !running) setPoll(false);
  const start = async (steps?: string[]) => {
    setError(null);
    try {
      await api.post("/api/data/refresh", { steps });
      setPoll(true);
      void refetch();
    } catch (e) {
      setError(e);
    }
  };
  if (!data) return <Loading what="состояния данных" />;
  const prog = data.refresh.progress;
  return (
    <section className="panel">
      <h2>Данные</h2>
      <p className="small">
        Приложение поставляется со снимком данных, поэтому работает офлайн. Обновление данных берёт свежие цифры из OpenDota: около
        650 запросов и 15 минут на всё. Бесплатный лимит около 3000 запросов в день.
      </p>
      <p className="small">
        Запросов к OpenDota сегодня: <strong>{data.usage.requests_today}</strong>
        {data.usage.remaining_day !== null ? `, осталось на сегодня: ${data.usage.remaining_day}` : ""}
        {data.usage.has_api_key ? " (с вашим API-ключом)" : ""}.
      </p>
      <div className="row">
        <button className="btn primary" type="button" disabled={running} onClick={() => void start()}>
          Обновить всё
        </button>
        <button className="btn" type="button" disabled={running} onClick={() => void start(["constants", "hero_stats"])}>
          Быстрое обновление (только мета)
        </button>
        <button className="btn" type="button" disabled={running} onClick={() => void start(["turbo"])}>
          Собрать игры Turbo сейчас
        </button>
      </div>
      <ErrorBox error={error} />
      {running && prog.step && (
        <div style={{ marginTop: "0.75rem" }}>
          <p className="small">
            {prog.step}: {prog.message} ({prog.done}/{prog.total})
          </p>
          <Bar value={(prog.done ?? 0) / Math.max(prog.total ?? 1, 1)} label="Ход обновления" />
        </div>
      )}
      {data.refresh.error && <div className="error">Обновление остановлено: {data.refresh.error}</div>}
      {data.refresh.results.length > 0 && (
        <p className="small muted">
          Последнее обновление: {data.refresh.results.map((r) => `${r.step}: строк ${r.rows}, запросов ${r.calls}`).join("; ")}.
        </p>
      )}
      <table style={{ marginTop: "0.75rem" }}>
        <thead>
          <tr>
            <th>Файл</th>
            <th>Откуда</th>
            <th>Обновлён</th>
            <th className="num">Строк</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(data.files).map(([name, f]) => (
            <tr key={name}>
              <td className="small">{name}</td>
              <td className="small muted" title={f.source}>
                {f.present ? `${f.location === "refreshed" ? "Ваше обновление" : "Встроенный снимок"}: ${f.source ?? ""}` : "Нет файла"}
              </td>
              <td className="small">{dateTime(f.generated_at)}</td>
              <td className="num small">{f.rows?.toLocaleString("ru-RU") ?? "–"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Recordings() {
  const { data } = useRecordings();
  const [error, setError] = useState<unknown>(null);
  const play = async (name: string) => {
    try {
      await api.post("/api/replay", { name, speed: 8 });
    } catch (e) {
      setError(e);
    }
  };
  return (
    <section className="panel">
      <h2>Записи и демо</h2>
      <p className="small">
        Каждая игра записывается на этом компьютере, чтобы её можно было воспроизвести на странице «Матч». Отключается в
        настройках.
      </p>
      <button className="btn" type="button" onClick={() => void api.post("/api/demo", { hero: "juggernaut", speed: 8 })}>
        Запустить демо-матч
      </button>
      <ErrorBox error={error} />
      <table style={{ marginTop: "0.75rem" }}>
        <tbody>
          {(data ?? []).map((r) => (
            <tr key={r.name}>
              <td className="small">{r.name}</td>
              <td className="small muted">{dateTime(r.modified)}</td>
              <td className="num small">{Math.round(r.bytes / 1024)} КБ</td>
              <td>
                <button className="btn small" type="button" onClick={() => void play(r.name)}>
                  Воспроизвести запись на 8×
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {data && !data.length && <p className="small muted">Записей пока нет.</p>}
    </section>
  );
}

export function SetupPage({ live }: { live: LiveSnapshot | null }) {
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Подключение</h1>
          <p>Подключите игру один раз, обновляйте данные и воспроизводите прошлые игры.</p>
        </div>
      </div>
      <div className="stack">
        <div className="grid cols-2">
          <Gsi live={live} />
          <Recordings />
        </div>
        <Data />
      </div>
    </>
  );
}
