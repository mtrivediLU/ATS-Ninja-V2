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
  highlightClaims: boolean;
  refresh: () => Promise<void>;
  openEvidence: (claimId?: string) => void;
  closeEvidence: () => void;
  selectClaim: (claimId: string) => void;
  setEvidenceOpen: (open: boolean) => void;
  setHighlightClaims: (enabled: boolean) => void;
};

const KitContext = createContext<KitContextValue | null>(null);

export function KitProvider({ kitId, children }: { kitId: string | null; children: ReactNode }) {
  const [kit, setKit] = useState<KitRead | null>(null);
  const [loading, setLoading] = useState(Boolean(kitId));
  const [error, setError] = useState<ApiError | null>(null);
  const [delayed, setDelayed] = useState(false);
  const [selectedClaimId, setSelectedClaimId] = useState<string | null>(null);
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [highlightClaims, setHighlightClaims] = useState(true);
  const controllerRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef(false);
  const processingStartedRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    if (!kitId || inFlightRef.current) return;
    inFlightRef.current = true;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    try {
      const next = await getKit(kitId, controller.signal);
      setKit(next);
      setError(null);
      if (next.status === "pending" || next.status === "processing") {
        processingStartedRef.current ??= Date.now();
        setDelayed(Date.now() - processingStartedRef.current > 20_000);
      } else {
        processingStartedRef.current = null;
        setDelayed(false);
      }
    } catch (caught) {
      if (controller.signal.aborted) return;
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
    setEvidenceOpen(false);
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
    if (claimId) setSelectedClaimId(claimId);
    setEvidenceOpen(true);
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
      highlightClaims,
      refresh: load,
      openEvidence,
      closeEvidence: () => setEvidenceOpen(false),
      selectClaim: setSelectedClaimId,
      setEvidenceOpen,
      setHighlightClaims,
    }),
    [
      claims,
      delayed,
      error,
      evidenceOpen,
      highlightClaims,
      kit,
      kitId,
      load,
      loading,
      openEvidence,
      selectedClaimId,
    ],
  );

  return <KitContext.Provider value={value}>{children}</KitContext.Provider>;
}

export function useKit(): KitContextValue {
  const value = useContext(KitContext);
  if (!value) throw new Error("useKit must be used within KitProvider");
  return value;
}
