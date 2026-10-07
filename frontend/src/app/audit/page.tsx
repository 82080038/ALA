"use client";

/** Audit Log — append-only, RLS per tenant, chain-of-custody SHA-256. */
import useSWR from "swr";
import { fetchAuditLogs } from "@/lib/api-client";
import { useSession } from "@/lib/session";
import AuditLogs from "@/components/audit-logs";

export default function AuditPage() {
  const { identity, hydrated } = useSession();
  const { data } = useSWR(
    hydrated ? "audit-logs" : null,
    () => fetchAuditLogs(identity, 100),
    { refreshInterval: 15000 }
  );

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-2xl font-semibold tracking-tight">
          Audit Log Immutable
        </h2>
        <p className="text-muted-foreground">
          Append-only (UPDATE/DELETE dicabut dari role aplikasi). Checksum
          SHA-256 bukti dicatat untuk kepatuhan KUHAP.
        </p>
      </section>

      <AuditLogs logs={data?.logs ?? []} />
    </div>
  );
}
