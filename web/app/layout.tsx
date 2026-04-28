import "./globals.css";
import Link from "next/link";
import { ReactNode } from "react";

export const metadata = {
  title: "NetSuite Docs Hub",
  description: "Documentation vivante du compte NetSuite NDK",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="fr">
      <body className="min-h-screen flex flex-col">
        <header className="border-b">
          <div className="max-w-6xl mx-auto px-6 py-4 flex items-center justify-between">
            <Link href="/" className="font-semibold text-lg">
              NetSuite Docs Hub
            </Link>
            <nav className="flex gap-6 text-sm text-muted-foreground">
              <Link href="/search" className="hover:text-foreground font-medium text-foreground">🔍 Search</Link>
              <Link href="/scripts" className="hover:text-foreground">Scripts</Link>
              <Link href="/deployments" className="hover:text-foreground">Deployments</Link>
              <Link href="/fields" className="hover:text-foreground">Custom fields</Link>
              <Link href="/custom-records" className="hover:text-foreground">Custom records</Link>
              <Link href="/changes" className="hover:text-foreground">Changes</Link>
            </nav>
          </div>
        </header>
        <main className="flex-1 max-w-6xl mx-auto w-full px-6 py-8">
          {children}
        </main>
        <footer className="border-t mt-12">
          <div className="max-w-6xl mx-auto px-6 py-4 text-xs text-muted-foreground">
            POC interne NDK — données extraites du sandbox NetSuite
          </div>
        </footer>
      </body>
    </html>
  );
}
