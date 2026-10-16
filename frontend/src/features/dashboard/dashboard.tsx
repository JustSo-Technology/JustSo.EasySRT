import { AlertTriangle, ArrowUpRight, Play, RotateCcw, ShieldAlert, Square } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { ConfigBundle, RedundancyNodeSummary, RedundancyStatus, SavedSiteConfigSummary, ServiceStatus } from "@/lib/api";

export function Dashboard({
  config,
  activeSavedConfig,
  status,
  redundancy,
  onAction,
  actionError,
  isActionPending,
}: {
  config: ConfigBundle;
  activeSavedConfig?: SavedSiteConfigSummary | null;
  status?: ServiceStatus;
  redundancy?: RedundancyStatus;
  onAction: (action: "start" | "stop" | "restart") => Promise<void>;
  actionError?: string | null;
  isActionPending: boolean;
}) {
  const allowedActions = new Set(status?.allowed_actions ?? []);

  return (
    <div className="space-y-6">
      {redundancy ? <RedundancyOverview redundancy={redundancy} /> : null}
      <div className="grid gap-6 lg:grid-cols-[1.5fr_0.95fr]">
        <Card className="min-w-0 space-y-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="section-label">Stream Control</p>
              <h2 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">{config.app.station_name}</h2>
              <p className="soft-text mt-3 max-w-xl text-sm leading-6">
                Live routing and transport summary for the active sender.
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-200">
                  {activeSavedConfig ? `Active config: ${activeSavedConfig.name}` : "Active config: unsaved live changes"}
                </span>
              </div>
            </div>
            <div className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-100">
              {status?.running ? "Streaming now" : status?.status ?? "Unknown"}
            </div>
          </div>
          <dl className="grid gap-4 md:grid-cols-2">
            <Metric label="Input" value={`${config.site.input.name} · ${config.site.input.url}`} />
            <Metric
              label="Destination"
              value={`${config.site.destination.protocol}://${formatDestinationHost(config.site.destination.host)}:${config.site.destination.port}`}
            />
            <Metric label="Profile" value={config.site.profile.name} />
            <Metric label="Mux Rate" value={`${config.site.profile.mux_rate_kbps} kbps`} />
          </dl>
          <div className="flex flex-wrap gap-3">
            <Button className="gap-2" onClick={() => onAction("start")} disabled={isActionPending || !allowedActions.has("start")}>
              <Play size={16} />
              Start
            </Button>
            <Button
              className="gap-2 border-rose-300/20 bg-[linear-gradient(135deg,#f6c17a,#f38d7a)] text-slate-950 shadow-[0_10px_35px_rgba(243,141,122,0.18)] hover:shadow-[0_12px_40px_rgba(243,141,122,0.26)]"
              onClick={() => onAction("stop")}
              disabled={isActionPending || !allowedActions.has("stop")}
            >
              <Square size={16} />
              Stop
            </Button>
            <Button
              className="gap-2 border-white/10 bg-white/5 text-white shadow-none hover:bg-white/10 hover:text-white"
              onClick={() => onAction("restart")}
              disabled={isActionPending || !allowedActions.has("restart")}
            >
              <RotateCcw size={16} />
              Restart
            </Button>
          </div>
          {actionError ? (
            <div className="rounded-[24px] border border-rose-300/20 bg-rose-300/10 px-4 py-3 text-sm whitespace-pre-line text-rose-100">
              {actionError}
            </div>
          ) : null}
          {!status?.preflight_ok && status?.preflight_failures.length ? (
            <div className="rounded-[24px] border border-amber-300/20 bg-amber-300/10 px-4 py-3 text-sm text-amber-50">
              <div className="font-medium">Start is blocked by preflight checks.</div>
              <ul className="mt-2 list-disc pl-5 text-amber-100">
                {status.preflight_failures.map((failure) => (
                  <li key={failure}>{failure}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </Card>
        <Card className="min-w-0 space-y-5">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="section-label">Runtime Preview</p>
              <h3 className="mt-3 text-2xl font-semibold tracking-[-0.04em] text-white">Sender command</h3>
            </div>
            <ArrowUpRight size={18} className="text-[var(--accent)]" />
          </div>
          <pre className="overflow-x-auto rounded-[24px] border border-white/10 bg-black/20 p-4 text-xs leading-6 text-cyan-100">
            {config.runtime.ffmpeg_command}
          </pre>
          <div className="flex items-start gap-3 rounded-[24px] border border-amber-300/20 bg-amber-300/10 p-4 text-sm text-amber-50">
            <AlertTriangle size={18} className="mt-0.5 shrink-0" />
            This instance is running in development mode. Do not expose it to untrusted networks.
          </div>
        </Card>
      </div>
    </div>
  );
}

function RedundancyOverview({ redundancy }: { redundancy: RedundancyStatus }) {
  return (
    <Card className="min-w-0 space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="section-label">Partner Redundancy</p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <div className={statusBadgeClass(redundancy.product_state)}>{formatProductState(redundancy.product_state)}</div>
            <div className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-100">
              Live node: {redundancy.live_node_label ?? "Unavailable"}
            </div>
          </div>
          <p className="soft-text mt-3 max-w-3xl text-sm leading-6">{redundancy.product_state_reason}</p>
        </div>
        <div className="flex items-start gap-3 rounded-[24px] border border-white/10 bg-black/20 px-4 py-3 text-sm text-slate-100">
          <ShieldAlert size={18} className="mt-0.5 shrink-0 text-[var(--accent)]" />
          <div>
            <div className="font-medium">Last action</div>
            <div className="soft-text mt-1">{redundancy.last_action}</div>
          </div>
        </div>
      </div>
      <dl className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Metric label="Standby" value={redundancy.standby_node_label ?? "Not configured"} />
        <Metric label="Config Sync" value={formatSyncState(redundancy.config_sync_status)} />
        <Metric label="Takeover Readiness" value={redundancy.partner_takeover_ready ? "Ready" : "Not ready"} />
        <Metric label="Output Verification" value={formatOutputState(redundancy.output_status)} />
      </dl>
      <div className="grid gap-4 lg:grid-cols-2">
        {redundancy.nodes.map((node) => (
          <NodeCard key={node.id} node={node} />
        ))}
      </div>
      <div className="rounded-[24px] border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-200">
        <span className="font-medium text-white">Output detail:</span> {redundancy.output_status_reason}
      </div>
      <div className="rounded-[24px] border border-white/10 bg-black/20 px-4 py-3 text-sm text-slate-200">
        <span className="font-medium text-white">Config sync:</span> {redundancy.config_sync_reason}
      </div>
    </Card>
  );
}

function NodeCard({ node }: { node: RedundancyNodeSummary }) {
  return (
    <div className="rounded-[24px] border border-white/10 bg-black/20 p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-lg font-semibold text-white">{node.label}</div>
          <div className="mt-1 text-xs uppercase tracking-[0.2em] text-slate-400">{formatNodeRole(node.role)}</div>
        </div>
        <div className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-200">
          {node.connection_state}
        </div>
      </div>
      <dl className="mt-4 grid gap-3 sm:grid-cols-2">
        <Metric label="Stream Authority" value={node.stream_authority ? "Yes" : "No"} />
        <Metric label="Config Authority" value={node.config_authority ? "Yes" : "No"} />
        <Metric label="Runtime" value={formatRuntimeState(node.runtime_status)} />
        <Metric label="Sync" value={formatSyncState(node.sync_status)} />
      </dl>
      <p className="soft-text mt-4 text-sm leading-6">
        {node.detail ?? (node.takeover_ready ? "This node is takeover-ready." : "This node is not takeover-ready.")}
      </p>
    </div>
  );
}

function formatDestinationHost(host: string) {
  if (host.includes(":") && !host.startsWith("[")) {
    return `[${host}]`;
  }
  return host;
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[24px] border border-white/10 bg-black/20 p-5">
      <dt className="text-xs uppercase tracking-[0.24em] text-slate-400">{label}</dt>
      <dd className="mt-3 text-sm leading-6 text-white">{value}</dd>
    </div>
  );
}

function formatProductState(state: RedundancyStatus["product_state"]) {
  switch (state) {
    case "protected":
      return "Protected";
    case "degraded_protection":
      return "Degraded Protection";
    case "failed_over":
      return "Failed Over";
    case "transitioning":
      return "Transitioning";
    default:
      return "Unprotected";
  }
}

function formatOutputState(state: RedundancyStatus["output_status"]) {
  switch (state) {
    case "healthy":
      return "Healthy";
    case "degraded":
      return "Degraded";
    case "no_verified_output":
      return "No verified output";
    case "verification_unavailable":
      return "Verification unavailable";
    default:
      return "Unknown";
  }
}

function formatSyncState(state: RedundancyStatus["config_sync_status"] | RedundancyNodeSummary["sync_status"]) {
  switch (state) {
    case "up_to_date":
      return "Up to date";
    case "syncing":
      return "Syncing";
    case "behind":
      return "Behind";
    case "sync_failed":
      return "Sync failed";
    case "read_only":
      return "Read only";
    case "not_applicable":
      return "Not applicable";
    default:
      return "Unknown";
  }
}

function formatRuntimeState(state: RedundancyNodeSummary["runtime_status"]) {
  switch (state) {
    case "healthy":
      return "Healthy";
    case "valid":
      return "Valid";
    case "degraded":
      return "Degraded";
    case "invalid":
      return "Invalid";
    default:
      return "Unknown";
  }
}

function formatNodeRole(role: RedundancyNodeSummary["role"]) {
  switch (role) {
    case "live":
      return "Live";
    case "standby":
      return "Standby";
    case "partner":
      return "Partner";
    default:
      return "Unknown";
  }
}

function statusBadgeClass(state: RedundancyStatus["product_state"]) {
  if (state === "protected") {
    return "rounded-full border border-emerald-300/20 bg-emerald-300/15 px-4 py-2 text-sm font-medium text-emerald-50";
  }
  if (state === "failed_over") {
    return "rounded-full border border-sky-300/20 bg-sky-300/15 px-4 py-2 text-sm font-medium text-sky-50";
  }
  if (state === "transitioning") {
    return "rounded-full border border-white/10 bg-white/10 px-4 py-2 text-sm font-medium text-white";
  }
  if (state === "degraded_protection") {
    return "rounded-full border border-amber-300/20 bg-amber-300/15 px-4 py-2 text-sm font-medium text-amber-50";
  }
  return "rounded-full border border-slate-300/15 bg-slate-300/10 px-4 py-2 text-sm font-medium text-slate-100";
}
