"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { TrustBadge } from "@/components/trust-ladder";
import {
  Empty,
  ErrorNote,
  Meter,
  PageHeader,
  PageSkeleton,
  Panel,
  Stat,
} from "@/components/ui";
import { useDomains, useRoi } from "@/lib/api/queries";
import { hours, percent } from "@/lib/format";
import type { CoveragePoint } from "@/lib/api/types";

const AXIS = { stroke: "#3a4354", fontSize: 10 };
const GRID = "#1e232c";

export default function RoiPage() {
  const { data, isLoading, error } = useRoi();
  const { data: domains } = useDomains();

  if (isLoading) return <PageSkeleton rows={3} />;
  if (error) return <div className="p-8"><ErrorNote error={error} /></div>;
  if (!data) return null;

  // Coverage trend, one line per automation.
  const byAutomation = new Map<string, { name: string; points: CoveragePoint[] }>();
  for (const point of data.coverage_trend) {
    const entry = byAutomation.get(point.automation_id) ?? {
      name: point.automation_name,
      points: [],
    };
    entry.points.push(point);
    byAutomation.set(point.automation_id, entry);
  }
  const maxSequence = Math.max(1, ...data.coverage_trend.map((p) => p.sequence));
  const trendRows = Array.from({ length: maxSequence }, (_, index) => {
    const row: Record<string, number | string> = { run: index + 1 };
    for (const [id, entry] of byAutomation) {
      const point = entry.points.find((p) => p.sequence === index + 1);
      if (point) row[id] = Math.round(point.coverage * 1000) / 10;
    }
    return row;
  });
  const seriesColours = ["#3b82f6", "#10b981", "#f59e0b", "#a78bfa", "#f87171"];

  const distribution = data.trust_distribution.map((entry) => ({
    level: entry.level,
    count: entry.count,
  }));
  const levelColour: Record<string, string> = {
    OBSERVE: "#3a4354",
    SUGGEST: "#6b7688",
    SHADOW: "#3b82f6",
    ASSIST: "#f59e0b",
    AUTONOMOUS: "#10b981",
  };

  return (
    <div className="pb-16">
      <PageHeader
        eyebrow="Impact"
        title="How much work we're taking off people"
        subtitle="Two numbers, and they are deliberately different. Possible is what we could save if every workflow we found were automated. Saved so far counts only automations you have actually approved to run, multiplied by how much of the job they really handle on their own."
      />

      <div className="space-y-6 px-8 pt-6">
        <EffortBand
          burden={data.projected_annual_hours + data.interruption_tax_hours}
          possible={data.projected_annual_hours}
          saved={data.realised_annual_hours}
        />

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Possible to save"
            value={hours(data.projected_annual_hours)}
            unit="hrs/yr"
            tone="accent"
            hint="If everything we found were automated"
          />
          <Stat
            label="Saved so far"
            value={hours(data.realised_annual_hours)}
            unit="hrs/yr"
            tone={data.realised_annual_hours > 0 ? "good" : "default"}
            hint="Only what approved automations actually handle today"
          />
          <Stat
            label="Time lost switching apps"
            value={hours(data.interruption_tax_hours)}
            unit="hrs/yr"
            tone="warn"
            hint={`${hours(data.interruption_tax_recovered_hours)} hrs of it won back so far`}
          />
          <Stat
            label="Handled without a person"
            value={percent(data.average_coverage)}
            hint={`${data.autonomous_count} automation(s) now run start to finish`}
          />
        </div>

        <Panel
          title="Possible against saved so far"
          hint="The gap is the work still to do. We show it rather than hide it."
        >
          <div className="space-y-4 px-4 py-4">
            <ProgressRow
              label="Time doing the work"
              realised={data.realised_annual_hours}
              projected={data.projected_annual_hours}
            />
            <ProgressRow
              label="Time lost switching apps"
              realised={data.interruption_tax_recovered_hours}
              projected={data.interruption_tax_hours}
              tone="warn"
            />
          </div>
        </Panel>

        <div className="grid gap-6 lg:grid-cols-2">
          <Panel
            title="Getting better with practice"
            hint="How much of each job the automation handled by itself, run after run, while it was still practising safely."
          >
            {trendRows.length === 0 ? (
              <Empty
                title="No practice runs yet"
                hint="This fills in once the automations have run a few times."
              />
            ) : (
              <div className="h-64 px-2 py-4">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={trendRows} margin={{ top: 4, right: 12, bottom: 4, left: -18 }}>
                    <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
                    <XAxis
                      dataKey="run"
                      {...AXIS}
                      tickLine={false}
                      label={{ value: "practice run", position: "insideBottom", offset: -2, fill: "#6b7688", fontSize: 10 }}
                    />
                    <YAxis {...AXIS} tickLine={false} unit="%" domain={[0, 100]} />
                    <Tooltip
                      contentStyle={{
                        background: "#11141a",
                        border: "1px solid #2a3140",
                        borderRadius: 6,
                        fontSize: 11,
                      }}
                      labelStyle={{ color: "#8b96a8" }}
                      formatter={(value: number, key: string) => [
                        `${value}%`,
                        byAutomation.get(key)?.name ?? key,
                      ]}
                    />
                    {Array.from(byAutomation.keys()).map((id, index) => (
                      <Line
                        key={id}
                        type="monotone"
                        dataKey={id}
                        stroke={seriesColours[index % seriesColours.length]}
                        strokeWidth={1.75}
                        dot={false}
                        connectNulls
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </Panel>

          <Panel title="How far each automation has earned its way">
            <div className="h-64 px-2 py-4">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={distribution} margin={{ top: 4, right: 12, bottom: 4, left: -18 }}>
                  <CartesianGrid stroke={GRID} strokeDasharray="2 4" vertical={false} />
                  <XAxis dataKey="level" {...AXIS} tickLine={false} interval={0} />
                  <YAxis {...AXIS} tickLine={false} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{
                      background: "#11141a",
                      border: "1px solid #2a3140",
                      borderRadius: 6,
                      fontSize: 11,
                    }}
                    labelStyle={{ color: "#8b96a8" }}
                  />
                  <Bar dataKey="count" radius={[3, 3, 0, 0]}>
                    {distribution.map((entry) => (
                      <Cell key={entry.level} fill={levelColour[entry.level] ?? "#3b82f6"} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </Panel>
        </div>

        <Panel title="Per automation">
          {data.automations.length === 0 ? (
            <Empty title="No automations yet" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-ink-700 text-left">
                    <th className="px-4 py-2 font-medium text-mist-500">Automation</th>
                    <th className="px-4 py-2 font-medium text-mist-500">Trust</th>
                    <th className="px-4 py-2 text-right font-medium text-mist-500">Hrs/yr saved</th>
                    <th className="px-4 py-2 text-right font-medium text-mist-500">Switching</th>
                    <th className="px-4 py-2 text-right font-medium text-mist-500">Got it right</th>
                    <th className="px-4 py-2 text-right font-medium text-mist-500">Runs</th>
                    <th className="px-4 py-2 font-medium text-mist-500">Handled alone</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-800">
                  {data.automations.map((automation) => (
                    <tr key={automation.id}>
                      <td className="px-4 py-2.5 text-mist-200">{automation.name}</td>
                      <td className="px-4 py-2.5">
                        <TrustBadge level={automation.trust_level} />
                      </td>
                      <td className="tnum px-4 py-2.5 text-right text-accent-400">
                        {hours(automation.annual_hours)}
                      </td>
                      <td className="tnum px-4 py-2.5 text-right text-warn-400">
                        {hours(automation.interruption_tax_hours)}
                      </td>
                      <td className="tnum px-4 py-2.5 text-right text-mist-300">
                        {automation.replay_accuracy === null
                          ? "—"
                          : percent(automation.replay_accuracy, 1)}
                      </td>
                      <td className="tnum px-4 py-2.5 text-right text-mist-400">
                        {automation.shadow_run_count}
                      </td>
                      <td className="px-4 py-2.5">
                        <div className="flex items-center gap-2">
                          <Meter value={automation.coverage} tone="good" />
                          <span className="tnum w-9 shrink-0 text-right text-2xs text-mist-400">
                            {percent(automation.coverage)}
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        {domains && domains.items.length > 0 && (
          <Panel
            title="Effort reduction by area"
            hint="What could be handed over, against what is being spent today. Scaled by how much of each job a machine could really take on."
          >
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-ink-700 text-left">
                    <th className="px-4 py-2 font-medium text-mist-500">Area</th>
                    <th className="px-4 py-2 text-right font-medium text-mist-500">
                      Spent now
                    </th>
                    <th className="px-4 py-2 text-right font-medium text-mist-500">
                      Of which interruption
                    </th>
                    <th className="px-4 py-2 text-right font-medium text-mist-500">
                      Reclaimable
                    </th>
                    <th className="px-4 py-2 font-medium text-mist-500">Effort reduction</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-ink-800">
                  {[...domains.items]
                    .sort((a, b) => b.reclaimable_hours - a.reclaimable_hours)
                    .map((domain) => (
                      <tr key={domain.key}>
                        <td className="px-4 py-2.5 text-mist-200">
                          {domain.label}
                          {domain.is_template && (
                            <span className="ml-2 text-2xs text-warn-400">not researched</span>
                          )}
                        </td>
                        <td className="tnum px-4 py-2.5 text-right text-mist-300">
                          {hours(domain.annual_hours + domain.interruption_hours)}
                        </td>
                        <td className="tnum px-4 py-2.5 text-right text-warn-400">
                          {hours(domain.interruption_hours)}
                        </td>
                        <td className="tnum px-4 py-2.5 text-right text-good-400">
                          {domain.do_not_automate ? "—" : hours(domain.reclaimable_hours)}
                        </td>
                        <td className="px-4 py-2.5">
                          {domain.do_not_automate ? (
                            <span className="text-2xs text-bad-400">
                              Too variable — kept human
                            </span>
                          ) : (
                            <div className="flex items-center gap-2">
                              <Meter value={domain.effort_reduction} tone="good" />
                              <span className="tnum w-9 shrink-0 text-right text-2xs text-mist-300">
                                {percent(domain.effort_reduction)}
                              </span>
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </Panel>
        )}

        <Panel title="Detection summary">
          <div className="grid gap-4 px-4 py-4 sm:grid-cols-3">
            <Figure
              label="Workflows detected"
              value={String(data.total_clusters)}
              hint="Distinct repetitive workflows mined from the log"
            />
            <Figure
              label="Recommended"
              value={String(data.automatable_clusters)}
              hint="Consistent enough to automate safely"
            />
            <Figure
              label="Deliberately not automated"
              value={String(data.do_not_automate_clusters)}
              hint="Too variable or too judgement-heavy. Documented, not automated."
            />
          </div>
        </Panel>
      </div>
    </div>
  );
}

/** A working day, in hours — the unit people actually think in. */
const WORKING_DAY_HOURS = 8;
/** One person, full time, for a year: 8 hours × 5 days × 48 weeks. */
const PERSON_YEAR_HOURS = WORKING_DAY_HOURS * 5 * 48;

/**
 * The headline: the same hours, said in a unit somebody can picture.
 *
 * Hours per year is the honest unit but a poor one for judging scale — nobody
 * has an instinct for whether 646 is a lot. Working days and full-time people
 * are the same number, restated so the answer is obvious without arithmetic.
 */
function EffortBand({
  burden,
  possible,
  saved,
}: {
  burden: number;
  possible: number;
  saved: number;
}) {
  const days = Math.round(burden / WORKING_DAY_HOURS);
  const people = burden / PERSON_YEAR_HOURS;
  const share = burden > 0 ? possible / burden : 0;

  return (
    <Panel
      title="The work we found"
      hint={`Working days assume an ${WORKING_DAY_HOURS}-hour day and a 48-week year — the same basis the hours are counted on.`}
    >
      <div className="px-4 py-4">
        <p className="text-sm leading-relaxed text-mist-200">
          People here spend{" "}
          <strong className="tnum font-semibold text-mist-100">{hours(burden)} hours a year</strong>{" "}
          doing jobs LOOP watched them repeat — about{" "}
          <strong className="tnum font-semibold text-mist-100">
            {days.toLocaleString()} working days
          </strong>
          , or {people.toFixed(1)} full-time {people === 1 ? "person" : "people"}.
        </p>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <p className="eyebrow">LOOP could take over</p>
            <p className="metric mt-1.5 text-2xl text-accent-400">
              {hours(possible)}
              <span className="ml-1.5 text-xs font-normal tracking-normal text-mist-500">
                hrs/yr
              </span>
            </p>
            <div className="mt-2.5">
              <Meter value={share} tone="accent" />
            </div>
            <p className="mt-2 text-2xs leading-snug text-mist-500">
              {percent(share)} of the repeated work. The rest needs a person to decide.
            </p>
          </div>

          <div>
            <p className="eyebrow">It has taken over so far</p>
            <p
              className={`metric mt-1.5 text-2xl ${saved > 0 ? "text-good-400" : "text-mist-400"}`}
            >
              {hours(saved)}
              <span className="ml-1.5 text-xs font-normal tracking-normal text-mist-500">
                hrs/yr
              </span>
            </p>
            <div className="mt-2.5">
              <Meter value={possible > 0 ? saved / possible : 0} tone="good" />
            </div>
            <p className="mt-2 text-2xs leading-snug text-mist-500">
              {saved > 0
                ? `${percent(possible > 0 ? saved / possible : 0)} of what is possible. Approve more to close the gap.`
                : "Nothing approved yet, so nothing is counted. This stays at zero until you say yes."}
            </p>
          </div>
        </div>
      </div>
    </Panel>
  );
}

function ProgressRow({
  label,
  realised,
  projected,
  tone = "accent",
}: {
  label: string;
  realised: number;
  projected: number;
  tone?: "accent" | "warn";
}) {
  const ratio = projected > 0 ? realised / projected : 0;
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="eyebrow">{label}</span>
        <span className="tnum text-2xs text-mist-400">
          <span className="font-semibold text-mist-100">{hours(realised)}</span> realised of{" "}
          {hours(projected)} projected
          <span className="ml-2 text-mist-500">({percent(ratio)})</span>
        </span>
      </div>
      <Meter value={ratio} tone={tone === "warn" ? "warn" : "good"} height="h-2" />
    </div>
  );
}

function Figure({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div>
      <p className="eyebrow">{label}</p>
      <p className="tnum mt-1.5 text-2xl font-semibold leading-none text-mist-100">{value}</p>
      <p className="mt-2 text-2xs leading-snug text-mist-500">{hint}</p>
    </div>
  );
}
