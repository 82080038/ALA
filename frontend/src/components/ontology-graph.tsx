"use client";

/**
 * Pohon Ontologi Hukum — dipakai halaman /alcd.
 * Node dikelompokkan per kategori dengan skor kesiapan berwarna.
 */
import type { OntologyNode } from "@/lib/api-client";
import { cn } from "@/lib/utils";

export default function OntologyGraph({ nodes }: { nodes: OntologyNode[] }) {
  const byCategory = nodes.reduce<Record<string, OntologyNode[]>>((acc, n) => {
    (acc[n.category] ||= []).push(n);
    return acc;
  }, {});

  if (nodes.length === 0)
    return (
      <p className="text-sm text-muted-foreground">
        Ontologi kosong — jalankan bootstrap ALCD.
      </p>
    );

  return (
    <div className="space-y-4">
      {Object.entries(byCategory).map(([cat, catNodes]) => (
        <div key={cat}>
          <h4 className="mb-1 text-sm font-semibold uppercase tracking-wide text-muted-foreground">
            {cat.replace(/_/g, " ")}
          </h4>
          <ul className="grid gap-1 md:grid-cols-2">
            {catNodes.map((n) => (
              <li
                key={n.id}
                className="flex items-center justify-between rounded border px-3 py-1.5 text-sm"
              >
                <span>
                  {n.subcategory}
                  <span className="ml-2 text-xs text-muted-foreground">
                    P{n.priority} · {n.laws_ingested} UU
                  </span>
                </span>
                <span
                  className={cn(
                    "text-xs font-medium",
                    n.knowledge_score >= 0.7
                      ? "text-green-600"
                      : n.knowledge_score >= 0.4
                        ? "text-amber-600"
                        : "text-destructive"
                  )}
                >
                  {Math.round(n.knowledge_score * 100)}%
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
