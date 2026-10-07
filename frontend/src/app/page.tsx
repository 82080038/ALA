"use client";

import useSWR from "swr";
import {
  fetchAlcdStatus,
  fetchSystemStatus,
  API_BASE_URL,
} from "@/lib/api-client";
import { useSession } from "@/lib/session";
import { cn } from "@/lib/utils";

interface Health {
  status: string;
  ollama_status: string;
  hardware?: { cuda_device_count?: number; ollama_num_ctx?: number };
}

export default function DashboardPage() {
  const { identity, hydrated } = useSession();

  const { data: status } = useSWR(
    hydrated ? "system-status" : null,
    () => fetchSystemStatus(identity),
    { refreshInterval: 15000 }
  );
  const { data: alcd } = useSWR(
    hydrated ? "alcd-status" : null,
    () => fetchAlcdStatus(identity),
    { refreshInterval: 15000 }
  );
  const { data: health } = useSWR<Health>(
    hydrated ? "health" : null,
    () => fetch(`${API_BASE_URL}/health`).then((r) => r.json()),
    { refreshInterval: 30000 }
  );

  const score = Math.round((status?.knowledge_score ?? 0) * 100);

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-2xl font-semibold tracking-tight">
          Dashboard Utama
        </h2>
        <p className="text-muted-foreground">
          Status real-time pipeline 4-agen dan basis pengetahuan hukum GLOBAL.
        </p>
      </section>

      <div className="grid gap-4 md:grid-cols-4">
        <StatCard
          label="Kesiapan Pengetahuan"
          value={`${score}%`}
          hint={
            status?.knowledge_ready
              ? "ALCD siap menerima query"
              : "ALCD masih membangun corpus"
          }
          tone={status?.knowledge_ready ? "ok" : "warn"}
        />
        <StatCard
          label="UU Ter-ingest"
          value={String(alcd?.laws_ingested ?? status?.laws_ingested ?? 0)}
          hint={`${alcd?.total_chunks ?? 0} chunk di ChromaDB GLOBAL`}
        />
        <StatCard
          label="Node Ontologi"
          value={String(alcd?.ontology_nodes ?? 0)}
          hint={`${alcd?.unresolved_gaps ?? 0} gap belum terselesaikan`}
        />
        <StatCard
          label="Ollama (LLM Lokal)"
          value={health?.ollama_status ?? "…"}
          hint={`${health?.hardware?.cuda_device_count ?? 0} GPU · ctx ${
            health?.hardware?.ollama_num_ctx ?? "…"
          }`}
          tone={health?.ollama_status === "connected" ? "ok" : "warn"}
        />
      </div>

      <section className="rounded-lg border bg-card p-6">
        <h3 className="font-semibold">Cara Pakai</h3>
        <ol className="mt-3 list-decimal space-y-1 pl-5 text-sm text-muted-foreground">
          <li>
            Pilih <b>role</b>, <b>tier</b>, dan <b>Institution ID</b> di pojok
            kanan atas (header-based auth; JWT menyusul).
          </li>
          <li>
            Buka <b>Analisis Tren</b>, kirim query investigasi — pipeline
            menjalankan ALCD → Legal Foundation → Crawler → Synthesis.
          </li>
          <li>
            Kode yang dihasilkan AI memerlukan persetujuan manusia
            (human-in-the-loop) sebelum dieksekusi di sandbox terkunci.
          </li>
          <li>
            Semua aktivitas tercatat di <b>Audit Log</b> (append-only, RLS
            per-institusi) termasuk checksum SHA-256 bukti.
          </li>
        </ol>
      </section>
    </div>
  );
}

function StatCard({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: string;
  hint: string;
  tone?: "ok" | "warn";
}) {
  return (
    <div className="rounded-lg border bg-card p-6 shadow-sm">
      <h3 className="text-sm font-medium text-muted-foreground">{label}</h3>
      <p
        className={cn(
          "mt-2 text-3xl font-bold",
          tone === "ok" && "text-green-600",
          tone === "warn" && "text-amber-600"
        )}
      >
        {value}
      </p>
      <p className="text-sm text-muted-foreground">{hint}</p>
    </div>
  );
}
