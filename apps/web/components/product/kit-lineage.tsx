"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { RefreshCw, Trash2 } from "lucide-react";

import { ApiError, deleteKit, regenerateKit } from "@/lib/api-client";
import { Banner, Button, Card } from "@/components/ui/primitives";

/**
 * Kit lineage + lifecycle controls: revision indicator, parent link, regenerate
 * (creates a new linked kit from the same inputs), and delete (with an explicit
 * confirmation step). Never destructive without confirmation.
 */
export function KitLineageActions({
  kitId,
  parentKitId,
  revision,
}: {
  kitId: string;
  parentKitId: string | null;
  revision: number;
}) {
  const router = useRouter();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [busy, setBusy] = useState<"regenerate" | "delete" | null>(null);
  const [error, setError] = useState<string>("");

  async function handleRegenerate() {
    setBusy("regenerate");
    setError("");
    try {
      const created = await regenerateKit(kitId);
      router.push(`/kits/${created.id}`);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The kit could not be regenerated.");
      setBusy(null);
    }
  }

  async function handleDelete() {
    setBusy("delete");
    setError("");
    try {
      await deleteKit(kitId);
      router.push("/history");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "The kit could not be deleted.");
      setBusy(null);
      setConfirmingDelete(false);
    }
  }

  return (
    <Card className="flex flex-wrap items-center gap-3 shadow-none">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-semibold">Kit history</p>
        <p className="text-xs text-ink-muted">
          Revision {revision}
          {parentKitId ? (
            <>
              {" · regenerated from "}
              <Link href={`/kits/${parentKitId}`} className="text-accent underline-offset-2 hover:underline">
                the source kit
              </Link>
            </>
          ) : (
            " · original generation"
          )}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="secondary" onClick={handleRegenerate} disabled={busy !== null}>
          <RefreshCw aria-hidden="true" className="size-4" />
          {busy === "regenerate" ? "Regenerating…" : "Regenerate"}
        </Button>
        {confirmingDelete ? (
          <div className="flex items-center gap-2" role="group" aria-label="Confirm delete">
            <span className="text-xs text-ink-muted">Delete permanently?</span>
            <Button size="sm" variant="destructive" onClick={handleDelete} disabled={busy !== null}>
              {busy === "delete" ? "Deleting…" : "Confirm delete"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setConfirmingDelete(false)} disabled={busy !== null}>
              Cancel
            </Button>
          </div>
        ) : (
          <Button size="sm" variant="ghost" onClick={() => setConfirmingDelete(true)} disabled={busy !== null}>
            <Trash2 aria-hidden="true" className="size-4" />
            Delete
          </Button>
        )}
      </div>
      {error && (
        <Banner tone="danger" className="w-full" title="Action failed.">
          {error}
        </Banner>
      )}
    </Card>
  );
}
