"use client";

/** Pemilih identitas pengguna — header-based auth sampai JWT tersedia. */
import { ROLES, TIERS, useSession, type Role, type Tier } from "@/lib/session";

export default function IdentitySelector() {
  const { identity, setIdentity, hydrated } = useSession();
  if (!hydrated) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs">
      <select
        aria-label="Role pengguna"
        className="rounded border bg-background px-2 py-1"
        value={identity.role}
        onChange={(e) => setIdentity({ role: e.target.value as Role })}
      >
        {ROLES.map((r) => (
          <option key={r} value={r}>
            {r}
          </option>
        ))}
      </select>
      <select
        aria-label="Tier akses"
        className="rounded border bg-background px-2 py-1"
        value={identity.tier}
        onChange={(e) => setIdentity({ tier: e.target.value as Tier })}
      >
        {TIERS.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>
      <input
        aria-label="Institution ID"
        className="w-72 rounded border bg-background px-2 py-1 font-mono"
        placeholder="X-Institution-ID (UUID)"
        value={identity.institutionId}
        onChange={(e) => setIdentity({ institutionId: e.target.value.trim() })}
      />
    </div>
  );
}
