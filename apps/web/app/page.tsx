import type { Metadata } from "next";
import Link from "next/link";
import { History, ShieldCheck, WandSparkles } from "lucide-react";
import { Banner, buttonClassName } from "@/components/ui/primitives";

export const metadata: Metadata = { title: "New Kit" };

export default function Home() {
  return (
    <div className="space-y-6">
      <Banner tone="neutral" title="Private local application.">Your inputs are sent only to the configured local ATS-Ninja API. Authentication and public hosting are not part of D1.</Banner>
      <section className="mx-auto flex max-w-[660px] flex-col items-center py-10 text-center sm:py-16">
        <div className="mb-5 grid size-[72px] place-items-center rounded-lg border border-accent-border bg-accent-subtle text-accent"><WandSparkles aria-hidden="true" className="size-9" /></div>
        <h2 className="text-2xl font-bold leading-tight tracking-[-0.01em]">Create an application kit</h2>
        <p className="mt-3 max-w-[580px] text-pretty text-base text-ink-secondary">Add your resume and a job description. ATS-Ninja builds selected artifacts with candidate claims grounded in your evidence.</p>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <Link href="/kits/new" className={buttonClassName("primary")}><ShieldCheck aria-hidden="true" className="size-[17px]" />Start new kit</Link>
          <Link href="/history" className={buttonClassName()}><History aria-hidden="true" className="size-[17px]" />Open recent kits</Link>
        </div>
      </section>
    </div>
  );
}
