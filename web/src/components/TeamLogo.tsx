// web/src/components/TeamLogo.tsx
import { logoUrl } from '../logo';

export default function TeamLogo({ code, size }: { code: string; size: number }) {
  return (
    <img
      className="tlogo"
      src={logoUrl(code)}
      alt=""
      width={size}
      height={size}
      loading="lazy"
      onError={(e) => { e.currentTarget.style.visibility = 'hidden'; }}
    />
  );
}
