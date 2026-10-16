import { useEffect, useMemo, useState } from "react";

import { ArrowRight, CheckCircle2, CircleAlert, RadioTower, Settings2, Waypoints } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { ConfigBundle, DiagnosticCheck, ServiceStatus } from "@/lib/api";
import { cn } from "@/lib/utils";

const AUDIO_BITRATE_OPTIONS = [128, 160, 192, 256, 320];
const LATENCY_OPTIONS = [80, 120, 250, 500, 1000];
const MUX_RATE_OPTIONS = [384, 512, 600, 768, 1000];

const PRESETS: Array<{
  id: string;
  title: string;
  description: string;
  profile: ConfigBundle["site"]["profile"];
}> = [
  {
    id: "balanced",
    title: "Balanced",
    description: "Good general-purpose transport for public internet paths without over-tuning.",
    profile: {
      name: "Balanced",
      audio_bitrate_kbps: 256,
      sample_rate_hz: 48000,
      channels: 2,
      srt_latency_ms: 120,
      mux_rate_kbps: 600,
      pcr_period_ms: 40,
      enable_video: false,
      video_codec: "mpeg2video",
      video_bitrate_kbps: 0,
      video_resolution: "1280x720",
      video_frame_rate: 25,
      video_source: "none",
    },
  },
  {
    id: "stable",
    title: "Stable",
    description: "More forgiving buffering for longer-distance links or shakier routing.",
    profile: {
      name: "Stable",
      audio_bitrate_kbps: 192,
      sample_rate_hz: 48000,
      channels: 2,
      srt_latency_ms: 250,
      mux_rate_kbps: 512,
      pcr_period_ms: 40,
      enable_video: false,
      video_codec: "mpeg2video",
      video_bitrate_kbps: 0,
      video_resolution: "1280x720",
      video_frame_rate: 25,
      video_source: "none",
    },
  },
  {
    id: "low-latency",
    title: "Low latency",
    description: "Tighter transport settings when you trust the network path and need quicker turnaround.",
    profile: {
      name: "Low Latency",
      audio_bitrate_kbps: 192,
      sample_rate_hz: 48000,
      channels: 2,
      srt_latency_ms: 80,
      mux_rate_kbps: 384,
      pcr_period_ms: 40,
      enable_video: false,
      video_codec: "mpeg2video",
      video_bitrate_kbps: 0,
      video_resolution: "1280x720",
      video_frame_rate: 25,
      video_source: "none",
    },
  },
];

const STEP_ITEMS = [
  {
    title: "Preset",
    summary: "Pick a sensible starting transport profile.",
    icon: Settings2,
  },
  {
    title: "Input",
    summary: "Tell EasySRT what to listen to.",
    icon: RadioTower,
  },
  {
    title: "Destination",
    summary: "Point the sender at the receiver endpoint.",
    icon: Waypoints,
  },
  {
    title: "Review",
    summary: "Save, validate, and move into control.",
    icon: CheckCircle2,
  },
] as const;

const DIAGNOSTIC_COPY: Record<string, { title: string; guidance: string }> = {
  "ffmpeg-binary-present": {
    title: "FFmpeg installed",
    guidance: "The VM needs a working FFmpeg binary before EasySRT can generate or run the sender command.",
  },
  "ffmpeg-binary": {
    title: "FFmpeg installed",
    guidance: "The VM needs a working FFmpeg binary before EasySRT can generate or run the sender command.",
  },
  "ffmpeg-version-readable": {
    title: "FFmpeg responds",
    guidance: "Version output is a quick sanity check that the binary can actually be executed.",
  },
  "ffmpeg-version": {
    title: "FFmpeg responds",
    guidance: "Version output is a quick sanity check that the binary can actually be executed.",
  },
  "config-valid": {
    title: "Configuration valid",
    guidance: "The backend accepted the current site config and can derive runtime artifacts from it.",
  },
  "runtime-config-current": {
    title: "Runtime file current",
    guidance: "The generated runtime config matches the saved settings on disk.",
  },
  "sender-env-current": {
    title: "Sender env current",
    guidance: "The sender service has the latest generated FFmpeg command in its environment file.",
  },
  "runtime-config": {
    title: "Runtime file present",
    guidance: "The generated runtime config exists on disk and can be used by service control and diagnostics.",
  },
  "sender-env": {
    title: "Sender env present",
    guidance: "The sender environment file exists on disk and contains the command that systemd will execute.",
  },
  "service-name": {
    title: "Service name configured",
    guidance: "The backend has a concrete systemd unit name to target for service actions and diagnostics.",
  },
  "service-unit-installed": {
    title: "Sender service installed",
    guidance: "Systemd knows about the sender unit that the control tab will start and stop.",
  },
  "sender-service-state": {
    title: "Sender service state readable",
    guidance: "EasySRT can inspect the sender unit and report meaningful control status.",
  },
  "input-reachability": {
    title: "Input reachable",
    guidance: "The upstream source responds from the VM, so the sender should be able to pull audio from it.",
  },
  "destination-health": {
    title: "Destination looks sane",
    guidance: "The destination host and port passed a basic network-level precheck from the VM.",
  },
};

export function OnboardingPanel({
  config,
  diagnostics,
  status,
  onSave,
  onAction,
  onOpenControl,
  onOpenConfig,
  onOpenDiagnostics,
}: {
  config: ConfigBundle;
  diagnostics?: { checks: DiagnosticCheck[] };
  status?: ServiceStatus;
  onSave: (site: ConfigBundle["site"]) => Promise<void>;
  onAction: (action: "start") => Promise<void>;
  onOpenControl: () => void;
  onOpenConfig: () => void;
  onOpenDiagnostics: () => void;
}) {
  const [stepIndex, setStepIndex] = useState(0);
  const [draft, setDraft] = useState(config.site);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "success" | "error">("idle");
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [startState, setStartState] = useState<"idle" | "starting" | "error">("idle");
  const [startMessage, setStartMessage] = useState<string | null>(null);

  useEffect(() => {
    setDraft(config.site);
  }, [config.site]);

  const checks = useMemo(() => diagnostics?.checks ?? [], [diagnostics?.checks]);
  const readiness = useMemo(() => {
    const important = checks.filter((check) => check.blocking || check.category === "input" || check.category === "output");
    const blockingIssues = important.filter((check) => !check.ok && check.blocking);
    const advisoryIssues = important.filter((check) => !check.ok && !check.blocking);
    return {
      important,
      blockingIssues,
      advisoryIssues,
      ready: blockingIssues.length === 0,
    };
  }, [checks]);

  function update<K extends keyof ConfigBundle["site"]>(key: K, value: ConfigBundle["site"][K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  function applyPreset(profile: ConfigBundle["site"]["profile"]) {
    update("profile", profile);
  }

  function updateDestinationHost(rawValue: string) {
    const parsed = splitHostAndPort(rawValue);
    if (parsed.port !== null) {
      update("destination", { ...draft.destination, host: parsed.host, port: parsed.port });
      return;
    }
    update("destination", { ...draft.destination, host: rawValue });
  }

  function updateDestinationPort(rawValue: string) {
    const sanitized = rawValue.replace(/[^\d]/g, "");
    if (!sanitized) {
      return;
    }
    update("destination", { ...draft.destination, port: Number(sanitized) });
  }

  async function handleSave() {
    setSaveState("saving");
    setSaveMessage(null);
    try {
      await onSave(draft);
      setSaveState("success");
      setSaveMessage("Routing saved. The backend regenerated runtime artifacts and refreshed the service preflight state.");
    } catch (error) {
      setSaveState("error");
      setSaveMessage(error instanceof Error ? error.message : "Unable to save onboarding settings.");
    }
  }

  async function handleStart() {
    setStartState("starting");
    setStartMessage(null);
    try {
      await onAction("start");
      setStartState("idle");
      setStartMessage("Sender started. Move to Control to watch the live service state.");
    } catch (error) {
      setStartState("error");
      setStartMessage(error instanceof Error ? error.message : "Unable to start sender.");
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[0.34fr_0.66fr]">
      <Card className="space-y-6">
        <div>
          <p className="section-label">Onboarding</p>
          <h2 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">Get to first clean send without turning setup into a wall of fields.</h2>
          <p className="soft-text mt-3 text-sm leading-6">
            This flow keeps the first pass narrow: pick a sensible preset, wire the source, point at the receiver, then check that the machine is actually ready.
          </p>
        </div>
        <ol className="space-y-3">
          {STEP_ITEMS.map((step, index) => {
            const Icon = step.icon;
            const isCurrent = index === stepIndex;
            const isComplete = index < stepIndex;
            return (
              <li
                key={step.title}
                className={cn(
                  "rounded-[24px] border p-4 transition",
                  isCurrent ? "border-[rgba(133,221,198,0.34)] bg-[rgba(133,221,198,0.1)]" : "border-white/10 bg-black/20",
                )}
              >
                <button className="w-full text-left" onClick={() => setStepIndex(index)} type="button">
                  <div className="flex items-start gap-3">
                    <span
                      className={cn(
                        "mt-0.5 flex h-10 w-10 items-center justify-center rounded-full text-sm font-semibold",
                        isCurrent || isComplete
                          ? "bg-[linear-gradient(135deg,#c9f8a3,#72decf)] text-slate-950"
                          : "border border-white/10 bg-black/30 text-slate-300",
                      )}
                    >
                      {isComplete ? <CheckCircle2 size={18} /> : <Icon size={18} />}
                    </span>
                    <div className="min-w-0">
                      <div className="text-base font-semibold text-white">{step.title}</div>
                      <p className="soft-text mt-1 text-sm leading-6">{step.summary}</p>
                    </div>
                  </div>
                </button>
              </li>
            );
          })}
        </ol>
        <div className="rounded-[24px] border border-white/10 bg-black/20 p-4 text-sm text-slate-300">
          <div className="flex items-center justify-between gap-4">
            <span className="font-medium text-white">Current service state</span>
            <span className="rounded-full border border-white/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-200">
              {status?.status ?? "unknown"}
            </span>
          </div>
          <p className="soft-text mt-3 leading-6">
            {status?.detail ?? "Service status will appear here once the backend responds."}
          </p>
        </div>
      </Card>

      <Card className="space-y-6">
        {stepIndex === 0 ? (
          <div className="space-y-6">
            <div>
              <p className="section-label">Step 1</p>
              <h3 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">Choose a transport preset that matches the line, not every edge case.</h3>
              <p className="soft-text mt-3 max-w-3xl text-sm leading-6">
                You can still fine-tune later in Configuration. The job here is to pick a stable starting point so the rest of the flow stays understandable.
              </p>
            </div>
            <div className="grid gap-4 lg:grid-cols-3">
              {PRESETS.map((preset) => {
                const active = draft.profile.name === preset.profile.name;
                return (
                  <button
                    key={preset.id}
                    type="button"
                    onClick={() => applyPreset(preset.profile)}
                    className={cn(
                      "rounded-[28px] border p-5 text-left transition",
                      active
                        ? "border-[rgba(133,221,198,0.38)] bg-[linear-gradient(145deg,rgba(133,221,198,0.16),rgba(111,186,168,0.08))]"
                        : "border-white/10 bg-black/20 hover:border-white/20",
                    )}
                  >
                    <div className="flex items-center justify-between gap-4">
                      <div className="text-lg font-semibold text-white">{preset.title}</div>
                      {active ? (
                        <span className="rounded-full border border-emerald-300/20 bg-emerald-300/10 px-3 py-1 text-xs uppercase tracking-[0.18em] text-emerald-100">
                          Selected
                        </span>
                      ) : null}
                    </div>
                    <p className="soft-text mt-3 text-sm leading-6">{preset.description}</p>
                    <dl className="mt-5 space-y-2 text-sm text-slate-300">
                      <PresetRow label="Audio" value={`${preset.profile.audio_bitrate_kbps} kbps`} />
                      <PresetRow label="Latency" value={`${preset.profile.srt_latency_ms} ms`} />
                      <PresetRow label="Mux rate" value={`${preset.profile.mux_rate_kbps} kbps`} />
                    </dl>
                  </button>
                );
              })}
            </div>
          </div>
        ) : null}

        {stepIndex === 1 ? (
          <div className="space-y-6">
            <div>
              <p className="section-label">Step 2</p>
              <h3 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">Set the source in plain broadcast terms.</h3>
              <p className="soft-text mt-3 max-w-3xl text-sm leading-6">
                Start with a friendly input name and the exact URL or file path the VM should pull from. No other tuning belongs here.
              </p>
            </div>
            <div className="grid gap-5 md:grid-cols-2">
              <Field label="Input Name">
                <Input value={draft.input.name} onChange={(event) => update("input", { ...draft.input, name: event.target.value })} />
              </Field>
              <Field label="Input URL">
                <Input value={draft.input.url} onChange={(event) => update("input", { ...draft.input, url: event.target.value })} />
              </Field>
            </div>
          </div>
        ) : null}

        {stepIndex === 2 ? (
          <div className="space-y-6">
            <div>
              <p className="section-label">Step 3</p>
              <h3 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">Point the sender at the receiver and keep the transport readable.</h3>
              <p className="soft-text mt-3 max-w-3xl text-sm leading-6">
                Paste a plain host or a full <span className="font-medium text-slate-200">host:port</span> pair. If you need to fine-tune the transport later, the full Configuration tab is still there.
              </p>
            </div>
            <div className="grid gap-5 md:grid-cols-2">
              <Field label="Destination Name">
                <Input
                  value={draft.destination.name}
                  onChange={(event) => update("destination", { ...draft.destination, name: event.target.value })}
                />
              </Field>
              <Field label="Destination Host">
                <Input value={draft.destination.host} onChange={(event) => updateDestinationHost(event.target.value)} />
              </Field>
              <Field label="Destination Port">
                <Input
                  type="text"
                  inputMode="numeric"
                  pattern="[0-9]*"
                  value={draft.destination.port}
                  onChange={(event) => updateDestinationPort(event.target.value)}
                />
              </Field>
              <Field label="Latency">
                <SelectField
                  value={draft.profile.srt_latency_ms}
                  options={LATENCY_OPTIONS}
                  formatLabel={(value) => `${value} ms`}
                  onChange={(value) => update("profile", { ...draft.profile, srt_latency_ms: value })}
                />
              </Field>
              <Field label="Audio Bitrate">
                <SelectField
                  value={draft.profile.audio_bitrate_kbps}
                  options={AUDIO_BITRATE_OPTIONS}
                  formatLabel={(value) => `${value} kbps`}
                  onChange={(value) => update("profile", { ...draft.profile, audio_bitrate_kbps: value })}
                />
              </Field>
              <Field label="Mux Rate">
                <SelectField
                  value={draft.profile.mux_rate_kbps}
                  options={MUX_RATE_OPTIONS}
                  formatLabel={(value) => `${value} kbps`}
                  onChange={(value) => update("profile", { ...draft.profile, mux_rate_kbps: value })}
                />
              </Field>
            </div>
          </div>
        ) : null}

        {stepIndex === 3 ? (
          <div className="space-y-6">
            <div>
              <p className="section-label">Step 4</p>
              <h3 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">Save the routing, then let the backend tell you if the machine is truly ready.</h3>
              <p className="soft-text mt-3 max-w-3xl text-sm leading-6">
                This is where onboarding hands off to real system state. Save once, read the checks in plain language, then move into Control when the machine looks trustworthy.
              </p>
            </div>

            <div className="grid gap-5 lg:grid-cols-[0.92fr_1.08fr]">
              <div className="rounded-[28px] border border-white/10 bg-black/20 p-5">
                <p className="text-xs uppercase tracking-[0.24em] text-slate-400">Draft Summary</p>
                <h4 className="mt-2 text-xl font-semibold text-white">{draft.input.name || "Unnamed input"}</h4>
                <dl className="mt-5 space-y-3 text-sm text-slate-300">
                  <SummaryRow label="Input URL" value={draft.input.url || "Not set"} />
                  <SummaryRow
                    label="Destination"
                    value={`${draft.destination.host || "Not set"}:${draft.destination.port || "?"}`}
                  />
                  <SummaryRow label="Preset" value={draft.profile.name} />
                  <SummaryRow label="Audio" value={`${draft.profile.audio_bitrate_kbps} kbps`} />
                  <SummaryRow label="Latency" value={`${draft.profile.srt_latency_ms} ms`} />
                  <SummaryRow label="Mux rate" value={`${draft.profile.mux_rate_kbps} kbps`} />
                </dl>
              </div>

              <div className="rounded-[28px] border border-white/10 bg-black/20 p-5">
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <p className="text-xs uppercase tracking-[0.24em] text-slate-400">Readiness</p>
                    <h4 className="mt-2 text-xl font-semibold text-white">
                      {readiness.ready ? "No blocking issues detected" : "Some blocking issues still need attention"}
                    </h4>
                  </div>
                  <span
                    className={cn(
                      "rounded-full border px-3 py-1 text-xs uppercase tracking-[0.18em]",
                      readiness.ready ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-100" : "border-amber-300/20 bg-amber-300/10 text-amber-100",
                    )}
                  >
                    {readiness.blockingIssues.length} blocking
                  </span>
                </div>
                <div className="mt-5 space-y-3">
                  {readiness.important.length > 0 ? (
                    readiness.important.map((check) => {
                      const copy = DIAGNOSTIC_COPY[check.name] ?? {
                        title: check.name,
                        guidance: "This check comes directly from the backend diagnostics layer.",
                      };
                      return (
                        <div
                          key={check.name}
                          className={cn(
                            "rounded-[22px] border p-4",
                            check.ok ? "border-white/10 bg-black/25" : check.blocking ? "border-rose-300/20 bg-rose-300/8" : "border-amber-300/20 bg-amber-300/8",
                          )}
                        >
                          <div className="flex items-start justify-between gap-4">
                            <div>
                              <div className="font-medium text-white">{copy.title}</div>
                              <p className="mt-1 text-sm leading-6 text-slate-400">{copy.guidance}</p>
                            </div>
                            {check.ok ? (
                              <CheckCircle2 className="mt-1 shrink-0 text-emerald-200" size={18} />
                            ) : (
                              <CircleAlert className="mt-1 shrink-0 text-amber-200" size={18} />
                            )}
                          </div>
                          <p className="mt-3 text-sm text-slate-300">{check.detail}</p>
                        </div>
                      );
                    })
                  ) : (
                    <div className="rounded-[22px] border border-white/10 bg-black/25 p-4 text-sm text-slate-300">
                      Save the routing once to refresh backend diagnostics, then the readiness cards will fill in here.
                    </div>
                  )}
                </div>
              </div>
            </div>

            {saveMessage ? (
              <div
                className={cn(
                  "rounded-[24px] border px-4 py-3 text-sm whitespace-pre-line",
                  saveState === "success"
                    ? "border-emerald-300/20 bg-emerald-300/10 text-emerald-100"
                    : "border-rose-300/20 bg-rose-300/10 text-rose-100",
                )}
              >
                {saveMessage}
              </div>
            ) : null}

            {startMessage ? (
              <div
                className={cn(
                  "rounded-[24px] border px-4 py-3 text-sm whitespace-pre-line",
                  startState === "error"
                    ? "border-rose-300/20 bg-rose-300/10 text-rose-100"
                    : "border-cyan-300/20 bg-cyan-300/10 text-cyan-100",
                )}
              >
                {startMessage}
              </div>
            ) : null}

            <div className="flex flex-wrap gap-3">
              <Button onClick={() => void handleSave()} disabled={saveState === "saving"}>
                {saveState === "saving" ? "Saving..." : "Save Routing"}
              </Button>
              <Button
                className="bg-[linear-gradient(135deg,#a7f2ef,#6fd0cb)]"
                onClick={() => void handleStart()}
                disabled={saveState === "saving" || startState === "starting" || !readiness.ready || !status?.allowed_actions.includes("start")}
              >
                {startState === "starting" ? "Starting..." : "Start Sender"}
              </Button>
              <Button className="bg-[linear-gradient(135deg,#9cd7ff,#6ea2dc)]" onClick={onOpenControl}>
                Open Control
              </Button>
              <Button className="bg-[linear-gradient(135deg,#d8eef9,#8ebcd8)]" onClick={onOpenConfig}>
                Full Configuration
              </Button>
              <Button className="bg-[linear-gradient(135deg,#d8eef9,#8ebcd8)]" onClick={onOpenDiagnostics}>
                Full Diagnostics
              </Button>
            </div>
          </div>
        ) : null}

        <div className="flex items-center justify-between gap-4 border-t border-white/10 pt-4">
          <button
            type="button"
            onClick={() => setStepIndex((current) => Math.max(0, current - 1))}
            className="text-sm font-medium text-slate-300 transition hover:text-white disabled:cursor-not-allowed disabled:text-slate-600"
            disabled={stepIndex === 0}
          >
            Back
          </button>
          <button
            type="button"
            onClick={() => setStepIndex((current) => Math.min(STEP_ITEMS.length - 1, current + 1))}
            className="inline-flex items-center gap-2 text-sm font-medium text-[var(--accent-strong)] transition hover:text-white disabled:cursor-not-allowed disabled:text-slate-600"
            disabled={stepIndex === STEP_ITEMS.length - 1}
          >
            Continue
            <ArrowRight size={16} />
          </button>
        </div>
      </Card>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="space-y-2 text-sm text-slate-300">
      <span className="text-xs uppercase tracking-[0.22em] text-slate-400">{label}</span>
      {children}
    </label>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-6 border-b border-white/5 pb-3 last:border-b-0 last:pb-0">
      <dt className="text-slate-400">{label}</dt>
      <dd className="text-right font-medium text-white">{value}</dd>
    </div>
  );
}

function PresetRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-4">
      <dt className="text-slate-400">{label}</dt>
      <dd className="font-medium text-white">{value}</dd>
    </div>
  );
}

function SelectField({
  value,
  options,
  formatLabel,
  onChange,
}: {
  value: number;
  options: number[];
  formatLabel: (value: number) => string;
  onChange: (value: number) => void;
}) {
  const choices = [...new Set([...options, value])].sort((left, right) => left - right);
  return (
    <select
      value={String(value)}
      onChange={(event) => onChange(Number(event.target.value))}
      className="w-full rounded-[18px] border border-white/10 bg-black/20 px-4 py-3 text-sm text-white outline-none transition focus:border-[var(--accent)]"
    >
      {choices.map((option) => (
        <option key={option} value={option} className="bg-slate-950 text-white">
          {formatLabel(option)}
        </option>
      ))}
    </select>
  );
}

function splitHostAndPort(value: string): { host: string; port: number | null } {
  const trimmed = value.trim();
  const ipv6Match = trimmed.match(/^\[([^\]]+)\]:(\d+)$/);
  if (ipv6Match) {
    return { host: ipv6Match[1], port: Number(ipv6Match[2]) };
  }

  const colonCount = (trimmed.match(/:/g) ?? []).length;
  if (colonCount === 1) {
    const [host, port] = trimmed.split(":");
    if (host && /^\d+$/.test(port ?? "")) {
      return { host, port: Number(port) };
    }
  }

  return { host: value, port: null };
}
