import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

function formatCheckName(name: string) {
  return name
    .split("-")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function statusPillClass(ok: boolean) {
  return ok
    ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-100"
    : "border-amber-300/20 bg-amber-300/10 text-amber-100";
}

function severityPillClass(severity: "info" | "warning" | "critical") {
  if (severity === "critical") {
    return "border-rose-300/20 bg-rose-300/10 text-rose-100";
  }
  if (severity === "warning") {
    return "border-amber-300/20 bg-amber-300/10 text-amber-100";
  }
  return "border-cyan-300/20 bg-cyan-300/10 text-cyan-100";
}

export function DiagnosticsPanel({
  diagnostics,
  logs,
  system,
  diagnosticsError,
  logsError,
  systemError,
}: {
  diagnostics?: {
    checks: Array<{
      name: string;
      ok: boolean;
      detail: string;
      severity: "info" | "warning" | "critical";
      category: "runtime" | "input" | "output" | "service" | "system";
      blocking: boolean;
    }>;
  };
  logs?: { service_name: string; lines: string[] };
  system?: {
    app_version: string;
    installed_commit: string | null;
    platform: string;
    ffmpeg_available: boolean;
    ffmpeg_binary: string;
    config_path: string;
    data_path: string;
  };
  diagnosticsError?: string | null;
  logsError?: string | null;
  systemError?: string | null;
}) {
  const checks = diagnostics?.checks ?? [];
  const summary = {
    total: checks.length,
    passing: checks.filter((check) => check.ok).length,
    blocking: checks.filter((check) => check.blocking && !check.ok).length,
    warning: checks.filter((check) => check.severity === "warning" && !check.ok).length,
  };

  return (
    <div className="grid gap-6 lg:grid-cols-[0.95fr_1.05fr]">
      <Card className="space-y-4">
        <div>
          <p className="section-label">Diagnostics</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">System health</h2>
          <p className="soft-text mt-3 text-sm leading-6 text-slate-300">
            {summary.total > 0
              ? `${summary.passing}/${summary.total} checks passing. ${summary.blocking} blocking issue${summary.blocking === 1 ? "" : "s"}, ${summary.warning} warning${summary.warning === 1 ? "" : "s"}.`
              : "No diagnostics have been loaded yet."}
          </p>
        </div>
        <div className="space-y-3">
          {diagnosticsError ? (
            <div className="rounded-[24px] border border-rose-300/20 bg-rose-300/10 p-4 text-sm text-rose-100">{diagnosticsError}</div>
          ) : null}
          {checks.map((check) => (
            <div
              key={check.name}
              className={cn(
                "rounded-[24px] border bg-black/20 p-4",
                check.ok ? "border-white/10" : check.severity === "critical" ? "border-rose-300/20" : "border-amber-300/20",
              )}
            >
              <div className="flex items-center justify-between gap-4">
                <span className="font-medium text-white">{formatCheckName(check.name)}</span>
                <div className="flex flex-wrap items-center justify-end gap-2">
                  <span className={cn("rounded-full border px-3 py-1 text-xs uppercase tracking-[0.18em]", statusPillClass(check.ok))}>
                    {check.ok ? "Passing" : "Issue"}
                  </span>
                  <span className={cn("rounded-full border px-3 py-1 text-xs uppercase tracking-[0.18em]", severityPillClass(check.severity))}>
                    {check.severity}
                  </span>
                </div>
              </div>
              <div className="mt-3 flex flex-wrap gap-2 text-[11px] uppercase tracking-[0.18em] text-slate-400">
                <span className="rounded-full border border-white/10 px-2 py-1 text-slate-300">{check.category}</span>
                <span className="rounded-full border border-white/10 px-2 py-1 text-slate-300">
                  {check.blocking ? "Blocking" : "Advisory"}
                </span>
              </div>
              <p className="mt-2 text-sm text-slate-400">{check.detail}</p>
            </div>
          ))}
        </div>
        {systemError ? (
          <div className="rounded-[24px] border border-rose-300/20 bg-rose-300/10 p-4 text-sm text-rose-100">{systemError}</div>
        ) : null}
        {system ? (
          <div className="rounded-[24px] border border-white/10 bg-black/20 p-4 text-sm text-slate-300">
            <div>
              EasySRT: {system.app_version}
              {system.installed_commit ? ` (${system.installed_commit.slice(0, 7)})` : ""}
            </div>
            <div>Platform: {system.platform}</div>
            <div>FFmpeg: {system.ffmpeg_available ? system.ffmpeg_binary : "missing"}</div>
            <div>Config Path: {system.config_path}</div>
            <div>Data Path: {system.data_path}</div>
          </div>
        ) : null}
      </Card>
      <Card className="space-y-4">
        <div>
          <p className="section-label">Logs</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">Recent service output</h2>
        </div>
        {logsError ? (
          <div className="rounded-[24px] border border-rose-300/20 bg-rose-300/10 p-4 text-sm text-rose-100">{logsError}</div>
        ) : null}
        <pre className="h-[28rem] overflow-y-auto overflow-x-hidden whitespace-pre-wrap break-words rounded-[24px] border border-white/10 bg-black/20 p-4 text-xs leading-6 text-cyan-100">
          {(logs?.lines ?? ["No logs loaded"]).join("\n")}
        </pre>
      </Card>
    </div>
  );
}
