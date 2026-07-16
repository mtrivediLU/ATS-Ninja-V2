"use client";

import { useEffect, useState } from "react";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/primitives";
import { Dialog } from "@/components/ui/dialog";

export function FeedbackDemo() {
  const [dialogOpen, setDialogOpen] = useState(false);
  const [toast, setToast] = useState(false);

  useEffect(() => {
    if (!toast) return;
    const timer = window.setTimeout(() => setToast(false), 2600);
    return () => window.clearTimeout(timer);
  }, [toast]);

  return (
    <>
      <div className="flex flex-wrap gap-3">
        <Button onClick={() => setDialogOpen(true)}>Open confirmation dialog</Button>
        <Button onClick={() => setToast(true)}>Show copy-success toast</Button>
      </div>
      <Dialog
        open={dialogOpen}
        onClose={() => setDialogOpen(false)}
        title="Discard this synthetic kit?"
        actions={
          <>
            <Button variant="ghost" onClick={() => setDialogOpen(false)}>Cancel</Button>
            <Button variant="destructive" onClick={() => { setDialogOpen(false); setToast(true); }}>Discard</Button>
          </>
        }
      >
        This demonstrates confirmation behavior only. No kit is stored or deleted in D0.
      </Dialog>
      <div aria-live="polite" aria-atomic="true" className="fixed bottom-20 left-1/2 z-[var(--z-toast)] -translate-x-1/2 md:bottom-5">
        {toast && (
          <div role="status" className="flex items-center gap-3 rounded-md bg-ink px-4 py-3 text-sm text-surface shadow-lg">
            <Check aria-hidden="true" className="size-[17px] text-positive" />
            Copied synthetic content. No clipboard API was called.
          </div>
        )}
      </div>
    </>
  );
}
