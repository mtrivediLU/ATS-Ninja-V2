"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { Check } from "lucide-react";
import { ArtifactTabs } from "@/components/shell/artifact-tabs";
import { EvidencePanel } from "@/components/shell/evidence-panel";
import { MobileBottomNav, MobileNavDrawer } from "@/components/shell/mobile-nav";
import { Sidebar } from "@/components/shell/sidebar";
import { WorkspaceHeader } from "@/components/shell/workspace-header";
import { Drawer } from "@/components/ui/drawer";
import { demoKit } from "@/lib/demo-data";
import { kitStatusPresentation } from "@/lib/status";

const screenMeta: Record<string, { title: string; meta?: string }> = {
  "/": { title: "New Kit", meta: "D0 foundation · disconnected placeholder" },
  "/history": { title: "Kit history", meta: "Synthetic foundation records" },
  "/components": { title: "Component foundation", meta: "Signal design-system reference" },
  "/settings": { title: "Local settings", meta: "Foundation preferences · not persisted" },
  "/states/processing": { title: "Generating kit…", meta: "kit_demo_processing · synthetic state" },
  "/states/error": { title: "Generation unavailable", meta: "Synthetic error-state demonstrations" },
};

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const results = pathname.startsWith("/kits/demo/");
  const hasCurrentKit = results;
  const [navOpen, setNavOpen] = useState(false);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [notice, setNotice] = useState("");

  useEffect(() => {
    setNavOpen(false);
    if (!results) setEvidenceOpen(false);
  }, [pathname, results]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 2600);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const closeEvidence = useCallback(() => setEvidenceOpen(false), []);
  const meta = useMemo(
    () =>
      results
        ? { title: `${demoKit.role} — ${demoKit.company}`, meta: `${demoKit.id} · ${demoKit.schemaVersion}` }
        : screenMeta[pathname] ?? { title: "ATS-Ninja", meta: "D0 foundation" },
    [pathname, results],
  );

  return (
    <div className="min-h-screen bg-canvas md:grid md:grid-cols-[64px_minmax(0,1fr)] lg:grid-cols-[248px_minmax(0,1fr)]">
      <a href="#main-content" className="sr-only z-[var(--z-toast)] rounded-control bg-accent px-4 py-2 text-on-accent focus:not-sr-only focus:fixed focus:left-4 focus:top-4">Skip to content</a>
      <Sidebar hasCurrentKit={hasCurrentKit} onOpenDrawer={() => setNavOpen(true)} onEvidence={() => setEvidenceOpen(true)} />
      <div className="flex min-h-screen min-w-0 flex-col">
        <WorkspaceHeader
          title={meta.title}
          meta={meta.meta}
          status={results ? kitStatusPresentation[demoKit.status] : undefined}
          results={results}
          evidenceOpen={evidenceOpen}
          onMenu={() => setNavOpen(true)}
          onEvidence={() => setEvidenceOpen((open) => !open)}
          onNotice={setNotice}
        />
        {results && <ArtifactTabs />}
        <div className="flex min-h-0 flex-1">
          <main id="main-content" className="min-w-0 flex-1 overflow-x-hidden px-4 py-6 pb-[calc(var(--bottomnav-h)+24px)] sm:px-6 md:pb-6">
            <div className="mx-auto max-w-[1200px]">{children}</div>
          </main>
          {results && evidenceOpen && (
            <div className="sticky top-[60px] hidden h-[calc(100vh-60px)] shrink-0 lg:block">
              <EvidencePanel onClose={closeEvidence} />
            </div>
          )}
        </div>
      </div>
      <MobileNavDrawer open={navOpen} onClose={() => setNavOpen(false)} hasCurrentKit={hasCurrentKit} onEvidence={() => { setNavOpen(false); setEvidenceOpen(true); }} />
      <MobileBottomNav hasCurrentKit={hasCurrentKit} onMore={() => setNavOpen(true)} />
      <Drawer open={results && evidenceOpen} onClose={closeEvidence} title="Evidence" fullWidthOnMobile>
        <EvidencePanel compact />
      </Drawer>
      <div aria-live="polite" aria-atomic="true" className="fixed bottom-20 left-1/2 z-[var(--z-toast)] -translate-x-1/2 md:bottom-5">
        {notice && <div role="status" className="flex items-center gap-3 rounded-md bg-ink px-4 py-3 text-sm text-surface shadow-lg"><Check aria-hidden="true" className="size-[17px] text-positive" />{notice}</div>}
      </div>
    </div>
  );
}
