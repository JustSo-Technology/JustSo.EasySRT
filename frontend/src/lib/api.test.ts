import { afterEach, describe, expect, it, vi } from "vitest";

function jsonResponse(payload: unknown, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const authStatus = {
  authenticated: true,
  user: { id: "owner-id", username: "owner", role: "owner", disabled: false },
  csrf_token: "csrf-token",
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetModules();
});

describe("API CSRF handling", () => {
  it("uses the CSRF token returned by login on later writes", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(authStatus))
      .mockResolvedValueOnce(
        jsonResponse({ id: "engineer-id", username: "engineer", role: "engineer", disabled: false }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("./api");

    await api.login("owner", "supersecurepass");
    await api.createUser({ username: "engineer", password: "engineerpass123", role: "engineer" });

    const [, secondInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(new Headers(secondInit.headers).get("X-CSRF-Token")).toBe("csrf-token");
  });

  it("does not attach the CSRF token to safe requests", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(authStatus))
      .mockResolvedValueOnce(jsonResponse({ requires_bootstrap: false }));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("./api");

    await api.login("owner", "supersecurepass");
    await api.getBootstrapStatus();

    const [, secondInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(new Headers(secondInit.headers).has("X-CSRF-Token")).toBe(false);
  });

  it("clears the CSRF token after an unauthorized response", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(authStatus))
      .mockResolvedValueOnce(jsonResponse({ detail: "Not authenticated" }, 401))
      .mockResolvedValueOnce(
        jsonResponse({ id: "engineer-id", username: "engineer", role: "engineer", disabled: false }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("./api");

    await api.login("owner", "supersecurepass");
    await expect(api.getMe()).rejects.toThrow("Not authenticated");
    await api.createUser({ username: "engineer", password: "engineerpass123", role: "engineer" });

    const [, thirdInit] = fetchMock.mock.calls[2] as [string, RequestInit];
    expect(new Headers(thirdInit.headers).has("X-CSRF-Token")).toBe(false);
  });
});

describe("API request contracts", () => {
  it("bootstraps the first account as an owner with credentialed fetches", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(authStatus));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("./api");

    await api.bootstrapOwner("owner", "supersecurepass");

    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/auth/bootstrap-owner");
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
    expect(JSON.parse(String(init.body))).toEqual({
      username: "owner",
      password: "supersecurepass",
      role: "owner",
    });
  });

  it("maps sender and updater actions to POST endpoints", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(jsonResponse({}))
      .mockResolvedValueOnce(jsonResponse({}));
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("./api");

    await api.runServiceAction("restart");
    await api.checkForUpdates();
    await api.startUpdate();

    expect(fetchMock.mock.calls.map(([path, init]) => [path, (init as RequestInit).method])).toEqual([
      ["/api/service/restart", "POST"],
      ["/api/update/check", "POST"],
      ["/api/update/install", "POST"],
    ]);
  });

  it("formats field validation errors with their nested paths", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse(
        {
          detail: [
            { loc: ["body", "destination", "port"], msg: "Input should be less than or equal to 65535" },
          ],
        },
        422,
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    const { api } = await import("./api");

    await expect(
      api.updateSiteConfig({
        input: { name: "input", url: "https://example.com/live" },
        destination: { name: "output", protocol: "srt", host: "example.com", port: 70000 },
        profile: {
          name: "standard",
          audio_bitrate_kbps: 256,
          sample_rate_hz: 48000,
          channels: 2,
          srt_latency_ms: 120,
          mux_rate_kbps: 600,
          pcr_period_ms: 20,
          enable_video: false,
          video_codec: "mpeg2video",
          video_bitrate_kbps: 1000,
          video_resolution: "1280x720",
          video_frame_rate: 25,
          video_source: "none",
        },
      }),
    ).rejects.toThrow("destination.port: Input should be less than or equal to 65535");
  });
});
