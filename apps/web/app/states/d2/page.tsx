import type { Metadata } from "next";
import { ArtifactState } from "@/components/product/artifact-states";
import { RecoveryState } from "@/components/product/recovery-state";
import { EvidenceCard } from "@/components/shell/evidence-panel";
import { Banner } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "D2 synthetic states" };

/** Development-only fixtures for states the current API cannot reliably produce on demand. */
const unavailableEvidence = { id: "dev-evidence-unavailable", artifact: "resume", claim_type: "development_fixture", text: "Development-only unavailable evidence trace", status: "unavailable", disposition: "unavailable", reason: "This fixture demonstrates a transport-level unavailable evidence record.", evidence: [] };

export default function D2SyntheticStatesPage() {
  return <div className="space-y-6"><Banner tone="neutral" title="Development-only synthetic fixtures.">These examples are not production Kits and are isolated from real history. They exercise safe D2 presentation for unavailable, partial, old-format, and malformed-response states.</Banner><div className="grid gap-4 lg:grid-cols-2"><ArtifactState title="Evidence attachment unavailable" state="unavailable" /><ArtifactState title="Optional artifact partially generated" state="partial" /><ArtifactState title="Older ApplicationKit format" state="old-schema" /><ArtifactState title="Empty selected artifact" state="empty" /></div><div className="grid gap-4 lg:grid-cols-2"><RecoveryState state="malformed" /><RecoveryState state="unavailable" /></div><section className="max-w-md"><h2 className="mb-3 text-md font-semibold">Evidence unavailable fixture</h2><EvidenceCard record={unavailableEvidence} active={false} /></section></div>;
}
