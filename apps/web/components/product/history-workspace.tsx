"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertCircle, ChevronRight, History, Search, X } from "lucide-react";
import { getKit, listKits } from "@/lib/api-client";
import type { KitRead, KitStatus, KitSummary } from "@/lib/api-types";
import { formatDate, kitTarget } from "@/lib/product";
import { artifactNavigation, type ArtifactSlug } from "@/lib/navigation";
import { Banner, Button, Card, EmptyState, Input, Select, StatusLabel, buttonClassName } from "@/components/ui/primitives";
import { kitStatusPresentation } from "@/lib/status";

const PAGE_SIZE = 20;
type Sort = "recent" | "role" | "company";
type StatusFilter = "all" | KitStatus | "warnings";

export function HistoryWorkspace() {
  const [items, setItems] = useState<KitSummary[]>([]);
  const [details, setDetails] = useState<Record<string, KitRead>>({});
  const [total, setTotal] = useState<number | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [artifact, setArtifact] = useState<"all" | ArtifactSlug>("all");
  const [sort, setSort] = useState<Sort>("recent");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [unavailable, setUnavailable] = useState(false);

  const loadPage = useCallback(async (offset: number, append: boolean, signal?: AbortSignal) => {
    if (append) setLoadingMore(true);
    else setLoading(true);
    setUnavailable(false);
    try {
      const listing = await listKits(PAGE_SIZE, offset, signal);
      if (signal?.aborted) return;
      setTotal(listing.total);
      setItems((current) => append ? [...current, ...listing.items.filter((item) => !current.some((existing) => existing.id === item.id))] : listing.items);
      const settled = await Promise.allSettled(listing.items.map((item) => getKit(item.id, signal)));
      if (signal?.aborted) return;
      setDetails((current) => {
        const next = append ? { ...current } : {};
        settled.forEach((result) => { if (result.status === "fulfilled") next[result.value.id] = result.value; });
        return next;
      });
    } catch {
      if (!signal?.aborted) setUnavailable(true);
    } finally {
      if (!signal?.aborted) { setLoading(false); setLoadingMore(false); }
    }
  }, []);

  useEffect(() => { const controller = new AbortController(); void loadPage(0, false, controller.signal); return () => controller.abort(); }, [loadPage]);

  const rows = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const current = items.filter((item) => {
      const detail = details[item.id];
      const target = kitTarget(detail ?? null);
      const matchesQuery = !normalized || `${target.role} ${target.company} ${item.id}`.toLowerCase().includes(normalized);
      const hasWarnings = Boolean(detail?.result && (detail.result.validation.warning_count > 0 || detail.result.warnings.length > 0 || artifactWarning(detail)));
      const matchesStatus = status === "all" || status === "warnings" ? status === "all" || hasWarnings : item.status === status;
      const matchesArtifact = artifact === "all" || (detail ? selectedArtifact(detail, artifact) : false);
      return matchesQuery && matchesStatus && matchesArtifact;
    });
    return current.sort((a, b) => {
      if (sort === "recent") return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      const aTarget = kitTarget(details[a.id] ?? null);
      const bTarget = kitTarget(details[b.id] ?? null);
      return sort === "role" ? aTarget.role.localeCompare(bTarget.role) : aTarget.company.localeCompare(bTarget.company);
    });
  }, [artifact, details, items, query, sort, status]);

  const activeFilters = [query ? { id: "query", label: `“${query}”` } : null, status !== "all" ? { id: "status", label: status === "warnings" ? "Validation notes" : status } : null, artifact !== "all" ? { id: "artifact", label: artifactNavigation.find((item) => item.id === artifact)?.label ?? artifact } : null].filter((filter): filter is { id: string; label: string } => Boolean(filter));
  function clear(id?: string) { if (!id || id === "query") setQuery(""); if (!id || id === "status") setStatus("all"); if (!id || id === "artifact") setArtifact("all"); }

  if (loading && !items.length) return <div aria-live="polite" aria-busy="true" className="space-y-3">{Array.from({ length: 4 }, (_, index) => <Card key={index}><div className="h-3 w-2/5 animate-pulse rounded-sm bg-border-subtle" /><div className="mt-3 h-3 w-3/4 animate-pulse rounded-sm bg-border-subtle" /></Card>)}</div>;
  if (unavailable && !items.length) return <HistoryUnavailable onRetry={() => void loadPage(0, false)} />;
  if (total === 0) return <div className="rounded-lg border border-dashed border-border-strong bg-surface-subtle px-5"><EmptyState icon={History} title="No saved Kits yet" description="Completed, processing, and failed Kits will appear here after the API accepts the first submission." action={<Link href="/kits/new" className={buttonClassName("primary")}>Create a Kit</Link>} /></div>;

  return <div className="space-y-6">
    {unavailable && <Banner tone="warning" title="History refresh interrupted.">Previously loaded Kits remain visible. Check that the local API is running, then retry retrieval.</Banner>}
    <Banner tone="neutral" title="Loaded-page controls.">Search, filtering, and sorting apply only to the {items.length} Kit{items.length === 1 ? "" : "s"} currently loaded from the API, not to server-wide history.</Banner>
    <div className="flex flex-wrap items-center gap-3"><label className="relative min-w-[220px] flex-1"><span className="sr-only">Search loaded Kits</span><Search aria-hidden="true" className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-muted" /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search loaded role, company, or Kit ID…" className="pl-9" /></label><div className="flex flex-wrap gap-1" aria-label="Filter loaded Kits by status">{(["all", "pending", "processing", "completed", "failed", "warnings"] as const).map((value) => <button key={value} type="button" aria-pressed={status === value} onClick={() => setStatus(value)} className="min-h-11 rounded-pill border border-border bg-surface px-3 text-sm capitalize text-ink-secondary aria-pressed:border-border-strong aria-pressed:bg-surface-raised aria-pressed:font-semibold aria-pressed:text-ink">{value === "all" ? "All" : value === "warnings" ? "Notes" : value}</button>)}</div><Select aria-label="Filter loaded Kits by included artifact" value={artifact} onChange={(event) => setArtifact(event.target.value as "all" | ArtifactSlug)} className="w-auto"><option value="all">Any artifact</option>{artifactNavigation.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</Select><Select aria-label="Sort loaded Kits" value={sort} onChange={(event) => setSort(event.target.value as Sort)} className="w-auto"><option value="recent">Newest first</option><option value="role">Role A–Z</option><option value="company">Company A–Z</option></Select></div>
    {activeFilters.length > 0 && <div className="flex flex-wrap items-center gap-2" aria-label="Active filters">{activeFilters.map((filter) => <span key={filter.id} className="inline-flex min-h-9 items-center gap-1 rounded-pill border border-border bg-surface-raised px-3 text-xs text-ink-secondary">{filter.label}<button type="button" aria-label={`Remove ${filter.label} filter`} onClick={() => clear(filter.id)} className="ml-1 rounded-sm p-0.5 hover:bg-surface"><X aria-hidden="true" className="size-3" /></button></span>)}<button type="button" onClick={() => clear()} className="min-h-9 text-sm font-semibold text-accent hover:underline">Clear all filters</button></div>}
    {rows.length ? <div className="space-y-2">{rows.map((item) => <HistoryCard key={item.id} item={details[item.id] ?? item} />)}</div> : <Card className="text-center"><h2 className="font-semibold">No Kits match this loaded page</h2><p className="mt-2 text-sm text-ink-muted">Clear a local filter to view the loaded Kits again.</p>{activeFilters.length > 0 && <Button variant="ghost" className="mt-3" onClick={() => clear()}>Clear filters</Button>}</Card>}
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle pt-4"><p className="text-sm text-ink-muted">Loaded {items.length} of {total ?? items.length} Kits</p><div className="flex gap-2">{unavailable && <Button variant="secondary" onClick={() => void loadPage(items.length, true)}>Retry retrieval</Button>}{items.length < (total ?? 0) && <Button disabled={loadingMore} onClick={() => void loadPage(items.length, true)}>{loadingMore ? "Loading…" : `Load more (${Math.min(PAGE_SIZE, (total ?? 0) - items.length)} more)`}<ChevronRight aria-hidden="true" className="size-4" /></Button>}</div></div>
  </div>;
}

function HistoryUnavailable({ onRetry }: { onRetry: () => void }) { return <Card className="mx-auto max-w-[620px] text-center"><AlertCircle aria-hidden="true" className="mx-auto size-10 text-danger" /><h2 className="mt-3 text-lg font-semibold">History unavailable</h2><p className="mt-2 text-sm text-ink-secondary">The local API could not be reached. Check that the local stack is running, then retry.</p><Button variant="primary" className="mt-4" onClick={onRetry}>Retry retrieval</Button></Card>; }
function artifactWarning(detail: KitRead): boolean { const result = detail.result; if (!result) return false; return [result.resume, result.cover_letter, result.answers, result.job_fit, result.interview_prep, result.linkedin_outreach].some((item) => item && (item.validation.warnings.length > 0 || item.validation.status === "repaired")); }
function selectedArtifact(detail: KitRead, artifact: ArtifactSlug): boolean { return artifact === "resume" ? detail.include_resume : artifact === "cover-letter" ? detail.include_cover_letter : artifact === "answers" ? detail.include_application_answers : artifact === "job-fit" ? detail.include_job_fit : artifact === "interview-prep" ? detail.include_interview_prep : detail.include_linkedin_outreach; }
type SummaryLike = { id: string; status: KitStatus; created_at: string; updated_at: string };
function HistoryCard({ item }: { item: SummaryLike | KitRead }) { const detail = "result" in item ? item : null; const target = kitTarget(detail); const fit = detail?.result?.job_fit?.fit_band; const artifacts = detail?.result ? [detail.result.resume, detail.result.cover_letter, detail.result.answers, detail.result.job_fit, detail.result.interview_prep, detail.result.linkedin_outreach].filter(Boolean).length : 0; const oldSchema = detail?.result && detail.result.schema_version !== "application-kit/v4"; const warning = detail && artifactWarning(detail); return <Link href={`/kits/${item.id}`} className="flex flex-col gap-3 rounded-md border border-border bg-surface p-4 text-ink transition-[border-color,box-shadow] hover:border-border-strong hover:shadow-xs sm:flex-row sm:items-center"><div className="min-w-0 flex-1"><h3 className="truncate font-semibold">{target.role} — {target.company}</h3><p className="truncate font-mono text-xs text-ink-muted">{item.id}{detail?.result ? ` · ${detail.result.schema_version}` : ""}</p><p className="mt-1 text-xs text-ink-muted">{formatDate(item.created_at)}{fit ? ` · ${fit} fit` : ""}{artifacts ? ` · ${artifacts} artifacts` : ""}{oldSchema ? " · compatibility view" : ""}{warning ? " · validation notes" : ""}</p></div><div className="flex items-center gap-2">{oldSchema && <span className="rounded-pill border border-neutral-border bg-neutral-bg px-2 py-1 text-xs text-neutral">Older format</span>}{warning && <span className="rounded-pill border border-warning-border bg-warning-bg px-2 py-1 text-xs text-warning">Notes</span>}<StatusLabel presentation={kitStatusPresentation[item.status]} /></div></Link>; }
