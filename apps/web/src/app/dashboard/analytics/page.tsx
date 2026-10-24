"use client";

import { Skeleton, SkeletonRegion } from "@/components/ui/Skeleton";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useOrganization } from "@/providers/OrganizationProvider";
import type { UsageSummary } from "@/lib/types";

const RANGES = [7, 30, 90];

// Flat: these sit inside the stats card below, divided by a hairline rather
// than each getting its own shadow.
function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="p-4">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="text-2xl font-semibold text-gray-900 mt-1">{value}</p>
      {hint && <p className="text-xs text-gray-500 mt-1">{hint}</p>}
    </div>
  );
}

function Panel({ title, children }: { title?: string; children: React.ReactNode }) {
  return (
    <section className="rounded-2xl border border-border bg-bg-white p-5">
      {title && <h2 className="text-sm font-medium text-gray-900 mb-3">{title}</h2>}
      {children}
    </section>
  );
}

const pct = (v: number | null) => (v === null ? "-" : `${(v * 100).toFixed(1)}%`);
const usd = (v: number | null) => (v === null ? "-" : `$${v.toFixed(v < 1 ? 4 : 2)}`);

export default function AnalyticsPage() {
  const { currentOrg } = useOrganization();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<UsageSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!currentOrg) return;
    let cancelled = false;
    api
      .get<UsageSummary>(`/api/v1/analytics/usage?days=${days}`, currentOrg.id)
      .then((d) => !cancelled && setData(d))
      .catch((e) => {
        if (cancelled) return;
        setData(null);
        setError(
          e instanceof ApiError && e.status === 403
            ? "Analytics are available to organization owners and admins."
            : e instanceof Error
              ? e.message
              : "Failed to load analytics"
        );
      })
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [currentOrg, days]);

  function selectRange(r: number) {
    if (r === days) return;
    setLoading(true);
    setError(null);
    setDays(r);
  }

  const maxDaily = Math.max(1, ...(data?.daily.map((d) => d.answers) ?? [1]));
  const stages = Object.entries(data?.avg_stage_ms ?? {}).sort((a, b) => b[1] - a[1]);
  const maxStage = Math.max(1, ...stages.map(([, ms]) => ms));

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900">Analytics</h1>
          <p className="text-gray-500 text-sm mt-1">Usage, abstention and cost across the workspace</p>
        </div>
        <div className="flex rounded-lg border border-gray-200 bg-white overflow-hidden text-sm">
          {RANGES.map((r) => (
            <button
              key={r}
              onClick={() => selectRange(r)}
              aria-pressed={days === r}
              className={`cursor-pointer px-3 py-1.5 ${days === r ? "bg-blue-600 text-white" : "text-gray-600 hover:bg-gray-50"}`}
            >
              {r}d
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <SkeletonRegion label="Loading analytics" className="space-y-6">
          <Panel>
            <div className="grid grid-cols-2 divide-y divide-gray-100 lg:grid-cols-4 lg:divide-y-0 lg:divide-x">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="p-4">
                  <Skeleton className="h-3 w-20" />
                  <Skeleton className="mt-3 h-7 w-24" />
                  <Skeleton className="mt-3 h-3 w-32" />
                </div>
              ))}
            </div>
          </Panel>
          <Panel title="Answers per day">
            <Skeleton className="h-32 w-full" />
          </Panel>
        </SkeletonRegion>
      ) : error ? (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-6 text-amber-800 text-sm">
          {error}
        </div>
      ) : data && data.total_answers === 0 ? (
        <div className="bg-bg-white rounded-2xl border border-border p-12 text-center text-gray-500 text-sm">
          No answers in the last {data.days} days.
        </div>
      ) : data ? (
        <div className="space-y-6">
          {data.truncated && (
            <p className="text-xs text-amber-700">
              Showing the most recent 5,000 answers; older ones in this range are excluded.
            </p>
          )}

          <Panel>
            <div className="grid grid-cols-2 divide-y divide-gray-100 lg:grid-cols-4 lg:divide-y-0 lg:divide-x">
              <Stat label="Answers" value={data.total_answers.toLocaleString()} />
              <Stat
                label="Abstention rate"
                value={pct(data.abstention_rate)}
                hint={`${data.abstained} refused for lack of evidence`}
              />
              <Stat label="Total cost" value={usd(data.total_cost_usd)} hint={`avg ${usd(data.avg_cost_usd)} / answer`} />
              <Stat
                label="Avg citations"
                value={data.avg_citations === null ? "-" : data.avg_citations.toFixed(1)}
                hint={`${data.conflicts_flagged} answers flagged conflicts`}
              />
            </div>
          </Panel>

          <Panel title="Answers per day">
            {data.daily.every((d) => d.answers === 0) ? (
              <div className="flex h-32 items-center justify-center text-sm text-text-muted">
                No answers recorded yet
              </div>
            ) : (
              <>
                <div className="relative flex items-end gap-0.5 h-32">
                  {data.daily.map((d) => (
                    <div
                      key={d.date}
                      className="flex-1 max-w-8 h-full flex flex-col justify-end"
                      title={`${d.date}: ${d.answers} answers, ${d.abstained} abstained, ${usd(d.cost_usd)}`}
                    >
                      <div
                        className="bg-primary/70 rounded-t transition-all"
                        style={{ height: `${Math.max((d.answers / maxDaily) * 100, d.answers > 0 ? 2 : 0)}%` }}
                      />
                    </div>
                  ))}
                </div>
                <div className="flex justify-between text-[11px] text-gray-500 mt-2">
                  <span>{data.daily[0]?.date}</span>
                  <span>{data.daily[data.daily.length - 1]?.date}</span>
                </div>
              </>
            )}
          </Panel>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Panel title="Retrieval strategy">
              <ul className="space-y-2 text-sm">
                {Object.entries(data.strategy_counts).map(([name, n]) => (
                  <li key={name} className="flex justify-between">
                    <span className="text-gray-600">{name}</span>
                    <span className="font-mono text-gray-900">{n}</span>
                  </li>
                ))}
                {data.agentic_answers > 0 && (
                  <li className="flex justify-between text-gray-500">
                    <span>deep research answers</span>
                    <span className="font-mono">{data.agentic_answers}</span>
                  </li>
                )}
                {Object.keys(data.strategy_counts).length === 0 && data.agentic_answers === 0 && (
                  <li className="text-gray-500">No retrieval runs recorded yet.</li>
                )}
              </ul>
            </Panel>

            <Panel title="Average stage latency">
              {stages.length === 0 ? (
                <p className="text-xs text-gray-500">No stage timings recorded yet.</p>
              ) : (
                <ul className="space-y-2 text-xs">
                  {stages.map(([name, ms]) => (
                    <li key={name}>
                      <div className="flex justify-between text-gray-600">
                        <span>{name}</span>
                        <span className="font-mono">{ms.toFixed(0)} ms</span>
                      </div>
                      <div className="h-1.5 bg-gray-100 rounded mt-1">
                        <div
                          className="h-1.5 bg-indigo-500 rounded"
                          style={{ width: `${(ms / maxStage) * 100}%` }}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>
        </div>
      ) : null}
    </div>
  );
}
