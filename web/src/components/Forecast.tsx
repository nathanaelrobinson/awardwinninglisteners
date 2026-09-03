import type { ForecastPick } from '../types';

interface Props {
  forecast: ForecastPick[];
  done: boolean;
}

export default function Forecast({ forecast, done }: Props) {
  if (done || forecast.length === 0) return null; // empty when it's already your pick
  return (
    <div className="forecast panel">
      <h3>Likely before your pick</h3>
      <div className="forecast-row">
        {forecast.map((f) => (
          <span key={f.pick} className="forecast-item">
            <span className="forecast-pick">P{f.player}</span>
            {f.code}
          </span>
        ))}
        <span className="forecast-you">→ YOU</span>
      </div>
    </div>
  );
}
