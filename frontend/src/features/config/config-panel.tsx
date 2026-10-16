import { useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import type { ConfigBundle, SavedDestinationEntry, SavedInputEntry, SavedSiteConfigSummary } from "@/lib/api";

const AUDIO_BITRATE_OPTIONS = [128, 160, 192, 256, 320];
const LATENCY_OPTIONS = [80, 120, 250, 500, 1000, 2000];
const MUX_RATE_OPTIONS = [384, 512, 600, 768, 1000, 1500];
const SAMPLE_RATE_OPTIONS = [32000, 44100, 48000];
const PCR_PERIOD_OPTIONS = [10, 20, 40, 100];
const VIDEO_CODEC_OPTIONS: Array<ConfigBundle["site"]["profile"]["video_codec"]> = ["mpeg2video", "libx264"];
const VIDEO_BITRATE_OPTIONS = [500, 1000, 1500, 2000, 3000];
const VIDEO_RESOLUTION_OPTIONS = ["640x360", "720x576", "1280x720", "1920x1080"];
const VIDEO_FRAME_RATE_OPTIONS = [25, 30, 50];
const VIDEO_SOURCE_OPTIONS: Array<ConfigBundle["site"]["profile"]["video_source"]> = ["none", "black_test_frames"];

export function ConfigPanel({
  config,
  savedConfigs,
  savedInputs,
  savedDestinations,
  isLoadingSavedConfigs,
  isMutatingSavedConfigs,
  onSave,
  onLoadSaved,
  onRenameSaved,
  onDeleteSaved,
  onCreateSavedInput,
  onCreateSavedDestination,
}: {
  config: ConfigBundle;
  savedConfigs?: SavedSiteConfigSummary[];
  savedInputs?: SavedInputEntry[];
  savedDestinations?: SavedDestinationEntry[];
  isLoadingSavedConfigs?: boolean;
  isMutatingSavedConfigs?: boolean;
  onSave: (name: string, site: ConfigBundle["site"], overwrite?: boolean) => Promise<void>;
  onLoadSaved: (savedConfigId: string) => Promise<ConfigBundle>;
  onRenameSaved: (savedConfigId: string, name: string) => Promise<void>;
  onDeleteSaved: (savedConfigId: string) => Promise<void>;
  onCreateSavedInput: (input: ConfigBundle["site"]["input"]) => Promise<SavedInputEntry>;
  onCreateSavedDestination: (destination: ConfigBundle["site"]["destination"]) => Promise<SavedDestinationEntry>;
}) {
  const [site, setSite] = useState(config.site);
  const [isSaving, setIsSaving] = useState(false);
  const [isLoadingSaved, setIsLoadingSaved] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [saveState, setSaveState] = useState<"idle" | "success" | "error">("idle");
  const [isSaveDialogOpen, setIsSaveDialogOpen] = useState(false);
  const [isLoadMenuOpen, setIsLoadMenuOpen] = useState(false);
  const [saveName, setSaveName] = useState(defaultSaveName(config.site));
  const [showOverwriteWarning, setShowOverwriteWarning] = useState(false);
  const [renameTarget, setRenameTarget] = useState<SavedSiteConfigSummary | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<SavedSiteConfigSummary | null>(null);
  const [isInputMenuOpen, setIsInputMenuOpen] = useState(false);
  const [isDestinationMenuOpen, setIsDestinationMenuOpen] = useState(false);
  const [isCreateInputOpen, setIsCreateInputOpen] = useState(false);
  const [isCreateDestinationOpen, setIsCreateDestinationOpen] = useState(false);
  const [isAdvancedOpen, setIsAdvancedOpen] = useState(hasAdvancedOverrides(config.site.profile));
  const [isVideoPanelOpen, setIsVideoPanelOpen] = useState(config.site.profile.enable_video);
  const [draftInput, setDraftInput] = useState(config.site.input);
  const [draftDestination, setDraftDestination] = useState(config.site.destination);
  const [destinationEndpointInput, setDestinationEndpointInput] = useState(formatDestinationEndpoint(config.site.destination.protocol, config.site.destination.host, config.site.destination.port));
  const [draftDestinationEndpointInput, setDraftDestinationEndpointInput] = useState(
    formatDestinationEndpoint(config.site.destination.protocol, config.site.destination.host, config.site.destination.port),
  );
  const [entityMessage, setEntityMessage] = useState<string | null>(null);
  const [entityMessageTone, setEntityMessageTone] = useState<"success" | "error">("success");
  const inputMenuRef = useRef<HTMLDivElement | null>(null);
  const destinationMenuRef = useRef<HTMLDivElement | null>(null);
  const loadMenuRef = useRef<HTMLDivElement | null>(null);
  const saveDialogRef = useRef<HTMLDivElement | null>(null);
  const createInputDialogRef = useRef<HTMLDivElement | null>(null);
  const createDestinationDialogRef = useRef<HTMLDivElement | null>(null);
  const renameDialogRef = useRef<HTMLDivElement | null>(null);
  const deleteDialogRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setSite(config.site);
    setSaveName(defaultSaveName(config.site));
    setDraftInput(config.site.input);
    setDraftDestination(config.site.destination);
    setDestinationEndpointInput(formatDestinationEndpoint(config.site.destination.protocol, config.site.destination.host, config.site.destination.port));
    setDraftDestinationEndpointInput(formatDestinationEndpoint(config.site.destination.protocol, config.site.destination.host, config.site.destination.port));
    setIsAdvancedOpen(hasAdvancedOverrides(config.site.profile));
    setIsVideoPanelOpen(config.site.profile.enable_video);
  }, [config.site]);

  useEffect(() => {
    function handlePointerDown(event: MouseEvent) {
      const target = event.target;
      if (!(target instanceof Node)) {
        return;
      }
      if (isInputMenuOpen && inputMenuRef.current && !inputMenuRef.current.contains(target)) {
        setIsInputMenuOpen(false);
      }
      if (isDestinationMenuOpen && destinationMenuRef.current && !destinationMenuRef.current.contains(target)) {
        setIsDestinationMenuOpen(false);
      }
      if (isLoadMenuOpen && loadMenuRef.current && !loadMenuRef.current.contains(target)) {
        setIsLoadMenuOpen(false);
      }
      if (isSaveDialogOpen && saveDialogRef.current && !saveDialogRef.current.contains(target)) {
        setIsSaveDialogOpen(false);
        setShowOverwriteWarning(false);
      }
      if (isCreateInputOpen && createInputDialogRef.current && !createInputDialogRef.current.contains(target)) {
        setIsCreateInputOpen(false);
      }
      if (isCreateDestinationOpen && createDestinationDialogRef.current && !createDestinationDialogRef.current.contains(target)) {
        setIsCreateDestinationOpen(false);
      }
      if (renameTarget && renameDialogRef.current && !renameDialogRef.current.contains(target)) {
        setRenameTarget(null);
      }
      if (deleteTarget && deleteDialogRef.current && !deleteDialogRef.current.contains(target)) {
        setDeleteTarget(null);
      }
    }

    document.addEventListener("mousedown", handlePointerDown);
    return () => document.removeEventListener("mousedown", handlePointerDown);
  }, [deleteTarget, isCreateDestinationOpen, isCreateInputOpen, isDestinationMenuOpen, isInputMenuOpen, isLoadMenuOpen, isSaveDialogOpen, renameTarget]);

  const visibleSavedConfigs = savedConfigs ?? [];
  const visibleSavedInputs = savedInputs ?? [];
  const visibleSavedDestinations = savedDestinations ?? [];
  function update<K extends keyof ConfigBundle["site"]>(key: K, value: ConfigBundle["site"][K]) {
    setSite((current) => ({ ...current, [key]: value }));
  }

  async function handleSave() {
    setIsSaving(true);
    setSaveState("idle");
    setSaveMessage(null);
    try {
      const parsedDestination = parseDestinationEndpoint(destinationEndpointInput, site.destination);
      if (!parsedDestination) {
        throw new Error("Destination must be a full endpoint such as srt://203.39.245.44:16466");
      }
      const nextSite = { ...site, destination: parsedDestination };
      setSite(nextSite);
      await onSave(saveName, nextSite, showOverwriteWarning);
      setSaveState("success");
      setSaveMessage(`Site config saved as "${saveName}". Runtime artifacts were regenerated on the backend.`);
      setIsSaveDialogOpen(false);
      setShowOverwriteWarning(false);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Save failed";
      if (message.includes("already exists")) {
        setShowOverwriteWarning(true);
        setSaveMessage(`A saved config named "${saveName}" already exists. Save again to overwrite it.`);
      } else {
        setSaveState("error");
        setSaveMessage(message);
      }
    } finally {
      setIsSaving(false);
    }
  }

  async function handleLoadSaved(savedConfigId: string, savedConfigName: string) {
    setIsLoadingSaved(true);
    setSaveState("idle");
    setSaveMessage(null);
    try {
      const bundle = await onLoadSaved(savedConfigId);
      setSite(bundle.site);
      setSaveName(defaultSaveName(bundle.site));
      setSaveState("success");
      setSaveMessage(`Loaded saved config "${savedConfigName}". Current runtime artifacts were refreshed.`);
      setIsLoadMenuOpen(false);
    } catch (error) {
      setSaveState("error");
      setSaveMessage(error instanceof Error ? error.message : "Unable to load saved config.");
    } finally {
      setIsLoadingSaved(false);
    }
  }

  async function handleRenameSaved() {
    if (!renameTarget) {
      return;
    }
    setSaveState("idle");
    setSaveMessage(null);
    try {
      await onRenameSaved(renameTarget.id, renameValue);
      setSaveState("success");
      setSaveMessage(`Renamed saved config to "${renameValue}".`);
      setRenameTarget(null);
      setRenameValue("");
    } catch (error) {
      setSaveState("error");
      setSaveMessage(error instanceof Error ? error.message : "Unable to rename saved config.");
    }
  }

  async function handleDeleteSaved() {
    if (!deleteTarget) {
      return;
    }
    setSaveState("idle");
    setSaveMessage(null);
    try {
      await onDeleteSaved(deleteTarget.id);
      setSaveState("success");
      setSaveMessage(`Deleted saved config "${deleteTarget.name}".`);
      setDeleteTarget(null);
    } catch (error) {
      setSaveState("error");
      setSaveMessage(error instanceof Error ? error.message : "Unable to delete saved config.");
    }
  }

  async function handleCreateInput() {
    setEntityMessage(null);
    try {
      const created = await onCreateSavedInput(draftInput);
      update("input", { name: created.name, url: created.url });
      setEntityMessageTone("success");
      setEntityMessage(`Created saved input "${created.name}".`);
      setIsCreateInputOpen(false);
      setIsInputMenuOpen(false);
    } catch (error) {
      setEntityMessageTone("error");
      setEntityMessage(error instanceof Error ? error.message : "Unable to save input.");
    }
  }

  async function handleCreateDestination() {
    setEntityMessage(null);
    try {
      const parsedDestination = parseDestinationEndpoint(draftDestinationEndpointInput, draftDestination);
      if (!parsedDestination) {
        throw new Error("Destination must be a full endpoint such as srt://203.39.245.44:16466");
      }
      const created = await onCreateSavedDestination({ ...draftDestination, ...parsedDestination });
      update("destination", { name: created.name, protocol: created.protocol, host: created.host, port: created.port });
      setDestinationEndpointInput(formatDestinationEndpoint(created.protocol, created.host, created.port));
      setEntityMessageTone("success");
      setEntityMessage(`Created saved destination "${created.name}".`);
      setIsCreateDestinationOpen(false);
      setIsDestinationMenuOpen(false);
    } catch (error) {
      setEntityMessageTone("error");
      setEntityMessage(error instanceof Error ? error.message : "Unable to save destination.");
    }
  }

  return (
    <>
      <Card className="space-y-8">
        <div className="flex items-center justify-between gap-4">
          <div>
            <p className="section-label">Configuration</p>
            <h2 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">Stream configuration</h2>
            <p className="soft-text mt-3 max-w-3xl text-sm leading-6">
              Manage your stream routing. Save named configurations to quickly switch between setups.
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <div className="flex flex-wrap justify-end gap-2">
              <div className="relative" ref={loadMenuRef}>
                <Button
                  className="bg-[linear-gradient(135deg,#d8eef9,#8ebcd8)]"
                  onClick={() => setIsLoadMenuOpen((current) => !current)}
                  disabled={isLoadingSaved || isLoadingSavedConfigs || isMutatingSavedConfigs}
                >
                  {isLoadingSaved ? "Loading..." : "Load Saved Config"}
                </Button>
                {isLoadMenuOpen ? (
                  <div className="absolute right-0 top-[calc(100%+0.65rem)] z-20 w-[22rem] rounded-[24px] border border-white/10 bg-slate-950/96 p-3 shadow-[0_20px_60px_rgba(4,10,18,0.6)] backdrop-blur-xl">
                    <div className="px-3 pb-2">
                      <div className="text-xs uppercase tracking-[0.22em] text-slate-400">Saved Site Configs</div>
                    </div>
                    <div className="max-h-72 space-y-2 overflow-y-auto">
                      {visibleSavedConfigs.length > 0 ? (
                        visibleSavedConfigs.map((savedConfig) => (
                          <div key={savedConfig.id} className="rounded-[18px] border border-white/10 bg-black/20 px-4 py-3">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="flex flex-wrap items-center gap-2">
                                  <div className="font-medium text-white">{savedConfig.name}</div>
                                  {savedConfig.is_active ? (
                                    <span className="rounded-full border border-emerald-300/20 bg-emerald-300/10 px-2.5 py-0.5 text-[10px] uppercase tracking-[0.18em] text-emerald-100">
                                      Active
                                    </span>
                                  ) : null}
                                </div>
                                <div className="mt-1 text-xs uppercase tracking-[0.18em] text-slate-400">
                                  Updated {formatTimestamp(savedConfig.updated_at)}
                                </div>
                              </div>
                              <div className="flex shrink-0 flex-wrap gap-2">
                                <button
                                  type="button"
                                  onClick={() => void handleLoadSaved(savedConfig.id, savedConfig.name)}
                                  className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-slate-100 transition hover:bg-white/10"
                                >
                                  Load
                                </button>
                                <button
                                  type="button"
                                  onClick={() => {
                                    setRenameTarget(savedConfig);
                                    setRenameValue(savedConfig.name);
                                  }}
                                  className="rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium text-slate-100 transition hover:bg-white/10"
                                >
                                  Rename
                                </button>
                                <button
                                  type="button"
                                  onClick={() => setDeleteTarget(savedConfig)}
                                  className="rounded-full border border-rose-300/20 bg-rose-300/10 px-3 py-1.5 text-xs font-medium text-rose-100 transition hover:bg-rose-300/20"
                                >
                                  Delete
                                </button>
                              </div>
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-[18px] border border-white/10 bg-black/20 px-4 py-3 text-sm text-slate-300">
                          No saved site configs yet.
                        </div>
                      )}
                    </div>
                  </div>
                ) : null}
              </div>
              <Button onClick={() => setIsSaveDialogOpen(true)} disabled={isSaving}>
                {isSaving ? "Saving..." : saveState === "success" ? "Saved" : "Save Site Config"}
              </Button>
            </div>
            <span
              className={
                saveState === "success"
                  ? "text-xs uppercase tracking-[0.18em] text-emerald-200"
                  : saveState === "error"
                    ? "text-xs uppercase tracking-[0.18em] text-rose-200"
                    : "text-xs uppercase tracking-[0.18em] text-slate-500"
              }
            >
              {saveState === "success" ? "Confirmed" : saveState === "error" ? "Action failed" : "Configuration ready"}
            </span>
          </div>
        </div>
        {saveMessage ? (
          <div
            className={
              saveState === "success"
                ? "rounded-[24px] border border-emerald-300/20 bg-emerald-300/10 px-4 py-3 text-sm text-emerald-100"
                : "rounded-[24px] border border-rose-300/20 bg-rose-300/10 px-4 py-3 text-sm whitespace-pre-line text-rose-100"
            }
          >
            {saveMessage}
          </div>
        ) : null}
        {entityMessage ? (
          <div
            className={
              entityMessageTone === "success"
                ? "rounded-[24px] border border-emerald-300/20 bg-emerald-300/10 px-4 py-3 text-sm text-emerald-100"
                : "rounded-[24px] border border-rose-300/20 bg-rose-300/10 px-4 py-3 text-sm whitespace-pre-line text-rose-100"
            }
          >
            {entityMessage}
          </div>
        ) : null}
        <div className="grid gap-x-6 lg:grid-cols-[1.8fr_1fr]">
          <section className="space-y-6 rounded-[28px] border border-white/10 bg-black/20 p-5 sm:p-6">
            <div>
              <p className="text-xs uppercase tracking-[0.24em] text-slate-400">Input and Destination</p>
              <h3 className="mt-2 text-xl font-semibold text-white">Select the source and receiving endpoint</h3>
            </div>
            <div className="grid gap-5 md:grid-cols-2">
              <Field label="Input Name">
                <div className="relative" ref={inputMenuRef}>
                  <button
                    type="button"
                    onClick={() => setIsInputMenuOpen((current) => !current)}
                    className="flex w-full items-center justify-between rounded-[18px] border border-white/10 bg-black/20 px-4 py-3 text-left text-sm text-white transition hover:border-white/20"
                  >
                    <span>{site.input.name || "Select or create input"}</span>
                    <span className="text-xs uppercase tracking-[0.18em] text-slate-400">Select</span>
                  </button>
                  {isInputMenuOpen ? (
                    <div className="absolute left-0 top-[calc(100%+0.65rem)] z-20 w-full rounded-[24px] border border-white/10 bg-slate-950/96 p-3 shadow-[0_20px_60px_rgba(4,10,18,0.6)] backdrop-blur-xl">
                      <button
                        type="button"
                        onClick={() => {
                          setDraftInput(site.input);
                          setIsCreateInputOpen(true);
                        }}
                        className="w-full rounded-[18px] border border-white/10 bg-white/5 px-4 py-3 text-left text-sm font-medium text-white transition hover:bg-white/10"
                      >
                        Create New...
                      </button>
                      <div className="mt-2 max-h-72 space-y-2 overflow-y-auto">
                        {visibleSavedInputs.map((savedInput) => (
                          <button
                            key={savedInput.id}
                            type="button"
                            onClick={() => {
                              update("input", { name: savedInput.name, url: savedInput.url });
                              setIsInputMenuOpen(false);
                            }}
                            className="w-full rounded-[18px] border border-white/10 bg-black/20 px-4 py-3 text-left transition hover:border-white/20 hover:bg-black/30"
                          >
                            <div className="font-medium text-white">{savedInput.name}</div>
                            <div className="mt-1 text-sm text-slate-400">{savedInput.url}</div>
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              </Field>
              <Field label="Input URL">
                <Input value={site.input.url} onChange={(event) => update("input", { ...site.input, url: event.target.value })} />
              </Field>
              <Field label="Destination Name">
                <div className="relative" ref={destinationMenuRef}>
                  <button
                    type="button"
                    onClick={() => setIsDestinationMenuOpen((current) => !current)}
                    className="flex w-full items-center justify-between rounded-[18px] border border-white/10 bg-black/20 px-4 py-3 text-left text-sm text-white transition hover:border-white/20"
                  >
                    <span>{site.destination.name || "Select or create destination"}</span>
                    <span className="text-xs uppercase tracking-[0.18em] text-slate-400">Select</span>
                  </button>
                  {isDestinationMenuOpen ? (
                    <div className="absolute left-0 top-[calc(100%+0.65rem)] z-20 w-full rounded-[24px] border border-white/10 bg-slate-950/96 p-3 shadow-[0_20px_60px_rgba(4,10,18,0.6)] backdrop-blur-xl">
                      <button
                        type="button"
                        onClick={() => {
                          setDraftDestination(site.destination);
                          setDraftDestinationEndpointInput(formatDestinationEndpoint(site.destination.protocol, site.destination.host, site.destination.port));
                          setIsCreateDestinationOpen(true);
                        }}
                        className="w-full rounded-[18px] border border-white/10 bg-white/5 px-4 py-3 text-left text-sm font-medium text-white transition hover:bg-white/10"
                      >
                        Create New...
                      </button>
                      <div className="mt-2 max-h-72 space-y-2 overflow-y-auto">
                        {visibleSavedDestinations.map((savedDestination) => (
                          <button
                            key={savedDestination.id}
                            type="button"
                            onClick={() => {
                              const nextDestination = {
                                name: savedDestination.name,
                                protocol: savedDestination.protocol,
                                host: savedDestination.host,
                                port: savedDestination.port,
                              };
                              update("destination", nextDestination);
                              setDestinationEndpointInput(formatDestinationEndpoint(nextDestination.protocol, nextDestination.host, nextDestination.port));
                              setIsDestinationMenuOpen(false);
                            }}
                            className="w-full rounded-[18px] border border-white/10 bg-black/20 px-4 py-3 text-left transition hover:border-white/20 hover:bg-black/30"
                          >
                            <div className="font-medium text-white">{savedDestination.name}</div>
                            <div className="mt-1 text-sm text-slate-400">
                              {formatDestinationEndpoint(savedDestination.protocol, savedDestination.host, savedDestination.port)}
                            </div>
                          </button>
                        ))}
                      </div>
                    </div>
                  ) : null}
                </div>
              </Field>
              <Field label="Destination URL or IP + Port">
                <Input
                  value={destinationEndpointInput}
                  onChange={(event) => setDestinationEndpointInput(event.target.value)}
                  onBlur={() => {
                    const parsedDestination = parseDestinationEndpoint(destinationEndpointInput, site.destination);
                    if (parsedDestination) {
                      update("destination", parsedDestination);
                    }
                  }}
                />
              </Field>
            </div>
          </section>
          <aside className="rounded-[28px] border border-white/10 bg-white/[0.04] px-7 py-5 sm:px-7 sm:py-6">
            <p className="text-xs uppercase tracking-[0.24em] text-slate-400">Current Profile</p>
            <h3 className="mt-2 text-xl font-semibold text-white">{site.profile.name}</h3>
            <dl className="mt-5 space-y-4 text-sm">
              <SummaryRow label="Sample rate" value={`${site.profile.sample_rate_hz} Hz`} />
              <SummaryRow label="Channels" value={`${site.profile.channels}`} />
              <SummaryRow label="PCR period" value={`${site.profile.pcr_period_ms} ms`} />
              <SummaryRow label="Video" value={site.profile.enable_video ? "Enabled" : "Disabled"} />
            </dl>
          </aside>
        </div>
        <section className="space-y-5 rounded-[28px] border border-white/10 bg-black/20 p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.24em] text-slate-400">Transport Tuning</p>
              <h3 className="mt-2 text-xl font-semibold text-white">Transport settings</h3>
            </div>
            <div className="flex flex-wrap justify-end gap-2">
              <TogglePill
                label="Advanced"
                active={isAdvancedOpen}
                onClick={() => setIsAdvancedOpen((current) => !current)}
              />
              <TogglePill
                label="Video"
                active={isVideoPanelOpen}
                tone={site.profile.enable_video ? "teal" : "amber"}
                onClick={() => setIsVideoPanelOpen((current) => !current)}
              />
            </div>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <Field label="Audio Bitrate">
              <SelectField
                value={site.profile.audio_bitrate_kbps}
                options={withCurrentOption(AUDIO_BITRATE_OPTIONS, site.profile.audio_bitrate_kbps)}
                formatLabel={(value) => `${value} kbps`}
                onChange={(value) => update("profile", { ...site.profile, audio_bitrate_kbps: value })}
              />
            </Field>
            <Field label="Latency">
              <SelectField
                value={site.profile.srt_latency_ms}
                options={withCurrentOption(LATENCY_OPTIONS, site.profile.srt_latency_ms)}
                formatLabel={(value) => `${value} ms`}
                onChange={(value) => update("profile", { ...site.profile, srt_latency_ms: value })}
              />
            </Field>
            <Field label="Mux Rate">
              <SelectField
                value={site.profile.mux_rate_kbps}
                options={withCurrentOption(MUX_RATE_OPTIONS, site.profile.mux_rate_kbps)}
                formatLabel={(value) => `${value} kbps`}
                onChange={(value) => update("profile", { ...site.profile, mux_rate_kbps: value })}
              />
            </Field>
          </div>
          {isAdvancedOpen ? (
            <div className="grid gap-4 rounded-[24px] border border-white/10 bg-white/[0.04] p-4 md:grid-cols-2 xl:grid-cols-4">
              <Field label="Audio Output Format">
                <select
                  value="mp2"
                  disabled
                  className="w-full cursor-not-allowed rounded-[18px] border border-white/10 bg-black/20 px-4 py-3 text-sm text-slate-300 opacity-80 outline-none"
                >
                  <option value="mp2" className="bg-slate-950 text-white">
                    MP2 Broadcast
                  </option>
                </select>
              </Field>
              <Field label="Sample Rate">
                <SelectField
                  value={site.profile.sample_rate_hz}
                  options={withCurrentOption(SAMPLE_RATE_OPTIONS, site.profile.sample_rate_hz)}
                  formatLabel={(value) => `${value} Hz`}
                  onChange={(value) => update("profile", { ...site.profile, sample_rate_hz: value })}
                />
              </Field>
              <Field label="Channels">
                <select
                  value={String(site.profile.channels)}
                  onChange={(event) => update("profile", { ...site.profile, channels: Number(event.target.value) })}
                  className="w-full rounded-[18px] border border-white/10 bg-black/20 px-4 py-3 text-sm text-white outline-none transition focus:border-[var(--accent)]"
                >
                  <option value="1" className="bg-slate-950 text-white">
                    Mono
                  </option>
                  <option value="2" className="bg-slate-950 text-white">
                    Stereo
                  </option>
                </select>
              </Field>
              <Field label="PCR Period">
                <SelectField
                  value={site.profile.pcr_period_ms}
                  options={withCurrentOption(PCR_PERIOD_OPTIONS, site.profile.pcr_period_ms)}
                  formatLabel={(value) => `${value} ms`}
                  onChange={(value) => update("profile", { ...site.profile, pcr_period_ms: value })}
                />
              </Field>
            </div>
          ) : null}
          {isVideoPanelOpen ? (
            <div
              className={
                site.profile.enable_video
                  ? "grid gap-4 rounded-[24px] border border-emerald-200/12 bg-emerald-200/[0.04] p-4 md:grid-cols-[auto_1fr_1fr]"
                  : "grid gap-4 rounded-[24px] border border-amber-200/12 bg-amber-200/[0.04] p-4 md:grid-cols-[auto_1fr_1fr]"
              }
            >
              <Field label="Enable">
                <button
                  type="button"
                  aria-pressed={site.profile.enable_video}
                  onClick={() =>
                    update("profile", {
                      ...site.profile,
                      enable_video: !site.profile.enable_video,
                      video_source: !site.profile.enable_video && site.profile.video_source === "none" ? "black_test_frames" : site.profile.video_source,
                    })
                  }
                  className={
                    site.profile.enable_video
                      ? "relative flex h-12 w-20 items-center rounded-full border border-emerald-200/25 bg-emerald-200/15 px-1.5 shadow-[0_8px_24px_rgba(116,232,201,0.14)] transition"
                      : "relative flex h-12 w-20 items-center rounded-full border border-white/10 bg-black/20 px-1.5 transition"
                  }
                >
                  <span
                    className={
                      site.profile.enable_video
                        ? "absolute right-1.5 h-8 w-8 rounded-full bg-[linear-gradient(135deg,#9aeccd,#66c6bd)] shadow-[0_8px_18px_rgba(102,198,189,0.28)]"
                        : "absolute left-1.5 h-8 w-8 rounded-full bg-white/85 shadow-[0_8px_18px_rgba(15,23,42,0.22)]"
                    }
                  />
                  <span className="sr-only">{site.profile.enable_video ? "Disable video" : "Enable video"}</span>
                </button>
              </Field>
              <Field label="Video Mode">
                <div className="flex min-h-[3rem] items-center rounded-[18px] border border-white/10 bg-black/20 px-4 text-sm text-slate-200">
                  {site.profile.enable_video ? "Video multiplexed into MPEG-TS output" : "Video settings visible, but currently disabled"}
                </div>
              </Field>
              <Field label="Video Codec">
                <select
                  value={site.profile.video_codec}
                  onChange={(event) =>
                    update("profile", {
                      ...site.profile,
                      video_codec: event.target.value as ConfigBundle["site"]["profile"]["video_codec"],
                    })
                  }
                  className="w-full rounded-[18px] border border-white/10 bg-black/20 px-4 py-3 text-sm text-white outline-none transition focus:border-[var(--accent)]"
                >
                  {VIDEO_CODEC_OPTIONS.map((option) => (
                    <option key={option} value={option} className="bg-slate-950 text-white">
                      {formatVideoCodec(option)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Video Bitrate">
                <SelectField
                  value={site.profile.video_bitrate_kbps}
                  options={withCurrentOption(VIDEO_BITRATE_OPTIONS, site.profile.video_bitrate_kbps)}
                  formatLabel={(value) => `${value} kbps`}
                  onChange={(value) => update("profile", { ...site.profile, video_bitrate_kbps: value })}
                />
              </Field>
              <Field label="Resolution">
                <select
                  value={site.profile.video_resolution}
                  onChange={(event) => update("profile", { ...site.profile, video_resolution: event.target.value })}
                  className="w-full rounded-[18px] border border-white/10 bg-black/20 px-4 py-3 text-sm text-white outline-none transition focus:border-[var(--accent)]"
                >
                  {withCurrentStringOption(VIDEO_RESOLUTION_OPTIONS, site.profile.video_resolution).map((option) => (
                    <option key={option} value={option} className="bg-slate-950 text-white">
                      {option}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Frame Rate">
                <SelectField
                  value={site.profile.video_frame_rate}
                  options={withCurrentOption(VIDEO_FRAME_RATE_OPTIONS, site.profile.video_frame_rate)}
                  formatLabel={(value) => `${value} fps`}
                  onChange={(value) => update("profile", { ...site.profile, video_frame_rate: value })}
                />
              </Field>
              <Field label="Source Mapping">
                <select
                  value={site.profile.video_source}
                  onChange={(event) =>
                    update("profile", {
                      ...site.profile,
                      video_source: event.target.value as ConfigBundle["site"]["profile"]["video_source"],
                    })
                  }
                  className="w-full rounded-[18px] border border-white/10 bg-black/20 px-4 py-3 text-sm text-white outline-none transition focus:border-[var(--accent)]"
                >
                  {VIDEO_SOURCE_OPTIONS.map((option) => (
                    <option key={option} value={option} className="bg-slate-950 text-white">
                      {formatVideoSource(option)}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
          ) : null}
        </section>
      </Card>
      {isSaveDialogOpen ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-[rgba(5,12,18,0.5)] px-4 backdrop-blur-[10px]">
          <div ref={saveDialogRef} className="w-full max-w-xl">
            <Card className="space-y-6 border border-white/10 bg-[rgba(8,14,22,0.94)]">
              <div>
                <p className="section-label">Save Site Config</p>
                <h3 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">Save configuration</h3>
                <p className="soft-text mt-3 text-sm leading-6">
                  Save a named snapshot of the current routing. Load it again at any time from this tab.
                </p>
              </div>
              <Field label="Saved Config Name">
                <Input value={saveName} onChange={(event) => setSaveName(event.target.value)} autoFocus />
              </Field>
              {showOverwriteWarning ? (
                <div className="rounded-[22px] border border-amber-300/20 bg-amber-300/10 px-4 py-3 text-sm text-amber-100">
                  A saved config with this name already exists. Saving now will overwrite that existing config and make it the active route.
                </div>
              ) : null}
              <div className="flex flex-wrap justify-end gap-3">
                <Button
                  className="bg-[linear-gradient(135deg,#d8eef9,#8ebcd8)]"
                  onClick={() => {
                    setIsSaveDialogOpen(false);
                    setShowOverwriteWarning(false);
                  }}
                  type="button"
                >
                  Cancel
                </Button>
                <Button onClick={() => void handleSave()} disabled={isSaving || !saveName.trim()}>
                  {isSaving ? "Saving..." : showOverwriteWarning ? "Overwrite Config" : "Save Config"}
                </Button>
              </div>
            </Card>
          </div>
        </div>
      ) : null}
      {isCreateInputOpen ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-[rgba(5,12,18,0.5)] px-4 backdrop-blur-[10px]">
          <div ref={createInputDialogRef} className="w-full max-w-xl">
            <Card className="space-y-6 border border-white/10 bg-[rgba(8,14,22,0.94)]">
              <div>
                <p className="section-label">Create Input</p>
                <h3 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">New saved input</h3>
              </div>
              <Field label="Input Nickname">
                <Input value={draftInput.name} onChange={(event) => setDraftInput((current) => ({ ...current, name: event.target.value }))} autoFocus />
              </Field>
              <Field label="Input URL">
                <Input value={draftInput.url} onChange={(event) => setDraftInput((current) => ({ ...current, url: event.target.value }))} />
              </Field>
              <div className="flex flex-wrap justify-end gap-3">
                <Button className="bg-[linear-gradient(135deg,#d8eef9,#8ebcd8)]" onClick={() => setIsCreateInputOpen(false)} type="button">
                  Cancel
                </Button>
                <Button onClick={() => void handleCreateInput()} disabled={!draftInput.name.trim() || !draftInput.url.trim() || isMutatingSavedConfigs}>
                  Save Input
                </Button>
              </div>
            </Card>
          </div>
        </div>
      ) : null}
      {isCreateDestinationOpen ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-[rgba(5,12,18,0.5)] px-4 backdrop-blur-[10px]">
          <div ref={createDestinationDialogRef} className="w-full max-w-xl">
            <Card className="space-y-6 border border-white/10 bg-[rgba(8,14,22,0.94)]">
              <div>
                <p className="section-label">Create Destination</p>
                <h3 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">New saved destination</h3>
              </div>
              <Field label="Destination Nickname">
                <Input
                  value={draftDestination.name}
                  onChange={(event) => setDraftDestination((current) => ({ ...current, name: event.target.value }))}
                  autoFocus
                />
              </Field>
              <Field label="Destination URL or IP + Port">
                <Input
                  value={draftDestinationEndpointInput}
                  onChange={(event) => setDraftDestinationEndpointInput(event.target.value)}
                  onBlur={() => {
                    const parsedDestination = parseDestinationEndpoint(draftDestinationEndpointInput, draftDestination);
                    if (parsedDestination) {
                      setDraftDestination((current) => ({ ...current, ...parsedDestination }));
                    }
                  }}
                />
              </Field>
              <div className="flex flex-wrap justify-end gap-3">
                <Button className="bg-[linear-gradient(135deg,#d8eef9,#8ebcd8)]" onClick={() => setIsCreateDestinationOpen(false)} type="button">
                  Cancel
                </Button>
                <Button
                  onClick={() => void handleCreateDestination()}
                  disabled={!draftDestination.name.trim() || !draftDestination.host.trim() || isMutatingSavedConfigs}
                >
                  Save Destination
                </Button>
              </div>
            </Card>
          </div>
        </div>
      ) : null}
      {renameTarget ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-[rgba(5,12,18,0.5)] px-4 backdrop-blur-[10px]">
          <div ref={renameDialogRef} className="w-full max-w-xl">
            <Card className="space-y-6 border border-white/10 bg-[rgba(8,14,22,0.94)]">
              <div>
                <p className="section-label">Rename Saved Config</p>
                <h3 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">Rename configuration</h3>
              </div>
              <Field label="Saved Config Name">
                <Input value={renameValue} onChange={(event) => setRenameValue(event.target.value)} autoFocus />
              </Field>
              <div className="flex flex-wrap justify-end gap-3">
                <Button className="bg-[linear-gradient(135deg,#d8eef9,#8ebcd8)]" onClick={() => setRenameTarget(null)} type="button">
                  Cancel
                </Button>
                <Button onClick={() => void handleRenameSaved()} disabled={!renameValue.trim() || isMutatingSavedConfigs}>
                  Save Name
                </Button>
              </div>
            </Card>
          </div>
        </div>
      ) : null}
      {deleteTarget ? (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-[rgba(5,12,18,0.5)] px-4 backdrop-blur-[10px]">
          <div ref={deleteDialogRef} className="w-full max-w-xl">
            <Card className="space-y-6 border border-white/10 bg-[rgba(8,14,22,0.94)]">
              <div>
                <p className="section-label">Delete Saved Config</p>
                <h3 className="mt-3 text-3xl font-semibold tracking-[-0.04em] text-white">Delete "{deleteTarget.name}"?</h3>
                <p className="soft-text mt-3 text-sm leading-6">
                  This permanently removes the saved configuration. Your current active settings are not affected.
                </p>
              </div>
              <div className="flex flex-wrap justify-end gap-3">
                <Button className="bg-[linear-gradient(135deg,#d8eef9,#8ebcd8)]" onClick={() => setDeleteTarget(null)} type="button">
                  Cancel
                </Button>
                <Button
                  className="border-rose-300/20 bg-[linear-gradient(135deg,#f6c17a,#f38d7a)] text-slate-950 shadow-[0_10px_35px_rgba(243,141,122,0.18)] hover:shadow-[0_12px_40px_rgba(243,141,122,0.26)]"
                  onClick={() => void handleDeleteSaved()}
                  disabled={isMutatingSavedConfigs}
                >
                  Delete Config
                </Button>
              </div>
            </Card>
          </div>
        </div>
      ) : null}
    </>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col text-sm text-slate-300">
      <span className="ml-2 pb-2.5 text-xs uppercase tracking-[0.22em] text-slate-400">{label}</span>
      {children}
    </label>
  );
}

function TogglePill({
  label,
  active,
  onClick,
  tone = "teal",
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  tone?: "teal" | "amber";
}) {
  const activeClass =
    tone === "amber"
      ? "rounded-full border border-amber-200/20 bg-[linear-gradient(135deg,rgba(246,193,122,0.95),rgba(243,141,122,0.86))] px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-950 shadow-[0_10px_35px_rgba(243,141,122,0.2)]"
      : "rounded-full border border-emerald-200/20 bg-[linear-gradient(135deg,rgba(152,236,220,0.9),rgba(102,198,189,0.82))] px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-950 shadow-[0_10px_35px_rgba(102,198,189,0.18)]";
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        active
          ? activeClass
          : "rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-200 transition hover:border-white/20 hover:bg-white/[0.08]"
      }
    >
      {label}
    </button>
  );
}

function SummaryRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-6 border-b border-white/5 pb-3 last:border-b-0 last:pb-0">
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
  return (
    <select
      value={String(value)}
      onChange={(event) => onChange(Number(event.target.value))}
      className="w-full rounded-[18px] border border-white/10 bg-black/20 px-4 py-3 text-sm text-white outline-none transition focus:border-[var(--accent)]"
    >
      {options.map((option) => (
        <option key={option} value={option} className="bg-slate-950 text-white">
          {formatLabel(option)}
        </option>
      ))}
    </select>
  );
}

function withCurrentOption(options: number[], current: number) {
  return [...new Set([...options, current])].sort((left, right) => left - right);
}

function withCurrentStringOption(options: string[], current: string) {
  return [...new Set([...options, current])];
}

function hasAdvancedOverrides(profile: ConfigBundle["site"]["profile"]) {
  return profile.sample_rate_hz !== 48000 || profile.channels !== 2 || profile.pcr_period_ms !== 20;
}

function formatVideoCodec(codec: ConfigBundle["site"]["profile"]["video_codec"]) {
  if (codec === "libx264") {
    return "H.264";
  }
  return "MPEG-2 Video";
}

function formatVideoSource(source: ConfigBundle["site"]["profile"]["video_source"]) {
  if (source === "black_test_frames") {
    return "Black Test Frames";
  }
  return "No Video Source";
}

function defaultSaveName(site: ConfigBundle["site"]) {
  return site.input.name?.trim() || site.destination.name?.trim() || "New Site Config";
}

function formatTimestamp(value: string) {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "recently";
  }
  return parsed.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatDestinationEndpoint(protocol: ConfigBundle["site"]["destination"]["protocol"], host: string, port: number) {
  if (!host) {
    return "";
  }
  const endpoint = host.includes(":") && !host.startsWith("[") ? `[${host}]` : host;
  return `${protocol}://${endpoint}:${port}`;
}

function parseDestinationEndpoint(
  value: string,
  current: ConfigBundle["site"]["destination"],
): ConfigBundle["site"]["destination"] | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const schemeMatch = trimmed.match(/^(srt|udp):\/\/(.+)$/i);
  const protocol = (schemeMatch?.[1]?.toLowerCase() as ConfigBundle["site"]["destination"]["protocol"] | undefined) ?? current.protocol;
  const endpoint = schemeMatch?.[2] ?? trimmed;

  const ipv6Match = endpoint.match(/^\[([^\]]+)\]:(\d+)$/);
  if (ipv6Match) {
    return { ...current, protocol, host: ipv6Match[1], port: Number(ipv6Match[2]) };
  }

  const colonCount = (endpoint.match(/:/g) ?? []).length;
  if (colonCount === 1) {
    const [host, port] = endpoint.split(":");
    if (host && /^\d+$/.test(port ?? "")) {
      return { ...current, protocol, host, port: Number(port) };
    }
  }

  return null;
}
