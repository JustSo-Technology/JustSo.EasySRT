import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { UpdateJobStatus, UpdateStatus } from "@/lib/api";

function shortCommit(commit: string | null | undefined) {
  return commit ? commit.slice(0, 7) : "unknown";
}

function formatTimestamp(value: string | null | undefined) {
  if (!value) {
    return "Not checked yet";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

export function UpdateModal({
  status,
  job,
  updateAvailable,
  isChecking,
  isInstalling,
  isPolling,
  pollError,
  onClose,
  onCheck,
  onInstall,
}: {
  status: UpdateStatus | undefined;
  job: UpdateJobStatus | undefined;
  updateAvailable: boolean;
  isChecking: boolean;
  isInstalling: boolean;
  isPolling: boolean;
  pollError: string | null;
  onClose: () => void;
  onCheck: () => void;
  onInstall: () => void;
}) {
  const effectiveStatus = job?.job_status && job.job_status !== "idle" ? job.job_status : status?.job_status ?? "idle";
  const effectiveStep = job?.current_step ?? status?.current_step ?? "Ready";
  const logLines = (job?.log_lines?.length ? job.log_lines : status?.log_lines) ?? [];
  const isRunning = effectiveStatus === "running";
  const isTerminal = effectiveStatus === "succeeded" || effectiveStatus === "failed" || effectiveStatus === "rolled_back";
  const latestCommit = job?.latest_commit ?? status?.latest_commit ?? null;
  const installedCommit = job?.installed_commit_after ?? status?.installed_commit ?? null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-[rgba(2,7,12,0.54)] px-4 py-4 backdrop-blur-[10px] sm:items-center sm:px-7 sm:py-6">
      <div className="absolute inset-0" onClick={onClose} />
      <Card className="float-in relative z-10 w-full max-w-5xl overflow-hidden rounded-[32px] border border-white/15 p-0 shadow-[0_24px_90px_rgba(0,0,0,0.42)]">
        <div className="grid max-h-[88vh] overflow-y-auto lg:grid-cols-[0.92fr_1.28fr]">
          <section className="border-b border-white/10 bg-[linear-gradient(160deg,rgba(8,24,31,0.96),rgba(5,12,18,0.92))] p-5 sm:p-7 lg:border-r lg:border-b-0">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="section-label">Updates</p>
                <h2 className="mt-3 text-3xl font-semibold tracking-[-0.05em] text-white">Control plane updates</h2>
              </div>
              <Button className="px-4 py-2.5" onClick={onClose}>
                Close
              </Button>
            </div>

            <div className="mt-8 rounded-[28px] border border-amber-300/20 bg-amber-300/10 p-5 text-sm text-amber-100">
              {status?.sender_message ?? "This update restarts the control plane only. The live sender is not restarted automatically."}
            </div>

            <div className="mt-8 grid gap-4">
              <Metric label="Installed commit" value={shortCommit(status?.installed_commit)} />
              <Metric label="Latest commit" value={shortCommit(latestCommit)} />
              <Metric label="Target ref" value={`${status?.repo_ref ?? "main"} · ${status?.repo_url ?? ""}`} />
              <Metric label="Last checked" value={formatTimestamp(status?.checked_at)} />
              <Metric label="Status" value={effectiveStatus} />
              <Metric label="Current step" value={effectiveStep} />
            </div>

            {(pollError || status?.error || job?.error) ? (
              <div className="mt-6 rounded-[24px] border border-rose-300/20 bg-rose-300/10 px-4 py-3 text-sm whitespace-pre-line text-rose-100">
                {pollError ?? job?.error ?? status?.error}
              </div>
            ) : null}

            <div className="mt-6 flex flex-wrap gap-3">
              <Button disabled={isChecking || isInstalling || isRunning} onClick={onCheck}>
                {isChecking ? "Checking..." : "Check again"}
              </Button>
              <Button
                className="bg-[linear-gradient(135deg,#9cd7ff,#6ea2dc)] text-slate-950"
                disabled={isInstalling || isRunning || !updateAvailable}
                onClick={onInstall}
              >
                {isInstalling || isRunning ? "Opening updater..." : "Open updater"}
              </Button>
            </div>

            {isRunning ? (
              <p className="mt-4 text-sm text-slate-300">
                The control plane may briefly disconnect while backend and frontend services restart. Keep this popup open and it will retry automatically.
              </p>
            ) : null}

            {isTerminal ? (
              <div className="mt-6 rounded-[24px] border border-white/10 bg-black/20 p-4 text-sm text-slate-300">
                <div>Result: {effectiveStatus}</div>
                <div>Installed after update: {shortCommit(installedCommit)}</div>
                <div>Backup path: {job?.backup_path ?? status?.backup_path ?? "n/a"}</div>
                <div>Stash ref: {job?.stash_ref ?? status?.stash_ref ?? "none"}</div>
                <div>Rollback: {job?.rollback_succeeded == null ? "not needed" : job?.rollback_succeeded ? "succeeded" : "failed"}</div>
              </div>
            ) : null}
          </section>

          <section className="bg-[linear-gradient(180deg,rgba(7,17,26,0.82),rgba(3,8,15,0.92))] p-5 sm:p-7">
            <div className="flex items-end justify-between gap-4">
              <div>
                <p className="section-label">Progress</p>
                <h3 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">Update activity</h3>
              </div>
              <div className="text-right text-sm text-slate-400">
                <div>{isRunning ? "Running" : isPolling ? "Reconnecting..." : "Idle"}</div>
                <div>{logLines.length} log lines</div>
              </div>
            </div>

            <pre className="mt-6 h-[30rem] overflow-y-auto overflow-x-hidden whitespace-pre-wrap break-words rounded-[24px] border border-white/10 bg-black/20 p-4 text-xs leading-6 text-cyan-100">
              {(logLines.length ? logLines : ["No update activity yet."]).join("\n")}
            </pre>
          </section>
        </div>
      </Card>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-[24px] border border-white/10 bg-black/20 p-4">
      <div className="text-xs uppercase tracking-[0.22em] text-slate-400">{label}</div>
      <div className="mt-2 text-sm font-medium text-white break-all">{value}</div>
    </div>
  );
}
