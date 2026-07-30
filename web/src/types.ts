export interface Team {
  code: string;
  name: string;
  division: string;
  win_total: number;
  strength: number;
  mean: number;
  sd: number;
  ceiling: number;
  floor: number;
}

export interface TeamsResponse {
  teams: Team[];
  pick_order: number[];
  n_players: number;
}

export interface Recommendation {
  code: string;
  pwin: number;
  delta_wins: number;
  survival?: number;
}

export interface RecommendResponse {
  current_player: number;
  my_turn: boolean;
  my_next_in: number;
  done: boolean;
  p_win_me: number | null;
  rosters: Record<string, string[]>;
  recommendations: Recommendation[];
}

export type Mode = 'naive' | 'rollout';

export type MyStrategy = 'optimal' | 'power' | 'market' | 'random';
export type OppStrategy = 'market' | 'power' | 'random';

export interface AutosimRequest {
  slot: number;
  my_strategy: MyStrategy;
  opp_strategy: OppStrategy;
  n_sims?: number;
  seed?: number;
}

export interface AutosimResponse {
  slot: number;
  my_strategy: MyStrategy;
  opp_strategy: OppStrategy;
  n_sims: number;
  win_pct: number;
  p10: number;
  p90: number;
  fair_share: number;
}
