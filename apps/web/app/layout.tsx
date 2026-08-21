import type { ReactNode } from "react";
import Link from "next/link";

import "./globals.css";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "FinServGlobal Compliance",
  description: "Evidence-backed regulatory queries and transaction screening.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="site-header">
          <Link className="brand" href="/" aria-label="FinServGlobal home">
            <span className="brand-mark" aria-hidden="true">FG</span>
            <span>FinServGlobal</span>
          </Link>
          <nav aria-label="Primary navigation">
            <Link href="/">Regulatory query</Link>
            <Link href="/screen">Transaction screening</Link>
            <Link href="/reports">Compliance posture</Link>
          </nav>
        </header>
        {children}
        <footer>Decision support with clause-level evidence. Human review remains required.</footer>
      </body>
    </html>
  );
}
