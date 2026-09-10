// web/src/components/Login.tsx
import { useEffect, useState } from 'react';
import { HttpError, login, PLAYERS } from '../league';

export default function Login({ onDone }: { onDone: () => void }) {
  const [name, setName] = useState<string | null>(null);
  const [pin, setPin] = useState('');
  const [bad, setBad] = useState(false);
  // Seconds left on the server's login backoff. Without this the form just
  // shakes and a locked-out player keeps guessing, extending their own lockout.
  const [wait, setWait] = useState(0);

  useEffect(() => {
    if (wait <= 0) return;
    const id = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(id);
  }, [wait]);

  async function submit() {
    if (!name || wait > 0) return;
    try {
      await login(name, pin);
      onDone();
    } catch (e) {
      if (e instanceof HttpError && e.retryAfter) setWait(e.retryAfter);
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
      <button className="btn primary" disabled={!name || !pin || wait > 0} onClick={submit}>
        {wait > 0 ? `Try again in ${wait}s` : 'Enter'}
      </button>
    </div>
  );
}
