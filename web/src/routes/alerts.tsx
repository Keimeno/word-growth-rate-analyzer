import { createFileRoute, stripSearchParams } from "@tanstack/react-router";
import { useAlerts } from "@/api/generated/endpoints";
import { useAsOf } from "@/api/hooks";
import { PageHeader } from "@/components/AppShell";
import { DataTable } from "@/components/DataTable";
import { ScopeLink, StatusBadge, StrengthWord, TermLink } from "@/components/Entity";
import { EmptyState, Loaded, Panel } from "@/components/Panel";
import { Segmented } from "@/components/Pickers";
import { KpiRow, StatTile } from "@/components/Stat";
import { ago, count, formatDateTime, strength } from "@/lib/format";
import { intentKind } from "@/lib/kinds";
import { useSetSearch } from "@/lib/navigation";
import { alertsDefaults, alertsSearch } from "@/lib/search";

export const Route = createFileRoute("/alerts")({
  validateSearch: alertsSearch,
  search: { middlewares: [stripSearchParams(alertsDefaults)] },
  component: AlertsPage,
});

/** Every alert and forecast alert sent (WEB-DASHBOARD.md §6.3), each a click from its
 * term page and the explainer. */
function AlertsPage() {
  const search = Route.useSearch();
  const set = useSetSearch();
  const asOf = useAsOf();
  const alerts = useAlerts({ ...asOf, range: search.range });
  const rows = alerts.data;
  const days = { "7d": "7 days", "30d": "30 days", "90d": "90 days" }[search.range] ?? search.range;
  return (
    <>
      <PageHeader
        title="Alerts"
        actions={
          <Segmented
            label="Range"
            value={search.range}
            onChange={(range) => set({ range })}
            options={[
              ["7d", "7 days"],
              ["30d", "30 days"],
              ["90d", "90 days"],
            ]}
          />
        }
      >
        What was sent to your phone, the newest first. Open a term for why it trended.
      </PageHeader>
      <div className="flex flex-col gap-4">
        <KpiRow>
          <StatTile
            label="Alerts sent"
            value={rows ? count(rows.length) : "…"}
            unit={`in ${days}`}
            hint="at most 5 a day, every group"
          />
          <StatTile
            label="Terms"
            value={rows ? count(new Set(rows.map((row) => row.term)).size) : "…"}
            unit="different"
          />
          <StatTile
            label="Scopes"
            value={rows ? count(new Set(rows.map((row) => row.scope)).size) : "…"}
            unit="alerted in"
          />
          <StatTile
            label="Forecast alerts"
            value={rows ? count(rows.filter((row) => row.kind === "forecast").length) : "…"}
            hint="where a term should show up next"
          />
          <StatTile
            label="Failed to send"
            value={rows ? count(rows.filter((row) => !row.ok).length) : "…"}
            hint={
              rows && rows.every((row) => row.ok)
                ? "every alert reached ntfy"
                : "see the rows marked failed"
            }
          />
        </KpiRow>
        <Panel
          title="Sent"
          subtitle={`Alerts and forecast alerts of the last ${days}, the newest first`}
          flush
        >
          <Loaded query={alerts} shape="table">
            {(rows) => (
              <DataTable
                label="Alerts sent"
                rows={rows}
                rowKey={(row) => `${row.time}|${row.scope}|${row.term}`}
                limit={50}
                empty={
                  <EmptyState title="No alerts in this range">
                    Instant alerts need a strength of 10 and 20 people, at most 5 a day.
                  </EmptyState>
                }
                columns={[
                  {
                    id: "time",
                    header: "Sent",
                    sort: (row) => row.time,
                    cell: (row) => (
                      <span className="whitespace-nowrap" title={formatDateTime(row.time)}>
                        {ago(row.time)}
                      </span>
                    ),
                  },
                  {
                    id: "term",
                    header: "Term",
                    cell: (row) => (
                      <TermLink
                        term={row.term}
                        kind={
                          row.term_kind ??
                          intentKind(row.term) ??
                          (row.term.includes(" ") ? "phrase" : "word")
                        }
                        scope={row.scope}
                      />
                    ),
                  },
                  { id: "scope", header: "Where", cell: (row) => <ScopeLink scope={row.scope} /> },
                  {
                    id: "kind",
                    header: "Kind",
                    wide: true,
                    cell: (row) => (
                      <span className="whitespace-nowrap">
                        {row.kind === "forecast"
                          ? "Forecast"
                          : `Trend${row.horizon ? `, ${row.horizon}` : ""}`}
                      </span>
                    ),
                  },
                  {
                    id: "strength",
                    header: "Strength",
                    wide: true,
                    cell: (row) =>
                      row.score === null ? "–" : <StrengthWord value={strength(row.score)} />,
                  },
                  {
                    id: "message",
                    header: "Said",
                    wide: true,
                    cell: (row) => (
                      <span className="line-clamp-2 text-xs text-ink-secondary">{row.message}</span>
                    ),
                  },
                  {
                    id: "ok",
                    header: "",
                    cell: (row) =>
                      row.ok ? null : <StatusBadge status="critical">Failed</StatusBadge>,
                  },
                ]}
              />
            )}
          </Loaded>
        </Panel>
      </div>
    </>
  );
}
