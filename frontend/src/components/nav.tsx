"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";

const LINKS = [
  { href: "/", label: "Dashboard" },
  { href: "/analyze", label: "Analisis Tren" },
  { href: "/alcd", label: "ALCD" },
  { href: "/cases", label: "Kasus" },
  { href: "/audit", label: "Audit Log" },
  { href: "/admin", label: "Super Admin" },
];

export default function Nav() {
  const pathname = usePathname();
  return (
    <nav className="flex gap-1 border-b px-6 py-2">
      {LINKS.map((l) => (
        <Link
          key={l.href}
          href={l.href}
          className={cn(
            "rounded px-3 py-1.5 text-sm transition-colors",
            pathname === l.href
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:bg-muted"
          )}
        >
          {l.label}
        </Link>
      ))}
    </nav>
  );
}
