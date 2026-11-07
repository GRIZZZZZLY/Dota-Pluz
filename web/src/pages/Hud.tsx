import { useParams } from "react-router-dom";
import { useHud } from "../api/hooks";
import type { Hud } from "../api/types";
import { ItemIcon, Portrait } from "../components/common";

const PLACEHOLDER: Record<string, string> = {
  skill: "Подсказка: что прокачать",
  draft: "Подсказка: кого взять",
  items: "Подсказка: что купить",
};

const MODE: Record<string, string> = {
  setting: "из настроек",
  gold_rate: "по золоту",
  last_game: "как в прошлой игре",
  unknown: "режим не определён",
};

function Skill({ hint }: { hint: NonNullable<Hud["skill"]> }) {
  if (hint.kind === "talent") {
    return (
      <div title={hint.reason}>
        <div className="hud-title">Талант</div>
        <strong>{hint.name}</strong>
        {hint.instead.length > 0 && <div className="muted small">а не {hint.instead.join(", ")}</div>}
      </div>
    );
  }
  return (
    <div title={hint.reason}>
      <div className="hud-title">Прокачать{hint.slot ? `: ${hint.slot}-я способность` : ""}</div>
      <strong>{hint.name}</strong>
    </div>
  );
}

function Draft({ hint }: { hint: NonNullable<Hud["draft"]> }) {
  return (
    <div>
      <div className="hud-title">
        Пик{hint.position ? ` на позицию ${hint.position}` : ""}
        {hint.heroes_known === 0 && <span className="muted"> · героев не видно, запустите run-cv.cmd</span>}
      </div>
      {hint.picks.map((p) => (
        <div key={p.hero} className="hud-row">
          <Portrait hero={p.hero} size={24} />
          <span>
            <strong>{p.name}</strong> <span className="muted small">{p.why}</span>
          </span>
        </div>
      ))}
      {hint.bans.length > 0 && (
        <div className="small">
          <span className="hud-title">Бан:</span> {hint.bans.map((b) => b.name).join(", ")}
        </div>
      )}
    </div>
  );
}

function Items({ hint, hud }: { hint: NonNullable<Hud["items"]>; hud: Hud }) {
  return (
    <div>
      <div className="hud-title">
        {hint.title} <span className="muted">· {hud.mode === "turbo" ? "Turbo" : hud.mode === "normal" ? "обычная" : "?"}, {MODE[hud.mode_source]}</span>
      </div>
      <div className="hud-items">
        {hint.items.map((i) => (
          <ItemIcon key={i.key} itemKey={i.key} link={false} caption={i.detail || " "} />
        ))}
      </div>
      <div className="muted small">{hint.note}</div>
    </div>
  );
}

/** One small overlay widget (`/hud/skill`, `/hud/draft`, `/hud/items`). The overlay shows its window
 *  only while the widget has a hint; the placeholder is what he sees while he moves the widgets. */
export function HudPage() {
  const { widget = "" } = useParams();
  const { data: hud } = useHud();
  const body =
    widget === "skill" && hud?.skill ? <Skill hint={hud.skill} /> :
    widget === "draft" && hud?.draft ? <Draft hint={hud.draft} /> :
    widget === "items" && hud?.items ? <Items hint={hud.items} hud={hud} /> :
    <div className="muted">{PLACEHOLDER[widget] ?? "Неизвестная подсказка"}</div>;
  return <div className="hud">{hud?.source === "demo" && <span className="hud-demo">демо</span>}{body}</div>;
}
