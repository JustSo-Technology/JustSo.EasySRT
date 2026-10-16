# Deployment security

EasySRT is an administrative control plane for FFmpeg and system services.

## Network policy

- Bind the backend to `127.0.0.1`; the frontend proxy is the only supported
  browser entry point.
- Do not expose TCP ports 8000 or 5174 to untrusted networks.
- Restrict the frontend port to the management network with the host or
  perimeter firewall.
- For internet or untrusted-network access, terminate HTTPS at a maintained
  reverse proxy and set:

```text
EASYSRT_FRONTEND_ORIGIN=https://easysrt.example.com
EASYSRT_SESSION_COOKIE_SECURE=true
EASYSRT_ALLOW_INSECURE_HTTP=false
EASYSRT_TRUSTED_HOSTS=easysrt.example.com,localhost,127.0.0.1
```

The updater uses a separate local service. For HTTPS deployments, publish it
through its own authenticated reverse-proxy origin and set, for example,
`EASYSRT_UPDATER_PUBLIC_ORIGIN=https://easysrt-updater.example.com`. Do not
publish raw port `5174` to the internet. Configure the frontend reverse proxy
to preserve the original `Host` header and set `X-Forwarded-Proto=https`.

LAN HTTP mode is supported only with the explicit
`EASYSRT_ALLOW_INSECURE_HTTP=true` opt-in and secure cookies disabled.

## Secrets and access

- Generate `EASYSRT_SECRET_KEY` from at least 32 random bytes. Rotating it
  invalidates active sessions and updater handoff links.
- Keep `/etc/justso-easysrt/easysrt.env` readable only by administrators and
  the service account.
- Use a dedicated owner account and individual operator accounts.
- Keep Ubuntu, FFmpeg, Python, Node build tooling, and EasySRT updated.

## Release firewall checklist

Confirm externally that only the intended HTTPS or management-network
frontend endpoint is reachable. The backend, helper Unix socket, and updater
must not be directly internet-accessible.

## Privileged code and updates

The root helper and updater are installed in `/usr/local/lib/justso-easysrt`.
Their files and parent directories must remain owned by root and must not be
writable by the service account or other users. The application checkout and
builds remain owned by `easysrt`. The installer and updater fetch privileged
scripts and service units separately into a private root-owned checkout; they
never promote scripts from the writable application checkout to root execution.

`/etc/justso-easysrt/update-policy.json` is the administrator-owned allowlist for
the update repository URL and ref. Changing channels requires an administrator
to change this policy and the corresponding environment settings. A pinned tag
stays pinned; tracking a branch explicitly opts into that branch's updates.
The default `main` is a development branch, not a published-release channel.
Use `refs/heads/main` or `refs/tags/v0.1.0-alpha.1` to disambiguate when a branch
and tag share a name. The installer/updater accept these fully qualified refs.
The updater exchanges its short handoff link for a scoped session lasting up to
12 hours (`EASYSRT_UPDATER_SESSION_TTL_SECONDS`, default `43200`).

Update tracking is confined to `/var/lib/justso-easysrt-updates`. This directory
is owned by root and is not service-account writable. Its two tracking files
are root-owned and group writable for the application; they must be regular,
single-link files. Tracking contents are status information, never authority
for root code execution.

To migrate an older installation with helper code inside `/opt`, rerun the
reviewed installer from a trusted download as an administrator. An old,
service-account-writable updater cannot safely bootstrap this boundary. Run
manual updates with `sudo /usr/local/lib/justso-easysrt/update-ubuntu.sh`.
Installation, update and rollback require a committed backend `uv.lock` and
use `uv sync --locked --no-dev`; an absent or stale lock fails the deployment.
