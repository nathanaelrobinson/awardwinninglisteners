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
export interface StandingsResponse { rows: StandingsRow[]; stale: boolean; overrides: Record<string, number> }

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { credentials: 'same-origin', ...init });
  if (res.status === 401) throw new Error('401');
  if (!res.ok) throw new Error(String(res.status));
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
export const pickTeam = (team: string) => call<LeagueView>('/api/league/pick', json({ team }));
export const undoPick = () => call<LeagueView>('/api/league/undo', { method: 'POST' });
export const getMessages = (since?: number) =>
  call<Message[]>(since ? `/api/messages?since=${since}` : '/api/messages');
export const postMessage = (text: string) => call<Message>('/api/messages', json({ text }));
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
