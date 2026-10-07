"use client";

/**
 * Analisis Tren — kirim query ke pipeline 4-agen, tampilkan hasil,
 * lalu minta persetujuan manusia sebelum kode AI dieksekusi di sandbox.
 */
import { useState } from "react";
import {
  analyzeTrend,
  approveWorkflow,
  type AnalysisResult,
  type ExecutionResult,
} from "@/lib/api-client";
import { useSession } from "@/lib/session";
import Mermaid from "@/components/mermaid";

export default function AnalyzePage() {
  const { identity } = useSession();
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<AnalysisResult | null>(null);
  const [exec, setExec] = useState<ExecutionResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    if (query.trim().length < 3) return;
    setBusy(true);
    setError(null);
    setResult(null);
    setExec(null);
    try {
      setResult(await analyzeTrend(identity, query.trim()));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Pipeline gagal");
    } finally {
      setBusy(false);
    }
  };

  const decide = async (approved: boolean) => {
    if (!result) return;
    setBusy(true);
    try {
      setExec(await approveWorkflow(identity, result.request_id, approved));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Approval gagal");
    } finally {
      setBusy(false);
    }
  };

  const gen = result?.generated_output;

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-2xl font-semibold tracking-tight">Analisis Tren</h2>
        <p className="text-muted-foreground">
          Query dijalankan melalui pipeline: ALCD → Legal Foundation → Internet
          Crawler → Synthesis &amp; Developer.
        </p>
      </section>

      <div className="flex gap-2">
        <textarea
          className="min-h-20 flex-1 rounded-lg border bg-background p-3 text-sm"
          placeholder="Contoh: modus pencucian uang melalui cryptocurrency"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button
          onClick={run}
          disabled={busy || query.trim().length < 3}
          className="self-end rounded-lg bg-primary px-5 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {busy ? "Memproses…" : "Analisis"}
        </button>
      </div>
      {busy && !exec && (
        <p className="text-sm text-muted-foreground">
          Pipeline sedang berjalan — dapat memakan waktu beberapa menit pada
          bootstrap pertama.
        </p>
      )}
      {error && (
        <p className="rounded-lg border border-destructive/50 bg-destructive/10 p-3 text-sm text-destructive">
          {error}
        </p>
      )}

      {result && (
        <div className="space-y-6">
          <section className="grid gap-4 md:grid-cols-3">
            <Card title="Ringkasan Hukum">
              <p className="whitespace-pre-wrap text-sm">
                {result.legal_summary || "—"}
              </p>
            </Card>
            <Card title={`Pasal Relevan (${result.legal_articles.length})`}>
              <ul className="space-y-1 text-sm">
                {result.legal_articles.slice(0, 8).map((a, i) => (
                  <li key={i}>
                    <b>{a.law_name}</b> {a.article_number}{" "}
                    <span className="text-muted-foreground">
                      ({a.relevance_score?.toFixed(2)})
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
            <Card title={`Sumber Tren (${result.crime_data.length})`}>
              <p className="mb-2 text-sm">{result.crime_summary || "—"}</p>
              <ul className="space-y-1 text-xs">
                {result.crime_data.slice(0, 5).map((c, i) => (
                  <li key={i}>
                    <a
                      className="text-blue-600 underline"
                      href={c.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {c.title}
                    </a>
                  </li>
                ))}
              </ul>
            </Card>
          </section>

          {result.errors.length > 0 && (
            <Card title="Catatan Pipeline">
              <ul className="list-disc pl-5 text-xs text-muted-foreground">
                {result.errors.map((e, i) => (
                  <li key={i}>{e}</li>
                ))}
              </ul>
            </Card>
          )}

          {gen?.code && (
            <section className="space-y-3 rounded-lg border bg-card p-6">
              <div className="flex items-center justify-between">
                <h3 className="font-semibold">
                  Kode Hasil AI — {gen.filename || "utility.py"}
                </h3>
                {!exec && (
                  <div className="flex gap-2">
                    <button
                      onClick={() => decide(true)}
                      disabled={busy}
                      className="rounded bg-green-600 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                    >
                      Setujui &amp; Jalankan
                    </button>
                    <button
                      onClick={() => decide(false)}
                      disabled={busy}
                      className="rounded bg-destructive px-4 py-1.5 text-sm font-medium text-destructive-foreground disabled:opacity-50"
                    >
                      Tolak
                    </button>
                  </div>
                )}
              </div>
              {gen.description && (
                <p className="text-sm text-muted-foreground">
                  {gen.description}
                </p>
              )}
              <pre className="max-h-96 overflow-auto rounded bg-muted p-4 text-xs">
                <code>{gen.code}</code>
              </pre>
              {gen.flowchart && <Mermaid chart={gen.flowchart} />}
              {result.requires_approval && !exec && (
                <p className="text-xs text-amber-600">
                  ⚠ Eksekusi memerlukan persetujuan manusia — kode dipindai
                  ulang guardrail lalu berjalan di sandbox tanpa jaringan.
                </p>
              )}
            </section>
          )}

          {exec && (
            <section className="rounded-lg border bg-card p-6">
              <h3 className="font-semibold">
                Hasil Eksekusi —{" "}
                <span
                  className={
                    exec.status === "executed"
                      ? "text-green-600"
                      : "text-destructive"
                  }
                >
                  {exec.status}
                </span>
              </h3>
              {exec.guardrail_violations?.length ? (
                <ul className="mt-2 list-disc pl-5 text-sm text-destructive">
                  {exec.guardrail_violations.map((v, i) => (
                    <li key={i}>{v}</li>
                  ))}
                </ul>
              ) : null}
              {exec.stdout && (
                <pre className="mt-3 max-h-60 overflow-auto rounded bg-muted p-3 text-xs">
                  {exec.stdout}
                </pre>
              )}
              {exec.stderr && (
                <pre className="mt-2 max-h-40 overflow-auto rounded bg-destructive/10 p-3 text-xs text-destructive">
                  {exec.stderr}
                </pre>
              )}
              <p className="mt-2 text-xs text-muted-foreground">
                exit={exec.exit_code} timeout={String(exec.timed_out)}
              </p>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

function Card({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-lg border bg-card p-5">
      <h3 className="mb-2 font-semibold">{title}</h3>
      {children}
    </div>
  );
}
