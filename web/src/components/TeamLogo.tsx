// web/src/components/TeamLogo.tsx
import { useEffect, useState } from 'react';
import { logoUrl } from '../logo';

export default function TeamLogo({ code, size }: { code: string; size: number }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [code]);

  return (
    <span style={{ width: size, height: size, display: 'inline-block' }}>
      {!failed && (
        <img
          className="tlogo"
          src={logoUrl(code)}
          alt=""
          width={size}
          height={size}
          loading="lazy"
          onError={() => setFailed(true)}
        />
      )}
    </span>
  );
}
