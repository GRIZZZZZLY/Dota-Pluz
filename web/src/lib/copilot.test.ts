import type { CopilotStatus, Recommendation } from "../api/types";
import { adviceLabel, dataState, quickbuyHint, sortAdvice } from "./copilot";

const rec = (type: Recommendation["type"], category: Recommendation["category"] = null): Recommendation => ({
  id: `${type}:${category}`,
  match_id: "1",
  game_time_s: 600,
  type,
  category,
  candidate_id: "x",
  alternatives: [],
  reason_ru: "",
  source: "baseline",
  confidence: null,
  confidence_kind: "none",
  evidence_ids: [],
  context_hash: "h",
  model_version: "baseline",
  data_patch: "7.41",
  status: "suggested",
  expires_at: null,
});

const status = (state: CopilotStatus["state"], mode: CopilotStatus["mode"]) => ({ state, mode }) as CopilotStatus;

test("advice is ordered skill, talent, core, buyback, defensive, situational", () => {
  const sorted = sortAdvice([
    rec("ITEM_SITUATIONAL", "situational"),
    rec("ITEM_BUYBACK_GUARD", "buyback"),
    rec("ITEM_SITUATIONAL", "defensive"),
    rec("ITEM_NEXT", "core"),
    rec("TALENT"),
    rec("SKILL_LEVEL"),
  ]);
  expect(sorted.map(adviceLabel)).toEqual(["Скилл", "Талант", "Основной предмет", "Выкуп", "Защита", "По ситуации"]);
});

test("demo, replays, stale and missing data are always labelled", () => {
  expect(dataState(undefined).warn).toBe(true);
  expect(dataState(status("no_data", "none")).text).toMatch(/Нет данных/);
  expect(dataState(status("stale", "game")).text).toMatch(/устарели/);
  expect(dataState(status("ok", "demo")).text).toMatch(/Демо/);
  expect(dataState(status("ok", "replay")).warn).toBe(true);
  expect(dataState(status("ok", "game"))).toEqual({ text: "Данные игры", warn: false });
});

test("the quickbuy hint is an instruction, not an action", () => {
  expect(quickbuyHint("Black King Bar")).toMatch(/«Black King Bar»/);
  expect(quickbuyHint("Black King Bar")).toMatch(/ничего в игре не нажимает/);
});
