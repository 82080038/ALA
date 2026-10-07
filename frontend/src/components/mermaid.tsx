"use client";

/** Render diagram Mermaid (flowchart hasil Agent 3) di sisi klien. */
import { useEffect, useRef, useState } from "react";
import mermaid from "mermaid";

mermaid.initialize({ startOnLoad: false, theme: "neutral" });

export default function Mermaid({ chart }: { chart: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setError(false);
    if (ref.current && chart.trim()) {
      mermaid
        .render(`mmd-${Math.random().toString(36).slice(2)}`, chart)
        .then(({ svg }) => {
          if (!cancelled && ref.current) ref.current.innerHTML = svg;
        })
        .catch(() => setError(true));
    }
    return () => {
      cancelled = true;
    };
  }, [chart]);

  if (error)
    return (
      <pre className="overflow-x-auto rounded bg-muted p-3 text-xs">
        {chart}
      </pre>
    );
  return <div ref={ref} className="overflow-x-auto" />;
}
