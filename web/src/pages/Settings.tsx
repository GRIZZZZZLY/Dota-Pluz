import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useHeroes, useSaveSettings, useSettings, useVersion } from "../api/hooks";
import type { Settings } from "../api/types";
import { ErrorBox, HeroChip, Loading, Segmented } from "../components/common";
import { HeroPicker } from "../components/HeroPicker";
import { BUCKETS } from "../lib/format";

function HeroList({ label, ids, onChange }: { label: string; ids: number[]; onChange: (ids: number[]) => void }) {
  const { data: heroes } = useHeroes();
  const [open, setOpen] = useState(false);
  return (
    <div>
      <h3>{label}</h3>
      <div className="row">
        {ids.map((id) => (
          <button key={id} type="button" className="btn small" onClick={() => onChange(ids.filter((x) => x !== id))} title="Убрать">
            <HeroChip hero={id} size={20} link={false} />
          </button>
        ))}
        <button className="btn small" type="button" onClick={() => setOpen((o) => !o)}>
          {open ? "Готово" : "Добавить героев"}
        </button>
      </div>
      {open && heroes && <HeroPicker heroes={heroes} taken={new Set(ids)} onPick={(h) => onChange([...ids, h.id])} />}
    </div>
  );
}

export function SettingsPage() {
  const { data: settings, error } = useSettings();
  const { data: version } = useVersion();
  const save = useSaveSettings();
  const [timerRules, setTimerRules] = useState<{ id: string; label: string; default_on: boolean; cite: string }[]>([]);
  const [account, setAccount] = useState<string | null>(null); // null: show the saved value
  const [key, setKey] = useState("");

  useEffect(() => {
    void api.get<{ rules: { id: string; label: string; default_on: boolean; cite: string }[] }>("/api/timers").then((r) => setTimerRules(r.rules));
  }, []);

  if (error) return <ErrorBox error={error} />;
  if (!settings) return <Loading what="настроек" />;
  const set = (changes: Partial<Settings>) => save.mutate(changes);
  const accountText = account ?? (settings.account_id ? String(settings.account_id) : "");

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Настройки</h1>
          <p>Хранятся на этом компьютере в {version?.user_dir ?? "папке пользователя"}. Изменения применяются сразу.</p>
        </div>
      </div>
      <ErrorBox error={save.error} />
      <div className="grid cols-2">
        <section className="panel stack">
          <div>
            <h3>ID аккаунта Steam</h3>
            <div className="row">
              <input className="input" value={accountText} onChange={(e) => setAccount(e.target.value.replace(/\D/g, ""))} placeholder="например, 123456789" aria-label="ID аккаунта" />
              <button className="btn" type="button" onClick={() => set({ account_id: accountText ? Number(accountText) : null })}>
                Сохранить аккаунт
              </button>
            </div>
            <p className="small muted">Число из профиля Dota или из адреса OpenDota (32-битный ID аккаунта).</p>
          </div>
          <div>
            <h3>Ранговая группа для советов</h3>
            <Segmented label="Ранговая группа" value={settings.rank_bucket} onChange={(v) => set({ rank_bucket: v })} options={BUCKETS.map((b) => ({ value: b.value, label: b.label }))} />
          </div>
          <div>
            <h3>Вес синергии ({settings.synergy_weight.toFixed(2)})</h3>
            <input type="range" min={0} max={1} step={0.05} value={settings.synergy_weight} onChange={(e) => set({ synergy_weight: Number(e.target.value) })} aria-label="Вес синергии" />
            <p className="small muted">0: пики оцениваются только по игре против врагов; 1: синергия с вашей командой учитывается полностью.</p>
          </div>
          <div>
            <h3>Пул героев</h3>
            <Segmented
              label="Режим пула героев"
              value={settings.pool_mode}
              onChange={(v) => set({ pool_mode: v })}
              options={[
                { value: "off", label: "Не учитывать" },
                { value: "boost", label: "Предпочитать моих героев" },
                { value: "only", label: "Только мои герои" },
              ]}
            />
          </div>
          <HeroList label="Мои герои" ids={settings.hero_pool} onChange={(ids) => set({ hero_pool: ids })} />
          <HeroList label="Никогда не предлагать" ids={settings.blacklist} onChange={(ids) => set({ blacklist: ids })} />
        </section>
        <section className="panel stack">
          <div>
            <h3>Таймеры</h3>
            {timerRules.map((r) => {
              const on = settings.timers.enabled[r.id] ?? r.default_on;
              return (
                <label key={r.id} className="check small" title={r.cite}>
                  <input type="checkbox" checked={on} onChange={(e) => set({ timers: { ...settings.timers, enabled: { ...settings.timers.enabled, [r.id]: e.target.checked } } })} />
                  {r.label}
                </label>
              );
            })}
            <label className="check small" style={{ marginTop: "0.5rem" }}>
              <input type="checkbox" checked={settings.timers.voice} onChange={(e) => set({ timers: { ...settings.timers, voice: e.target.checked } })} />
              Голосовые подсказки (голос также нужно один раз включить на странице «Матч»: браузеру нужен клик)
            </label>
          </div>
          <div>
            <h3>После каждой игры</h3>
            <label className="check small">
              <input type="checkbox" checked={settings.auto_post_game} onChange={(e) => set({ auto_post_game: e.target.checked })} />
              Загружать матч из OpenDota после окончания (несколько запросов на игру)
            </label>
            <label className="check small">
              <input type="checkbox" checked={settings.request_parse} onChange={(e) => set({ request_parse: e.target.checked })} />
              Также просить OpenDota разобрать реплей (даёт тайминги предметов)
            </label>
            <label className="check small">
              <input type="checkbox" checked={settings.record_gsi} onChange={(e) => set({ record_gsi: e.target.checked })} />
              Записывать игры на этом компьютере для воспроизведения (хранятся последние, не больше {settings.keep_recordings})
            </label>
            <label className="check small">
              <input type="checkbox" checked={settings.turbo_collect} onChange={(e) => set({ turbo_collect: e.target.checked })} />
              Раз в день собирать игры Turbo сильных игроков (Божество и выше) для сборок Turbo: около 900 запросов к OpenDota
            </label>
            <label className="small">
              Сборки для режима{" "}
              <select className="input" value={settings.game_mode} onChange={(e) => set({ game_mode: e.target.value as typeof settings.game_mode })}>
                <option value="auto">определять сам (по золоту в первые секунды после горна)</option>
                <option value="turbo">всегда Turbo</option>
                <option value="normal">всегда обычная игра</option>
              </select>
            </label>
          </div>
          <div>
            <h3>API-ключ OpenDota (необязательно)</h3>
            <div className="row">
              <input className="input" type="password" value={key} onChange={(e) => setKey(e.target.value)} placeholder={settings.opendota_api_key ? "Ключ сохранён" : "Вставьте ключ"} aria-label="API-ключ OpenDota" />
              <button className="btn" type="button" disabled={!key} onClick={() => { set({ opendota_api_key: key }); setKey(""); }}>
                Сохранить ключ
              </button>
              {settings.opendota_api_key && (
                <button className="btn danger" type="button" onClick={() => set({ opendota_api_key: null })}>
                  Удалить ключ
                </button>
              )}
            </div>
            <p className="small muted">Повышает лимиты OpenDota. Создайте ключ сами на opendota.com; он хранится только на этом компьютере.</p>
          </div>
          <div>
            <h3>Оформление</h3>
            <Segmented label="Тема" value={settings.theme} onChange={(v) => set({ theme: v })} options={[{ value: "dark", label: "Тёмная" }, { value: "light", label: "Светлая" }]} />
          </div>
          <div>
            <h3>Телефон или второй экран</h3>
            <p className="small">
              Откройте <code>/compact</code>: это компактный вид с таймерами и следующим предметом. Чтобы открыть его с телефона в
              вашей Wi-Fi-сети, запустите приложение в режиме локальной сети: <code>.\run.cmd --lan</code>; оно выведет адрес с
              токеном доступа.
            </p>
          </div>
        </section>
      </div>
    </>
  );
}
