import type { Mode, RecommendResponse, TeamsResponse } from './types';

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
  mode: Mode,
  rollouts = 60,
  temp = 8.0
): Promise<RecommendResponse> {
  const res = await fetch('/api/recommend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ slot, taken, mode, rollouts, temp }),
  });
  if (!res.ok) {
    throw new Error(`POST /api/recommend failed: ${res.status}`);
  }
  return res.json();
}
