import type { Metadata } from "next";
import type { ReactNode } from "react";

import { ThemeProvider } from "@/components/ThemeProvider";

import "./globals.css";

export const metadata: Metadata = {
  title: "EnclaveRAG — Zero-Trust Multi-Tenant Enterprise RAG",
  description: "Database-enforced clearance control with PostgreSQL RLS & pgvector",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen antialiased">
        <ThemeProvider>{children}</ThemeProvider>
      </body>
    </html>
  );
}
