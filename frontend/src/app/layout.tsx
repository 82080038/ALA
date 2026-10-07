import type { Metadata } from "next";
import "./globals.css";
import { SessionProvider } from "@/lib/session";
import IdentitySelector from "@/components/identity-selector";
import Nav from "@/components/nav";

export const metadata: Metadata = {
  title: "ALA — Autonomous Legal Agent",
  description:
    "Dashboard sistem intelijen hukum otonom untuk Aparat Penegak Hukum (APH) Indonesia",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="id">
      <body className="min-h-screen bg-background font-sans antialiased">
        <SessionProvider>
          <div className="flex min-h-screen flex-col">
            <header className="flex flex-wrap items-center justify-between gap-3 border-b px-6 py-4">
              <div>
                <h1 className="text-xl font-bold tracking-tight">
                  ALA — Autonomous Legal Agent
                </h1>
                <p className="text-sm text-muted-foreground">
                  Sistem Intelijen Hukum Otonom untuk APH Indonesia
                </p>
              </div>
              <IdentitySelector />
            </header>
            <Nav />
            <main className="flex-1 p-6">{children}</main>
          </div>
        </SessionProvider>
      </body>
    </html>
  );
}
