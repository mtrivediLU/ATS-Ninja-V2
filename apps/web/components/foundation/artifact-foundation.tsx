import { ShieldCheck } from "lucide-react";
import { Banner, Card, PlaceholderBlock, StatusLabel } from "@/components/ui/primitives";
import { notRequestedPresentation, withheldPresentation } from "@/lib/status";
import type { ArtifactSlug } from "@/lib/navigation";

const artifactTitles: Record<ArtifactSlug, string> = {
  resume: "Tailored resume",
  "cover-letter": "Cover letter",
  answers: "Application answers",
  "job-fit": "Job-fit analysis",
  "interview-prep": "Interview preparation",
  "linkedin-outreach": "LinkedIn outreach drafts",
};

export function ArtifactFoundation({ artifact }: { artifact: ArtifactSlug }) {
  const title = artifactTitles[artifact];

  if (artifact === "interview-prep") {
    return (
      <div className="space-y-4">
        <StatusLabel presentation={notRequestedPresentation} />
        <Card>
          <h2 className="text-md font-semibold">Interview preparation was not requested</h2>
          <p className="mt-2 text-pretty text-sm text-ink-secondary">This neutral foundation state represents an API artifact value of null. The frontend does not treat absence as a failure.</p>
        </Card>
      </div>
    );
  }

  if (artifact === "linkedin-outreach") {
    return (
      <div className="space-y-4">
        <StatusLabel presentation={withheldPresentation} />
        <Banner tone="danger" title="Could not be generated safely.">This synthetic withheld state demonstrates how a fatal validation result is surfaced. No outreach is sent.</Banner>
        <PlaceholderBlock label="Withheld LinkedIn outreach workspace — detailed screen arrives later" />
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <Banner tone={artifact === "resume" ? "warning" : "neutral"} title={artifact === "resume" ? "Validation adjustment demonstrated." : "Evidence-led workspace foundation."}>
        {artifact === "resume"
          ? "Two synthetic claims were adjusted to remain accurate. Open Evidence to inspect the presentation pattern."
          : "Detailed artifact content is intentionally deferred. This route demonstrates only the shared shell, header, tabs, and evidence affordance."}
      </Banner>
      <div className="flex items-center gap-2 text-sm text-ink-secondary">
        <ShieldCheck aria-hidden="true" className="size-[18px] text-positive" />
        <span>{title} · synthetic placeholder</span>
      </div>
      <PlaceholderBlock label={`${title} workspace — detailed design begins after D0`} />
      {artifact === "answers" && (
        <Card className="shadow-none">
          <h2 className="text-md font-semibold">Empty artifact state</h2>
          <p className="mt-2 text-sm text-ink-secondary">No application questions were supplied. This is a valid empty result, not an inferred error.</p>
        </Card>
      )}
      {artifact === "job-fit" && (
        <div className="grid gap-4 sm:grid-cols-2">
          <Card><p className="text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-ink-muted">Requirement coverage</p><p className="mt-2 font-mono text-2xl font-semibold">82<span className="text-md text-ink-muted">/100</span></p><p className="text-sm text-ink-muted">Synthetic policy index, not a probability.</p></Card>
          <Card><p className="text-[0.6875rem] font-semibold uppercase tracking-[0.06em] text-ink-muted">Fit band</p><p className="mt-2 text-lg font-semibold">Competitive</p><p className="text-sm text-ink-muted">Rendered API value; not recomputed here.</p></Card>
        </div>
      )}
    </div>
  );
}
