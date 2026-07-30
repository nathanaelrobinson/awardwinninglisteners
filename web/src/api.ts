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
