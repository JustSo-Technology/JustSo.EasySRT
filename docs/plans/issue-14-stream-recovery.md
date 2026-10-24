# Stream path recovery — implementation plan

Date: 24 October 2026

Issue: [#14 — Recover stream paths gracefully when input or output is lost](https://github.com/JustSo-Technology/JustSo.EasySRT/issues/14)

Baseline: public `main`, `dcdfba48e33a5e23624b7474a632d7b264d6d65c`. The inspected local checkout also contains an unrelated password-confirmation commit; its streaming code matches this baseline.

Status: telemetry gate passed and recovery implemented. See the [validation report](../validation/issue-14-recovery.md) for measured results and the implemented host-policy choice. The sections below retain the original implementation plan.

## Outcome and scope

Automatically recover a sender whose input or output disconnects or stops making media progress. A deliberate Stop must cancel recovery. Report the evidence for health and the reason for recovery, and retain enough history to investigate an incident.

The public app currently has one active input, one output, and one sender service per instance. Implement recovery at that boundary, with an internal path identifier (initially `default`). Do not add a multi-path configuration system or partner failover in this issue. Recovery must never restart another instance, the control plane, or a partner node. Validate isolation using a second sender instance in the integration harness.

Standalone monitoring, external notifications, fallback audio, and receiver playback verification remain outside this issue. A silent audio stream with advancing samples is valid media.

## What the current code establishes

| Area | Current behavior | Consequence |
| --- | --- | --- |
| `ops/easysrt-sender.service` | Runs FFmpeg directly; `Restart=always`, five-second delay, twenty-second stop deadline | Restarts after exit, but has no media-progress watchdog |
| `backend/app/services/service_control.py` | Maps systemd `active` to `running=True` | Process state can be mistaken for media health |
| `frontend/src/features/dashboard/dashboard.tsx` | Shows “Streaming now” whenever `running` is true | A stalled live process can remain green |
| `backend/app/services/health_checks.py` | Input HTTP/file reachability and destination DNS/empty-datagram prechecks | These do not establish progress through the active sender or receiver receipt |
| `backend/app/services/config_service.py` | Generates one FFmpeg command; no progress channel or recovery policy | Runtime needs structured arguments, telemetry, and bounded network operations |
| `docs/configuration.md` | Saving/loading configuration does not apply it to an already-running sender | Recovery must preserve the applied runtime, rather than silently adopting saved edits |
| `ops/host-control-helper.py` | Restricts service actions through a local socket; subprocess calls have no explicit timeout | Extend the existing control boundary and bound calls so one hung request cannot block subsequent Stop/status requests |
| `frontend/src/app.tsx` | Service status query has no interval | Add polling so retry state updates without operator interaction |
| `ops/update-ubuntu.sh` | Refreshes units, then restarts control-plane services only | Introducing the supervisor requires an explicit live-sender activation/migration step |

## 1. Prove the media signals on the deployment baseline

First build a small, repeatable Ubuntu 24.04 fixture using the FFmpeg/libsrt build actually installed by EasySRT. Record versions and capabilities. The development Mac has FFmpeg 8.1.2 and cannot establish compatibility with the Ubuntu runtime.

Exercise audio-only and audio-with-generated-black-video configurations. Observe separately:

- **Source media:** advancing decoded source-audio frames/samples, including digitally silent audio. Bind observations to the real audio source; generated video must never satisfy this condition.
- **Local output media:** advancing media handed through the mux/output path, using counters demonstrated to correspond to writes rather than merely encoded or queued packets.
- **Process/transport:** child liveness, connection errors, and protocol timeout evidence. Keep these separate from media observations.
- **Remote receipt:** unknown unless a real receiver or transport acknowledgement provides that evidence; even acknowledged transport data does not prove playback.

Candidate FFmpeg interfaces are `-progress` with an explicit reporting period and audio-specific `-stats_enc_pre` records. Test their availability, counter semantics, buffering, and behavior under output backpressure on the supported build. Pre-encoding samples are a source-processing observation, not a direct network-read counter. `-stats_mux_pre` is explicitly before muxing and must not be treated as completed output. FFmpeg's timestamp debug log is unsuitable as a stable parser interface. See the [FFmpeg command documentation](https://ffmpeg.org/ffmpeg.html).

Use controlled input disconnect, connected-but-idle input, output disconnect, and output backpressure fixtures. Compare reported counters with the fixture's actual observations. If the stock interfaces cannot supply both required signals, record that result and select an explicit media-I/O instrumentation approach before implementing health decisions; an aggregate heartbeat is not an acceptable substitute. This is the main technical decision gate.

When an output stall propagates backpressure upstream, both counters may stop. Report `media_stalled` with cause unconfirmed unless there is independent evidence of the failing side. Recovery must still happen within its deadline; do not invent an input/network diagnosis.

**Deliverable:** a checked-in capability/signal report, selected telemetry adapter, and reproductions that distinguish healthy silent media from stalled media. All later work depends on passing this gate.

## 2. Define the applied runtime and recovery policy

Extend runtime generation with a versioned manifest containing validated FFmpeg argument arrays, telemetry configuration, a non-secret configuration identifier, and a recovery policy. Keep the displayed command for operator review, but launch the child with argument arrays rather than shell `eval`.

Maintain separate **candidate** and **applied** runtime manifests. An explicit Start or Restart selects and pins the candidate as the applied manifest. Automatic child retries and supervisor crash restarts reuse the applied manifest. Saving another preset while streaming must not change the route during the next recovery. Pin destination, encoding, SRT latency/options, stream mapping, and any existing service metadata/PIDs/signalling; do not regenerate recovery defaults differently on each attempt. The public schema does not currently expose custom service-signalling controls, so adding those controls is separate work.

Serialize Start/Stop/Restart and manifest publication with a per-service lock. Restart must first stop and reap the previous sender, then publish the new applied runtime and launch it. On migration, do not claim that current disk configuration describes an already-running legacy process: activate the new applied runtime on the next explicit Start/Restart.

Add a validated recovery configuration with bounded values. Proposed initial rehearsal settings, subject to step 1:

| Setting | Initial proposal |
| --- | --- |
| Telemetry/supervisor observation interval | 1 second |
| Startup deadline before first required media | 30 seconds |
| Input media-stall deadline | 15 seconds |
| Output media-stall deadline | 15 seconds |
| Retry delay | Exponential from 2 seconds to a maximum of 30 seconds, with bounded jitter |
| Healthy duration before resetting backoff | 30 seconds of sustained required media |
| Child shutdown budget | At most 10 seconds across graceful stop, termination, and kill/reap |

Define valid ranges, cross-field constraints, and protocol presets before shipping. Timeouts must accommodate configured buffering/latency and stream cadence. Every connection attempt, including a protocol's own reconnect behavior, must fit within a supervisor deadline.

Apply only supported protocol-specific network timeouts/reconnect options, placed on the correct input or output. Verify units and behavior per protocol/build; do not apply HTTP reconnect flags to SRT, UDP, or file input. The [FFmpeg protocol documentation](https://ffmpeg.org/ffmpeg-protocols.html) describes the generic read/write timeout and protocol-specific options; the deployed build is the compatibility authority. Treat finite file EOF explicitly as completed/stopped by default, rather than retrying a finished file indefinitely. Unexpected live-input EOF remains recoverable.

Old configurations must load with defaults. If policy is stored in the site/preset schema, introduce a compatible portable-format revision and explicit v1 migration. `config_transfer.py` currently checks exact keys and requires every model field, so Pydantic defaults alone will not preserve old imports. Update saved presets, frontend payloads, transfer preview/commit, and replicated snapshots together. Never import/export applied runtime state or retry history as configuration.

## 3. Add one supervisor inside the existing sender service

Make `easysrt-sender.service` run a small Python supervisor as the existing unprivileged `easysrt` account. It owns exactly one FFmpeg child for its path, reads/drains telemetry and stderr continuously, and evaluates deadlines using a monotonic clock. Recovery must continue with the browser closed and during backend/helper restarts.

The supervisor owns media recovery and child retry delays. Systemd owns service lifecycle and recovery from supervisor crashes. Avoid two independent watchdogs issuing service restarts. Configure systemd process-group cleanup and crash rate limits explicitly so a supervisor crash cannot leave an orphan child or create a fast crash loop. Expose supervisor failure separately if systemd crash limits are reached.

Use these path states:

| State | Meaning and next action |
| --- | --- |
| `stopped` | No active run requested; retries cancelled |
| `connecting` | Child started; waiting for first required media within startup deadline |
| `healthy` | Required source-audio and local-output media observations are recent and advancing |
| `degraded` | A deadline/error fired; report evidence and begin bounded cleanup |
| `retrying` | Previous child reaped; waiting until the next scheduled attempt |
| `unknown` | Observation unavailable/stale; never display confirmed health |

On disconnect, child exit, startup timeout, or stale required media: record the event; stop the child gracefully; escalate termination within the shutdown budget; reap it; then schedule a retry. Keep retrying transient connectivity failures indefinitely at the capped delay so a long outage can recover unattended. A brief reconnect must not reset the backoff until media stays healthy for the stability window.

Stop must cancel pending timers before child teardown. Receiving the service shutdown signal must atomically prevent further launches, including during startup, failure cleanup, and backoff. Keep the total shutdown budget below systemd's service stop deadline. Never launch a replacement while the old child is still alive; if OS-level cleanup cannot complete, report cleanup failure and escalate diagnostics rather than creating duplicates.

Use the unit as the lifecycle authority; do not introduce a backend startup task that automatically starts a stopped unit. Preserve existing boot enablement behavior. Test direct `systemctl stop` as well as the API, and verify backend restart, supervisor crash, and reboot behavior for stopped services.

## 4. Expose trustworthy status and bounded history

Publish an atomic per-path status snapshot, refreshed independently of media arrival. Include service/run identifier, child generation/PID, applied configuration identifier, state, reason code/detail, input/output evidence and last progress times, attempt count, next retry time, failure/recovery times, and snapshot freshness. Use UTC timestamps for display/history and monotonic elapsed time for timeout logic.

Keep state files private to the service account, validate their format and run identity, and reject stale samples or samples from a previous child generation. A dead supervisor's last `healthy` snapshot must never remain healthy. When an old sender is active after upgrade, report “Legacy sender: media health unavailable until restart.”

Record structured transition events in journald, with bounded retention for any additional local event store. Retain failure cause evidence, selected deadlines, attempt number/delay, cleanup outcome, exit status, and time to recovered media. Distinguish confirmed causes from suspected ones. Redact credentials/query secrets; rate-limit repeated errors and retain a bounded stderr tail. Do not log per-frame telemetry indefinitely.

Extend `ServiceStatus` additively with media/recovery fields and keep systemd status separate. Continue deriving allowed actions on the backend. Stop must be available throughout connecting/degraded/retrying, including systemd auto-restart states, even when configuration preflight fails. Serialize concurrent actions and add helper-side command timeouts; a timed-out systemctl request needs state reconciliation because the systemd job may still complete.

Relabel HTTP/DNS/datagram checks as reachability/preflight evidence and add actual runtime-media diagnostics. These probes must not declare a live path healthy or independently trigger recovery. For UDP output, successful local sending provides no receiver acknowledgement: show local progress with remote receipt unknown, and recover only on observable local errors/stalls.

## 5. Update the existing UI

Replace the `running ? "Streaming now"` badge with the path state. Show separate input/local-output progress, evidence freshness, failure reason, retry count/countdown, and last recovery time. Label “Healthy — local media progressing”; receiver receipt remains a separate field with its evidence source.

Add bounded status polling to the existing TanStack Query, and display stale/unavailable status when polling fails. Keep Stop enabled while connecting or retrying. Show which applied configuration is running and when saved settings are pending an explicit Restart. Add an advanced recovery section with units, validated limits, and protocol defaults; normal operation should not require operators to tune it.

## 6. Test failures, deployment, and activation

Use deterministic clock/process tests for the state machine and real FFmpeg transport tests on Ubuntu. Fake-process tests alone cannot establish that media resumes.

| Scenario | Required result |
| --- | --- |
| Input disconnected; then restored | Automatic retry and resumed media without a manual command |
| Input connection open but no media | Stall detected despite socket/process liveness |
| SRT output disconnected or unreachable | Bounded attempt/cleanup/retry; recovers when receiver returns |
| Connected SRT receiver stops accepting media | Stalled media/backpressure detected even while control traffic remains possible; resumes after restoration |
| Both sides stop / root cause ambiguous | Controlled recovery, honest reason, no guessed diagnosis |
| Persistent failure / rapidly flapping link | Capped retries, stability window, bounded logs/resources, at most one child |
| Quiet/digitally silent audio, with and without black video | Healthy while audio samples and output media progress |
| Source audio stalls while generated video continues | Required-audio failure; video alone cannot keep the path healthy |
| Hung child / blocked telemetry pipe / supervisor crash | Bounded cleanup where OS permits, no duplicate child, stale health rejected |
| Stop during startup, teardown, or backoff | No later relaunch; remains stopped after backend/helper restart |
| Saved config edited before failure | Recovery keeps the applied route, codec, latency and signalling; deliberate Restart applies the edits |
| Finite file EOF | Completes without an unintended replay loop |
| Second sender remains healthy | Unaffected PID, media continuity and configuration throughout first-path recovery |
| UDP receiver unavailable | No false claim of remote receipt; local evidence accurately reported |

Measure the actual no-progress detection and recovery times. A post-restoration upper bound should include observation delay, any remaining per-attempt deadline, bounded child cleanup, the capped retry delay, and successful reconnect/startup time under the fixture's conditions. Assert resumption at the test receiver using advancing media timestamps/audio packets, and compare before/after stream parameters and MPEG-TS signalling. Do not claim the incident's unproven trigger has been reproduced simply because a generic failure test passes.

Extend backend service/helper/API tests; add supervisor and telemetry tests; add frontend state/action/polling tests; and run the installer/update regression suites. Existing checks include backend `uv run pytest`, frontend `pnpm test`, `pnpm lint`, `pnpm build`, and the ops unittest files.

Install/update the manifest format, supervisor entry point, permissions, and service unit together. Test fresh install, repeat install, upgrade with a live sender, explicit activation, and rollback on the Ubuntu baseline. A control-plane-only update must not interrupt a live stream to activate recovery. Clearly show when activation awaits the next deliberate Start/Restart; if the supervisor depends on code in the mutable checkout, prove updates do not change an in-flight run, or install a versioned runtime entry point.

## Suggested delivery sequence

1. **Telemetry proof and failure harness:** pass the signal gate and fix the supported measurement contract.
2. **Runtime and supervisor:** applied snapshots, policy/migrations, deadlines, process ownership, retries, and stop semantics.
3. **Status and operator controls:** helper/API integration, diagnostic history, UI polling and recovery settings.
4. **Release validation:** real transport fault matrix, second-instance isolation, installation/upgrade/rollback, and operator documentation.

Do not mark the issue complete until all four issue failure classes have real media-resumption evidence, intentional Stop survives recovery races, normal silence stays healthy, and the UI no longer derives media health from process activity alone.
