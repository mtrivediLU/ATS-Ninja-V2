"use client";

import { useMemo, useState } from "react";
import { Check, Lock, RotateCcw, X } from "lucide-react";

import type { ChangeActionKind, ChangeRecord, ChangeStatus, ChangeType } from "@/lib/api-types";
import { ApiError, applyChangeActions } from "@/lib/api-client";
import { Badge, Banner, Button, Card, Select } from "@/components/ui/primitives";

/**
 * The transparent change ledger. Shows every tailoring change with its original
 * vs tailored text, deterministic reason, matched keywords, bounded evidence,
 * estimated keyword-match impact, and confidence. Reversible changes can be
 * accepted or rejected in a batch; truth-grounding removals are locked and can
 * never be reverted. Fully keyboard accessible with screen-reader labels.
 */

const TYPE_LABEL: Record<ChangeType, string> = {
  summary: "Summary",
  targeting_clause: "Targeting clause",
  bullet: "Bullet rewrite",
  skill: "Skill surfacing",
  cover_letter_paragraph: "Cover letter paragraph",
  grounding_removal: "Grounding removal",
};

const OPERATION_LABEL: Record<string, string> = {
  added: "Added",
  rewritten: "Rewritten",
  reordered: "Reordered",
  omitted: "Omitted",
  removed: "Removed (grounding)",
};

const STATUS_TONE: Record<ChangeStatus, "neutral" | "positive" | "danger"> = {
  proposed: "neutral",
  accepted: "positive",
  rejected: "danger",
};

type Pending = Record<string, ChangeActionKind>;

export function ChangeLedger({
  kitId,
  records,
  revision,
  onApplied,
  title = "Change ledger",
}: {
  kitId: string;
  records: ChangeRecord[];
  revision: number;
  onApplied: () => Promise<void>;
  title?: string;
}) {
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [pending, setPending] = useState<Pending>({});
  const [state, setState] = useState<"idle" | "applying" | "success" | "error" | "conflict">("idle");
  const [message, setMessage] = useState<string>("");

  // Unique per-ledger id so two ledgers (resume + cover letter) on one page never
  // collide on heading / aria-labelledby ids.
  const instanceId = useMemo(() => `ledger-${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`, [title]);
  const headingId = `${instanceId}-heading`;

  const filtered = useMemo(
    () =>
      records.filter(
        (record) =>
          (typeFilter === "all" || record.change_type === typeFilter) &&
          (statusFilter === "all" || record.status === statusFilter),
      ),
    [records, typeFilter, statusFilter],
  );

  const pendingCount = Object.keys(pending).length;

  function setAction(id: string, action: ChangeActionKind) {
    setPending((prev) => {
      const next = { ...prev };
      if (next[id] === action) {
        delete next[id];
      } else {
        next[id] = action;
      }
      return next;
    });
  }

  async function apply() {
    if (pendingCount === 0) return;
    setState("applying");
    setMessage("");
    try {
      await applyChangeActions(kitId, {
        expected_revision: revision,
        actions: Object.entries(pending).map(([change_id, action]) => ({ change_id, action })),
      });
      setPending({});
      setState("success");
      setMessage("Changes applied.");
      await onApplied();
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        // A concurrent writer advanced the revision. Refresh so the indicator and
        // records reflect the current state; keep the user's pending selection so
        // they can reapply against the refreshed revision.
        setState("conflict");
        setMessage("This kit changed since you loaded it. It has been refreshed — review and reapply your changes.");
        await onApplied();
      } else if (error instanceof ApiError && error.status === 422) {
        // Invalid request (e.g. a locked change). Keep the user's selection intact.
        setState("error");
        setMessage(error.message);
      } else {
        setState("error");
        setMessage(error instanceof ApiError ? error.message : "The changes could not be applied.");
      }
    }
  }

  if (records.length === 0) {
    return (
      <section className="mt-6" aria-labelledby={headingId}>
        <h2 id={headingId} className="text-md font-semibold">
          {title}
        </h2>
        <p className="mt-2 text-sm text-ink-muted">No tailoring changes were recorded for this artifact.</p>
      </section>
    );
  }

  return (
    <section className="mt-6" aria-labelledby={headingId}>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id={headingId} className="text-md font-semibold">
          {title}
        </h2>
        <span className="font-mono text-xs text-ink-muted" aria-label={`Kit revision ${revision}`}>
          revision {revision}
        </span>
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="text-xs text-ink-muted">
          <span className="mb-1 block">Change type</span>
          <Select value={typeFilter} onChange={(event) => setTypeFilter(event.target.value)} aria-label="Filter by change type">
            <option value="all">All types</option>
            {Object.entries(TYPE_LABEL).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
        </label>
        <label className="text-xs text-ink-muted">
          <span className="mb-1 block">Status</span>
          <Select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} aria-label="Filter by status">
            <option value="all">All statuses</option>
            <option value="proposed">Proposed</option>
            <option value="accepted">Accepted</option>
            <option value="rejected">Rejected</option>
          </Select>
        </label>
      </div>

      {state === "conflict" && (
        <Banner tone="warning" className="mt-3" title="Revision conflict.">
          {message}
        </Banner>
      )}
      {state === "error" && (
        <Banner tone="danger" className="mt-3" title="Could not apply changes.">
          {message}
        </Banner>
      )}
      {state === "success" && (
        <Banner tone="info" className="mt-3" title="Applied.">
          {message}
        </Banner>
      )}

      <ul className="mt-3 space-y-3">
        {filtered.map((record) => (
          <li key={record.id}>
            <LedgerRow record={record} action={pending[record.id]} onAction={setAction} />
          </li>
        ))}
      </ul>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        <Button variant="primary" onClick={apply} disabled={pendingCount === 0 || state === "applying"}>
          {state === "applying" ? "Applying…" : `Apply ${pendingCount || ""} change${pendingCount === 1 ? "" : "s"}`.trim()}
        </Button>
        {pendingCount > 0 && (
          <Button variant="ghost" onClick={() => setPending({})} disabled={state === "applying"}>
            Clear selection
          </Button>
        )}
      </div>
    </section>
  );
}

function LedgerRow({
  record,
  action,
  onAction,
}: {
  record: ChangeRecord;
  action: ChangeActionKind | undefined;
  onAction: (id: string, action: ChangeActionKind) => void;
}) {
  const impactTone = record.ats_impact_delta > 0 ? "positive" : record.ats_impact_delta < 0 ? "warning" : "neutral";
  return (
    <Card className="shadow-none">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold">{TYPE_LABEL[record.change_type]}</span>
          <Badge tone="neutral">{OPERATION_LABEL[record.operation] ?? record.operation}</Badge>
          <Badge tone={STATUS_TONE[record.status]}>{record.status}</Badge>
          <Badge tone={impactTone}>{record.ats_impact}</Badge>
        </div>
        {record.reversible ? (
          <div className="flex items-center gap-1" role="group" aria-label={`Actions for ${TYPE_LABEL[record.change_type]}`}>
            <ActionButton
              label="Accept this change"
              active={action === "accept"}
              tone="positive"
              onClick={() => onAction(record.id, "accept")}
              icon={<Check aria-hidden="true" className="size-4" />}
            >
              Accept
            </ActionButton>
            <ActionButton
              label="Reject this change"
              active={action === "reject"}
              tone="danger"
              onClick={() => onAction(record.id, "reject")}
              icon={<X aria-hidden="true" className="size-4" />}
            >
              Reject
            </ActionButton>
            {record.status !== "proposed" && (
              <ActionButton
                label="Restore the tailored change"
                active={action === "restore"}
                tone="neutral"
                onClick={() => onAction(record.id, "restore")}
                icon={<RotateCcw aria-hidden="true" className="size-4" />}
              >
                Restore
              </ActionButton>
            )}
          </div>
        ) : (
          <span
            className="inline-flex items-center gap-1.5 text-xs text-ink-muted"
            title={
              record.change_type === "grounding_removal"
                ? "A truth-grounding removal cannot be restored; doing so would reintroduce unsupported content."
                : "This change is informational and is managed through regeneration, not individual reversal."
            }
          >
            <Lock aria-hidden="true" className="size-3.5" />
            {record.change_type === "grounding_removal" ? "Permanent" : "Locked"}
          </span>
        )}
      </div>

      <p className="mt-2 text-sm text-ink-secondary">{record.reason}</p>

      {(record.original_text || record.tailored_text) && (
        <div className="mt-3 grid gap-2 md:grid-cols-2">
          {record.original_text && (
            <div className="rounded-lg border border-border-subtle bg-surface-subtle p-2 text-sm">
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.05em] text-ink-muted">Original</p>
              <p className="text-ink-secondary">{record.original_text}</p>
            </div>
          )}
          {record.tailored_text && (
            <div className="rounded-lg border border-border-subtle bg-surface p-2 text-sm">
              <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.05em] text-ink-muted">Tailored</p>
              <p className="text-ink-secondary">{record.tailored_text}</p>
            </div>
          )}
        </div>
      )}

      {record.evidence.length > 0 && (
        <div className="mt-3 rounded-lg border border-border-subtle bg-surface-subtle p-2">
          <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.05em] text-ink-muted">Supporting evidence</p>
          <ul className="space-y-1 text-xs text-ink-secondary">
            {record.evidence.map((ref, index) => (
              <li key={`${ref.locator}-${index}`}>
                <span className="text-ink-muted">{ref.source || "candidate resume"}:</span>{" "}
                {ref.excerpt || ref.locator}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-muted">
        {record.matched_keywords.length > 0 && <span>Keywords: {record.matched_keywords.join(", ")}</span>}
        <span>Confidence: {record.confidence}</span>
        {record.change_type === "grounding_removal" && <span>Truth-grounding removal (cannot be restored)</span>}
      </div>
    </Card>
  );
}

function ActionButton({
  label,
  active,
  tone,
  onClick,
  icon,
  children,
}: {
  label: string;
  active: boolean;
  tone: "positive" | "danger" | "neutral";
  onClick: () => void;
  icon: React.ReactNode;
  children: React.ReactNode;
}) {
  const activeClasses =
    tone === "positive"
      ? "border-positive-border bg-positive-bg text-positive"
      : tone === "danger"
        ? "border-danger-border bg-danger-bg text-danger"
        : "border-border bg-surface-subtle text-ink";
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      aria-pressed={active}
      className={`inline-flex min-h-11 items-center gap-1.5 rounded-control border px-2.5 text-xs font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent ${active ? activeClasses : "border-border text-ink-muted hover:bg-surface-subtle"}`}
    >
      {icon}
      {children}
    </button>
  );
}
