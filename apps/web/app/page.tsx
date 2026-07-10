// Phase 0 product shell. This is a static marketing/landing shell that proves
// the frontend builds and runs. It intentionally contains NO business logic:
// resume scoring, gap analysis, claim validation, and evidence logic all live
// in the Python engine (packages/engine) and are reached only through the API.

const principles = [
  {
    title: "Truth-grounded",
    body: "Every claim is backed by evidence from your own resume. Nothing is fabricated to game an ATS.",
  },
  {
    title: "Deterministic-first",
    body: "Parsing, matching, scoring, and gap analysis are deterministic. The LLM only writes prose, and its output is validated.",
  },
  {
    title: "Built to scale",
    body: "A modular monolith with a separately runnable worker: portable, testable, and cheap to operate.",
  },
];

const roadmap = [
  { label: "Tailored resume", status: "engine-ready" },
  { label: "Tailored cover letter", status: "engine-ready" },
  { label: "Application answers", status: "engine-ready" },
  { label: "Job-fit analysis", status: "planned" },
  { label: "Interview preparation", status: "planned" },
  { label: "LinkedIn outreach", status: "planned" },
];

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-5xl flex-col gap-16 px-6 py-16 sm:py-24">
      <header className="flex flex-col gap-5">
        <span className="inline-flex w-fit items-center rounded-full border border-black/10 px-3 py-1 text-xs font-medium uppercase tracking-widest text-black/60 dark:border-white/15 dark:text-white/60">
          Phase 0 · Foundation
        </span>
        <h1 className="text-4xl font-semibold tracking-tight sm:text-6xl">
          ATS-Ninja <span className="text-black/40 dark:text-white/40">V2</span>
        </h1>
        <p className="max-w-2xl text-lg text-black/70 dark:text-white/70">
          A deterministic-first, truth-grounded AI career toolkit. It turns a resume and a job
          description into an application kit that stays honest to what you have actually done.
        </p>
      </header>

      <section className="grid gap-5 sm:grid-cols-3">
        {principles.map((principle) => (
          <article
            key={principle.title}
            className="rounded-2xl border border-black/10 p-6 dark:border-white/15"
          >
            <h2 className="text-base font-semibold">{principle.title}</h2>
            <p className="mt-2 text-sm text-black/60 dark:text-white/60">{principle.body}</p>
          </article>
        ))}
      </section>

      <section className="flex flex-col gap-4">
        <h2 className="text-sm font-semibold uppercase tracking-widest text-black/50 dark:text-white/50">
          Application kit
        </h2>
        <ul className="grid gap-3 sm:grid-cols-2">
          {roadmap.map((item) => (
            <li
              key={item.label}
              className="flex items-center justify-between rounded-xl border border-black/10 px-4 py-3 text-sm dark:border-white/15"
            >
              <span>{item.label}</span>
              <span
                className={
                  item.status === "engine-ready"
                    ? "rounded-full bg-emerald-500/10 px-2.5 py-0.5 text-xs font-medium text-emerald-700 dark:text-emerald-300"
                    : "rounded-full bg-black/5 px-2.5 py-0.5 text-xs font-medium text-black/50 dark:bg-white/10 dark:text-white/50"
                }
              >
                {item.status}
              </span>
            </li>
          ))}
        </ul>
        <p className="text-xs text-black/40 dark:text-white/40">
          &ldquo;engine-ready&rdquo; capabilities exist in the Python engine; &ldquo;planned&rdquo;
          items are future work and are not yet implemented.
        </p>
      </section>
    </main>
  );
}
