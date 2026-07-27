import { Banner } from "@/components/ui/primitives";
import type { DeliveryReport } from "@/lib/api-types";

export function DeliveryFallbackBanner({
  artifact,
  report,
  className,
}: {
  artifact: "resume" | "cover-letter";
  report: DeliveryReport;
  className?: string;
}) {
  const title =
    artifact === "resume"
      ? "We delivered your resume preserving your original content; here's why tailoring was limited"
      : "We delivered your cover letter with a safe fallback.";
  const reason =
    report.fallback_reason?.trim() ||
    "No safe evidence-backed improvement was accepted, so the source-preserving version was delivered.";

  return (
    <Banner tone="warning" title={title} className={className}>
      {reason}
    </Banner>
  );
}
