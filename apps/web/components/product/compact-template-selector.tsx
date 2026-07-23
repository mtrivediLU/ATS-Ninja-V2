"use client";

import type { KeyboardEvent } from "react";
import { useTemplateSelection } from "@/components/product/template-selection";
import { templateById, type TemplateArtifact, type TemplateId } from "@/components/product/templates/template-definitions";

export function CompactTemplateSelector({ artifact }: { artifact: TemplateArtifact }) {
  const { templateFor, setTemplate } = useTemplateSelection();
  const selected = templateFor(artifact);
  const choices: TemplateId[] = ["classic", "modern"];
  function keys(event: KeyboardEvent<HTMLDivElement>) {
    const direction = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    if (!direction) return;
    event.preventDefault();
    const next = choices[(choices.indexOf(selected) + direction + choices.length) % choices.length];
    setTemplate(artifact, next);
  }
  return <div role="radiogroup" aria-label={`${artifact === "resume" ? "Resume" : "Cover letter"} template`} onKeyDown={keys} className="inline-flex rounded-control border border-border bg-surface-subtle p-0.5">
    {choices.map((choice) => <button key={choice} type="button" role="radio" aria-checked={selected === choice} onClick={() => setTemplate(artifact, choice)} className="min-h-9 rounded-sm px-2.5 text-xs font-semibold aria-checked:bg-surface aria-checked:shadow-xs">
      {templateById(choice).name.replace(" ATS", "")}
    </button>)}
  </div>;
}
