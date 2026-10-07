"use client";

/** Kasus — data operasional tenant (RLS per institution_id). */
import { useState } from "react";
import useSWR from "swr";
import { createCase, fetchCases } from "@/lib/api-client";
import { useSession } from "@/lib/session";

export default function CasesPage() {
  const { identity, hydrated } = useSession();
  const [form, setForm] = useState({
    title: "",
    case_number: "",
    crime_type: "",
    priority: "medium",
  });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const { data, mutate } = useSWR(
    hydrated ? "cases" : null,
    () => fetchCases(identity),
    { refreshInterval: 20000 }
  );

  const submit = async () => {
    if (form.title.trim().length < 3) return;
    setBusy(true);
    setError(null);
    try {
      await createCase(identity, {
        title: form.title.trim(),
        case_number: form.case_number || undefined,
        crime_type: form.crime_type || undefined,
        priority: form.priority,
      });
      setForm({ title: "", case_number: "", crime_type: "", priority: "medium" });
      mutate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Gagal membuat kasus");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-2xl font-semibold tracking-tight">Kasus</h2>
        <p className="text-muted-foreground">
          Data operasional institusi — terisolasi oleh PostgreSQL RLS per
          <code className="mx-1">institution_id</code>.
        </p>
      </section>

      <section className="grid gap-2 rounded-lg border bg-card p-5 md:grid-cols-5">
        <input
          className="rounded border bg-background px-3 py-2 text-sm md:col-span-2"
          placeholder="Judul kasus *"
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
        />
        <input
          className="rounded border bg-background px-3 py-2 text-sm"
          placeholder="No. perkara"
          value={form.case_number}
          onChange={(e) => setForm({ ...form, case_number: e.target.value })}
        />
        <input
          className="rounded border bg-background px-3 py-2 text-sm"
          placeholder="Jenis kejahatan"
          value={form.crime_type}
          onChange={(e) => setForm({ ...form, crime_type: e.target.value })}
        />
        <button
          onClick={submit}
          disabled={busy || form.title.trim().length < 3}
          className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          Tambah
        </button>
      </section>
      {error && <p className="text-sm text-destructive">{error}</p>}

      <section className="rounded-lg border bg-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="p-3">Judul</th>
              <th className="p-3">No. Perkara</th>
              <th className="p-3">Jenis</th>
              <th className="p-3">Status</th>
              <th className="p-3">Prioritas</th>
              <th className="p-3">Dibuat</th>
            </tr>
          </thead>
          <tbody>
            {(data?.cases ?? []).map((c) => (
              <tr key={c.id} className="border-b last:border-0">
                <td className="p-3">{c.title}</td>
                <td className="p-3 font-mono text-xs">{c.case_number || "—"}</td>
                <td className="p-3">{c.crime_type || "—"}</td>
                <td className="p-3">{c.status}</td>
                <td className="p-3">{c.priority}</td>
                <td className="p-3 text-xs text-muted-foreground">
                  {c.created_at?.slice(0, 10)}
                </td>
              </tr>
            ))}
            {(data?.cases.length ?? 0) === 0 && (
              <tr>
                <td colSpan={6} className="p-6 text-center text-muted-foreground">
                  Belum ada kasus untuk institusi ini.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
    </div>
  );
}
