# NFL Wins Pool — Draft Optimizer & Season Simulator

**Date:** 2026-07-29
**Status:** Design approved, pending spec review

## 1. Problem & Objective

Six players run a season-long NFL wins pool. Each drafts **5 teams** (30 of 32 teams
drafted; 2 left on the board) via a fixed, "optimized" snake order. At season's end the
player whose 5 teams have the **most combined regular-season wins** takes a
**winner-take-all** liquor prize.

**North-star objective:** maximize **P(I finish 1st of 6)** — *not* expected combined
wins. In a winner-take-all contest the correct target is probability of finishing first,
which makes the optimal strategy variance-seeking when trailing the field and
variance-averse when ahead. This is standard tournament / contest theory (the same math
that governs large-field DFS lineup construction). Applying it to a snake draft over a
*correlated joint distribution of team win totals* is the core idea of this tool.

### Draft order (fixed pattern)

On draft day each player is randomly assigned a slot P1–P6. From that moment the entire
pick sequence is deterministic and known:

| Player | Pick numbers |
|--------|--------------|
| P1 | 1, 12, 20, 23, 30 |
| P2 | 2, 14, 16, 22, 26 |
| P3 | 3, 11, 17, 19, 25 |
| P4 | 4, 9, 13, 24, 27 |
| P5 | 5, 7, 15, 18, 28 |
| P6 | 6, 8, 10, 21, 29 |

Covers picks 1–30 exactly once. Because the order is fully known, at any point in the
draft we know exactly which picks come before our next turn and who makes them.

### Pool scoring & tie rules

- Score = combined regular-season **wins** of a player's 5 teams (17 games/team → 85
  games/player).
- **Pool tie** (equal combined wins): both players are **co-champions** — both credited
  as winners. No least-losses tiebreak needed; scoring requires win totals only.
- **NFL tie game:** counts as **0 wins** for both teams (standard W/L tracking — a tie is
  not a win and not a loss). A small, history-calibrated tie rate (~1–2 games/season
  leaguewide) is applied to near-even matchups. Effect on results is negligible but the
  rule is modeled correctly.

## 2. Architecture — five decoupled layers

Each layer has one purpose, a well-defined interface, and is independently testable.

1. **Data layer** (`data/`) — pulls and caches three inputs to local files; the live app
   never hits the network.
2. **Ratings layer** (`ratings.py`) — blends market win totals with public power ratings
   into a per-team **strength** (points) plus an uncertainty.
3. **Simulation engine** (`sim.py`) — Monte Carlo season simulation producing an
   **N × 32 matrix** of team win totals. Single source of truth for all downstream
   analysis.
4. **Draft brain** (`draft.py`) — live draft state + pick recommendations that maximize
   P(I finish 1st), using the sim matrix and a high-entropy survival-probability lookahead.
5. **Mock-draft harness** (`mock.py`) — drives the brain programmatically for the
   positional-value study and interactive practice drafts.

The app is a **React (Vite + TypeScript) front end** over a **FastAPI backend** that
serves layers 3–4. A one-time **precompute step** (`build.py`) runs on draft morning to
produce the cached sim matrix the backend serves.

## 3. Data layer

All sources free / no-subscription:

- **Schedule + historical game data:** `nfl_data_py` (nflverse). Provides the 2026
  schedule (released) and full historical play-by-play for calibration.
- **Vegas win totals:** scrape a public aggregator (Vegas Insider / Sportsbook Review) or
  The Odds API free tier — ~32 numbers, easy to refresh.
- **Power ratings:** free sources — ESPN **FPI** (scrapeable), **Sagarin**, **Massey**.
  (FiveThirtyEight Elo is discontinued; DVOA is paywalled — both excluded.)

Each source cached to disk with a fetch timestamp; refresh on demand.

## 4. Ratings layer (`ratings.py`)

Every team gets a **strength in points** = expected scoring margin vs. a league-average
team on a neutral field.

1. Convert each power rating to the neutral-margin scale; average sources → `strength_power`.
2. Back out `strength_market` per team such that simulating its actual 2026 schedule
   yields expected wins ≈ its posted Vegas O/U (numerical fixed-point pass over 32 teams).
3. Blend: `strength = w · strength_market + (1 − w) · strength_power`, default
   **w ≈ 0.65** (market-anchored; power ratings allowed to pull it off the market number).
   `w` is the dial for how much we're willing to disagree with Vegas.
4. Attach per-team uncertainty `σ_team` from source disagreement + preseason uncertainty.

## 5. Simulation engine (`sim.py`)

Standard power-rating → margin → win-probability → Monte Carlo, the same skeleton used by
FiveThirtyEight's Elo model, ESPN FPI, and sportsbook win-total pricing.

For each of **N ≈ 25,000** simulated seasons:

- Draw each team's **true strength** once for the season from `Normal(strength, σ_team)`
  — injects preseason uncertainty so teams aren't identical every sim, realistically
  widening the win-total spread (matters for a variance-based objective).
- For each scheduled game:
  `p_home_win = Φ((strength_home − strength_away + HFA) / s)`
  with `HFA ≈ 2` pts and scale `s` calibrated to NFL margin-of-victory SD (~13.5 pts) so
  a 7-pt favorite wins ~70%, a 3-pt favorite ~57–60%. A small tie probability applies to
  near-even games. Sample W/L/T.
- Tally each team's wins → one row of the **N × 32 matrix**.

Correlation between teams (division-rivalry anti-correlation) emerges automatically
because teams share scheduled games; nothing else encodes it. This is the reason we
simulate game-by-game rather than modeling win totals independently — it is the only clean
way to get the correct **joint** distribution.

**Calibration check:** each team's simulated win distribution mean should sit near its
Vegas O/U; surfaced in the Setup screen for eyeball verification before trusting output.

## 6. Draft brain (`draft.py`)

### Why it's tractable

In sim season *s*, a player's pool score = sum of their 5 teams' win-columns in row *s*.
A player's whole outcome distribution is a length-N vector = sum of 5 columns. Comparing
all 6 players across N sims is one vectorized `argmax` over an N×6 array — so "who wins the
pool" is cheap for *any* full roster assignment, which makes the rollout affordable.

### Objective evaluation (full assignment)

- Build each player's length-N total-wins vector.
- P(I win) = fraction of the N sims where my total is the max (**ties count as a win** for
  each tied player — co-champion rule).

### Recommending a pick (one-ply decision + rollout)

At my turn, for each available team *t*:

1. Tentatively add *t* to my roster.
2. **Roll the rest of the draft forward R ≈ 300 times.** The fixed pick order advances;
   opponent seats pick via the **high-entropy opponent policy**; my remaining slots are
   filled greedily by marginal P(win) contribution (heuristic — the full brain is not
   recursed inside rollouts).
3. Each rollout → complete assignment → P(I win) over the N-season matrix. Average over R.
4. Rank available teams by averaged P(I win).

The rollout encodes "will it come back to me?" *without* predicting specific opponents:
because opponent seats pick semi-randomly, a candidate's value already reflects the chance
it survives (and the chance a comparable team survives if we wait).

### Opponent model

The friends draft chaotically, so the honest model is **high-entropy**: opponents pick
semi-randomly from the board with only a mild lean toward high-win-total teams, governed by
a single **"chalkiness" knob** (default low). This is a pluggable interface
`pick(board, roster) → team`, shared by the live lookahead and the mock harness. Available
policies: pure Vegas-O/U chalk, power-rating chalk, high-entropy random.

### Interpretable "what complements my team" layer

Alongside the P(win) ranking, each candidate shows *why*, read straight off the sim matrix:

- **Δ expected wins** added to my total,
- **Δ standard deviation** of my total (widen vs. tighten my range),
- **correlation with my current roster** (negative = hedge/compress; positive = double down),
- **survival probability** to my next pick (flags a stud that won't last → "take now").

Because the objective is P(1st), the ranking automatically tilts toward variance when
rollouts show me trailing and toward hedges when I'm ahead — visible as the Δσ column
flipping sign as the draft progresses.

### Cost

~20 candidates × ~300 rollouts × O(N) vectorized ≈ well under a second per turn; trivial to
precompute for mock studies.

## 7. Mock-draft harness (`mock.py`)

Same brain, driven programmatically. Reuses the sim matrix (layer 3) and ranking logic
(layer 4) verbatim; only new code is the loop advancing the fixed order and swapping in an
opponent policy.

1. **Positional-value study (pure sim).** Run K full auto-drafts where *I* draft optimally
   from each slot P1…P6 while the other five seats use a chosen opponent model. Aggregate
   my P(win) by starting slot → "which draft position is best, and how much does the slot I
   randomly draw actually matter?"
2. **Interactive practice draft.** I play a full mock; the brain advises my picks; the other
   five seats are either auto-piloted by a selectable scoring model or manually entered by
   me to rehearse a specific scenario.

## 8. Backend API (FastAPI)

Loads the precomputed N×32 matrix + ratings on startup. Heavy numpy stays server-side;
responses are small JSON.

- `GET /board` — teams, ratings, current draft state.
- `POST /pick` — log a pick (mine or anyone's); advances state.
- `GET /recommend` — run rollouts server-side; return ranked table
  (P(win), Δwins, Δσ, correlation, survival %).
- `POST /mock/positional` — positional-value study.
- `POST /mock/practice` — step an interactive practice draft.

## 9. Front end (React, Vite + TypeScript) — three screens

Disposable/iterable without touching the model.

1. **Setup** — choose my drawn slot (P1–P6); confirm the 32-team board and ratings;
   calibration check of each team's simulated win distribution vs. Vegas O/U.
2. **Live draft** (primary) — board of all 32 teams color-coded (available / mine / each
   opponent); the fixed pick order with a marker on whose clock it is and a countdown to my
   next pick; on my turn, the ranked recommendation table; one click logs any pick and the
   board updates; a running **"P(I win the pool)"** at the top that moves with every pick.
3. **Mock lab** — positional-value study (bar chart of P(win) by starting slot) and the
   interactive practice draft.

Screens will be iterated once reached.

## 10. Honest limitations

- **The market is efficient.** Our edge over a friend drafting straight off Vegas O/U comes
  almost entirely from (a) correctly exploiting correlation/variance for the winner-take-all
  objective, and (b) the modest disagreements the power-rating blend introduces — **not**
  from out-predicting Vegas on any single team's win total. (a) is the real edge; we should
  not fool ourselves that (b) is large.
- Opponent behavior is modeled as high-entropy uncertainty, not prediction. The tool
  estimates *survival probabilities*, not what a specific friend will do.

## 11. Testing approach

- **Ratings:** market back-out reproduces posted O/U within tolerance; blend endpoints
  (w=0, w=1) behave.
- **Sim:** calibration invariants (7-pt favorite ≈ 70%); each team's mean sim wins tracks
  its Vegas O/U; division rivals show negative win-total correlation.
- **Draft brain:** additive-scoring vectorization matches a brute-force reference on a small
  case; P(win) sums sensibly across 6 players; variance-seeking behavior appears when
  trailing in a constructed scenario.
- **Mock harness:** deterministic under a fixed RNG seed; positional study is reproducible.

## 12. Build order (for the implementation plan)

1. Data layer + caching.
2. Ratings (market back-out + blend).
3. Sim engine + calibration tests.
4. Draft brain (objective eval → rollout recommendation) + tests.
5. Mock harness.
6. FastAPI backend.
7. React front end (Setup → Live draft → Mock lab).
