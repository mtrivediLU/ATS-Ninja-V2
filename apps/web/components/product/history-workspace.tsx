"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { AlertCircle, ArrowLeft, ArrowRight, History, Search } from "lucide-react";
import { getKit, listKits } from "@/lib/api-client";
import type { KitList, KitRead, KitStatus } from "@/lib/api-types";
import { formatDate, kitTarget } from "@/lib/product";
import { Banner, Button, Card, EmptyState, Input, Select, StatusLabel, buttonClassName } from "@/components/ui/primitives";
import { kitStatusPresentation } from "@/lib/status";

const PAGE_SIZE = 20;
type Sort = "recent" | "role" | "company";

export function HistoryWorkspace() {
  const [page, setPage] = useState<KitList | null>(null);
  const [details, setDetails] = useState<Record<string, KitRead>>({});
  const [offset, setOffset] = useState(0);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<"all" | KitStatus>("all");
  const [sort, setSort] = useState<Sort>("recent");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError("");
    try {
      const listing = await listKits(PAGE_SIZE, offset, signal);
      setPage(listing);
      const settled = await Promise.allSettled(listing.items.map((item) => getKit(item.id, signal)));
      if (signal?.aborted) return;
      const next: Record<string, KitRead> = {};
      settled.forEach((result) => { if (result.status === "fulfilled") next[result.value.id] = result.value; });
      setDetails(next);
    } catch (caught) {
      if (signal?.aborted) return;
      setError(caught instanceof Error ? caught.message : "Kit history could not be loaded.");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [offset]);

  useEffect(() => { const controller = new AbortController(); void load(controller.signal); return () => controller.abort(); }, [load]);

  const rows = useMemo(() => {
    const normalized = query.trim().toLowerCase();
    const current = (page?.items ?? []).filter((item) => {
      const detail = details[item.id];
      const target = kitTarget(detail ?? null);
      const matchesQuery = !normalized || `${target.role} ${target.company} ${item.id}`.toLowerCase().includes(normalized);
      return matchesQuery && (status === "all" || item.status === status);
    });
    return current.sort((a, b) => {
      if (sort === "recent") return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      const aTarget = kitTarget(details[a.id] ?? null);
      const bTarget = kitTarget(details[b.id] ?? null);
      return (sort === "role" ? aTarget.role.localeCompare(bTarget.role) : aTarget.company.localeCompare(bTarget.company));
    });
  }, [details, page?.items, query, sort, status]);

  if (loading && !page) return <div aria-live="polite" aria-busy="true" className="space-y-3">{Array.from({ length: 4 }, (_, index) => <Card key={index}><div className="h-3 w-2/5 animate-pulse rounded-sm bg-border-subtle" /><div className="mt-3 h-3 w-3/4 animate-pulse rounded-sm bg-border-subtle" /></Card>)}</div>;
  if (error && !page) return <Card className="mx-auto max-w-[620px] text-center"><AlertCircle aria-hidden="true" className="mx-auto size-10 text-danger" /><h2 className="mt-3 text-lg font-semibold">History unavailable</h2><p className="mt-2 text-sm text-ink-secondary">{error}</p><Button variant="primary" className="mt-4" onClick={() => void load()}>Try again</Button></Card>;
  if (!page?.total) return <div className="rounded-lg border border-dashed border-border-strong bg-surface-subtle px-5"><EmptyState icon={History} title="No saved Kits yet" description="Completed, processing, and failed Kits will appear here after the API accepts the first submission." action={<Link href="/kits/new" className={buttonClassName("primary")}>Create a Kit</Link>} /></div>;

  const recent = page.items.slice(0, 4);
  return <div className="space-y-6">
    <Banner tone="neutral" title="Loaded-page controls.">Search, status filtering, and sorting apply only to the current API page of up to {PAGE_SIZE} Kits.</Banner>
    <section aria-labelledby="recent-heading"><h2 id="recent-heading" className="mb-3 text-md font-semibold">Recent</h2><div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">{recent.map((item) => <HistoryCard key={item.id} item={details[item.id] ?? item} compact />)}</div></section>
    <div className="flex flex-wrap items-center gap-3"><label className="relative min-w-[220px] flex-1"><span className="sr-only">Search loaded Kits</span><Search aria-hidden="true" className="absolute left-3 top-1/2 size-4 -translate-y-1/2 text-ink-muted" /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search loaded role, company, or Kit ID…" className="pl-9" /></label><div className="flex flex-wrap gap-1" aria-label="Filter by status">{(["all", "completed", "processing", "failed"] as const).map((value) => <button key={value} type="button" aria-pressed={status === value} onClick={() => setStatus(value)} className="min-h-11 rounded-pill border border-border bg-surface px-3 text-sm capitalize text-ink-secondary aria-pressed:border-border-strong aria-pressed:bg-surface-raised aria-pressed:font-semibold aria-pressed:text-ink">{value}</button>)}</div><Select aria-label="Sort loaded Kits" value={sort} onChange={(event) => setSort(event.target.value as Sort)} className="w-auto"><option value="recent">Most recent</option><option value="role">Role A–Z</option><option value="company">Company A–Z</option></Select></div>
    {rows.length ? <div className="space-y-2">{rows.map((item) => <HistoryCard key={item.id} item={details[item.id] ?? item} />)}</div> : <Card className="text-center"><h2 className="font-semibold">No Kits match this loaded page</h2><p className="mt-2 text-sm text-ink-muted">Clear the local search or status filter.</p></Card>}
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-border-subtle pt-4"><p className="text-sm text-ink-muted">Showing {offset + 1}–{Math.min(offset + page.items.length, page.total)} of {page.total}</p><div className="flex gap-2"><Button disabled={offset === 0 || loading} onClick={() => setOffset((current) => Math.max(0, current - PAGE_SIZE))}><ArrowLeft aria-hidden="true" className="size-4" />Previous</Button><Button disabled={offset + PAGE_SIZE >= page.total || loading} onClick={() => setOffset((current) => current + PAGE_SIZE)}>Next<ArrowRight aria-hidden="true" className="size-4" /></Button></div></div>
  </div>;
}

type SummaryLike = { id: string; status: KitStatus; created_at: string; updated_at: string };
function HistoryCard({ item, compact = false }: { item: SummaryLike | KitRead; compact?: boolean }) {
  const detail = "result" in item ? item : null;
  const target = kitTarget(detail);
  const fit = detail?.result?.job_fit?.fit_band;
  const artifacts = detail?.result ? [detail.result.resume, detail.result.cover_letter, detail.result.answers, detail.result.job_fit, detail.result.interview_prep, detail.result.linkedin_outreach].filter(Boolean).length : 0;
  const oldSchema = detail?.result && detail.result.schema_version !== "application-kit/v4";
  return <Link href={`/kits/${item.id}`} className={`flex gap-3 rounded-md border border-border bg-surface p-4 text-ink transition-[border-color,box-shadow] hover:border-border-strong hover:shadow-xs ${compact ? "flex-col" : "items-center"}`}><div className="min-w-0 flex-1"><h3 className="truncate font-semibold">{target.role} — {target.company}</h3><p className="truncate font-mono text-xs text-ink-muted">{item.id}{detail?.result ? ` · ${detail.result.schema_version}` : ""}</p>{!compact && <p className="mt-1 text-xs text-ink-muted">{formatDate(item.created_at)}{fit ? ` · ${fit} fit` : ""}{artifacts ? ` · ${artifacts} artifacts` : ""}{oldSchema ? " · compatibility view" : ""}</p>}</div><StatusLabel presentation={kitStatusPresentation[item.status]} /></Link>;
}
