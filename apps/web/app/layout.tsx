import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ATS-Ninja V2",
  description:
    "Deterministic-first, truth-grounded AI career toolkit. Generate ATS-optimized application kits grounded in your real experience.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">{children}</body>
    </html>
  );
}
