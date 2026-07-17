"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { ApiError, getKit } from "@/lib/api-client";
import type { Claim, KitRead } from "@/lib/api-types";
import { allClaims } from "@/lib/product";

type KitContextValue = {
  kitId: string | null;
  kit: KitRead | null;
  loading: boolean;
  error: ApiError | null;
  delayed: boolean;
  claims: Claim[];
  selectedClaimId: string | null;
  evidenceOpen: boolean;
  evidenceStatusFilter: string;
  evidenceArtifactFilter: string;
  highlightClaims: boolean;
  connectionRestored: boolean;
  refresh: () => Promise<void>;
  openEvidence: (claimId?: string) => void;
  closeEvidence: () => void;
  selectClaim: (claimId: string) => void;
  setEvidenceOpen: (open: boolean) => void;
  setEvidenceFilters: (filters: { status?: string; artifact?: string }) => void;
  setHighlightClaims: (enabled: boolean) => void;
};

const KitContext = createContext<KitContextValue | null>(null);

export function KitProvider({ kitId, children }: { kitId: string | null; children: ReactNode }) {
  const [kit, setKit] = useState<KitRead | null>(null);
  const [loading, setLoading] = useState(Boolean(kitId));
  const [error, setError] = useState<ApiError | null>(null);
  const [delayed, setDelayed] = useState(false);
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null);
  const [evidenceOpen, setEvidenceOpenState] = useState(false);
  const [evidenceStatusFilter, setEvidenceStatusFilter] = useState("all");
  const [evidenceArtifactFilter, setEvidenceArtifactFilter] = useState("all");
  const [highlightClaims, setHighlightClaims] = useState(true);
  const [connectionRestored, setConnectionRestored] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef(false);
  const processingStartedRef = useRef<number | null>(null);
  const evidenceTriggerRef = useRef<HTMLElement | null>(null);
  const hadConnectionErrorRef = useRef(false);

  const load = useCallback(async () => {
    if (!kitId || inFlightRef.current) return;
    inFlightRef.current = true;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    try {
      const next = await getKit(kitId, controller.signal);
      const recovered = hadConnectionErrorRef.current;
      setKit(next);
      setError(null);
      if (recovered) {
        hadConnectionErrorRef.current = false;
        setConnectionRestored(true);
        window.setTimeout(() => setConnectionRestored(false), 5_000);
      }
      if (next.status === "pending" || next.status === "processing") {
        processingStartedRef.current ??= Date.now();
        setDelayed(Date.now() - processingStartedRef.current > 20_000);
      } else {
        processingStartedRef.current = null;
        setDelayed(false);
      }
    } catch (caught) {
      if (controller.signal.aborted) return;
      hadConnectionErrorRef.current = true;
      setError(caught instanceof ApiError ? caught : new ApiError("The Kit could not be loaded.", null, "server"));
    } finally {
      if (!controller.signal.aborted) setLoading(false);
      inFlightRef.current = false;
    }
  }, [kitId]);

  useEffect(() => {
    setKit(null);
    setError(null);
    setLoading(Boolean(kitId));
    setSelectedClaimId(null);
    setEvidenceOpenState(false);
    setEvidenceStatusFilter("all");
    setEvidenceArtifactFilter("all");
    processingStartedRef.current = null;
    void load();
    return () => controllerRef.current?.abort();
  }, [kitId, load]);

  useEffect(() => {
    if (!kitId || (kit?.status !== "pending" && kit?.status !== "processing")) return;
    const interval = window.setInterval(() => void load(), 1_500);
    return () => window.clearInterval(interval);
  }, [kit?.status, kitId, load]);

  const claims = useMemo(() => allClaims(kit?.result ?? null), [kit?.result]);
  const openEvidence = useCallback((claimId?: string) => {
    evidenceTriggerRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    if (claimId) {
      setSelectedClaimId(claimId);
      setEvidenceStatusFilter("all");
      setEvidenceArtifactFilter("all");
    }
    setEvidenceOpenState(true);
  }, []);
  const closeEvidence = useCallback(() => {
    setEvidenceOpenState(false);
    window.requestAnimationFrame(() => evidenceTriggerRef.current?.focus());
  }, []);
  const setEvidenceOpen = useCallback((open: boolean) => {
    if (open) openEvidence();
    else closeEvidence();
  }, [closeEvidence, openEvidence]);
  const setEvidenceFilters = useCallback((filters: { status?: string; artifact?: string }) => {
    if (filters.status !== undefined) setEvidenceStatusFilter(filters.status);
    if (filters.artifact !== undefined) setEvidenceArtifactFilter(filters.artifact);
  }, []);

  const value = useMemo<KitContextValue>(
    () => ({
      kitId,
      kit,
      loading,
      error,
      delayed,
      claims,
      selectedClaimId,
      evidenceOpen,
      evidenceStatusFilter,
      evidenceArtifactFilter,
      highlightClaims,
      connectionRestored,
      refresh: load,
      openEvidence,
      closeEvidence,
      selectClaim: setSelectedClaimId,
      setEvidenceOpen,
      setEvidenceFilters,
      setHighlightClaims,
    }),
    [
      claims,
      closeEvidence,
      connectionRestored,
      delayed,
      error,
      evidenceOpen,
      evidenceArtifactFilter,
      evidenceStatusFilter,
      highlightClaims,
      kit,
      kitId,
      load,
      loading,
      openEvidence,
      selectedClaimId,
      setEvidenceFilters,
      setEvidenceOpen,
    ],
  );

  return <KitContext.Provider value={value}>{children}</KitContext.Provider>;
}

export function useKit(): KitContextValue {
  const value = useContext(KitContext);
  if (!value) throw new Error("useKit must be used within KitProvider");
  return value;
}
