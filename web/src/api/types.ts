// Response shapes of the d2bg API. The Playwright suite runs against the real server, so drift fails CI.

export type Side = "radiant" | "dire";
export type RankBucket = "1-2" | "3-4" | "5-6" | "7-8" | "all";

export interface HeroSummary {
  id: number;
  key: string;
  name: string;
  primary_attr: string;
  attack_type: string;
  roles: string[];
  img: string | null;
  icon: string | null;
  aliases: string[];
}

export interface HeroListRow extends HeroSummary {
  traits: string[];
  positions: number[];
  win_rate: number | null;
  pick_rate: number | null;
}

export interface TraitView {
  trait: string;
  label: string;
  evidence: string[];
}

export interface Positions {
  shares: Record<string, number>;
  source: string;
  games: number;
}

export interface HeroDetail extends HeroSummary {
  stats: Record<string, number | null>;
  abilities: {
    key: string;
    name: string;
    desc: string;
    img: string | null;
    cooldown: unknown;
    mana: unknown;
    behavior: string[];
    dmg_type: string | null;
    bkb_pierce: boolean;
    hidden: boolean;
    attrib: { header: string; value: unknown }[];
  }[];
  talents: { key: string; name: string; tier: number }[];
  scepter: { skill: string | null; desc: string | null } | null;
  shard: { skill: string | null; desc: string | null } | null;
  traits: TraitView[];
  positions: Positions | null;
  bucket: RankBucket;
  bucket_stats: { games: number; wins: number; wr: number; pick_rate: number } | null;
  best_against: { hero: number; value: number }[];
  worst_against: { hero: number; value: number }[];
  best_with: { hero: number; value: number }[];
  countered_by: { hero: number; edge: number }[];
  counterability: number;
  similar: { hero: number; similarity: number }[];
  benchmarks: Record<string, [number, number][]> | null;
  lane_roles: Record<string, [number, number]> | null;
  meta: { brackets?: Record<string, [number, number]>; pro?: [number, number, number]; turbo?: [number, number] };
}

export interface ItemRef {
  key: string;
  name: string;
  img: string | null;
  cost: number | null;
}

export interface BuildResponse {
  hero: HeroSummary;
  positions: Positions | null;
  skills: {
    rows: number;
    by_level: (ItemRefLike & { pick: number; share: number; n: number })[];
    orders: { order: ItemRefLike[]; n: number; win_rate: number | null }[];
    talents: { key: string; name: string; tier: number; level: number | null; share: number | null; n: number }[];
  };
  items: {
    starting: { items: ItemRef[]; n: number }[];
    order: (ItemRef & { share: number; median_time: number; median: string; n: number; win_rate: number | null })[];
    phases: Record<string, (ItemRef & { count: number; share: number })[]>;
    timing_win_rates: Record<
      string,
      ItemRef & { games: number; buckets: { until: number; label: string; games: number; win_rate: number | null }[] }
    >;
    rows?: number;
  };
  pro: { games: number; win_rate: number | null; since: number | null; matches: number | null };
  notes: string[];
}

export interface ItemRefLike {
  key: string;
  name: string;
  img: string | null;
}

export interface ItemRow {
  key: string;
  id: number;
  name: string;
  cost: number;
  img: string | null;
  tier: number | null;
  components: string[];
  builds_into: string[];
}

export type ItemSummary = Omit<ItemRow, "builds_into">;

export interface ItemDetail extends ItemSummary {
  quality: string | null;
  abilities: { type: string; title: string; description: string }[];
  attrib: string[];
  cooldown: unknown;
  notes: string | null;
  recipe_cost: number;
  components_detail: ItemSummary[];
  builds_into: ItemSummary[];
  bought_by: { hero: number; share: number; median_time: number }[];
}

export interface MetaRow {
  hero: number;
  name: string;
  icon: string | null;
  picks: number;
  wins: number;
  bans: number | null;
  win_rate: number | null;
  pick_share: number;
  positions: number[];
  tier: "S" | "A" | "B" | "C" | "D";
}

export interface MetaResponse {
  source: string;
  bracket: number | null;
  position: number | null;
  rows: MetaRow[];
  generated_at: number | null;
  data_source: string | null;
}

export interface Why {
  good_against: { hero: number; value: number }[];
  bad_against: { hero: number; value: number }[];
  with: { hero: number; value: number }[];
}

export interface Suggestion {
  hero: number;
  score: number;
  positions: number[];
  counterability: number;
  why: Why;
}

export interface TeamReport {
  heroes: number[];
  traits: Record<string, { label: string; heroes: string[] }>;
  roles: Record<string, number>;
  melee: number;
  ranged: number;
  damage: { magic: number; physical: number; pure: number };
  disablers: string[];
  positions_covered: number[];
  warnings: string[];
}

export interface SituationalRule {
  id: string;
  reason: string;
  reason_ru?: string;
  category?: string;
  heroes: string[];
  items: (ItemRef & { owned: boolean })[];
}

export interface DraftRequest {
  allies: number[];
  enemies: number[];
  bans: number[];
  side?: Side | null;
  rank_bucket?: RankBucket | null;
  synergy_weight?: number | null;
  pool_mode?: "off" | "boost" | "only" | null;
  compare?: number[];
  n?: number;
}

export interface DraftResponse {
  bucket: RankBucket;
  sample_matches: number;
  source_week: string;
  pool_mode: string;
  suggestions: Suggestion[];
  by_position: Record<string, Suggestion[]>;
  counters: Record<string, { hero: number; edge: number }[]>;
  hot_counters: { hero: number; enemies: number[]; advantage: number }[];
  bans: { hero: number; threat: number; wr: number; beats: { hero: number; value: number }[] }[];
  meta: { hero: number; wr: number }[];
  win: {
    us: number;
    them: number;
    side: Side | null;
    held_out_accuracy: number | null;
    detail: { contributions: { hero: number; side: Side; logit: number }[]; complete: boolean };
  } | null;
  ours: TeamReport;
  theirs: TeamReport;
  positions: { ours: Record<string, number>; theirs: Record<string, number> };
  lanes: { lane: string; ours: number[]; theirs: number[]; advantage: number; pairs_known: number; pairs_total: number }[];
  items: SituationalRule[];
  compare: Suggestion[];
  notes: string[];
}

export interface TimerView {
  id: string;
  label: string;
  at: number | null;
  seconds_left: number | null;
  lead: number;
  status: "upcoming" | "window" | "alive" | "active" | "estimated";
  detail: string;
  cite: string;
}

export interface Alert {
  id: number;
  clock: number | null;
  clock_text: string | null;
  at: number;
  kind: string;
  text: string;
  speak: string | null;
  severity: string;
}

export interface NextItem {
  item: string;
  name: string;
  cost: number;
  remaining: number;
  progress: number;
  eta_seconds?: number;
  pro_median?: string | null;
}

export interface LiveSnapshot {
  version: number;
  match_id: string | null;
  demo: boolean;
  timer_patch: string;
  phase: string;
  connection: { packets: number; last_packet_age: number | null; connected: boolean; source: string; blocks: string[] };
  clock?: number | null;
  clock_text?: string | null;
  daytime?: boolean | null;
  paused?: boolean | null;
  team?: Side | null;
  spectating?: boolean;
  score?: { radiant: number | null; dire: number | null };
  win_team?: string | null;
  timers?: TimerView[];
  hero?: HeroSummary & {
    level: number | null;
    alive: boolean | null;
    respawn_seconds: number | null;
    health: number | null;
    max_health: number | null;
    mana: number | null;
    max_mana: number | null;
    scepter: boolean | null;
    shard: boolean | null;
  };
  stats?: {
    kills: number;
    deaths: number;
    assists: number;
    last_hits: number;
    denies: number;
    gold: number;
    gold_reliable: number;
    gold_unreliable: number;
    gpm: number;
    xpm: number;
    net_worth: number | null;
    kill_participation: number | null;
    buyback_cost: number | null;
    buyback_cooldown: number | null;
  };
  items?: {
    inventory: { slot: string; key: string; name: string }[];
    backpack: { slot: string; key: string; name: string }[];
    stash: { slot: string; key: string; name: string }[];
    neutral: string | null;
  };
  next_items?: NextItem[];
  buyback_warning?: string | null;
  skills?: {
    unspent: number | null;
    next: { ability: string; name: string; share: number; n?: number | null; rank?: number } | null;
    abilities: { key: string; name: string; level: number; cooldown: number | null; ultimate: boolean | null }[];
  };
  benchmarks?: { metric: string; label: string; value: number; percentile: number | null; median: number | null }[];
  lh_target?: { at_10: number; now: number; you: number; percentile: number | null };
  draft?: {
    allies: number[];
    enemies: number[];
    side: Side;
    side_known?: boolean;
    bans: number[];
    /** What the game itself supplied so far, by kind: you, bans, allies, enemies. */
    sources?: Record<string, string>;
    note?: string;
    /** The last reading of the draft screen by d2bg-cv: slots it could not read, and its weakest match. */
    screen?: { unknown: number; confidence: number } | null;
  };
  situational_items?: SituationalRule[];
  enemy_threats?: { hero: number; traits: TraitView[]; countered_by: number[] }[];
  players?: {
    team: Side;
    slot: string;
    name: string | null;
    hero: number | null;
    level: number | null;
    alive: boolean | null;
    kills: number;
    deaths: number;
    assists: number;
    last_hits: number;
    gpm: number;
    net_worth: number | null;
    items: { key: string; name: string }[];
  }[];
  series?: { t: number; gold: number; net_worth: number | null; last_hits: number; level: number | null; gpm: number; xpm: number }[];
  events?: { type: string; clock: number | null; clock_text: string | null; team: string | null }[];
  alerts?: Alert[];
}

export interface Settings {
  account_id: number | null;
  rank_bucket: RankBucket;
  positions: number[];
  hero_pool: number[];
  pool_mode: "off" | "boost" | "only";
  blacklist: number[];
  whitelist: number[];
  synergy_weight: number;
  timers: { enabled: Record<string, boolean>; voice: boolean; lead_seconds: number };
  record_gsi: boolean;
  keep_recordings: number;
  auto_post_game: boolean;
  turbo_collect: boolean;
  game_mode: "auto" | "turbo" | "normal";
  providers: ProviderPrefs;
  hidden_hints: HintGroup[];
  request_parse: boolean;
  lan_mode: boolean;
  theme: "dark" | "light";
  opendota_api_key: "set" | null | string;
}

export interface GsiStatus {
  dota_found: boolean;
  dota_path?: string;
  installed: boolean;
  current: boolean;
  path: string | null;
  port: number;
  connection: LiveSnapshot["connection"];
  launch_option_hint: string;
}

export interface DataFileStatus {
  present: boolean;
  location?: string;
  source?: string;
  generated_at?: number;
  rows?: number;
  calls?: number;
}

export interface DataStatus {
  snapshot: string;
  refreshed: string;
  files: Record<string, DataFileStatus>;
  usage: { date: string; requests_today: number; remaining_minute: number | null; remaining_day: number | null; has_api_key: boolean };
  refresh: { running: boolean; steps: string[]; progress: { step?: string; done?: number; total?: number; message?: string }; results: { step: string; rows: number; calls: number; seconds: number; note: string }[]; error: string | null };
  steps: string[];
}

export interface VersionInfo {
  version: string;
  patch: string;
  timer_patch: string;
  user_dir: string;
  port: number;
}

export interface Recording {
  name: string;
  bytes: number;
  modified: number;
}

export interface MatchRow {
  hero_id: number;
  hero_name: string;
  start_time: number;
  duration: number;
  kills: number;
  deaths: number;
  assists: number;
  won: boolean;
  match_id?: number;
  lobby_type?: number;
  game_mode?: number;
}

export interface ProfileResponse {
  account_id: number;
  name: string | null;
  avatar: string | null;
  profile_url: string | null;
  rank: string | null;
  rank_tier: number | null;
  summary: { games: number; wins: number; win_rate: number | null; recent_20: { games: number; wins: number }; avg_kda: number | null; avg_duration_min: number | null };
  ranked_summary: ProfileResponse["summary"];
  streaks: { current: number; current_kind: "win" | "loss" | null; longest_win: number; longest_loss: number };
  sessions: { start: number; end: number; games: number; wins: number; results: ("W" | "L")[] }[];
  by_hour: { hour: number; games: number; wins: number; win_rate: number }[];
  hero_pool: { hero: number; name: string; games: number; wins: number; win_rate: number; wilson_lower: number; kda: number; last_played: number }[];
  comfort: number[];
  worth_adding: { hero: number; name: string; similar_to: string[] }[];
  trend: { start_time: number; win_rate: number }[];
  lanes: Record<string, number>;
  recent: MatchRow[];
  matches_considered: number;
  public: boolean;
}

export interface Peer {
  account_id: number;
  name: string | null;
  avatar: string | null;
  with_games: number;
  with_wins: number;
  with_win_rate: number | null;
  against_games: number | null;
  last_played: number | null;
}

export interface ReviewRow {
  account_id: number | null;
  name: string | null;
  rank: string | null;
  radiant: boolean;
  hero: number;
  hero_name: string;
  hero_img: string | null;
  level: number | null;
  kills: number | null;
  deaths: number | null;
  assists: number | null;
  last_hits: number | null;
  denies: number | null;
  gpm: number | null;
  xpm: number | null;
  net_worth: number | null;
  hero_damage: number | null;
  tower_damage: number | null;
  hero_healing: number | null;
  items: ItemRefLike[];
  backpack: ItemRefLike[];
  lh_10: number | null;
}

export interface MatchReview {
  match_id: number;
  start_time: number;
  duration: number;
  duration_text: string;
  radiant_win: boolean;
  score: { radiant: number | null; dire: number | null };
  parsed: boolean;
  radiant: ReviewRow[];
  dire: ReviewRow[];
  totals: Record<Side, { kills: number; net_worth: number; hero_damage: number }>;
  me: {
    row: ReviewRow;
    won: boolean;
    benchmarks: { metric: string; label: string; value: number; percentile: number }[];
    item_timings: { item: string; name: string; you: string; pro_median: string; delta_seconds: number; delta: string }[];
  } | null;
  notes: string[];
  gold_advantage: number[];
  xp_advantage: number[];
}

export interface PostGameJob {
  match_id: string;
  status: "waiting" | "ready" | "gave_up";
  attempts: number;
  parse_requested: boolean;
  error: string | null;
}

// ── Copilot (src/d2bg/api/copilot_routes.py) ─────────────────────

export type RecType =
  | "PICK_HERO"
  | "SKILL_LEVEL"
  | "TALENT"
  | "ITEM_NEXT"
  | "ITEM_SITUATIONAL"
  | "ITEM_BUYBACK_GUARD"
  | "POSTMATCH_FINDING";
export type RecStatus = "suggested" | "seen" | "dismissed" | "followed" | "unknown" | "expired";
export type RecCategory = "core" | "situational" | "defensive" | "buyback";

export interface Recommendation {
  id: string;
  match_id: string;
  game_time_s: number | null;
  type: RecType;
  category: RecCategory | null;
  candidate_id: string;
  alternatives: string[];
  reason_ru: string;
  source: "baseline" | "jev" | "groq" | "hybrid" | "deepseek";
  /** What the source measured (confidence_kind says what); never a win probability. */
  confidence: number | null;
  confidence_kind: "none" | "pro_pick_share" | "unverified_model_score";
  evidence_ids: string[];
  context_hash: string;
  model_version: string;
  data_patch: string | null;
  status: RecStatus;
  expires_at: number | null;
}

export interface CloudProvider {
  configured: boolean;
  model: string;
  /** Did the last call work; null before the first call. */
  online: boolean | null;
  error: string | null;
  calls_this_match: number;
  limit_per_match: number;
  cost_usd_total: number;
}

export interface Providers {
  mode: "baseline" | "jev" | "hybrid";
  baseline: { configured: boolean; online: boolean };
  jev: CloudProvider;
  advisor: CloudProvider;
}

export interface ProviderPrefs {
  mode: "baseline" | "jev" | "hybrid";
  jev_per_match: number;
  advisor_per_match: number;
  jev_model: string;
  advisor_base_url: string;
  advisor_model: string;
  in_demo: boolean;
}

export type ProviderTest = Record<"jev" | "advisor", { ok: boolean; latency_ms?: number; model?: string; error?: string; message?: string }>;

export interface CopilotStatus {
  state: "no_data" | "stale" | "ok";
  mode: "game" | "demo" | "replay" | "none";
  match_id: string | null;
  phase: string | null;
  patch: { data: string; timers: string };
  snapshot_generated_at: number | null;
  context: { sources: Record<string, string>; data_age_s: number | null; [key: string]: unknown };
  providers: Providers;
  journal: Record<string, number>;
  rejected: { type: string; candidate: string; reason: string }[];
  /** d2bg-cv asked for the status in the last few seconds. */
  screen_reader: { running: boolean };
  error: string | null;
}

export interface HudItem {
  key: string;
  name: string;
  detail: string;
}

/** What the overlay's small widgets show now; a null widget stays hidden. */
export interface Hud {
  source: string;
  mode: "turbo" | "normal" | null;
  mode_source: "setting" | "gold_rate" | "last_game" | "unknown";
  skill:
    | { kind: "skill"; key: string; name: string; slot: number | null; reason: string }
    | { kind: "talent"; key: string; name: string; instead: string[]; reason: string }
    | null;
  draft: {
    position: number | null;
    // Heroes the app knows in this draft: 0 until the screen reader runs (GSI sends none to a player).
    heroes_known: number;
    picks: { hero: number; name: string; why: string }[];
    bans: { hero: number; name: string }[];
  } | null;
  items: { title: string; note: string; items: HudItem[] } | null;
}

/** A match in the Copilot journal (his own games the app saw). */
export interface JournalMatch {
  match_id: string;
  source: string;
  hero_id: number | null;
  hero: string | null;
  team: string | null;
  first_seen_at: number;
  last_seen_at: number;
  last_game_time_s: number | null;
  recording: string | null;
  reports: string[];
}

export type Certainty = "verified" | "likely" | "insufficient_data";

export interface CoachFinding {
  id: string;
  metric: string;
  title: string;
  event_time_s: number | null;
  actual: unknown;
  baseline: unknown;
  comparison_group: string;
  evidence_ids: string[];
  certainty: Certainty;
  review_anchor: string | null;
  recommendation: string;
  goal: string | null;
}

export interface CoachReport {
  match_id: string;
  hero: string | null;
  hero_id: number | null;
  mode: "turbo" | "normal" | null;
  duration_s: number | null;
  won: boolean | null;
  stats: { kills: number; deaths: number; assists: number; last_hits: number; gpm: number; xpm: number; level: number | null } | null;
  findings: CoachFinding[];
  strengths: string[];
  goals: { metric: string; text: string }[];
  advice: {
    /** One line per piece of advice and what became of it. */
    outcomes: { type: string; candidate: string; name: string; first_t: string; times_shown: number; outcome: string; evidence: string }[];
    total: number;
    by_status: Record<string, number>;
    seen: number;
    models: { total: number; agreed: number };
    items: { id: string; t: number | null; type: string; candidate: string; name: string; status: string; source: string }[];
  };
  timeline: { t: number | null; kind: "death" | "item"; text: string; id: string }[];
  opendota: { parsed: boolean; me: unknown } | null;
  missing: string[];
  created_at: number;
}

export interface AiReview {
  summary: string;
  strengths: string[];
  findings: { text: string; evidence_ids: string[]; certainty: Certainty }[];
  practice_goals: string[];
  unknowns: string[];
  blocked_findings: number;
  model_version: string;
  created_at?: number;
}

export interface Recurring {
  metric: string;
  title: string;
  matches: number;
  of: number;
}

export interface MatchReviewResponse {
  facts: CoachReport;
  ai: AiReview | null;
  recurring: Recurring[];
}

export interface GoalsResponse {
  goals: { match_id: string; created_at: number; metric: string | null; text: string; source: string }[];
  recurring: Recurring[];
}

export type HintGroup = "skills" | "items" | "buyback" | "draft";
