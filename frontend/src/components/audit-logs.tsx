"use client";

/**
 * Tabel Audit Log Immutable — dipakai halaman /audit.
 * Menampilkan checksum SHA-256 chain-of-custody bila tersedia.
 */
import type { AuditLog } from "@/lib/api-client";

export default function AuditLogs({ logs }: { logs: AuditLog[] }) {
  return (
    <div className="overflow-x-auto rounded-lg border bg-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-muted-foreground">
            <th className="p-3">Waktu</th>
            <th className="p-3">Aksi</th>
            <th className="p-3">Request ID</th>
            <th className="p-3">Query</th>
            <th className="p-3">SHA-256 (sebelum → sesudah)</th>
          </tr>
        </thead>
        <tbody>
          {logs.map((l) => (
            <tr key={l.id} className="border-b align-top last:border-0">
              <td className="whitespace-nowrap p-3 text-xs">
                {l.timestamp?.replace("T", " ").slice(0, 19)}
              </td>
              <td className="p-3">{l.action}</td>
              <td className="p-3 font-mono text-xs">
                {l.request_id.slice(0, 8)}…
              </td>
              <td className="max-w-64 truncate p-3 text-xs">
                {l.query_input || "—"}
              </td>
              <td className="p-3 font-mono text-[10px] leading-tight text-muted-foreground">
                {l.evidence_sha256_before ? (
                  <>
                    {l.evidence_sha256_before.slice(0, 16)}… →{" "}
                    {l.evidence_sha256_after?.slice(0, 16)}…
                  </>
                ) : (
                  "—"
                )}
              </td>
            </tr>
          ))}
          {logs.length === 0 && (
            <tr>
              <td colSpan={5} className="p-6 text-center text-muted-foreground">
                Belum ada entri audit.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
