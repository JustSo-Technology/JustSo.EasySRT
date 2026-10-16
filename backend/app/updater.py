from __future__ import annotations

from fastapi import Depends, FastAPI, Header
from fastapi.responses import HTMLResponse

from app.models.auth import User
from app.services import update_manager
from app.services.update_handoff import decode_updater_session, exchange_handoff_token, user_from_handoff

app = FastAPI(title="JustSo EasySRT Updater")

HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>EasySRT Updater</title>
    <style>
      :root {
        color-scheme: dark;
        --bg: #08131b;
        --panel: rgba(11, 27, 36, 0.92);
        --panel-soft: rgba(18, 37, 49, 0.88);
        --border: rgba(255, 255, 255, 0.1);
        --text: #eff7fc;
        --muted: #8fa9b8;
        --accent: #93d7ff;
        --accent-strong: #d9f2ff;
        --warn: #ffd38c;
        --bad: #ff9f9f;
      }
      * { box-sizing: border-box; }
      body {
        margin: 0;
        font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
        background:
          radial-gradient(circle at top left, rgba(87, 168, 224, 0.18), transparent 28%),
          radial-gradient(circle at bottom right, rgba(255, 210, 140, 0.14), transparent 24%),
          linear-gradient(180deg, var(--bg), #050b10 72%);
        color: var(--text);
        min-height: 100vh;
      }
      .shell { max-width: 1180px; margin: 0 auto; padding: 28px; }
      .hero { display: flex; justify-content: space-between; gap: 24px; align-items: flex-start; }
      .eyebrow { letter-spacing: 0.24em; text-transform: uppercase; font-size: 12px; color: var(--accent); }
      h1 { margin: 10px 0 8px; font-size: clamp(2.2rem, 4vw, 4rem); line-height: 0.94; letter-spacing: -0.05em; }
      .lede { max-width: 720px; color: var(--muted); font-size: 1rem; line-height: 1.6; }
      .layout { margin-top: 28px; display: grid; grid-template-columns: minmax(320px, 0.92fr) minmax(380px, 1.08fr); gap: 20px; }
      .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 28px; padding: 22px; box-shadow: 0 22px 80px rgba(0, 0, 0, 0.28); backdrop-filter: blur(14px); }
      .panel h2 { margin: 0; font-size: 1.3rem; letter-spacing: -0.03em; }
      .subtle { color: var(--muted); font-size: 0.94rem; }
      .grid { display: grid; gap: 14px; margin-top: 20px; }
      .metric { background: var(--panel-soft); border: 1px solid var(--border); border-radius: 22px; padding: 14px 16px; }
      .metric .label { font-size: 11px; letter-spacing: 0.2em; text-transform: uppercase; color: var(--muted); }
      .metric .value { margin-top: 8px; font-size: 0.98rem; font-weight: 600; word-break: break-word; }
      .actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 18px; }
      button, .link-btn { appearance: none; border: 0; border-radius: 999px; padding: 13px 18px; font: inherit; font-weight: 700; cursor: pointer; text-decoration: none; }
      button.primary, .link-btn.primary { background: linear-gradient(135deg, #9cd7ff, #6ea2dc); color: #071219; }
      button.secondary { background: rgba(255,255,255,0.08); color: var(--text); border: 1px solid var(--border); }
      button:disabled { opacity: 0.55; cursor: default; }
      .banner { margin-top: 18px; padding: 14px 16px; border-radius: 20px; border: 1px solid var(--border); background: rgba(255, 211, 140, 0.1); color: var(--warn); }
      .error { margin-top: 18px; padding: 14px 16px; border-radius: 20px; border: 1px solid rgba(255, 159, 159, 0.28); background: rgba(255, 159, 159, 0.08); color: var(--bad); white-space: pre-wrap; }
      .status-pill { display: inline-flex; align-items: center; gap: 8px; padding: 9px 12px; border-radius: 999px; background: rgba(255,255,255,0.07); color: var(--accent-strong); font-size: 0.92rem; }
      .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--accent); box-shadow: 0 0 0 6px rgba(147, 215, 255, 0.12); }
      .result { margin-top: 18px; padding: 14px 16px; border-radius: 20px; border: 1px solid var(--border); background: rgba(255,255,255,0.04); }
      pre { margin: 18px 0 0; min-height: 420px; max-height: 60vh; overflow: auto; border-radius: 24px; border: 1px solid var(--border); background: rgba(0, 0, 0, 0.28); padding: 18px; color: #d1f7ff; font: 12px/1.6 "IBM Plex Mono", "SFMono-Regular", monospace; white-space: pre-wrap; }
      @media (max-width: 980px) {
        .layout { grid-template-columns: 1fr; }
        .hero { flex-direction: column; }
        .shell { padding: 18px; }
        pre { min-height: 280px; }
      }
    </style>
  </head>
  <body>
    <main class="shell">
      <section class="hero">
        <div>
          <div class="eyebrow">Maintenance window</div>
          <h1>EasySRT updater</h1>
          <p class="lede">This updater stays online while EasySRT restarts underneath it. Use it to verify the target commit, run the Linux update pipeline, and follow the real progress log without losing the page.</p>
        </div>
        <div class="status-pill"><span class="dot"></span><span id="connectionState">Connecting...</span></div>
      </section>
      <section class="layout">
        <section class="panel">
          <h2>Control plane update</h2>
          <p class="subtle">The sender is left untouched by default. Only backend and frontend services are restarted.</p>
          <div class="banner" id="banner">Waiting for updater handoff...</div>
          <div class="grid">
            <div class="metric"><div class="label">Installed commit</div><div class="value" id="installedCommit">Unknown</div></div>
            <div class="metric"><div class="label">Latest commit</div><div class="value" id="latestCommit">Unknown</div></div>
            <div class="metric"><div class="label">Status</div><div class="value" id="jobStatus">idle</div></div>
            <div class="metric"><div class="label">Current step</div><div class="value" id="currentStep">Ready</div></div>
          </div>
          <div class="actions">
            <button class="secondary" id="checkBtn">Check for update</button>
            <button class="primary" id="installBtn">Install update</button>
            <a class="link-btn primary" id="returnBtn" href="#" hidden>Open EasySRT</a>
          </div>
          <div class="error" id="errorBox" hidden></div>
          <div class="result" id="resultBox" hidden></div>
        </section>
        <section class="panel">
          <h2>Live activity</h2>
          <p class="subtle">This stream comes from the updater-owned job state, not from the EasySRT UI runtime.</p>
          <pre id="logLines">No update activity yet.</pre>
        </section>
      </section>
    </main>
    <script>
      const params = new URLSearchParams(window.location.search);
      const handoffToken = params.get("token");
      let token = sessionStorage.getItem("easysrt-updater-session");
      let returnUrl = sessionStorage.getItem("easysrt-updater-return") || "/";
      const state = { pollId: null, running: false };
      const els = {
        connectionState: document.getElementById("connectionState"),
        banner: document.getElementById("banner"),
        installedCommit: document.getElementById("installedCommit"),
        latestCommit: document.getElementById("latestCommit"),
        jobStatus: document.getElementById("jobStatus"),
        currentStep: document.getElementById("currentStep"),
        logLines: document.getElementById("logLines"),
        errorBox: document.getElementById("errorBox"),
        resultBox: document.getElementById("resultBox"),
        checkBtn: document.getElementById("checkBtn"),
        installBtn: document.getElementById("installBtn"),
        returnBtn: document.getElementById("returnBtn"),
      };
      els.returnBtn.href = returnUrl;
      if (handoffToken) {
        window.history.replaceState({}, document.title, window.location.pathname);
      }
      function shortCommit(value) {
        return value ? String(value).slice(0, 7) : "unknown";
      }
      function setError(message) {
        if (!message) {
          els.errorBox.hidden = true;
          els.errorBox.textContent = "";
          return;
        }
        els.errorBox.hidden = false;
        els.errorBox.textContent = message;
      }
      function setConnectionState(text) {
        els.connectionState.textContent = text;
      }
      function render(payload, logs) {
        els.installedCommit.textContent = shortCommit(payload.installed_commit_after || payload.installed_commit || payload.installed_commit_before);
        els.latestCommit.textContent = shortCommit(payload.latest_commit);
        els.jobStatus.textContent = payload.job_status || "idle";
        els.currentStep.textContent = payload.current_step || "Ready";
        els.logLines.textContent = logs.length ? logs.join("\\n") : "No update activity yet.";
        const status = payload.job_status || "idle";
        const available = Boolean(payload.update_available || (payload.installed_commit && payload.latest_commit && payload.installed_commit !== payload.latest_commit));
        els.installBtn.disabled = state.running || !available;
        els.checkBtn.disabled = state.running;
        if (status === "running") {
          els.banner.textContent = "Update in progress. This page stays active while EasySRT restarts.";
          state.running = true;
        } else if (status === "succeeded") {
          els.banner.textContent = "Update completed successfully. EasySRT is healthy again.";
          els.returnBtn.hidden = false;
          state.running = false;
        } else if (status === "rolled_back") {
          els.banner.textContent = "Update failed and rollback succeeded. Review the final log before returning.";
          els.returnBtn.hidden = false;
          state.running = false;
        } else if (status === "failed") {
          els.banner.textContent = "Update failed. Review the result and logs below.";
          state.running = false;
        } else if (available) {
          els.banner.textContent = "A newer control-plane build is available.";
          state.running = false;
        } else {
          els.banner.textContent = "EasySRT is already on the latest known commit.";
          state.running = false;
        }
        const resultBits = [];
        if (payload.installed_commit_after) resultBits.push("Installed after update: " + shortCommit(payload.installed_commit_after));
        if (payload.backup_path) resultBits.push("Backup path: " + payload.backup_path);
        if (payload.stash_ref) resultBits.push("Stash ref: " + payload.stash_ref);
        if (payload.rollback_succeeded != null) resultBits.push("Rollback: " + (payload.rollback_succeeded ? "succeeded" : "failed"));
        if (resultBits.length) {
          els.resultBox.hidden = false;
          els.resultBox.textContent = resultBits.join("\\n");
        } else {
          els.resultBox.hidden = true;
          els.resultBox.textContent = "";
        }
      }
      async function api(path, init = {}) {
        if (!token) {
          throw new Error("Missing updater handoff token.");
        }
        const response = await fetch(path, {
          ...init,
          headers: {
            "X-Updater-Token": token,
            ...(init.headers || {}),
          },
        });
        if (!response.ok) {
          let detail = "Request failed: " + response.status;
          try {
            const payload = await response.json();
            if (typeof payload.detail === "string") detail = payload.detail;
          } catch {}
          throw new Error(detail);
        }
        return response.json();
      }
      async function refreshStatus() {
        try {
          setConnectionState("Connected");
          setError("");
          const payload = await api("/api/update/status");
          render(payload, payload.log_lines || []);
          if (payload.job_status === "running") startPolling();
        } catch (error) {
          setConnectionState("Connection issue");
          setError(error instanceof Error ? error.message : "Unable to read updater status");
        }
      }
      async function checkForUpdate() {
        try {
          setError("");
          els.checkBtn.disabled = true;
          const payload = await api("/api/update/check", { method: "POST" });
          render(payload, payload.log_lines || []);
        } catch (error) {
          setError(error instanceof Error ? error.message : "Unable to check for updates");
        } finally {
          els.checkBtn.disabled = state.running;
        }
      }
      async function refreshJob() {
        try {
          const payload = await api("/api/update/job");
          render(payload, payload.log_lines || []);
          if (payload.error) setError(payload.error);
          if (payload.job_status !== "running") stopPolling();
        } catch (error) {
          setError(error instanceof Error ? error.message : "Unable to read update job");
        }
      }
      async function installUpdate() {
        try {
          setError("");
          els.installBtn.disabled = true;
          const payload = await api("/api/update/install", { method: "POST" });
          render(payload, payload.log_lines || []);
          startPolling();
        } catch (error) {
          setError(error instanceof Error ? error.message : "Unable to start update");
          els.installBtn.disabled = false;
        }
      }
      function startPolling() {
        if (state.pollId) return;
        state.running = true;
        state.pollId = window.setInterval(refreshJob, 3000);
      }
      function stopPolling() {
        state.running = false;
        if (!state.pollId) return;
        window.clearInterval(state.pollId);
        state.pollId = null;
      }
      els.checkBtn.addEventListener("click", checkForUpdate);
      els.installBtn.addEventListener("click", installUpdate);
      async function initialize() {
        try {
          if (handoffToken) {
            const response = await fetch("/api/update/session", {
              method: "POST",
              headers: { "X-Updater-Token": handoffToken },
            });
            if (!response.ok) throw new Error("Updater handoff expired or invalid. Reopen the updater from EasySRT.");
            const session = await response.json();
            token = session.token;
            returnUrl = session.return_url;
            sessionStorage.setItem("easysrt-updater-session", token);
            sessionStorage.setItem("easysrt-updater-return", returnUrl);
            els.returnBtn.href = returnUrl;
          }
          await refreshStatus();
          if (!state.running) await checkForUpdate();
        } catch (error) {
          setConnectionState("Authorization required");
          setError(error instanceof Error ? error.message : "Unable to authorize updater");
        }
      }
      initialize();
    </script>
  </body>
</html>
"""


def require_updater_user(x_updater_token: str = Header(alias="X-Updater-Token")) -> User:
    payload = decode_updater_session(x_updater_token)
    return user_from_handoff(payload)


@app.get("/", response_class=HTMLResponse)
def updater_home() -> str:
    return HTML


@app.get("/health")
def health() -> dict[str, bool]:
    return {"ok": True}


@app.get("/api/update/status")
def update_status(_: User = Depends(require_updater_user)):
    return update_manager.get_update_status()


@app.post("/api/update/check")
def update_check(_: User = Depends(require_updater_user)):
    return update_manager.check_for_updates()


@app.post("/api/update/install")
def update_install(user: User = Depends(require_updater_user)):
    return update_manager.start_update_job(user)


@app.get("/api/update/job")
def update_job(_: User = Depends(require_updater_user)):
    return update_manager.get_update_job()


@app.post("/api/update/session")
def update_session(x_updater_token: str = Header(alias="X-Updater-Token")):
    return exchange_handoff_token(x_updater_token)
