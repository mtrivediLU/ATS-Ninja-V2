import type { Metadata } from "next";
import { AppShell } from "@/components/shell/app-shell";
import { hankenGrotesk, ibmPlexMono } from "./fonts";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "ATS-Ninja",
    template: "%s · ATS-Ninja",
  },
  description:
    "Deterministic-first, truth-grounded AI career toolkit. Generate ATS-optimized application kits grounded in your real experience.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" data-theme="light">
      <body className={`${hankenGrotesk.variable} ${ibmPlexMono.variable}`}>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
