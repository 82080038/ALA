"use client";

/** Pemilih identitas pengguna — header-based auth sampai JWT tersedia. */
import useSWR from "swr";
import { fetchInstitutionOptions } from "@/lib/api-client";
import { ROLES, TIERS, useSession, type Role, type Tier } from "@/lib/session";

export default function IdentitySelector() {
  const { identity, setIdentity, hydrated } = useSession();
  const { data } = useSWR(
    hydrated ? "institution-options" : null,
    () => fetchInstitutionOptions(identity),
    { refreshInterval: 60000 }
  );

  if (!hydrated) return null;
  const institutions = data?.institutions ?? [];
  const known = institutions.some((i) => i.id === identity.institutionId);

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
      <select
        aria-label="Institusi"
        className="rounded border bg-background px-2 py-1"
        value={known ? identity.institutionId : ""}
        onChange={(e) => setIdentity({ institutionId: e.target.value })}
      >
        <option value="">— pilih institusi —</option>
        {institutions.map((i) => (
          <option key={i.id} value={i.id}>
            {i.name}
          </option>
        ))}
        {/* Pertahankan nilai tersimpan yang tidak ada di daftar (mis.
            institusi dinonaktifkan) agar tidak hilang diam-diam. */}
        {!known && identity.institutionId && (
          <option value={identity.institutionId}>
            {identity.institutionId.slice(0, 8)}… (tidak terdaftar)
          </option>
        )}
      </select>
      {identity.institutionId && !known && (
        <span className="text-amber-600">institusi tidak valid</span>
      )}
    </div>
  );
}
