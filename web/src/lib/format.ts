/** Game clock text: 75 -> "1:15", -12 -> "-0:12". */
export function clock(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "–";
  const sign = seconds < 0 ? "-" : "";
  const s = Math.floor(Math.abs(seconds));
  return `${sign}${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** 0.5234 -> "52.3%". */
export function pct(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "–";
  return `${(value * 100).toFixed(digits)}%`;
}

/** Signed percentage points: 2.345 -> "+2.3". */
export function pts(value: number, digits = 1): string {
  const v = value.toFixed(digits);
  return value > 0 ? `+${v}` : v;
}

export function gold(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return value.toLocaleString("ru-RU");
}

/** Russian masculine ordinal: 62 -> "62-й" (agrees with «перцентиль»). */
export function ordinal(n: number): string {
  return `${n}-й`;
}

export function percentileText(p: number | null | undefined): string {
  if (p === null || p === undefined) return "–";
  return `${ordinal(Math.round(p * 100))} перцентиль`;
}

export function date(ts: number | null | undefined): string {
  if (!ts) return "–";
  return new Date(ts * 1000).toLocaleDateString("ru-RU", { month: "short", day: "numeric", year: "numeric" });
}

export function dateTime(ts: number | null | undefined): string {
  if (!ts) return "–";
  return new Date(ts * 1000).toLocaleString("ru-RU", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export const POSITION_NAMES: Record<number, string> = {
  1: "Керри",
  2: "Мид",
  3: "Оффлейн",
  4: "Саппорт",
  5: "Полный саппорт",
};

export const BUCKETS = [
  { value: "all", label: "Все ранги" },
  { value: "1-2", label: "Рекрут–Страж" },
  { value: "3-4", label: "Рыцарь–Герой" },
  { value: "5-6", label: "Легенда–Властелин" },
  { value: "7-8", label: "Божество–Титан" },
] as const;

export const MEDALS = ["Рекрут", "Страж", "Рыцарь", "Герой", "Легенда", "Властелин", "Божество", "Титан"];
