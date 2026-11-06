import type { CopilotStatus, Recommendation } from "../api/types";

const ORDER = ["SKILL_LEVEL", "TALENT", "ITEM_NEXT", "ITEM_BUYBACK_GUARD", "ITEM_SITUATIONAL:defensive", "ITEM_SITUATIONAL:situational"];

function slot(rec: Recommendation): number {
  const i = ORDER.indexOf(rec.type === "ITEM_SITUATIONAL" ? `${rec.type}:${rec.category}` : rec.type);
  return i < 0 ? ORDER.length : i;
}

/** Skill first, then talent, core item, buyback, defensive and situational items. */
export function sortAdvice(recs: Recommendation[]): Recommendation[] {
  return [...recs].sort((a, b) => slot(a) - slot(b));
}

export function adviceLabel(rec: Recommendation): string {
  switch (rec.type) {
    case "SKILL_LEVEL":
      return "Скилл";
    case "TALENT":
      return "Талант";
    case "ITEM_NEXT":
      return "Основной предмет";
    case "ITEM_BUYBACK_GUARD":
      return "Выкуп";
    case "ITEM_SITUATIONAL":
      return rec.category === "defensive" ? "Защита" : "По ситуации";
    default:
      return rec.type;
  }
}

/** How fresh and how real the data is. Demo and replays are always labelled as such. */
export function dataState(status: CopilotStatus | undefined): { text: string; warn: boolean } {
  if (!status || status.state === "no_data") return { text: "Нет данных от игры", warn: true };
  if (status.state === "stale") return { text: "Данные устарели: игра молчит больше 30 с", warn: true };
  if (status.mode === "demo") return { text: "Демо-матч, не ваша игра", warn: true };
  if (status.mode === "replay") return { text: "Запись матча", warn: true };
  return { text: "Данные игры", warn: false };
}

/** The player buys by hand; the app never clicks anything in Dota. */
export function quickbuyHint(itemName: string): string {
  return `Откройте магазин, найдите «${itemName}» через поиск и щёлкните по нему правой кнопкой: предмет попадёт в быструю покупку (Quickbuy). Приложение само ничего в игре не нажимает.`;
}
