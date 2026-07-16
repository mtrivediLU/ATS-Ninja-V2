import type { Metadata } from "next";
import { Banner, ProcessingState, type ProcessingStep } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "Processing state" };

const steps: ProcessingStep[] = [
  { label: "Parse resume and job description", state: "done" },
  { label: "Extract candidate evidence", state: "done" },
  { label: "Match and score requirements deterministically", state: "active" },
  { label: "Generate validated prose", state: "pending" },
  { label: "Ground claims against evidence", state: "pending" },
  { label: "Validate and assemble ApplicationKit", state: "pending" },
];

export default function ProcessingPage() {
  return (
    <div className="space-y-5">
      <Banner tone="neutral" title="Synthetic lifecycle demonstration.">No job is running and no polling occurs on this route.</Banner>
      <ProcessingState slow title="Assembling a truth-grounded kit" description="Deterministic work runs first. Provider prose remains untrusted until validation completes." steps={steps} />
    </div>
  );
}
