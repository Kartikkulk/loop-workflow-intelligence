import Link from "next/link";
import { CountUp } from "@/components/landing/count-up";
import { DetectionDemo } from "@/components/landing/detection-demo";
import { Reveal } from "@/components/landing/reveal";

/**
 * The landing page.
 *
 * Outside the console on purpose: someone arriving here has agreed to nothing,
 * so nothing on this page reads data or calls the API. It renders on the
 * server, and the only thing it asks for is a click through to the product.
 *
 * Every figure shown is one the application actually produces from the demo
 * activity log the test suite runs against. There are no invented metrics,
 * no customer logos and no testimonials, because a number nobody can reproduce
 * is worth less than no number at all.
 */

export const metadata = {
  title: "LOOP — Workflow Intelligence",
  description:
    "LOOP watches how work actually gets done, finds the patterns people repeat, chooses the right way to automate them, and waits for approval before anything runs.",
};

const PROBLEM_CARDS = [
  { tag: "COPY", body: "Copy the same information between systems.", example: "Support Portal → Jira" },
  { tag: "REPEAT", body: "Perform the same browser steps again and again.", example: "Search → Read → Update → Submit" },
  { tag: "RECONCILE", body: "Move files, numbers and records between tools.", example: "PDF → Data → System" },
];

const JOURNEY = [
  { n: "01", title: "Observe", body: "Capture how work is actually performed.", chips: ["Browser", "Files", "Applications", "APIs"] },
  { n: "02", title: "Discover", body: "Find repeated patterns across activity.", chips: ["5 occurrences", "91% similarity", "Recurring sequence"] },
  { n: "03", title: "Understand", body: "Turn actions into a meaningful business task.", chips: ["High-Priority Support Escalation"] },
  { n: "04", title: "Build", body: "Choose the best way to automate it.", chips: ["n8n", "Python", "Browser", "Hybrid"] },
  { n: "05", title: "Approve", body: "Validate it. Review it. Then let it run.", chips: ["Validation", "Dry run", "Human approval"] },
];

const ROUTING = [
  { observed: ["Browser", "Support portal", "Read ticket", "Jira"], because: "Browser interaction required, and Jira has an API.", verdict: "Hybrid", detail: "Playwright + Jira API" },
  { observed: ["PDF", "Extract fields", "Jira"], because: "Local document work, then one API call.", verdict: "Python", detail: "Script + Jira API" },
  { observed: ["Webhook", "Transform JSON", "Jira"], because: "Every step is an API n8n already speaks.", verdict: "n8n", detail: "Node graph" },
];

const BEFORE = ["Open ticket", "Search customer", "Read issue", "Open Jira", "Copy details", "Create issue", "Repeat"];
const AFTER = ["Observe once", "Pattern discovered", "Automation built", "Human approval", "Runs automatically"];
const CHAIN = ["Observe", "Plan", "Validate", "Dry run", "Human approval", "Execute"];

const ENGINES = [
  { name: "n8n", body: "API-driven workflows and integrations." },
  { name: "Browser automation", body: "Work that genuinely requires a web interface." },
  { name: "Python", body: "Local files, PDFs and data processing." },
  { name: "Hybrid", body: "Browser, local and API execution combined when the process needs it." },
];

const CSV_ROWS = [
  ["09:15", "Chrome", "open", "Support Portal", "", "browser"],
  ["09:17", "Chrome", "search", "Ticket", "Ticket 1001", "browser"],
  ["09:19", "Chrome", "read", "Customer", "ABC", "browser"],
  ["09:25", "Jira", "open", "Create Issue", "", "jira"],
  ["09:33", "Jira", "create", "Issue", "SUP-4501", "jira"],
];

export default function LandingPage() {
  return (
    <div className="min-h-screen w-full overflow-x-hidden bg-ink-950">
      {/* ── header ──────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-30 border-b border-ink-800/70 bg-ink-950/80 backdrop-blur-md">
        <div className="mx-auto flex max-w-6xl items-center gap-3 px-6 py-3.5">
          <span aria-hidden className="relative flex h-3.5 w-3.5">
            <span className="absolute inset-0 animate-pulse-ring rounded-full border-2 border-good-500" />
          </span>
          <span className="text-sm font-semibold tracking-tight text-mist-100">LOOP</span>
          <span className="hidden text-2xs text-mist-600 sm:inline">Workflow Intelligence</span>
          <nav className="ml-auto hidden items-center gap-5 md:flex">
            {[
              { href: "#how", label: "How it works" },
              { href: "#decides", label: "How it chooses" },
              { href: "#control", label: "Control" },
            ].map((item) => (
              <a key={item.href} className="text-2xs text-mist-500 transition-colors hover:text-mist-200" href={item.href}>
                {item.label}
              </a>
            ))}
          </nav>
          <Link className="btn-primary md:ml-5" href="/dashboard">
            Go to Console
          </Link>
        </div>
      </header>

      {/* ── hero ────────────────────────────────────────────────────── */}
      <section className="relative overflow-hidden border-b border-ink-800">
        <div aria-hidden className="pointer-events-none absolute inset-0">
          <div className="absolute right-[-6rem] top-[-10rem] h-[34rem] w-[46rem] animate-drift rounded-full bg-good-600/[0.10] blur-[120px]" />
          <div className="absolute left-1/3 top-32 h-[24rem] w-[24rem] animate-drift-slow rounded-full bg-accent-600/[0.08] blur-[110px]" />
          <div
            className="absolute inset-0 opacity-30"
            style={{
              backgroundImage:
                "linear-gradient(to right,#1e232c 1px,transparent 1px),linear-gradient(to bottom,#1e232c 1px,transparent 1px)",
              backgroundSize: "60px 60px",
              maskImage: "radial-gradient(ellipse 75% 55% at 60% 0%,#000 35%,transparent 100%)",
              WebkitMaskImage: "radial-gradient(ellipse 75% 55% at 60% 0%,#000 35%,transparent 100%)",
            }}
          />
        </div>

        <div className="relative mx-auto max-w-6xl px-6 pb-20 pt-16 sm:pt-20">
          <div className="grid items-center gap-12 lg:grid-cols-[1.02fr_1fr] lg:gap-16">
            <div>
              <p className="eyebrow mb-5 text-good-400" style={{ animation: "fade-up 600ms ease-out 60ms both" }}>
                Workflow intelligence
              </p>
              <h1
                className="text-balance text-[2.6rem] font-semibold leading-[1.05] tracking-tight text-mist-100 sm:text-[3.5rem]"
                style={{ animation: "fade-up 700ms cubic-bezier(0.16,1,0.3,1) 140ms both" }}
              >
                Your team already has automations.
                <span className="block text-mist-500">They just haven&apos;t been built yet.</span>
              </h1>
              <p
                className="mt-6 max-w-xl text-pretty text-base leading-relaxed text-mist-400"
                style={{ animation: "fade-up 700ms ease-out 280ms both" }}
              >
                LOOP watches how work actually gets done and turns repetitive work into approved
                automations. It finds the patterns people repeat, estimates what can be handed
                over, chooses the right automation approach, and builds it for review.
              </p>
              <dl
                className="mt-10 grid max-w-lg grid-cols-3 gap-px overflow-hidden rounded-lg border border-ink-700 bg-ink-700"
                style={{ animation: "fade-up 700ms ease-out 520ms both" }}
              >
                {[
                  { value: "5", label: "repetitions to detect" },
                  { value: "4", label: "runtimes it can build" },
                  { value: "0", label: "actions without approval" },
                ].map((stat) => (
                  <div key={stat.label} className="bg-ink-950 px-4 py-3.5">
                    <dt className="text-xl font-semibold leading-none text-mist-100">{stat.value}</dt>
                    <dd className="mt-1.5 text-2xs leading-tight text-mist-600">{stat.label}</dd>
                  </div>
                ))}
              </dl>
            </div>

            <div style={{ animation: "scale-in 800ms cubic-bezier(0.16,1,0.3,1) 340ms both" }}>
              <DetectionDemo />
            </div>
          </div>
        </div>
      </section>

      {/* ── the problem ─────────────────────────────────────────────── */}
      <section className="border-b border-ink-800">
        <div className="mx-auto max-w-6xl px-6 py-24">
          <Reveal>
            <p className="eyebrow mb-3 text-good-400">The problem</p>
            <h2 className="text-balance text-3xl font-semibold tracking-tight text-mist-100 sm:text-4xl">
              Most automation starts with a request.
            </h2>
            <p className="mt-4 max-w-2xl text-lg leading-relaxed text-mist-300">
              But the work worth automating is already happening.
            </p>
            <p className="mt-3 max-w-2xl text-sm leading-relaxed text-mist-500">
              Employees don&apos;t always know which parts of their day are worth automating.
              They simply repeat them.
            </p>
          </Reveal>

          <div className="mt-12 grid gap-5 md:grid-cols-3">
            {PROBLEM_CARDS.map((card, index) => (
              <Reveal key={card.tag} delay={index * 110}>
                <div className="h-full rounded-xl border border-ink-700 bg-ink-900/60 p-6">
                  <p className="mono text-2xs tracking-widest text-good-400">{card.tag}</p>
                  <p className="mt-3 text-sm leading-relaxed text-mist-200">{card.body}</p>
                  <p className="mono mt-4 border-t border-ink-700 pt-3 text-2xs text-mist-600">
                    {card.example}
                  </p>
                </div>
              </Reveal>
            ))}
          </div>

          <Reveal delay={360}>
            <div className="mt-8 flex flex-wrap items-center justify-center gap-3 rounded-xl border border-ink-700 bg-ink-900/40 px-6 py-4">
              {["Observe", "Understand", "Automate"].map((word, index) => (
                <span key={word} className="flex items-center gap-3">
                  {index > 0 && <span aria-hidden className="text-mist-700">→</span>}
                  <span className="text-xs font-medium tracking-tight text-mist-200">{word}</span>
                </span>
              ))}
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── the journey ─────────────────────────────────────────────── */}
      <section id="how" className="scroll-mt-16 border-b border-ink-800 bg-ink-900/30">
        <div className="mx-auto max-w-6xl px-6 py-24">
          <Reveal>
            <p className="eyebrow mb-3 text-good-400">What LOOP does</p>
            <h2 className="text-balance text-3xl font-semibold tracking-tight text-mist-100 sm:text-4xl">
              LOOP starts with the work.
              <span className="block text-mist-500">Not the workflow.</span>
            </h2>
            <p className="mt-4 max-w-2xl text-sm leading-relaxed text-mist-400">
              You don&apos;t have to know what should be automated. LOOP discovers it.
            </p>
          </Reveal>

          <div className="relative mt-14">
            {/* the line the journey travels along */}
            <span
              aria-hidden
              className="absolute left-[1.05rem] top-2 hidden h-[calc(100%-2rem)] w-px bg-gradient-to-b from-good-500/50 via-ink-600 to-transparent sm:block"
            />
            <ol className="space-y-4">
              {JOURNEY.map((stage, index) => (
                <Reveal key={stage.n} delay={index * 90}>
                  <li className="relative flex gap-5 rounded-xl border border-ink-700 bg-ink-950 p-5 sm:pl-14">
                    <span className="mono absolute left-0 top-5 hidden h-[2.1rem] w-[2.1rem] items-center justify-center rounded-full border border-ink-600 bg-ink-900 text-2xs text-good-400 sm:flex">
                      {stage.n}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline gap-3">
                        <span className="mono text-2xs text-good-400 sm:hidden">{stage.n}</span>
                        <h3 className="text-sm font-semibold tracking-tight text-mist-100">
                          {stage.title}
                        </h3>
                        <p className="text-2xs text-mist-500">{stage.body}</p>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-1.5">
                        {stage.chips.map((chip) => (
                          <span
                            key={chip}
                            className="mono rounded border border-ink-600 bg-ink-900 px-2 py-0.5 text-2xs text-mist-400"
                          >
                            {chip}
                          </span>
                        ))}
                      </div>
                    </div>
                  </li>
                </Reveal>
              ))}
            </ol>
          </div>
        </div>
      </section>

      {/* ── the differentiator ──────────────────────────────────────── */}
      <section id="decides" className="scroll-mt-16 border-b border-ink-800">
        <div className="mx-auto max-w-6xl px-6 py-24">
          <Reveal>
            <p className="eyebrow mb-3 text-good-400">The difference</p>
            <h2 className="text-balance text-3xl font-semibold tracking-tight text-mist-100 sm:text-4xl">
              LOOP doesn&apos;t just generate workflows.
              <span className="block text-mist-500">It decides how the work should be automated.</span>
            </h2>
            <p className="mt-4 max-w-2xl text-sm leading-relaxed text-mist-400">
              Some work belongs in an API workflow. Some requires browser automation. Some is
              better handled locally. LOOP chooses based on what it actually observed.
            </p>
          </Reveal>

          <div className="mt-12 space-y-4">
            {ROUTING.map((route, index) => (
              <Reveal key={route.verdict} delay={index * 110}>
                <div className="grid items-center gap-4 rounded-xl border border-ink-700 bg-ink-900/50 p-5 lg:grid-cols-[1.4fr_1.4fr_0.9fr]">
                  <div>
                    <p className="eyebrow mb-2 text-mist-600">Observed work</p>
                    <div className="flex flex-wrap items-center gap-1.5">
                      {route.observed.map((node, i) => (
                        <span key={node} className="flex items-center gap-1.5">
                          {i > 0 && <span aria-hidden className="text-mist-700">→</span>}
                          <span className="mono rounded border border-ink-600 bg-ink-950 px-2 py-0.5 text-2xs text-mist-300">
                            {node}
                          </span>
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="lg:border-l lg:border-ink-700 lg:pl-5">
                    <p className="eyebrow mb-2 text-mist-600">LOOP decides</p>
                    <p className="text-2xs leading-relaxed text-mist-400">{route.because}</p>
                  </div>
                  <div className="rounded-lg border border-good-500/30 bg-good-500/[0.07] px-4 py-3">
                    <p className="text-sm font-semibold tracking-tight text-good-300">
                      {route.verdict}
                    </p>
                    <p className="mono mt-1 text-2xs text-mist-500">{route.detail}</p>
                  </div>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ── before / after ──────────────────────────────────────────── */}
      <section className="border-b border-ink-800 bg-ink-900/30">
        <div className="mx-auto max-w-6xl px-6 py-24">
          <Reveal>
            <p className="eyebrow mb-3 text-good-400">Before and after</p>
            <h2 className="text-balance text-3xl font-semibold tracking-tight text-mist-100 sm:text-4xl">
              From repetitive clicks to one approved workflow.
            </h2>
          </Reveal>

          <div className="mt-12 grid gap-5 md:grid-cols-2">
            <Reveal>
              <div className="h-full rounded-xl border border-ink-700 bg-ink-950 p-6">
                <p className="eyebrow mb-4 text-mist-600">Before LOOP · every time</p>
                <ol className="space-y-2">
                  {BEFORE.map((step, index) => (
                    <li key={step} className="flex items-center gap-3">
                      <span className="mono w-5 text-2xs text-mist-700">{index + 1}</span>
                      <span className="text-2xs text-mist-400">{step}</span>
                    </li>
                  ))}
                </ol>
              </div>
            </Reveal>
            <Reveal delay={140}>
              <div className="h-full rounded-xl border border-good-500/25 bg-good-500/[0.04] p-6">
                <p className="eyebrow mb-4 text-good-400">With LOOP · once</p>
                <ol className="space-y-2">
                  {AFTER.map((step, index) => (
                    <li key={step} className="flex items-center gap-3">
                      <span className="mono w-5 text-2xs text-good-500/70">{index + 1}</span>
                      <span className="text-2xs text-mist-300">{step}</span>
                    </li>
                  ))}
                </ol>
              </div>
            </Reveal>
          </div>
        </div>
      </section>

      {/* ── control ─────────────────────────────────────────────────── */}
      <section id="control" className="scroll-mt-16 border-b border-ink-800">
        <div className="mx-auto max-w-6xl px-6 py-24">
          <Reveal>
            <h2 className="max-w-3xl text-balance text-3xl font-semibold tracking-tight text-mist-100 sm:text-4xl">
              AI can build it.
              <span className="block text-mist-500">You decide whether it runs.</span>
            </h2>
            <p className="mt-4 max-w-2xl text-sm leading-relaxed text-mist-400">
              LOOP never turns an observation into an uncontrolled production action. Generated
              automations are reviewed, validated and approved before execution.
            </p>
          </Reveal>

          <Reveal delay={140}>
            <ol className="mt-10 grid gap-px overflow-hidden rounded-xl border border-ink-700 bg-ink-700 sm:grid-cols-3 lg:grid-cols-6">
              {CHAIN.map((stage, index) => (
                <li key={stage} className="bg-ink-950 px-4 py-5">
                  <p className="mono text-2xs text-mist-700">{String(index + 1).padStart(2, "0")}</p>
                  <p
                    className={`mt-2 text-xs font-medium tracking-tight ${
                      stage === "Human approval" ? "text-good-300" : "text-mist-200"
                    }`}
                  >
                    {stage}
                  </p>
                </li>
              ))}
            </ol>
          </Reveal>
        </div>
      </section>

      {/* ── engines ─────────────────────────────────────────────────── */}
      <section className="border-b border-ink-800 bg-ink-900/30">
        <div className="mx-auto max-w-6xl px-6 py-24">
          <Reveal>
            <p className="eyebrow mb-3 text-good-400">Automation engines</p>
            <h2 className="text-balance text-3xl font-semibold tracking-tight text-mist-100 sm:text-4xl">
              Use the right tool for the job.
            </h2>
          </Reveal>
          <div className="mt-12 grid gap-px overflow-hidden rounded-xl border border-ink-700 bg-ink-700 sm:grid-cols-2 lg:grid-cols-4">
            {ENGINES.map((engine, index) => (
              <Reveal key={engine.name} delay={index * 90}>
                <div className="h-full bg-ink-950 p-6">
                  <h3 className="text-xs font-semibold tracking-tight text-mist-100">{engine.name}</h3>
                  <p className="mt-2 text-2xs leading-relaxed text-mist-500">{engine.body}</p>
                </div>
              </Reveal>
            ))}
          </div>
          <Reveal delay={400}>
            <div className="mt-5 rounded-xl border border-good-500/25 bg-good-500/[0.05] px-6 py-5 text-center">
              <p className="text-xs font-semibold tracking-tight text-good-300">
                LOOP automation planner
              </p>
              <p className="mt-1.5 text-2xs text-mist-400">
                LOOP chooses, from the connectors the work was observed touching — and explains
                why. You can overrule it, and it will tell you when a choice cannot run.
              </p>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── measurement ─────────────────────────────────────────────── */}
      <section className="border-b border-ink-800">
        <div className="mx-auto max-w-6xl px-6 py-24">
          <Reveal>
            <p className="eyebrow mb-3 text-good-400">Measurement</p>
            <h2 className="text-balance text-3xl font-semibold tracking-tight text-mist-100 sm:text-4xl">
              Make repetitive work measurable.
            </h2>
            <p className="mt-4 max-w-2xl text-sm leading-relaxed text-mist-400">
              Figures below are from the support-escalation workflow in the demo activity log —
              the same one the test suite runs against. Your own numbers come from your own
              activity, on the ROI screen.
            </p>
          </Reveal>
          <div className="mt-12 grid gap-px overflow-hidden rounded-xl border border-ink-700 bg-ink-700 sm:grid-cols-3">
            {[
              { value: 5, decimals: 0, suffix: "", label: "occurrences observed" },
              { value: 91, decimals: 0, suffix: "%", label: "sequence similarity" },
              { value: 126, decimals: 0, suffix: "", label: "hours a year it accounts for" },
            ].map((metric, index) => (
              <Reveal key={metric.label} delay={index * 110}>
                <div className="bg-ink-950 px-6 py-8">
                  <p className="text-4xl font-semibold leading-none tracking-tight text-mist-100">
                    <CountUp to={metric.value} decimals={metric.decimals} suffix={metric.suffix} />
                  </p>
                  <p className="mt-3 text-2xs text-mist-500">{metric.label}</p>
                </div>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ── CSV ─────────────────────────────────────────────────────── */}
      <section className="border-b border-ink-800 bg-ink-900/30">
        <div className="mx-auto grid max-w-6xl gap-10 px-6 py-24 lg:grid-cols-2 lg:gap-14">
          <Reveal>
            <p className="eyebrow mb-3 text-good-400">Historical activity</p>
            <h2 className="text-balance text-3xl font-semibold tracking-tight text-mist-100 sm:text-4xl">
              Already have activity data?
            </h2>
            <p className="mt-4 text-sm leading-relaxed text-mist-400">
              Upload it. LOOP finds the patterns. A CSV goes through exactly the same
              normalisation, sessionisation and clustering as a live collector — so nobody has to
              perform the task five times during a demo to prove detection works.
            </p>
            <ol className="mt-6 space-y-2">
              {["CSV", "Activity events", "Pattern detection", "Repetitive work", "Automation opportunity"].map(
                (stage, index) => (
                  <li key={stage} className="flex items-center gap-3 text-2xs text-mist-400">
                    <span className="mono w-5 text-mist-700">{index + 1}</span>
                    {stage}
                  </li>
                ),
              )}
            </ol>
          </Reveal>

          <Reveal delay={140}>
            <div className="overflow-hidden rounded-xl border border-ink-700 bg-ink-950">
              <div className="flex items-center gap-2 border-b border-ink-700 bg-ink-900/70 px-4 py-2.5">
                <span className="mono text-2xs text-mist-600">activity.csv</span>
              </div>
              <div className="overflow-x-auto">
                <table className="mono w-full text-2xs">
                  <thead>
                    <tr className="border-b border-ink-700 text-mist-600">
                      {["time", "application", "action", "target", "value", "connector"].map((h) => (
                        <th key={h} className="whitespace-nowrap px-3 py-2 text-left font-normal">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {CSV_ROWS.map((row) => (
                      <tr key={row.join()} className="border-b border-ink-800/70 text-mist-400">
                        {row.map((cell, i) => (
                          <td key={i} className="whitespace-nowrap px-3 py-1.5">
                            {cell || <span className="text-mist-700">—</span>}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="border-t border-ink-700 bg-good-500/[0.05] px-4 py-3">
                <p className="text-2xs text-good-300">
                  → 5 repeated support escalations, one detected workflow
                </p>
              </div>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── final CTA ───────────────────────────────────────────────── */}
      <section className="relative overflow-hidden">
        <div
          aria-hidden
          className="pointer-events-none absolute left-1/2 top-1/2 h-72 w-[46rem] -translate-x-1/2 -translate-y-1/2 animate-drift rounded-full bg-good-600/[0.10] blur-[110px]"
        />
        <div className="relative mx-auto max-w-3xl px-6 py-28 text-center">
          <Reveal>
            <h2 className="text-balance text-3xl font-semibold tracking-tight text-mist-100 sm:text-4xl">
              Stop asking people what should be automated.
            </h2>
            <p className="mt-6 text-lg font-medium leading-relaxed text-mist-300">
              Watch the work. Find the loop. Let LOOP build it.
            </p>
            <p className="mx-auto mt-4 max-w-xl text-sm leading-relaxed text-mist-500">
              LOOP turns the repetitive work already happening across your organisation into
              reviewed, validated and approved automations.
            </p>
            <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
              <Link className="btn-primary px-6 py-2.5 text-xs" href="/dashboard">
                Explore LOOP
              </Link>
              <Link className="btn-ghost px-6 py-2.5 text-xs" href="/discovery">
                View the workflow
              </Link>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ── footer ──────────────────────────────────────────────────── */}
      <footer className="border-t border-ink-800">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-6 py-9">
          <div>
            <p className="text-xs font-semibold tracking-tight text-mist-200">LOOP</p>
            <p className="text-2xs text-mist-600">Workflow intelligence. Runs locally.</p>
          </div>
          <nav className="ml-auto flex flex-wrap gap-x-5 gap-y-2">
            {[
              { href: "/dashboard", label: "Product" },
              { href: "#how", label: "How it works" },
              { href: "/discovery", label: "Discoveries" },
              { href: "/automations", label: "Automation" },
              { href: "/activity", label: "Activity" },
            ].map((item) => (
              <Link
                key={item.label}
                className="text-2xs text-mist-500 transition-colors hover:text-mist-200"
                href={item.href}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        </div>
      </footer>
    </div>
  );
}
