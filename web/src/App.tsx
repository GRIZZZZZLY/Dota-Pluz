import { useEffect, useMemo, useState } from "react";
import { NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { useLive, useSettings, useVersion } from "./api/hooks";
import { useHotkeys } from "./lib/hotkeys";
import { CompactPage } from "./pages/Compact";
import { DraftPage } from "./pages/Draft";
import { HeroPage } from "./pages/Hero";
import { HeroesPage } from "./pages/Heroes";
import { ItemPage, ItemsPage } from "./pages/Items";
import { LivePage } from "./pages/Live";
import { MatchPage } from "./pages/Match";
import { MetaPage } from "./pages/Meta";
import { ProfilePage } from "./pages/Profile";
import { ReviewPage } from "./pages/Review";
import { SettingsPage } from "./pages/Settings";
import { SetupPage } from "./pages/Setup";

const NAV = [
  { to: "/", label: "Матч", key: "1" },
  { to: "/draft", label: "Драфт", key: "2" },
  { to: "/heroes", label: "Герои", key: "3" },
  { to: "/items", label: "Предметы", key: "4" },
  { to: "/meta", label: "Мета", key: "5" },
  { to: "/profile", label: "Профиль", key: "6" },
  { to: "/match", label: "Матчи", key: "7" },
  { to: "/review", label: "Разбор", key: "0" },
  { to: "/setup", label: "Подключение", key: "8" },
  { to: "/settings", label: "Настройки", key: "9" },
] as const;

function Shortcuts({ onClose }: { onClose: () => void }) {
  return (
    <div className="panel kbd-help" role="dialog" aria-label="Горячие клавиши">
      <h3>Горячие клавиши</h3>
      <p className="small">1–9 и 0 переключают страницы. В драфте: / поиск, Enter добавить, Tab сменить команду, B бан, Backspace отменить. На странице «Матч»: R Рошан убит, T Tormentor убит, A Аегис взят. ? показывает эту подсказку.</p>
      <button className="btn" type="button" onClick={onClose}>
        Закрыть
      </button>
    </div>
  );
}

export function App() {
  const location = useLocation();
  const navigate = useNavigate();
  const { data: settings } = useSettings();
  const { data: version } = useVersion();
  const live = useLive();
  const [help, setHelp] = useState(false);

  useEffect(() => {
    document.documentElement.dataset.theme = settings?.theme ?? "dark";
  }, [settings?.theme]);

  const keys = useMemo(() => {
    const map: Record<string, () => void> = { "?": () => setHelp((h) => !h), Escape: () => setHelp(false) };
    for (const n of NAV) map[n.key] = () => navigate(n.to);
    return map;
  }, [navigate]);
  useHotkeys(keys);

  if (location.pathname.startsWith("/compact")) return <CompactPage live={live} />;

  const conn = live.snap?.connection;
  return (
    <div className="shell">
      <nav className="nav" aria-label="Главное меню">
        <div className="brand">
          d2bg
          <small>Помощник для Dota 2, патч {version?.patch ?? "…"}</small>
        </div>
        {NAV.map((n) => (
          <NavLink key={n.to} to={n.to} end={n.to === "/"} className={({ isActive }) => (isActive ? "active" : undefined)}>
            {n.label}
            <kbd>{n.key}</kbd>
          </NavLink>
        ))}
        <div className="status" aria-live="polite">
          <span className={`dot ${conn?.connected ? "on" : live.online ? "" : "off"}`} />
          {!live.online ? "Сервер приложения недоступен" : conn?.connected ? (conn.source === "game" ? "Получаем данные игры" : conn.source === "demo" ? "Идёт демо-матч" : conn.source === "replay" ? "Воспроизводим запись" : `Источник: ${conn.source}`) : "Ждём Dota"}
        </div>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<LivePage live={live} />} />
          <Route path="/draft" element={<DraftPage live={live.snap} />} />
          <Route path="/heroes" element={<HeroesPage />} />
          <Route path="/heroes/:ref" element={<HeroPage />} />
          <Route path="/items" element={<ItemsPage />} />
          <Route path="/items/:key" element={<ItemPage />} />
          <Route path="/meta" element={<MetaPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="/match" element={<MatchPage />} />
          <Route path="/match/:id" element={<MatchPage />} />
          <Route path="/review" element={<ReviewPage />} />
          <Route path="/review/:id" element={<ReviewPage />} />
          <Route path="/setup" element={<SetupPage live={live.snap} />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="*" element={<p>Здесь ничего нет. Выберите страницу слева.</p>} />
        </Routes>
      </main>
      {help && <Shortcuts onClose={() => setHelp(false)} />}
    </div>
  );
}
