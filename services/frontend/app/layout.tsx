import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Research Agent",
  description: "A deep agent that reaches its tools over MCP.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
