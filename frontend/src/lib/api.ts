export interface User {
  id: string;
  username: string;
  role: "owner" | "engineer" | "operator";
  disabled: boolean;
}

export type UserRole = User["role"];

export interface AuthStatus {
  authenticated: boolean;
  user: User | null;
  csrf_token: string | null;
}

export interface ConfigBundle {
  app: { station_name: string; support_contact: string };
  site: {
    input: { name: string; url: string };
    destination: { name: string; protocol: "srt" | "udp"; host: string; port: number };
    profile: {
      name: string;
      audio_bitrate_kbps: number;
      sample_rate_hz: number;
      channels: number;
      srt_latency_ms: number;
      mux_rate_kbps: number;
      pcr_period_ms: number;
      enable_video: boolean;
      video_codec: "mpeg2video" | "libx264";
      video_bitrate_kbps: number;
      video_resolution: string;
      video_frame_rate: number;
      video_source: "none" | "black_test_frames";
    };
  };
  runtime: { ffmpeg_command: string; service_name: string; generated_from_station: string };
}

export interface SavedSiteConfigSummary {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  last_loaded_at: string | null;
  is_active: boolean;
}

export interface SavedSiteConfigResponse {
  saved_config: SavedSiteConfigSummary;
  bundle: ConfigBundle;
}

export interface SavedInputEntry {
  id: string;
  name: string;
  url: string;
  created_at: string;
  updated_at: string;
}

export interface SavedDestinationEntry {
  id: string;
  name: string;
  protocol: "srt" | "udp";
  host: string;
  port: number;
  created_at: string;
  updated_at: string;
}

export interface ServiceStatus {
  service_name: string;
  running: boolean;
  status: string;
  detail: string;
  allowed_actions: Array<"start" | "stop" | "restart">;
  preflight_ok: boolean;
  preflight_failures: string[];
  last_command: string | null;
  last_exit_code: number | null;
  stderr_tail: string | null;
}

export interface RedundancyNodeSummary {
  id: string;
  label: string;
  role: "live" | "standby" | "partner" | "unknown";
  connection_state: "online" | "offline" | "unknown";
  stream_authority: boolean;
  config_authority: boolean;
  runtime_status: "healthy" | "valid" | "degraded" | "invalid" | "unknown";
  sync_status: "up_to_date" | "syncing" | "behind" | "sync_failed" | "read_only" | "not_applicable" | "unknown";
  takeover_ready: boolean;
  detail: string | null;
}

export interface RedundancyStatus {
  mode: "single_node" | "partner_redundancy";
  product_state: "protected" | "degraded_protection" | "failed_over" | "unprotected" | "transitioning";
  product_state_reason: string;
  live_node_id: string | null;
  live_node_label: string | null;
  standby_node_id: string | null;
  standby_node_label: string | null;
  output_status: "healthy" | "degraded" | "no_verified_output" | "verification_unavailable" | "unknown";
  output_status_reason: string;
  config_sync_status: "up_to_date" | "syncing" | "behind" | "sync_failed" | "read_only" | "not_applicable" | "unknown";
  config_sync_reason: string;
  partner_takeover_ready: boolean;
  automatic_takeover_paused: boolean;
  allowed_actions: string[];
  last_action: string;
  source: "default" | "state_file";
  nodes: RedundancyNodeSummary[];
}

export interface DiagnosticCheck {
  name: string;
  ok: boolean;
  detail: string;
  severity: "info" | "warning" | "critical";
  category: "runtime" | "input" | "output" | "service" | "system";
  blocking: boolean;
}

export interface CreateUserRequest {
  username: string;
  password: string;
  role: UserRole;
}

export interface UpdateUserRequest {
  role?: UserRole;
  disabled?: boolean;
}

export interface UpdateStatus {
  repo_url: string;
  repo_ref: string;
  installed_commit: string | null;
  latest_commit: string | null;
  update_available: boolean;
  checked_at: string | null;
  job_status: "idle" | "checking" | "running" | "succeeded" | "failed" | "rolled_back";
  current_step: string | null;
  log_lines: string[];
  error: string | null;
  backup_path: string | null;
  stash_ref: string | null;
  rollback_succeeded: boolean | null;
  sender_impact: string;
  sender_message: string;
}

export interface UpdateJobStatus {
  repo_url: string;
  repo_ref: string;
  installed_commit_before: string | null;
  installed_commit_after: string | null;
  latest_commit: string | null;
  checked_at: string | null;
  job_status: "idle" | "checking" | "running" | "succeeded" | "failed" | "rolled_back";
  current_step: string | null;
  log_lines: string[];
  error: string | null;
  backup_path: string | null;
  stash_ref: string | null;
  rollback_succeeded: boolean | null;
  started_at: string | null;
  finished_at: string | null;
  sender_impact: string;
  sender_message: string;
}

export interface UpdateLaunchResponse {
  updater_url: string;
  expires_at: string;
}

type ApiErrorPayload =
  | { detail?: string | Array<{ loc?: Array<string | number>; msg?: string }> }
  | null;

function formatError(payload: ApiErrorPayload, status: number): string {
  if (!payload?.detail) {
    return `Request failed: ${status}`;
  }
  if (typeof payload.detail === "string") {
    return payload.detail;
  }
  if (Array.isArray(payload.detail)) {
    return payload.detail
      .map((issue) => {
        const path = issue.loc?.slice(1).join(".") ?? "field";
        return `${path}: ${issue.msg ?? "Invalid value"}`;
      })
      .join("\n");
  }
  return `Request failed: ${status}`;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const unsafeRequest = ["POST", "PUT", "PATCH", "DELETE"].includes(method);
  const response = await fetch(path, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(unsafeRequest && csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      ...(init?.headers ?? {}),
    },
  });

  if (!response.ok) {
    if (response.status === 401) {
      csrfToken = null;
    }
    const payload = (await response.json().catch(() => null)) as ApiErrorPayload;
    throw new Error(formatError(payload, response.status));
  }

  const payload = (await response.json()) as T;
  if (payload && typeof payload === "object" && "csrf_token" in payload) {
    const candidate = (payload as Record<string, unknown>).csrf_token;
    csrfToken = typeof candidate === "string" ? candidate : null;
  }
  return payload;
}

let csrfToken: string | null = null;

export interface ImportDecision {
  key: string;
  action: "add" | "skip" | "replace";
  name?: string;
  latency_ms?: number;
}

export interface ImportPreview {
  items: Array<{
    key: string;
    kind: "preset" | "input" | "destination";
    name: string;
    action: ImportDecision["action"];
    conflict: boolean;
    requires_latency_review: boolean;
    source_latency_ms: number | null;
    latency_ms: number | null;
    settings: Record<string, unknown>;
  }>;
  warnings: string[];
  errors: string[];
  can_import: boolean;
  preview_token: string;
}

export const api = {
  exportConfigurations: () => request<Record<string, unknown>>("/api/config/transfer/export"),
  previewImport: (document: Record<string, unknown>, decisions: ImportDecision[]) =>
    request<ImportPreview>("/api/config/transfer/preview", { method: "POST", body: JSON.stringify({ document, decisions }) }),
  importConfigurations: (document: Record<string, unknown>, decisions: ImportDecision[], preview_token: string) =>
    request<{ imported: Array<{ key: string; id: string; name: string; kind: string }>; active_configuration_changed: false }>(
      "/api/config/transfer/import", { method: "POST", body: JSON.stringify({ document, decisions, preview_token }) }),
  getBootstrapStatus: () => request<{ requires_bootstrap: boolean }>("/api/auth/bootstrap-status"),
  getMe: () => request<AuthStatus>("/api/auth/me"),
  login: (username: string, password: string) =>
    request<AuthStatus>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  bootstrapOwner: (username: string, password: string) =>
    request<AuthStatus>("/api/auth/bootstrap-owner", {
      method: "POST",
      body: JSON.stringify({ username, password, role: "owner" }),
    }),
  getUsers: () => request<User[]>("/api/auth/users"),
  createUser: (payload: CreateUserRequest) =>
    request<User>("/api/auth/users", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateUser: (userId: string, payload: UpdateUserRequest) =>
    request<User>(`/api/auth/users/${userId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  logout: () => request<AuthStatus>("/api/auth/logout", { method: "POST" }),
  getConfig: () => request<ConfigBundle>("/api/config"),
  updateSiteConfig: (site: ConfigBundle["site"]) =>
    request<ConfigBundle>("/api/config/site", {
      method: "PUT",
      body: JSON.stringify(site),
    }),
  listSavedSiteConfigs: () => request<SavedSiteConfigSummary[]>("/api/config/saved"),
  saveNamedSiteConfig: (name: string, site: ConfigBundle["site"], overwrite = false) =>
    request<SavedSiteConfigResponse>("/api/config/saved", {
      method: "POST",
      body: JSON.stringify({ name, site, overwrite }),
    }),
  loadSavedSiteConfig: (savedConfigId: string) =>
    request<ConfigBundle>(`/api/config/saved/${savedConfigId}/load`, {
      method: "POST",
    }),
  renameSavedSiteConfig: (savedConfigId: string, name: string) =>
    request<SavedSiteConfigSummary>(`/api/config/saved/${savedConfigId}`, {
      method: "PATCH",
      body: JSON.stringify({ name }),
    }),
  deleteSavedSiteConfig: (savedConfigId: string) =>
    request<{ ok: true }>(`/api/config/saved/${savedConfigId}`, {
      method: "DELETE",
    }),
  listSavedInputs: () => request<SavedInputEntry[]>("/api/config/saved-inputs"),
  saveInput: (input: ConfigBundle["site"]["input"]) =>
    request<SavedInputEntry>("/api/config/saved-inputs", {
      method: "POST",
      body: JSON.stringify({ input }),
    }),
  listSavedDestinations: () => request<SavedDestinationEntry[]>("/api/config/saved-destinations"),
  saveDestination: (destination: ConfigBundle["site"]["destination"]) =>
    request<SavedDestinationEntry>("/api/config/saved-destinations", {
      method: "POST",
      body: JSON.stringify({ destination }),
    }),
  getServiceStatus: () => request<ServiceStatus>("/api/service/status"),
  runServiceAction: (action: "start" | "stop" | "restart") =>
    request<ServiceStatus>(`/api/service/${action}`, {
      method: "POST",
    }),
  getLogs: () => request<{ service_name: string; lines: string[] }>("/api/logs"),
  getDiagnostics: () => request<{ checks: DiagnosticCheck[] }>("/api/diagnostics"),
  getSystemInfo: () =>
    request<{
      app_version: string;
      installed_commit: string | null;
      hostname: string;
      platform: string;
      ffmpeg_available: boolean;
      ffmpeg_binary: string;
      config_path: string;
      data_path: string;
    }>("/api/system"),
  getRedundancyStatus: () => request<RedundancyStatus>("/api/redundancy/status"),
  getUpdateStatus: () => request<UpdateStatus>("/api/update/status"),
  checkForUpdates: () =>
    request<UpdateStatus>("/api/update/check", {
      method: "POST",
    }),
  launchUpdater: () =>
    request<UpdateLaunchResponse>("/api/update/launch", {
      method: "POST",
    }),
  startUpdate: () =>
    request<UpdateJobStatus>("/api/update/install", {
      method: "POST",
    }),
  getUpdateJob: () => request<UpdateJobStatus>("/api/update/job"),
};
