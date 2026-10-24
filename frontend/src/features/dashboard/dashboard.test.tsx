// @vitest-environment jsdom
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { Dashboard } from "./dashboard";
import type { ConfigBundle, SenderHealth, ServiceStatus } from "@/lib/api";

const config: ConfigBundle = {
  app: { station_name: "Test", support_contact: "test@example.test" },
  site: {
    input: { name: "Saved source", url: "http://example.test/source" },
    destination: { name: "Saved receiver", protocol: "srt", host: "example.test", port: 1234 },
    profile: { name: "Saved profile", audio_bitrate_kbps: 256, sample_rate_hz: 48000, channels: 2,
      srt_latency_ms: 120, mux_rate_kbps: 600, pcr_period_ms: 20, enable_video: false,
      video_codec: "mpeg2video", video_bitrate_kbps: 1000, video_resolution: "1280x720",
      video_frame_rate: 25, video_source: "none" },
  },
  runtime: { ffmpeg_command: "ffmpeg preview", service_name: "sender", generated_from_station: "Test" },
};
const status: ServiceStatus = {
  service_name: "sender", running: true, status: "active", detail: "active", allowed_actions: ["stop", "restart"],
  preflight_ok: true, preflight_failures: [], last_command: null, last_exit_code: null, stderr_tail: null,
};
const media: SenderHealth = {
  state: "healthy", reason: "media_progress", detail: "Source audio and local media are progressing.",
  summary: { input: "Applied source", endpoint: "srt://applied.test:9000", profile: "Applied profile" },
  input: { value: 48000, age_seconds: .1, last_progress_at: null },
  output: { value: 10000, age_seconds: .1, last_progress_at: null }, attempt: 1, retry_count: 0,
  next_retry_at: null, last_failure_at: null, last_recovery_at: null, heartbeat_at: null,
  pending_config: false, remote_receipt: "unverified", policy: {}, events: [],
};
afterEach(() => { cleanup(); vi.useRealTimers(); });

it("never declares an active process healthy without media evidence", () => {
  render(<Dashboard config={config} status={status} onAction={vi.fn()} isActionPending={false} />);
  expect(screen.getAllByText("Unknown")[0]).toBeTruthy();
  expect(screen.queryByText("Streaming now")).toBeNull();
  expect(screen.queryByText(/Healthy ·/)).toBeNull();
  expect(screen.getByText(/running configuration is unknown/)).toBeTruthy();
});

it("shows the applied route and keeps Stop usable throughout retries", () => {
  const action = vi.fn().mockResolvedValue(undefined);
  render(<Dashboard config={config} status={{ ...status, pending_configuration: true, media: { ...media, state: "retrying", pending_config: true,
    retry_count: 3, next_retry_at: new Date(Date.now() + 5000).toISOString() } }} onAction={action} isActionPending={false} />);
  expect(screen.getByText("Applied source")).toBeTruthy();
  expect(screen.getByText("srt://applied.test:9000")).toBeTruthy();
  expect(screen.getByText(/Selected configuration is awaiting Start\/Restart/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  expect(action).toHaveBeenCalledWith("stop");
});

it("withdraws healthy status when polling fails or evidence ages out", () => {
  vi.useFakeTimers();
  const props = { config, status: { ...status, media }, onAction: vi.fn(), isActionPending: false, statusUpdatedAt: Date.now() };
  const view = render(<Dashboard {...props} />);
  expect(screen.getByText("Healthy · local media progressing")).toBeTruthy();
  view.rerender(<Dashboard {...props} statusUnavailable />);
  expect(screen.queryByText("Healthy · local media progressing")).toBeNull();
  view.rerender(<Dashboard {...props} />);
  act(() => vi.advanceTimersByTime(8000));
  expect(screen.getAllByText("Unknown")[0]).toBeTruthy();
});

it("shows different selected/running revisions and reviews Restart explicitly", async () => {
  const action = vi.fn().mockResolvedValue(undefined);
  const selected = { id: "b", source_preset_id: "preset", source_revision: 2, source_name: "Tomorrow", target: "default", created_at: "2026-10-24T00:00:00Z" };
  const running = { ...config, selected: { ...selected, id: "a", source_revision: 1, source_name: "Today" } };
  render(<Dashboard config={{ ...config, selected }} status={{ ...status, media, running_config: running, pending_configuration: true }} onAction={action} isActionPending={false} />);
  expect(screen.getByText(/Selected: Tomorrow · revision 2/)).toBeTruthy();
  expect(screen.getByText(/Running configuration: Today · revision 1/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Restart" }));
  expect(action).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Confirm Restart" }));
  expect(action).toHaveBeenCalledWith("restart", "b");
});
