import { AlertTriangle, ArrowUpRight, Play, RotateCcw, ShieldAlert, Square } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { ConfigBundle, RedundancyNodeSummary, RedundancyStatus, ServiceStatus } from "@/lib/api";

export function Dashboard({
  config,
  status,
  statusUnavailable = false,
  statusUpdatedAt,
  redundancy,
  onAction,
  actionError,
  isActionPending,
}: {
  config: ConfigBundle;
  status?: ServiceStatus;
  statusUnavailable?: boolean;
  statusUpdatedAt?: number;
  redundancy?: RedundancyStatus;
  onAction: (action: "start" | "stop" | "restart", expectedSelectionId?: string) => Promise<void>;
  actionError?: string | null;
  isActionPending: boolean;
}) {
  const [restartReview, setRestartReview] = useState<ConfigBundle["selected"]>(null);
  const allowedActions = new Set(status?.allowed_actions ?? []);
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const media = status?.media;
  const unavailable = statusUnavailable || (statusUpdatedAt !== undefined && now - statusUpdatedAt > 7000);
  const mediaState = unavailable ? "unknown" : media?.state ?? "unknown";
  const stateLabel = mediaState === "healthy" ? "Healthy · local media progressing" : mediaState.charAt(0).toUpperCase() + mediaState.slice(1);
  const retrySeconds = media?.next_retry_at ? Math.max(0, Math.ceil((Date.parse(media.next_retry_at) - now) / 1000)) : null;
  const run = !unavailable ? status?.running_config : null;
  const applied = mediaState === "stopped" || unavailable ? undefined : media?.summary;
  const selected = config.selected;
  const liveUnknown = mediaState !== "stopped" && !run;
  const routeDescription = mediaState === "stopped"
    ? "Selected configuration for the next Start."
    : applied?.endpoint
      ? mediaState === "unknown" ? "Last observed applied route; waiting for fresh sender evidence." : "Applied route for the current sender."
      : "The running configuration is unknown. Selected settings do not establish what is on air.";

  return (
    <div className="space-y-6">
      {restartReview ? (
        <div role="dialog" aria-modal="true" aria-label="Review Restart" className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6">
          <Card className="max-w-xl space-y-4">
            <h3 className="text-xl font-semibold">Restart will interrupt the stream</h3>
            <p>Start selected preset {restartReview.source_name} · revision {restartReview.source_revision ?? "legacy"}. The current sender will stop first.</p>
            <Button disabled={isActionPending} onClick={() => {
              void onAction("restart", restartReview.id).then(() => setRestartReview(null)).catch(() => setRestartReview(null));
            }}>Confirm Restart</Button>
            <Button disabled={isActionPending} onClick={() => setRestartReview(null)}>Cancel</Button>
          </Card>
        </div>
      ) : null}
      {redundancy ? <RedundancyOverview redundancy={redundancy} /> : null}
      <div className="grid gap-6 lg:grid-cols-[1.5fr_0.95fr]">
        <Card className="min-w-0 space-y-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="section-label">Stream Control</p>
              <h2 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">{config.app.station_name}</h2>
              <p className="soft-text mt-3 max-w-xl text-sm leading-6">
                {routeDescription}
              </p>
              <div className="mt-4 flex flex-wrap gap-2">
                <span className="rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-200">
                  {selected ? `Selected: ${selected.source_name} · revision ${selected.source_revision ?? "legacy"}` : "No selected configuration"}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-300">Running configuration: {run?.selected ? `${run.selected.source_name} · revision ${run.selected.source_revision ?? "legacy"}` : mediaState === "stopped" ? "None — sender stopped" : "Unknown"}</p>
            </div>
            <div className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm text-slate-100">
              {stateLabel}
            </div>
          </div>
          <dl className="grid gap-4 md:grid-cols-2">
            <Metric label="Input" value={run?.site.input.name ?? applied?.input ?? (liveUnknown ? "Unknown" : config.site.input.name)} />
            <Metric
              label="Destination"
              value={applied?.endpoint ?? (liveUnknown ? "Unknown" : `${config.site.destination.protocol}://${formatDestinationHost(config.site.destination.host)}:${config.site.destination.port}`)}
            />
            <Metric label="Profile" value={run?.site.profile.name ?? applied?.profile ?? (liveUnknown ? "Unknown" : config.site.profile.name)} />
            <Metric label="Remote receipt" value="Unverified · confirm audio at the receiver" />
          </dl>
          <div role="status" className="space-y-2 rounded-[24px] border border-white/10 bg-black/20 p-4 text-sm text-slate-200">
            <p>{unavailable ? "Status is unavailable or stale. Refreshing sender evidence…" : media?.detail ?? "Media health is unavailable; process activity alone does not establish streaming."}</p>
            {!unavailable && media ? (
              <>
                {mediaState !== "stopped" ? <>
                  <p>Source audio: {media.input.value.toLocaleString()} samples · {progressAge(media.input.age_seconds)}</p>
                  <p>Local output: {media.output.value.toLocaleString()} bytes · {progressAge(media.output.age_seconds)}</p>
                </> : null}
                {mediaState === "retrying" ? <p>Retry {media.retry_count} · {retrySeconds === 0 ? "reconnecting…" : `next attempt in ${retrySeconds ?? "…"}s`}</p> : null}
                {media.last_recovery_at ? <p>Last recovery: {new Date(media.last_recovery_at).toLocaleString()}</p> : null}
                {media.policy.input_stall_seconds ? <p className="soft-text">Automatic recovery: input deadline {media.policy.input_stall_seconds}s, output deadline {media.policy.output_stall_seconds}s, retry delay up to {media.policy.retry_max_seconds}s.</p> : null}
              </>
            ) : null}
          </div>
          {status?.pending_configuration ? (
            <p className="rounded-[24px] border border-amber-300/20 bg-amber-300/10 p-4 text-sm text-amber-50">
              Selected configuration is awaiting Start/Restart. Automatic retries keep the running configuration shown above.
            </p>
          ) : null}
          {media?.events.length ? (
            <details className="rounded-[24px] border border-white/10 p-4 text-sm text-slate-200">
              <summary className="cursor-pointer">Recent recovery history</summary>
              <ul className="mt-3 space-y-2">
                {media.events.slice(-5).reverse().map((event, index) => (
                  <li key={`${event.at}-${index}`}>{new Date(event.at).toLocaleString()} · {event.state} · {event.reason.replaceAll("_", " ")} · attempt {event.attempt}</li>
                ))}
              </ul>
            </details>
          ) : null}
          <div className="flex flex-wrap gap-3">
            <Button className="gap-2" onClick={() => { void onAction("start", selected?.id).catch(() => undefined); }} disabled={isActionPending || !allowedActions.has("start") || !selected}>
              <Play size={16} />
              Start
            </Button>
            <Button
              className="gap-2 border-rose-300/20 bg-[linear-gradient(135deg,#f6c17a,#f38d7a)] text-slate-950 shadow-[0_10px_35px_rgba(243,141,122,0.18)] hover:shadow-[0_12px_40px_rgba(243,141,122,0.26)]"
              onClick={() => { void onAction("stop").catch(() => undefined); }}
              disabled={isActionPending || !allowedActions.has("stop")}
            >
              <Square size={16} />
              Stop
            </Button>
            <Button
              className="gap-2 border-white/10 bg-white/5 text-white shadow-none hover:bg-white/10 hover:text-white"
              onClick={() => setRestartReview(selected)}
              disabled={isActionPending || !allowedActions.has("restart") || !selected}
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

function progressAge(seconds: number | null) {
  return seconds === null ? "waiting for media" : `last progress ${Math.floor(seconds)}s ago`;
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
