"use client";

import { ChevronDown, ChevronUp } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";
import { Button } from "@/components/ui/primitives";

type ExpandableArtifactProps = {
  artifact: string;
  expanded: boolean;
  onExpandedChange: (expanded: boolean) => void;
  children: ReactNode;
  label?: string;
};

export function ExpandableArtifact({ artifact, expanded, onExpandedChange, children, label = "Open" }: ExpandableArtifactProps) {
  const triggerRef = useRef<HTMLButtonElement>(null);
  const detailRef = useRef<HTMLElement>(null);
  const detailId = `detail-${artifact}`;
  useEffect(() => {
    if (expanded) window.requestAnimationFrame(() => detailRef.current?.focus());
  }, [expanded]);
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape" && expanded) {
        event.preventDefault();
        onExpandedChange(false);
        window.requestAnimationFrame(() => triggerRef.current?.focus());
      }
    };
    document.addEventListener("keydown", close);
    return () => document.removeEventListener("keydown", close);
  }, [expanded, onExpandedChange]);
  return <>
    <Button ref={triggerRef} size="sm" variant="secondary" aria-expanded={expanded} aria-controls={detailId} onClick={() => onExpandedChange(!expanded)}>
      {expanded ? <ChevronUp aria-hidden="true" className="size-4" /> : <ChevronDown aria-hidden="true" className="size-4" />}{expanded ? "Collapse" : label}
    </Button>
    {expanded && <section id={detailId} ref={detailRef} tabIndex={-1} aria-label={`${artifact.replaceAll("-", " ")} details`} className="k1-expansion mt-4 border-t border-border-subtle pt-4">
      {children}
    </section>}
  </>;
}
