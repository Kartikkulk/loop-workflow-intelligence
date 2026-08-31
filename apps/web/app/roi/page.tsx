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
import { Empty, ErrorNote, Loading, Meter, PageHeader, Panel, Stat } from "@/components/ui";
import { useRoi } from "@/lib/api/queries";
import { hours, percent } from "@/lib/format";
import type { CoveragePoint } from "@/lib/api/types";

const AXIS = { stroke: "#3a4354", fontSize: 10 };
const GRID = "#1e232c";

export default function RoiPage() {
  const { data, isLoading, error } = useRoi();

  if (isLoading) return <Loading label="Computing impact" />;
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
        title="Hours, tax and coverage"
        subtitle="Projected is what the detected workflows are worth if fully automated. Realised counts only automations that have actually earned ASSIST or above, scaled by measured coverage — the defensible number rather than the impressive one."
      />

      <div className="space-y-6 px-8 pt-6">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Stat
            label="Projected hours"
            value={hours(data.projected_annual_hours)}
            unit="hrs/yr"
            tone="accent"
            hint="Across every automatable workflow detected"
          />
          <Stat
            label="Realised hours"
            value={hours(data.realised_annual_hours)}
            unit="hrs/yr"
            tone={data.realised_annual_hours > 0 ? "good" : "default"}
            hint="Trusted automations only, × their coverage"
          />
          <Stat
            label="Interruption tax"
            value={hours(data.interruption_tax_hours)}
            unit="hrs/yr"
            tone="warn"
            hint={`${hours(data.interruption_tax_recovered_hours)} hrs recovered so far`}
          />
          <Stat
            label="Average coverage"
            value={percent(data.average_coverage)}
            hint={`${data.autonomous_count} automation(s) fully autonomous`}
          />
        </div>

        <Panel
          title="Projected against realised"
          hint="The gap is the work still to do, and it is shown deliberately rather than hidden."
        >
          <div className="space-y-4 px-4 py-4">
            <ProgressRow
              label="Task hours"
              realised={data.realised_annual_hours}
              projected={data.projected_annual_hours}
            />
            <ProgressRow
              label="Interruption tax"
              realised={data.interruption_tax_recovered_hours}
              projected={data.interruption_tax_hours}
              tone="warn"
            />
          </div>
        </Panel>

        <div className="grid gap-6 lg:grid-cols-2">
          <Panel
            title="Coverage trend"
            hint="Running agreement rate per automation, over its shadow-run history."
          >
            {trendRows.length === 0 ? (
              <Empty
                title="No shadow runs yet"
                hint="Coverage is measured from real runs, so the chart fills in as the automations are exercised."
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
                      label={{ value: "shadow run", position: "insideBottom", offset: -2, fill: "#6b7688", fontSize: 10 }}
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

          <Panel title="Automations by trust level">
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
                    <th className="px-4 py-2 text-right font-medium text-mist-500">Hrs/yr</th>
                    <th className="px-4 py-2 text-right font-medium text-mist-500">Tax</th>
                    <th className="px-4 py-2 text-right font-medium text-mist-500">Replay</th>
                    <th className="px-4 py-2 text-right font-medium text-mist-500">Runs</th>
                    <th className="px-4 py-2 font-medium text-mist-500">Coverage</th>
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
