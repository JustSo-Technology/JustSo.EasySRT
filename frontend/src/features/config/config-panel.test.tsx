// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ConfigPanel } from "./config-panel";
import type { ConfigBundle, SavedSiteConfigDetail } from "@/lib/api";

const config: ConfigBundle = {
  app: { station_name: "Studio", support_contact: "support@example.test" },
  site: {
    input: { name: "Today source", url: "https://example.test/today" },
    destination: { name: "Receiver", protocol: "srt", host: "today.example", port: 1234 },
    profile: { name: "Broadcast", audio_bitrate_kbps: 256, sample_rate_hz: 48000, channels: 2,
      srt_latency_ms: 120, mux_rate_kbps: 600, pcr_period_ms: 20, enable_video: false,
      video_codec: "mpeg2video", video_bitrate_kbps: 1000, video_resolution: "1280x720",
      video_frame_rate: 25, video_source: "none" },
  },
  runtime: { ffmpeg_command: "ffmpeg preview", service_name: "sender", generated_from_station: "Studio" },
  selected: { id: "today-selected", source_preset_id: "today", source_revision: 1, source_name: "Today", target: "default", created_at: "2026-10-24T00:00:00Z" },
  capabilities: ["presets:read", "presets:create", "presets:update", "presets:delete", "presets:apply"],
};
const tomorrow: SavedSiteConfigDetail = {
  saved_config: { id: "tomorrow", name: "Tomorrow", revision: 3, created_at: "2026-10-24T00:00:00Z", updated_at: "2026-10-24T00:00:00Z" },
  bundle: { ...config, site: { ...config.site, input: { name: "Tomorrow source", url: "https://example.test/tomorrow" } } },
  expected_selection_id: "today-selected", app_digest: "app", runtime_digest: "runtime", runtime_version: 1,
};
function props() {
  return { config, savedConfigs: [tomorrow.saved_config],
    onSave: vi.fn().mockResolvedValue(tomorrow), onLoadSaved: vi.fn().mockResolvedValue(tomorrow),
    onApply: vi.fn().mockResolvedValue({ ...config, selected: { ...config.selected, id: "tomorrow-selected" } }),
    onRenameSaved: vi.fn(), onDeleteSaved: vi.fn(), onCreateSavedInput: vi.fn(), onCreateSavedDestination: vi.fn() };
}
async function open() {
  fireEvent.click(screen.getByRole("button", { name: "Open preset" }));
  fireEvent.click(screen.getByRole("button", { name: "Open" }));
  await screen.findByText(/Opened preset/);
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

it("opens a saved revision into the editor without Apply", async () => {
  const callbacks = props();
  render(<ConfigPanel {...callbacks} />);
  await open();
  expect((screen.getByLabelText("Input URL") as HTMLInputElement).value).toBe(tomorrow.bundle.site.input.url);
  expect(callbacks.onApply).not.toHaveBeenCalled();
  expect(screen.getByText(/Selected: Today/)).toBeTruthy();
  expect((screen.getByRole("button", { name: "Apply preset" }) as HTMLButtonElement).disabled).toBe(false);
});

it("preserves dirty drafts when selected configuration refreshes", async () => {
  const callbacks = props();
  const view = render(<ConfigPanel {...callbacks} />);
  await open();
  fireEvent.change(screen.getByLabelText("Input URL"), { target: { value: "https://draft.example/unsaved" } });
  view.rerender(<ConfigPanel {...callbacks} config={{ ...config, site: structuredClone(config.site) }} />);
  expect((screen.getByLabelText("Input URL") as HTMLInputElement).value).toBe("https://draft.example/unsaved");
  expect((screen.getByRole("button", { name: "Apply preset" }) as HTMLButtonElement).disabled).toBe(true);
  vi.spyOn(window, "confirm").mockReturnValue(false);
  fireEvent.click(screen.getByRole("button", { name: "Open preset" }));
  fireEvent.click(screen.getByRole("button", { name: "Open" }));
  expect(callbacks.onLoadSaved).toHaveBeenCalledTimes(1);
});

it("saves with the opened revision and does not Apply", async () => {
  const callbacks = props();
  render(<ConfigPanel {...callbacks} />);
  await open();
  fireEvent.click(screen.getByRole("button", { name: "Save preset" }));
  fireEvent.click(screen.getAllByRole("button", { name: "Save preset" })[1]);
  await waitFor(() => expect(callbacks.onSave).toHaveBeenCalledWith("Tomorrow", tomorrow.bundle.site, tomorrow.saved_config));
  expect(callbacks.onApply).not.toHaveBeenCalled();
  await screen.findByText(/Apply it to select it for the next Start\/Restart/);
});

it("requires a separate Apply review and sends exactly that saved revision", async () => {
  const callbacks = props();
  render(<ConfigPanel {...callbacks} />);
  await open();
  fireEvent.click(screen.getByRole("button", { name: "Apply preset" }));
  expect(callbacks.onApply).not.toHaveBeenCalled();
  expect(screen.getByRole("dialog", { name: "Review Apply" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Confirm Apply" }));
  await waitFor(() => expect(callbacks.onApply).toHaveBeenCalledWith(tomorrow, expect.any(String)));
  await screen.findByText(/running sender was not restarted/);
});

it("retains the draft after a stale Save and does not silently retry", async () => {
  const callbacks = props();
  callbacks.onSave.mockRejectedValue(new Error("Preset changed; open and review it again before saving or applying"));
  render(<ConfigPanel {...callbacks} />);
  await open();
  fireEvent.change(screen.getByLabelText("Input URL"), { target: { value: "https://draft.example/unsaved" } });
  fireEvent.click(screen.getByRole("button", { name: "Save preset" }));
  fireEvent.click(screen.getAllByRole("button", { name: "Save preset" })[1]);
  await screen.findByText(/Preset changed/);
  expect(callbacks.onSave).toHaveBeenCalledTimes(1);
  expect((screen.getByLabelText("Input URL") as HTMLInputElement).value).toBe("https://draft.example/unsaved");
});

it("lets read-only operators Open while preventing library mutation and Apply", async () => {
  render(<ConfigPanel {...props()} config={{ ...config, capabilities: ["presets:read"] }} />);
  await open();
  expect((screen.getByRole("button", { name: "Save preset" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "Apply preset" }) as HTMLButtonElement).disabled).toBe(true);
});
