import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ALA — Autonomous Legal Agent",
  description:
    "Otak hukum otonom — membangun pemahaman hukum Indonesia dari nol data",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="id">
      <body className="m-0 min-h-screen overflow-hidden bg-black font-sans antialiased">
        {children}
      </body>
    </html>
  );
}
