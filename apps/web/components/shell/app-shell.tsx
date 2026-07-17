"use client";

import { usePathname } from "next/navigation";
import { type ReactNode, useMemo, useState } from "react";
import { ArtifactTabs } from "@/components/shell/artifact-tabs";
import { EvidencePanel } from "@/components/shell/evidence-panel";
import { MobileBottomNav, MobileNavDrawer } from "@/components/shell/mobile-nav";
import { Sidebar } from "@/components/shell/sidebar";
import { WorkspaceHeader } from "@/components/shell/workspace-header";
import { KitProvider, useKit } from "@/components/product/kit-context";
import { Drawer } from "@/components/ui/drawer";
import { Banner } from "@/components/ui/primitives";
import { kitStatusPresentation } from "@/lib/status";
import { kitTarget } from "@/lib/product";

const screenMeta: Record<string, { title: string; meta?: string }> = {
  "/": { title: "New Kit", meta: "Private local workspace" },
  "/kits/new": { title: "New Kit", meta: "Add inputs · Choose outputs · Review" },
  "/history": { title: "Kit history", meta: "Server-backed local history" },
  "/components": { title: "Component foundation", meta: "Signal design-system reference" },
  "/settings": { title: "Local settings", meta: "Foundation preferences · not persisted" },
  "/states/processing": { title: "Processing states", meta: "Development reference" },
  "/states/error": { title: "Error states", meta: "Development reference" },
  "/states/d2": { title: "D2 synthetic states", meta: "Development-only fixtures" },
};

function kitIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/kits\/([^/]+)/);
  return match && match[1] !== "new" && match[1] !== "demo" ? decodeURIComponent(match[1]) : null;
}

export function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const kitId = kitIdFromPath(pathname);
  return (
    <KitProvider kitId={kitId}>
      <AppShellContent>{children}</AppShellContent>
    </KitProvider>
  );
}

function AppShellContent({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [navOpen, setNavOpen] = useState(false);
  const { kitId, kit, evidenceOpen, setEvidenceOpen, closeEvidence, openEvidence, connectionRestored, error } = useKit();
  const target = kitTarget(kit);
  const completed = kit?.status === "completed" && Boolean(kit.result);
  const meta = useMemo(
    () =>
      kitId
        ? {
            title: `${target.role} — ${target.company}`,
            meta: `${kitId} · ${kit?.result?.schema_version ?? kit?.status ?? "loading"}`,
          }
        : screenMeta[pathname] ?? { title: "ATS-Ninja", meta: "Private local workspace" },
    [kit?.result?.schema_version, kit?.status, kitId, pathname, target.company, target.role],
  );

  return (
    <div className="min-h-screen bg-canvas md:grid md:grid-cols-[64px_minmax(0,1fr)] lg:grid-cols-[248px_minmax(0,1fr)]">
      <a href="#main-content" className="sr-only z-[var(--z-toast)] rounded-control bg-accent px-4 py-2 text-on-accent focus:not-sr-only focus:fixed focus:left-4 focus:top-4">Skip to content</a>
      <Sidebar hasCurrentKit={Boolean(kitId)} kitId={kitId ?? undefined} onOpenDrawer={() => setNavOpen(true)} onEvidence={() => openEvidence()} />
      <div className="flex min-h-screen min-w-0 flex-col">
        <WorkspaceHeader
          title={meta.title}
          meta={meta.meta}
          status={kit ? kitStatusPresentation[kit.status] : undefined}
          results={Boolean(kitId)}
          evidenceOpen={evidenceOpen}
          onMenu={() => setNavOpen(true)}
          onEvidence={() => setEvidenceOpen(!evidenceOpen)}
        />
        {kitId && completed && <ArtifactTabs kitId={kitId} />}
        <div className="flex min-h-0 flex-1">
          <main id="main-content" className="min-w-0 flex-1 overflow-x-hidden px-4 py-6 pb-[calc(var(--bottomnav-h)+24px)] sm:px-6 md:pb-6">
            <div className="mx-auto max-w-[1200px]">{error && kit && <Banner tone="warning" className="mb-4" title="Temporary retrieval interruption.">The last known Kit state remains visible. Check the local API, then use retry retrieval if the interruption persists.</Banner>}{connectionRestored && <Banner tone="info" className="mb-4" title="Connection restored.">The latest Kit state was retrieved from the local API.</Banner>}{children}</div>
          </main>
          {kitId && evidenceOpen && (
            <div className="sticky top-[60px] hidden h-[calc(100vh-60px)] shrink-0 lg:block">
              <EvidencePanel onClose={closeEvidence} />
            </div>
          )}
        </div>
      </div>
      <MobileNavDrawer open={navOpen} onClose={() => setNavOpen(false)} hasCurrentKit={Boolean(kitId)} kitId={kitId ?? undefined} onEvidence={() => { setNavOpen(false); openEvidence(); }} />
      <MobileBottomNav hasCurrentKit={Boolean(kitId)} kitId={kitId ?? undefined} onMore={() => setNavOpen(true)} />
      <Drawer open={Boolean(kitId) && evidenceOpen} onClose={closeEvidence} title="Evidence" fullWidthOnMobile>
        <EvidencePanel compact />
      </Drawer>
    </div>
  );
}
