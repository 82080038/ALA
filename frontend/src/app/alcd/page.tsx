"use client";

/** Konsol ALCD — pohon ontologi, gap pengetahuan, dan trigger bootstrap. */
import { useState } from "react";
import useSWR from "swr";
import {
  fetchAlcdStatus,
  fetchGaps,
  fetchOntology,
  triggerAlcd,
} from "@/lib/api-client";
import { useSession } from "@/lib/session";
import OntologyGraph from "@/components/ontology-graph";

export default function AlcdPage() {
  const { identity, hydrated } = useSession();
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const { data: status, mutate } = useSWR(
    hydrated ? "alcd-status" : null,
    () => fetchAlcdStatus(identity),
    { refreshInterval: 20000 }
  );
  const { data: onto } = useSWR(hydrated ? "alcd-ontology" : null, () =>
    fetchOntology(identity)
  );
  const { data: gaps } = useSWR(hydrated ? "alcd-gaps" : null, () =>
    fetchGaps(identity)
  );

  const trigger = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await triggerAlcd(identity);
      setMsg(`Bootstrap selesai: ${JSON.stringify(r).slice(0, 300)}`);
      mutate();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Trigger gagal");
    } finally {
      setBusy(false);
    }
  };

  // Ontologi dirender oleh <OntologyGraph>

  return (
    <div className="space-y-6">
      <section className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-2xl font-semibold tracking-tight">
            ALCD — Autonomous Legal Curriculum Designer
          </h2>
          <p className="text-muted-foreground">
            Basis pengetahuan hukum GLOBAL — dibagikan ke semua institusi.
          </p>
        </div>
        <button
          onClick={trigger}
          disabled={busy}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {busy ? "Bootstrap berjalan…" : "Picu Bootstrap"}
        </button>
      </section>
      {msg && (
        <p className="rounded border bg-muted p-3 font-mono text-xs">{msg}</p>
      )}

      <div className="grid gap-4 md:grid-cols-4">
        {[
          ["Skor Pengetahuan", `${Math.round((status?.knowledge_score ?? 0) * 100)}%`],
          ["Node Ontologi", String(status?.ontology_nodes ?? 0)],
          ["UU Ter-ingest", String(status?.laws_ingested ?? 0)],
          ["Gap Terbuka", String(status?.unresolved_gaps ?? 0)],
        ].map(([l, v]) => (
          <div key={l} className="rounded-lg border bg-card p-5">
            <p className="text-sm text-muted-foreground">{l}</p>
            <p className="mt-1 text-2xl font-bold">{v}</p>
          </div>
        ))}
      </div>

      <section className="rounded-lg border bg-card p-6">
        <h3 className="mb-4 font-semibold">Pohon Ontologi</h3>
        <OntologyGraph nodes={onto?.nodes ?? []} />
      </section>

      <section className="rounded-lg border bg-card p-6">
        <h3 className="mb-3 font-semibold">
          Gap Pengetahuan ({gaps?.gaps.length ?? 0})
        </h3>
        {(gaps?.gaps.length ?? 0) === 0 ? (
          <p className="text-sm text-muted-foreground">
            Tidak ada gap terbuka.
          </p>
        ) : (
          <ul className="space-y-2 text-sm">
            {gaps!.gaps.map((g) => (
              <li key={g.id} className="rounded border p-3">
                <p className="font-medium">{g.question}</p>
                <p className="text-xs text-muted-foreground">
                  kualitas jawaban {Math.round(g.answer_quality * 100)}% ·{" "}
                  {g.gap_description}
                </p>
                {g.remediation_action && (
                  <p className="mt-1 text-xs text-blue-600">
                    → {g.remediation_action}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
