import { Link } from "react-router-dom";
import { useSettings } from "../api/hooks";
import { CopilotPanel } from "../components/CopilotPanel";
import { useSpeakAlerts } from "../lib/voice";
import { AlertList, TimerColumn, type LiveState } from "./Live";

/** A narrow view for a second monitor, a phone, or the always-on-top window (`d2bg window`).
 *  The Copilot panel carries the next skill, the next items and the buyback guard; the Live page keeps the full lists. */
export function CompactPage({ live }: { live: LiveState }) {
  const { snap } = live;
  const { data: settings } = useSettings();
  useSpeakAlerts(snap?.alerts, settings?.timers.voice ?? true);
  if (!snap || snap.phase === "waiting") {
    return (
      <div className="compact">
        <p className="muted">Ждём Dota. <Link to="/">Открыть полную версию</Link></p>
      </div>
    );
  }
  return (
    <div className="compact stack">
      <CopilotPanel snap={snap} />
      <TimerColumn snap={snap} compact />
      <AlertList snap={snap} limit={6} />
    </div>
  );
}
