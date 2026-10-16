import { useState, type ChangeEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { api, type ImportDecision, type ImportPreview } from "@/lib/api";

const MAX_FILE_BYTES = 1_048_576;

export function ConfigTransfer({ onImported }: { onImported: () => Promise<void> }) {
  const [document, setDocument] = useState<Record<string, unknown> | null>(null);
  const [decisions, setDecisions] = useState<ImportDecision[]>([]);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function chooseFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    setPreview(null);
    setDocument(null);
    setDecisions([]);
    setReviewed(false);
    setMessage("");
    if (!file) return;
    setBusy(true);
    try {
      if (file.size > MAX_FILE_BYTES) throw new Error("Choose a JSON configuration file smaller than 1 MiB.");
      let parsed: unknown;
      try { parsed = JSON.parse(await file.text()); }
      catch { throw new Error("Choose a valid JSON configuration file."); }
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Choose a configuration document.");
      const doc = parsed as Record<string, unknown>;
      const result = await api.previewImport(doc, []);
      setDocument(doc);
      setPreview(result);
      // A first look is not confirmation of latency or conflict decisions.
      // Omit names until edited: preview names may have redacted URL credentials.
      setDecisions(result.items.map((item) => ({ key: item.key, action: item.action })));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not read the configuration.");
    } finally { setBusy(false); }
  }

  function changeDecision(key: string, patch: Partial<ImportDecision>) {
    setReviewed(false);
    setMessage("");
    setDecisions((current) => current.map((d) => d.key === key ? { ...d, ...patch } : d));
  }

  async function review() {
    if (!document) return;
    setBusy(true);
    setMessage("");
    setReviewed(false);
    try {
      setPreview(await api.previewImport(document, decisions));
      setReviewed(true);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not preview the import.");
    } finally { setBusy(false); }
  }

  async function importPresets() {
    if (!document || !preview || !reviewed) return;
    setBusy(true);
    setMessage("");
    try {
      const result = await api.importConfigurations(document, decisions, preview.preview_token);
      setDocument(null);
      setPreview(null);
      setDecisions([]);
      setReviewed(false);
      const success = `Imported ${result.imported.length} entries. The active configuration and stream were unchanged.`;
      setMessage(success);
      try { await onImported(); }
      catch { setMessage(`${success} Reload to refresh the saved entries list.`); }
    } catch (error) {
      setReviewed(false);
      setMessage(error instanceof Error ? error.message : "Could not import. Preview again before retrying.");
    } finally { setBusy(false); }
  }

  async function exportPresets() {
    setBusy(true);
    setMessage("");
    try {
      const result = await api.exportConfigurations();
      const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
      const a = window.document.createElement("a");
      a.href = url;
      a.download = "easysrt-configurations.json";
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not export configurations.");
    } finally { setBusy(false); }
  }

  return <Card className="space-y-4">
    <h2 className="text-xl font-semibold text-white">Import and export configurations</h2>
    <p className="text-sm text-slate-300">Move saved presets, inputs and destinations between installations. Importing adds saved entries; choose and load a preset separately to change the active configuration.</p>
    <p className="text-sm text-amber-200">Exported files can contain credentials in input URLs. Store them privately.</p>
    <div className="flex flex-wrap items-center gap-4">
      <Button onClick={() => void exportPresets()} disabled={busy}>Export configurations</Button>
      <label className="text-sm text-slate-200">Choose configuration file
        <input type="file" accept=".json,application/json" aria-label="Choose configuration file" disabled={busy} onChange={(e) => void chooseFile(e)} className="ml-3 max-w-full" />
      </label>
    </div>
    {preview && <div className="space-y-4">
      {preview.warnings.map((warning) => <p key={warning} className="text-sm text-amber-200">{warning}</p>)}
      {preview.items.map((item) => {
        const decision = decisions.find((d) => d.key === item.key);
        return <fieldset key={item.key} disabled={busy} className="space-y-3 rounded-2xl border border-white/15 p-4">
          <legend className="px-2 text-sm text-slate-200">{item.kind} · {item.name}</legend>
          {item.conflict && <p className="text-sm text-amber-200">A saved entry with this name exists. Skip, choose a different name, or explicitly replace it.</p>}
          <div className="flex flex-wrap gap-3">
            <label className="text-sm text-slate-300">Action
              <select aria-label={`Action for ${item.key}`} value={decision?.action ?? item.action} onChange={(e) => changeDecision(item.key, { action: e.target.value as ImportDecision["action"] })} className="ml-2 rounded-lg bg-slate-900 p-2 text-white">
                <option value="add">Add</option><option value="skip">Skip</option><option value="replace">Replace existing</option>
              </select>
            </label>
            <label className="text-sm text-slate-300">Import name
              <Input aria-label={`Import name for ${item.key}`} maxLength={120} value={decision?.name ?? item.name} onChange={(e) => changeDecision(item.key, { name: e.target.value })} />
            </label>
            {item.requires_latency_review && <label className="text-sm text-amber-200">Reviewed SRT latency (ms), previously labelled {item.source_latency_ms} ms
              <Input aria-label={`Reviewed latency for ${item.key}`} type="number" min={1} step={1} value={decision?.latency_ms ?? ""} placeholder="Enter reviewed milliseconds" onChange={(e) => changeDecision(item.key, { latency_ms: e.target.value ? Number(e.target.value) : undefined })} />
            </label>}
          </div>
          <details className="text-sm text-slate-300"><summary>Review settings (URL credentials hidden)</summary><pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-all">{JSON.stringify(item.settings, null, 2)}</pre></details>
        </fieldset>;
      })}
      {!!preview.errors.length && <ul className="space-y-1 text-sm text-amber-200">{preview.errors.map((error) => <li key={error}>{error}</li>)}</ul>}
      <div className="flex flex-wrap gap-3">
        <Button disabled={busy} onClick={() => void review()}>Review import</Button>
        <Button disabled={busy || !reviewed || !preview.can_import} onClick={() => void importPresets()}>Import saved entries</Button>
        <Button disabled={busy} onClick={() => { setPreview(null); setDocument(null); setDecisions([]); setReviewed(false); setMessage(""); }}>Cancel import</Button>
      </div>
    </div>}
    {message && <p role="status" className="text-sm text-slate-200">{message}</p>}
  </Card>;
}
