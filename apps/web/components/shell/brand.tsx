import Link from "next/link";

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link href="/" aria-label="ATS-Ninja home" className="flex min-h-11 items-center gap-2 rounded-sm px-1 text-ink no-underline sm:min-h-10">
      <span className="grid size-7 shrink-0 place-items-center rounded-sm bg-accent font-mono text-sm font-semibold text-on-accent">
        N
      </span>
      {!compact && <span className="text-md font-bold tracking-[-0.01em]">ATS-Ninja</span>}
    </Link>
  );
}
