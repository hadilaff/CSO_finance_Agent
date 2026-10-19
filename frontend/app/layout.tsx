import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CSO Intelligence Agent",
  description:
    "Strategic intelligence for a Chief Strategy Officer — RAG, live web search, market data, and forecasting.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
