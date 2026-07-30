import type { AutosimRequest, AutosimResponse, Mode, RecommendResponse, TeamsResponse } from './types';

export async function fetchTeams(): Promise<TeamsResponse> {
  const res = await fetch('/api/teams');
  if (!res.ok) {
    throw new Error(`GET /api/teams failed: ${res.status}`);
  }
  return res.json();
}

export async function fetchRecommend(
  slot: number,
  taken: string[],
  mode: Mode = 'rollout',
  seed?: number
): Promise<RecommendResponse> {
  const res = await fetch('/api/recommend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slot, taken, mode, seed }),
  });
  if (!res.ok) {
    throw new Error(`POST /api/recommend failed: ${res.status}`);
  }
  return res.json();
}

export interface AdvanceResponse {
  taken: string[];
  current_player: number;
  my_turn: boolean;
  done: boolean;
}

export async function advanceOpponents(
  slot: number,
  taken: string[],
  oppStrategy: string,
  seed: number
): Promise<AdvanceResponse> {
  const res = await fetch('/api/advance', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slot, taken, opp_strategy: oppStrategy, seed }),
  });
  if (!res.ok) {
    throw new Error(`POST /api/advance failed: ${res.status}`);
  }
  return res.json();
}

export interface StandingRow {
  player: number;
  is_me: boolean;
  teams: string[];
  exp_wins: number;
  pwin: number;
  p10: number;
  p90: number;
}

export async function fetchResults(slot: number, taken: string[]): Promise<{ standings: StandingRow[] }> {
  const res = await fetch('/api/results', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slot, taken }),
  });
  if (!res.ok) throw new Error(`POST /api/results failed: ${res.status}`);
  return res.json();
}

export interface SeasonTeam {
  code: string;
  wins: number;
}
export interface SeasonRow {
  player: number;
  is_me: boolean;
  teams: SeasonTeam[];
  total_wins: number;
}
export async function sampleSeason(
  slot: number,
  taken: string[],
  seed: number
): Promise<{ standings: SeasonRow[]; winners: number[] }> {
  const res = await fetch('/api/sample_season', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slot, taken, seed }),
  });
  if (!res.ok) throw new Error(`POST /api/sample_season failed: ${res.status}`);
  return res.json();
}

export async function fetchAutosim(req: AutosimRequest): Promise<AutosimResponse> {
  const res = await fetch('/api/autosim', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw new Error(`POST /api/autosim failed: ${res.status}`);
  }
  return res.json();
}
