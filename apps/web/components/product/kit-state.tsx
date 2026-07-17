"use client";

import Link from "next/link";
import { useKit } from "@/components/product/kit-context";
import { RecoveryState, RetryButton } from "@/components/product/recovery-state";
import { Card, buttonClassName } from "@/components/ui/primitives";

export function KitStateBoundary({ children }: { children: React.ReactNode }) {
  const { kit, loading, error, delayed, refresh } = useKit();
  if (loading && !kit) return <LoadingKit />;
  if (error && !kit) return <RecoveryState state="unavailable" actions={<><RetryButton onClick={() => void refresh()} /><Link href="/history" className={buttonClassName()}>Return to history</Link></>} />;
  if (!kit) return <RecoveryState state="malformed" actions={<><RetryButton onClick={() => void refresh()} /><Link href="/history" className={buttonClassName()}>Return to history</Link></>} />;
  if (kit.status === "pending" || kit.status === "processing") return <RecoveryState state={delayed ? "slow" : kit.status} pulse actions={<Link href="/history" className={buttonClassName("secondary")}>Return to history</Link>} />;
  if (kit.status === "failed") return <RecoveryState state="failed" actions={<><Link href="/kits/new" className={buttonClassName("primary")}>Create another Kit</Link><Link href="/history" className={buttonClassName()}>Return to history</Link></>} />;
  if (!kit.result) return <RecoveryState state="malformed" actions={<><RetryButton onClick={() => void refresh()} /><Link href="/history" className={buttonClassName()}>Return to history</Link></>} />;
  return <>{children}</>;
}

function LoadingKit() { return <div aria-live="polite" aria-busy="true" className="mx-auto max-w-[580px] py-10"><Card><div className="h-3 w-2/5 animate-pulse rounded-sm bg-border-subtle" /><div className="mt-3 h-3 animate-pulse rounded-sm bg-border-subtle" /><div className="mt-2 h-3 w-4/5 animate-pulse rounded-sm bg-border-subtle" /><p className="sr-only">Loading Kit status.</p></Card></div>; }
