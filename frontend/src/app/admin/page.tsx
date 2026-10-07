"use client";

/** Konsol Super Admin — institusi, pengguna, fitur, dan tier. */
import { useState } from "react";
import useSWR from "swr";
import {
  createInstitution,
  fetchFeatures,
  fetchInstitutions,
  fetchUsers,
  overrideFeatureTier,
  setUserTier,
  toggleFeature,
} from "@/lib/api-client";
import { TIERS, useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

const INST_TYPES = ["kepolisian", "kejaksaan", "pengadilan"];

export default function AdminPage() {
  const { identity, hydrated } = useSession();
  const isAdmin = identity.role === "super_admin";
  const [instForm, setInstForm] = useState({ name: "", type: INST_TYPES[0] });
  const [msg, setMsg] = useState<string | null>(null);

  const { data: insts, mutate: mutInst } = useSWR(
    hydrated && isAdmin ? "admin-inst" : null,
    () => fetchInstitutions(identity)
  );
  const { data: users, mutate: mutUsers } = useSWR(
    hydrated && isAdmin ? "admin-users" : null,
    () => fetchUsers(identity)
  );
  const { data: feats, mutate: mutFeats } = useSWR(
    hydrated && isAdmin ? "admin-feats" : null,
    () => fetchFeatures(identity)
  );

  if (!hydrated) return null;
  if (!isAdmin)
    return (
      <p className="rounded-lg border border-destructive/50 bg-destructive/10 p-6 text-sm text-destructive">
        Akses ditolak — pilih role <b>super_admin</b> di pojok kanan atas.
      </p>
    );

  const act = async (fn: () => Promise<unknown>, refresh?: () => void) => {
    setMsg(null);
    try {
      await fn();
      refresh?.();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Aksi gagal");
    }
  };

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-2xl font-semibold tracking-tight">
          Konsol Super Admin
        </h2>
        <p className="text-muted-foreground">
          Manajemen institusi, pengguna, fitur SaaS, dan override tier.
        </p>
      </section>
      {msg && <p className="text-sm text-destructive">{msg}</p>}

      {/* Institusi */}
      <section className="rounded-lg border bg-card p-6">
        <h3 className="mb-3 font-semibold">
          Institusi ({insts?.institutions.length ?? 0})
        </h3>
        <div className="mb-3 flex gap-2">
          <input
            className="flex-1 rounded border bg-background px-3 py-2 text-sm"
            placeholder="Nama institusi"
            value={instForm.name}
            onChange={(e) => setInstForm({ ...instForm, name: e.target.value })}
          />
          <select
            className="rounded border bg-background px-3 py-2 text-sm"
            value={instForm.type}
            onChange={(e) => setInstForm({ ...instForm, type: e.target.value })}
          >
            {INST_TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <button
            className="rounded bg-primary px-4 py-2 text-sm text-primary-foreground disabled:opacity-50"
            disabled={instForm.name.trim().length < 2}
            onClick={() =>
              act(
                () =>
                  createInstitution(identity, instForm.name.trim(), instForm.type),
                mutInst
              )
            }
          >
            Tambah
          </button>
        </div>
        <table className="w-full text-sm">
          <tbody>
            {(insts?.institutions ?? []).map((i) => (
              <tr key={i.id} className="border-b last:border-0">
                <td className="p-2">{i.name}</td>
                <td className="p-2 text-xs">{i.type}</td>
                <td className="p-2 font-mono text-xs">{i.id.slice(0, 8)}…</td>
                <td className="p-2 text-xs">{i.user_count} pengguna</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* Pengguna */}
      <section className="overflow-x-auto rounded-lg border bg-card p-6">
        <h3 className="mb-3 font-semibold">
          Pengguna ({users?.users.length ?? 0})
        </h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="p-2">Nama</th>
              <th className="p-2">Role</th>
              <th className="p-2">Institusi</th>
              <th className="p-2">Tier</th>
            </tr>
          </thead>
          <tbody>
            {(users?.users ?? []).map((u) => (
              <tr key={u.id} className="border-b last:border-0">
                <td className="p-2">
                  {u.name}
                  <span className="block text-xs text-muted-foreground">
                    {u.email}
                  </span>
                </td>
                <td className="p-2 text-xs">{u.role}</td>
                <td className="p-2 font-mono text-xs">
                  {u.institution_id.slice(0, 8)}…
                </td>
                <td className="p-2">
                  <select
                    className="rounded border bg-background px-2 py-1 text-xs"
                    value={u.tier_level}
                    onChange={(e) =>
                      act(() => setUserTier(identity, u.id, e.target.value), mutUsers)
                    }
                  >
                    {TIERS.map((t) => (
                      <option key={t}>{t}</option>
                    ))}
                  </select>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {/* Fitur */}
      <section className="overflow-x-auto rounded-lg border bg-card p-6">
        <h3 className="mb-3 font-semibold">
          Fitur SaaS ({feats?.features.length ?? 0})
        </h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="p-2">Fitur</th>
              <th className="p-2">Saran AI</th>
              <th className="p-2">Tier Wajib</th>
              <th className="p-2">Aktif</th>
            </tr>
          </thead>
          <tbody>
            {(feats?.features ?? []).map((f) => (
              <tr key={f.id} className="border-b last:border-0">
                <td className="p-2">
                  {f.name}
                  {f.is_ai_generated && (
                    <span className="ml-2 rounded bg-muted px-1.5 py-0.5 text-[10px]">
                      AI
                    </span>
                  )}
                </td>
                <td className="p-2 text-xs">{f.ai_suggested_tier || "—"}</td>
                <td className="p-2">
                  <select
                    className="rounded border bg-background px-2 py-1 text-xs"
                    value={f.required_tier}
                    onChange={(e) =>
                      act(
                        () => overrideFeatureTier(identity, f.id, e.target.value),
                        mutFeats
                      )
                    }
                  >
                    {TIERS.map((t) => (
                      <option key={t}>{t}</option>
                    ))}
                  </select>
                </td>
                <td className="p-2">
                  <button
                    onClick={() => act(() => toggleFeature(identity, f.id), mutFeats)}
                    className={cn(
                      "rounded px-2 py-1 text-xs font-medium",
                      f.is_active
                        ? "bg-green-100 text-green-700"
                        : "bg-muted text-muted-foreground"
                    )}
                  >
                    {f.is_active ? "aktif" : "nonaktif"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
