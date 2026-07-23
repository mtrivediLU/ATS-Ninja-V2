"use client";

import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import type { TemplateArtifact, TemplateId } from "@/components/product/templates/template-definitions";

type TemplateSelectionValue = {
  templateFor: (artifact: TemplateArtifact) => TemplateId;
  setTemplate: (artifact: TemplateArtifact, template: TemplateId) => void;
};

const TemplateSelectionContext = createContext<TemplateSelectionValue | null>(null);

/** Session-only presentation state. It intentionally never stores candidate content. */
export function TemplateSelectionProvider({ children }: { children: ReactNode }) {
  const [templates, setTemplates] = useState<Record<TemplateArtifact, TemplateId>>({
    resume: "classic",
    "cover-letter": "classic",
  });
  const value = useMemo<TemplateSelectionValue>(
    () => ({
      templateFor: (artifact) => templates[artifact],
      setTemplate: (artifact, template) => setTemplates((current) => ({ ...current, [artifact]: template })),
    }),
    [templates],
  );
  return <TemplateSelectionContext.Provider value={value}>{children}</TemplateSelectionContext.Provider>;
}

export function useTemplateSelection(): TemplateSelectionValue {
  const value = useContext(TemplateSelectionContext);
  if (!value) throw new Error("useTemplateSelection must be used within TemplateSelectionProvider");
  return value;
}
