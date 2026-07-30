import type { RecommendResponse } from '../types';

interface Props {
  slot: number;
  onSlotChange: (slot: number) => void;
  nPlayers: number;
  recommend: RecommendResponse | null;
  autoDraft: boolean;
  onAutoDraftChange: (v: boolean) => void;
  oppStrategy: string;
  onOppStrategyChange: (s: string) => void;
  onReset: () => void;
  onUndo: () => void;
  canUndo: boolean;
}

const OPP_STRATEGIES = ['market', 'power', 'random'];

function pct(x: number | null | undefined): string {
  if (x === null || x === undefined) return '—';
  return `${(x * 100).toFixed(1)}%`;
}

export default function Header({
  slot,
  onSlotChange,
  nPlayers,
  recommend,
  autoDraft,
  onAutoDraftChange,
  oppStrategy,
  onOppStrategyChange,
  onReset,
  onUndo,
  canUndo,
}: Props) {
  const players = Array.from({ length: nPlayers }, (_, i) => i + 1);

  return (
    <header className="header">
      <div className="header-row">
        <div className="slot-picker">
          <span className="label">I am player</span>
          {players.map((p) => (
            <button
              key={p}
              className={`slot-btn ${p === slot ? 'active' : ''}`}
              onClick={() => onSlotChange(p)}
            >
              {p}
            </button>
          ))}
        </div>

        <div className="pwin-readout">
          <span className="label">P(I win)</span>
          <span className="pwin-value">{pct(recommend?.p_win_me)}</span>
        </div>

        <div className="status-line">
          {recommend ? (
            recommend.done ? (
              <span>Draft complete</span>
            ) : (
              <span>
                On the clock: player {recommend.current_player}
                {' · '}
                {recommend.my_turn
                  ? 'your pick now'
                  : `your next pick in ${recommend.my_next_in}`}
              </span>
            )
          ) : (
            <span>Loading…</span>
          )}
        </div>

        <div className="header-actions">
          <label
            className="opp-strategy-label"
            title="How your league drafts — used both to auto-draft the bots and to model opponents in the recommendations (survival / what falls to you)"
          >
            Field:
            <select
              className="opp-strategy"
              value={oppStrategy}
              onChange={(e) => onOppStrategyChange(e.target.value)}
            >
              {OPP_STRATEGIES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </label>
          <label className="auto-toggle" title="Bots draft the other seats until it's your turn">
            <input
              type="checkbox"
              checked={autoDraft}
              onChange={(e) => onAutoDraftChange(e.target.checked)}
            />
            Auto-draft
          </label>
          <button className="btn" onClick={onUndo} disabled={!canUndo}>
            Undo
          </button>
          <button className="btn btn-danger" onClick={onReset}>
            Reset
          </button>
        </div>
      </div>
    </header>
  );
}
