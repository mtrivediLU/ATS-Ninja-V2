import type { Metadata } from "next";
import Link from "next/link";
import { ErrorState, Banner, buttonClassName } from "@/components/ui/primitives";
import { kitStatusPresentation, withheldPresentation } from "@/lib/status";

export const metadata: Metadata = { title: "Error states" };

export default function ErrorPage() {
  return (
    <div className="space-y-5">
      <Banner tone="neutral" title="Synthetic failure states.">These examples demonstrate honest recovery copy and do not report the live services.</Banner>
      <div className="grid gap-5 xl:grid-cols-3">
        <section className="rounded-lg border border-border bg-surface px-5"><ErrorState title="Kit generation failed" description="The kit is marked failed. A retry creates a new job; the worker itself is not treated as crashed." status={kitStatusPresentation.failed} action={<Link href="/" className={buttonClassName("primary", "sm")}>Retry as new kit</Link>} /></section>
        <section className="rounded-lg border border-border bg-surface px-5"><ErrorState title="API unavailable" description="The service could not be reached. Inputs stay in this disconnected demonstration only." status={kitStatusPresentation.failed} action={<Link href="/" className={buttonClassName("secondary", "sm")}>Return to New Kit</Link>} /></section>
        <section className="rounded-lg border border-border bg-surface px-5"><ErrorState title="Processing service unavailable" description="The Kit could not continue processing. The persisted lifecycle record does not reliably identify an underlying service, so no operational diagnosis is shown." status={withheldPresentation} action={<Link href="/history" className={buttonClassName("secondary", "sm")}>View history</Link>} /></section>
      </div>
    </div>
  );
}
