// web/src/league.ts
export interface Me { name: string; is_commissioner: boolean; slot: number | null }

export interface Pick { n: number; slot: number; team: string; by: string; ts: number }

export interface LeagueView {
  players: string[];
  commissioner: string;
  slots: Record<string, number> | null;
  status: 'lobby' | 'drafting' | 'done';
  picks: Pick[];
  pick_order: number[];
  rosters: Record<string, string[]>;
  current_slot: number | null;
  current_player: string | null;
  logged_in: Record<string, number>;
  teams: string[];
}

export interface Message { id: string; by: string; text: string; ts: number }

export interface StandingsRow { player: string; teams: { code: string; wins: number }[]; total: number }
export interface StandingsResponse {
  rows: StandingsRow[];
  stale: boolean;
  overrides: Record<string, number>;
  fetched_at: number;
}

export class HttpError extends Error {
  status: number;
  retryAfter?: number;
  constructor(status: number, retryAfter?: number) {
    super(String(status));
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: 'same-origin', ...init });
  if (res.status === 401) throw new HttpError(401);
  if (!res.ok) {
    // 429 carries the seconds left on a login backoff; the form counts it down.
    const after = Number(res.headers.get('retry-after'));
    throw new HttpError(res.status, Number.isFinite(after) && after > 0 ? after : undefined);
  }
  return res.json();
}
const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

export const login = (name: string, pin: string) => call<{ name: string }>('/api/login', json({ name, pin }));
export const getMe = () => call<Me>('/api/me');
export const getLeague = () => call<LeagueView>('/api/league');
export const randomize = () => call<LeagueView>('/api/league/randomize', { method: 'POST' });
export const resetDraft = () => call<LeagueView>('/api/league/reset', { method: 'POST' });
export const restartDraft = () => call<LeagueView>('/api/league/restart', { method: 'POST' });
export const pickTeam = (team: string) => call<LeagueView>('/api/league/pick', json({ team }));
export const undoPick = () => call<LeagueView>('/api/league/undo', { method: 'POST' });
export const getMessages = (since?: number) =>
  call<Message[]>(since ? `/api/messages?since=${since}` : '/api/messages');
export const postMessage = (text: string) => call<Message>('/api/messages', json({ text }));
export const getSimModel = () => call<import('./sim').SimModel>('/api/league/sim-model');
export const getStandings = (refresh = false) =>
  call<StandingsResponse>(refresh ? '/api/standings?refresh=1' : '/api/standings');
export const setOverride = (team: string, wins: number | null) =>
  call<{ overrides: Record<string, number> }>('/api/standings/override', json({ team, wins }));

// Login-screen names; the server's league doc is the source of truth.
export const PLAYERS = [
  'Nate Robinson',
  'Evan Goguillon-Bader',
  'Logan Borgelt',
  'Eric Whitley',
  'Mitch Fischer',
];

export interface ProjTeam { code: string; exp_wins: number }
export interface ProjRow {
  player: string;
  teams: ProjTeam[];
  exp_wins: number;
  pwin: number;
  p10: number;
  p90: number;
  dist: number[];
}
export interface ProjectionsResponse { rows: ProjRow[]; x: number[]; n_sims: number; locked_at: number }
export interface SeasonSample {
  standings: { player: string; teams: { code: string; wins: number }[]; total_wins: number }[];
  winners: string[];
}
export const getProjections = () => call<ProjectionsResponse>('/api/league/projections');
export const getSampleSeason = (seed: number) => call<SeasonSample>(`/api/league/sample_season?seed=${seed}`);

export interface LiveGame { team: string; opp: string; home: boolean; p: number; lock: boolean }
export interface LiveWeekRow {
  player: string; leverage: number; games: LiveGame[];
  exp_wins: number; min_wins: number; max_wins: number;
}
export interface LiveTeam { code: string; banked: number; exp_wins: number }
export interface LiveRow {
  player: string; teams: LiveTeam[]; banked: number; exp_wins: number;
  pwin: number; market_pwin: number | null; p10: number; p90: number; dist: number[];
}
export type LiveViewRow = Omit<LiveRow, 'dist' | 'market_pwin'>;
export interface LiveProjection {
  week: number; computed_at: number; ratings_fetched_at: string | null;
  rows: LiveRow[]; x: number[]; n_sims: number; this_week: LiveWeekRow[];
  /** Same projection under one source at 100%: keys 'blend' plus each source name. */
  views: Record<string, LiveViewRow[]>;
}
export interface WeekSlim { player: string; pwin: number; exp_wins: number }
export interface WeekPoint { week: number; rows: WeekSlim[]; views: Record<string, WeekSlim[]> }
export const getLive = () => call<LiveProjection>('/api/league/live');
export const getWeeks = () => call<WeekPoint[]>('/api/league/weeks');

export interface WeekGame {
  home: string; away: string; kickoff: string | null; state: 'pre' | 'final';
  spread: number | null; total: number | null;
  p_model: number | null; p_used: number | null;
  p_book: number | null; p_kalshi: number | null;
  home_score: number | null; away_score: number | null;
  swing: Record<string, number>;
  history: [number, number][];
}
export interface WeekPlayer {
  name: string; teams: string[]; locks: number; banked: number;
  chalk: number; dist: number[]; actual: number | null; pwin: number | null;
}
export interface WeekResponse {
  season: number; week: number; state: 'live' | 'final';
  games: WeekGame[]; players: WeekPlayer[];
}
export const getWeek = (week?: number) =>
  call<WeekResponse>(week == null ? '/api/week' : `/api/week?week=${week}`);

export interface AdminSource {
  name: string; last_ok: number | null; age_s: number | null;
  max_age_s: number; stale: boolean; last_error: string | null;
}
export interface AdminJob { name: string; at: number | null }
export interface AdminHealth { sources: AdminSource[]; jobs: AdminJob[] }
export const getAdminHealth = () => call<AdminHealth>('/api/admin/health');
