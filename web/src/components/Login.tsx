// web/src/components/Login.tsx
import { useState } from 'react';
import { login, PLAYERS } from '../league';

export default function Login({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState<string | null>(null);
  const [pin, setPin] = useState('');
  const [bad, setBad] = useState(false);

  async function submit() {
    if (!name) return;
    try {
      await login(name, pin);
      onDone();
    } catch {
      setBad(true);
      setTimeout(() => setBad(false), 600);
    }
  }

  return (
    <div className="login">
      <img className="login-shield" src="/nfl.png" alt="" width={48} height={48} />
      <h1 className="login-title">Wins Pool 2026</h1>
      <div className="login-names">
        {PLAYERS.map((p) => (
          <button key={p} className={`login-name ${name === p ? 'on' : ''}`} onClick={() => setName(p)}>
            {p}
          </button>
        ))}
      </div>
      <input
        className={`login-pin ${bad ? 'shake' : ''}`}
        type="password"
        placeholder="PIN"
        value={pin}
        onChange={(e) => setPin(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && submit()}
      />
      <button className="btn primary" disabled={!name || !pin} onClick={submit}>
        Enter
      </button>
    </div>
  );
}
