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
  selected?: SelectionSummary | null;
  capabilities?: string[];
  runtime: { ffmpeg_command: string; service_name: string; generated_from_station: string };
}

export interface SelectionSummary {
  id: string;
  source_preset_id: string | null;
  source_revision: number | null;
  source_name: string;
  target: string;
  created_at: string;
}

export interface SavedSiteConfigSummary {
  id: string;
  name: string;
  revision: number;
  created_at: string;
  updated_at: string;
}

export interface SavedSiteConfigResponse {
  saved_config: SavedSiteConfigSummary;
}

export interface SavedSiteConfigDetail extends SavedSiteConfigResponse {
  bundle: ConfigBundle;
  app_digest: string;
  runtime_digest: string;
  runtime_version: number;
  expected_selection_id: string | null;
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
  media?: SenderHealth;
  selected?: SelectionSummary | null;
  running_config?: ConfigBundle | null;
  pending_configuration?: boolean | null;
}

export interface SenderHealth {
  state: "stopped" | "connecting" | "healthy" | "degraded" | "retrying" | "unknown";
  reason: string;
  detail: string;
  summary: Record<string, string>;
  input: { value: number; age_seconds: number | null; last_progress_at: string | null };
  output: { value: number; age_seconds: number | null; last_progress_at: string | null };
  attempt: number;
  retry_count: number;
  next_retry_at: string | null;
  last_failure_at: string | null;
  last_recovery_at: string | null;
  heartbeat_at: string | null;
  pending_config: boolean;
  remote_receipt: "unverified";
  policy: Record<string, number>;
  events: Array<{ at: string; state: string; reason: string; attempt: number }>;
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
  listSavedSiteConfigs: () => request<SavedSiteConfigSummary[]>("/api/config/saved"),
  saveNamedSiteConfig: (name: string, site: ConfigBundle["site"], base?: SavedSiteConfigSummary) =>
    base && base.name === name
      ? request<SavedSiteConfigResponse>(`/api/config/saved/${base.id}`, {
          method: "PUT", body: JSON.stringify({ site, expected_revision: base.revision }),
        })
      : request<SavedSiteConfigResponse>("/api/config/saved", { method: "POST", body: JSON.stringify({ name, site }) }),
  openSavedSiteConfig: (id: string, expectedRevision?: number) => request<SavedSiteConfigDetail>(`/api/config/saved/${id}${expectedRevision === undefined ? "" : `?expected_revision=${expectedRevision}`}`),
  applySavedSiteConfig: (review: SavedSiteConfigDetail, requestId: string) =>
    request<ConfigBundle>(`/api/config/saved/${review.saved_config.id}/apply`, {
      method: "POST", body: JSON.stringify({
        expected_revision: review.saved_config.revision, expected_selection_id: review.expected_selection_id,
        app_digest: review.app_digest, runtime_digest: review.runtime_digest,
        runtime_version: review.runtime_version, target: "default", request_id: requestId,
      }),
    }),
  renameSavedSiteConfig: (preset: SavedSiteConfigSummary, name: string) =>
    request<SavedSiteConfigSummary>(`/api/config/saved/${preset.id}`, {
      method: "PATCH", body: JSON.stringify({ name, expected_revision: preset.revision }),
    }),
  deleteSavedSiteConfig: (preset: SavedSiteConfigSummary) =>
    request<{ ok: true }>(`/api/config/saved/${preset.id}?expected_revision=${preset.revision}`, { method: "DELETE" }),
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
  runServiceAction: (action: "start" | "stop" | "restart", expectedSelectionId?: string) =>
    request<ServiceStatus>(`/api/service/${action}`, {
      method: "POST",
      body: JSON.stringify({ expected_selection_id: expectedSelectionId }),
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

export interface ScopeGrant { scope: string; kind: string; resource_id: string; target: string | null }
export interface TokenCatalogue {
  instance_id: string;
  scopes: Array<{ id: string; group: string; kind: string; minimum_role: UserRole; description?: string }>;
  presets: Array<{ id: string; version: number; grants: ScopeGrant[] }>;
  resources: Record<string, Array<{ id: string; name: string }>>;
  endpoints: Record<string, string[]>;
}
export interface IntegrationToken {
  id: string; name: string; integration: string; owner_id: string; creator_id: string; instance_id: string;
  preset: string; preset_version: number; preset_customized?: boolean; revision: number; grants: ScopeGrant[]; effective_grants: ScopeGrant[];
  status: string; created_at: string; expires_at: string; revoked_at: string | null; last_used_at: string | null;
  credentials: Array<{ id: string; prefix: string; created_at: string; last_used_at: string | null; retire_at: string | null; revoked_at: string | null }>;
}
export interface TokenAudit { id: string; action: string; outcome: string; created_at: string; actor_id: string; request_id: string }
export const tokenApi = {
  catalogue: () => request<TokenCatalogue>('/api/v1/token-catalogue'),
  list: (offset = 0) => request<{ items: IntegrationToken[] }>(`/api/v1/tokens?limit=100&offset=${offset}`),
  create: (body: { name: string; integration: string; owner_id: string; grants: ScopeGrant[]; expires_at: string; preset: string; current_password: string }) =>
    request<{ token: IntegrationToken; secret: string }>('/api/v1/tokens', { method: 'POST', body: JSON.stringify(body) }),
  update: (id: string, body: { name: string; grants: ScopeGrant[]; expires_at: string; expected_revision: number; current_password: string }) =>
    request<IntegrationToken>(`/api/v1/tokens/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  rotate: (id: string, body: { expected_revision: number; overlap_seconds: number; current_password: string }) =>
    request<{ token: IntegrationToken; secret: string }>(`/api/v1/tokens/${id}/rotate`, { method: 'POST', body: JSON.stringify(body) }),
  revoke: (ids: string[]) => request<{ revoked_ids: string[] }>('/api/v1/tokens/revoke', { method: 'POST', body: JSON.stringify({ ids }) }),
  audit: (id: string) => request<{ items: TokenAudit[] }>(`/api/v1/tokens/${id}/audit-events`),
};
