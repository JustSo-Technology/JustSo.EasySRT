// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ConfigTransfer } from "./config-transfer";
import { api, type ImportPreview } from "@/lib/api";

vi.mock("@/lib/api", () => ({ api: { previewImport: vi.fn(), importConfigurations: vi.fn(), exportConfigurations: vi.fn() } }));

const preview: ImportPreview = {
  items: [{ key: "preset:0", kind: "preset", name: "Old preset", action: "add", conflict: false,
    requires_latency_review: true, latency_ms: 80, source_latency_ms: 80, settings: { input: { url: "https://[credentials]@example.test/live?[query redacted]" } } }],
  warnings: ["Review latency units before importing."], errors: ["Review latency in milliseconds"], can_import: false, preview_token: "first-token",
};

async function selectFile(contents = '{"format":"test-document"}') {
  const file = new File([contents], "config.json", { type: "application/json" });
  Object.defineProperty(file, "text", { value: async () => contents });
  fireEvent.change(screen.getByLabelText("Choose configuration file"), { target: { files: [file] } });
  await waitFor(() => expect(api.previewImport).toHaveBeenCalledTimes(1));
  await screen.findByText("Review latency units before importing.");
}

beforeEach(() => {
  vi.mocked(api.previewImport).mockResolvedValue(structuredClone(preview));
  vi.mocked(api.importConfigurations).mockResolvedValue({ imported: [{ key: "preset:0", id: "new-id", name: "Old preset", kind: "preset" }], active_configuration_changed: false });
});
afterEach(() => { cleanup(); vi.resetAllMocks(); });

describe("configuration transfer", () => {
  it("requires an explicit review and latency decision, then imports the reviewed selection", async () => {
    const onImported = vi.fn().mockResolvedValue(undefined);
    render(<ConfigTransfer onImported={onImported} />);
    await selectFile();
    const importButton = screen.getByRole("button", { name: "Import saved entries" }) as HTMLButtonElement;
    expect(importButton.disabled).toBe(true);
    expect((screen.getByLabelText("Reviewed latency for preset:0") as HTMLInputElement).value).toBe("");
    fireEvent.change(screen.getByLabelText("Reviewed latency for preset:0"), { target: { value: "120" } });
    vi.mocked(api.previewImport).mockResolvedValue({ ...preview, items: [{ ...preview.items[0], latency_ms: 120 }], errors: [], can_import: true, preview_token: "reviewed-token" });
    fireEvent.click(screen.getByRole("button", { name: "Review import" }));
    await waitFor(() => expect(importButton.disabled).toBe(false));
    expect(screen.getByText(/previously labelled 80 ms/)).toBeTruthy();
    fireEvent.click(importButton);
    await screen.findByText("Imported 1 entries. The active configuration and stream were unchanged.");
    expect(api.importConfigurations).toHaveBeenCalledWith({ format: "test-document" }, [
      { key: "preset:0", action: "add", latency_ms: 120 },
    ], "reviewed-token");
    expect(onImported).toHaveBeenCalledOnce();
  });

  it("keeps a successful import visible when refreshing the saved list fails", async () => {
    render(<ConfigTransfer onImported={vi.fn().mockRejectedValue(new Error('network failed'))} />);
    await selectFile();
    vi.mocked(api.previewImport).mockResolvedValue({ ...preview, errors: [], can_import: true });
    fireEvent.click(screen.getByRole('button', { name: 'Review import' }));
    const button = screen.getByRole('button', { name: 'Import saved entries' }) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.click(button);
    await screen.findByText(/Imported 1 entries.*Reload to refresh/);
    expect(api.importConfigurations).toHaveBeenCalledOnce();
    expect(screen.queryByRole('button', { name: 'Import saved entries' })).toBeNull();
  });

  it("invalidates review after edits, and cancel never imports", async () => {
    render(<ConfigTransfer onImported={vi.fn()} />);
    await selectFile();
    vi.mocked(api.previewImport).mockResolvedValue({ ...preview, errors: [], can_import: true });
    fireEvent.click(screen.getByRole("button", { name: "Review import" }));
    const button = screen.getByRole("button", { name: "Import saved entries" }) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    fireEvent.change(screen.getByLabelText("Import name for preset:0"), { target: { value: "New name" } });
    expect(button.disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Cancel import" }));
    expect(screen.queryByRole("button", { name: "Import saved entries" })).toBeNull();
    expect(api.importConfigurations).not.toHaveBeenCalled();
  });

  it("requires a new review after a stale preview is rejected", async () => {
    render(<ConfigTransfer onImported={vi.fn()} />);
    await selectFile();
    vi.mocked(api.previewImport).mockResolvedValue({ ...preview, errors: [], can_import: true });
    fireEvent.click(screen.getByRole("button", { name: "Review import" }));
    const button = screen.getByRole("button", { name: "Import saved entries" }) as HTMLButtonElement;
    await waitFor(() => expect(button.disabled).toBe(false));
    vi.mocked(api.importConfigurations).mockRejectedValue(new Error("Saved configuration changed; preview again"));
    fireEvent.click(button);
    await screen.findByText("Saved configuration changed; preview again");
    expect(button.disabled).toBe(true);
  });

  it("rejects invalid files without displaying their sensitive content", async () => {
    render(<ConfigTransfer onImported={vi.fn()} />);
    const file = new File(["secret-invalid-json"], "invalid.json");
    Object.defineProperty(file, "text", { value: async () => "secret-invalid-json" });
    fireEvent.change(screen.getByLabelText("Choose configuration file"), { target: { files: [file] } });
    await screen.findByText("Choose a valid JSON configuration file.");
    expect(screen.queryByText(/secret-invalid/)).toBeNull();
    expect(api.previewImport).not.toHaveBeenCalled();
  });
});
