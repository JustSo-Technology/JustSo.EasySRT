# Stream recovery validation — issue #14

Date: 24 October 2026 (Australia/Sydney).

Issue: [Recover stream paths gracefully when input or output is lost](https://github.com/JustSo-Technology/JustSo.EasySRT/issues/14).

Environment: disposable Ubuntu 24.04.4 LTS, x86-64, Ubuntu FFmpeg `6.1.1-3ubuntu5` with libsrt `1.5.3-1build2`. All media sockets used loopback. Production senders were not changed.

## Telemetry decision

The independent media-signal gate passed before recovery implementation began. Eight baseline cases covered input disconnect, connected-but-idle input, output disconnect, and connected-output backpressure, with audio-only and generated-black-video output. The final repeat additionally decoded received MP2 to PCM. The complete observations are in [the telemetry evidence](issue-14-telemetry-ubuntu24.json).

The selected interfaces are:

| Signal | Measurement | Evidence limit |
| --- | --- | --- |
| Source audio | `-stats_enc_pre:a`, explicitly formatted audio sample count `sn` | Samples processed from the mapped source, not a direct socket-read counter; upstream buffering/backpressure affects timing |
| Local output | `-progress` numeric `total_size` advances, with `-flush_packets 1` | Media submitted through the local output, including transport buffering; not proof of remote receipt or playback |
| Process | Child exit/status | Supplementary; a live child never establishes media health |
| Receiver in tests | Independent FFmpeg receiver decodes MP2 into PCM bytes | Proves media restoration in the fixture; the deployed UI has no receiver-playback signal |

In the black-video/input-disconnect case, the process remained alive and output grew from approximately 0.5 MB to 7.8 MB while source audio stopped. The audio counter correctly failed the health condition. Under output backpressure, both counters eventually stopped while the process remained alive; the supervisor must not guess which side failed from those two stopped counters alone.

Counter changes, not progress-record arrival, reset deadlines. `progress=continue`, repeated sizes, `N/A`, generated video frames, and transport keepalives cannot refresh source-audio health. Audio sample values/levels are never used, so digital silence remains healthy. The stock interfaces passed this bounded local-progress contract; a custom libavformat build was unnecessary.

SRT output uses bounded sender buffering and disables too-late packet dropping so sustained backpressure can surface as a blocked/failed write. This is a deliberate recovery transport choice and should be included in receiver/latency rehearsals. Receive-side playback and UDP delivery cannot be verified from local counters.

## End-to-end recovery

[Production-command recovery evidence](issue-14-recovery-ubuntu24.json) contains fourteen passing cases:

- Ten fault cases: the four issue failure types plus a `SIGSTOP`-hung FFmpeg child, each with and without generated black video.
- Intentional Stop during retry/backoff.
- Finite file completion with black video, without automatic replay.
- Persistent failure with controlled, capped retries.
- An independent second sender remained healthy throughout the matrix, with the same child PID and no retries.

Every restored fault case resumed decoded audio at the receiver and retained the applied configuration identifier and route summary. The applied manifest and candidate are separate files. Unit tests also verify that saving a new candidate does not modify the applied manifest.

The matrix used accelerated deadlines (startup 15 seconds; input/output stalls 3 seconds; I/O timeout 2 seconds; retry delay 1–2 seconds). Observed network-failure detection ranged from about 0.4 to 7.1 seconds, reflecting FFmpeg buffering and transport behavior; decoded audio returned about 7.0–7.2 seconds after restoring the fixture. Hung-child cleanup took longer because termination was escalated before replacement. These are fixture measurements, not network-wide recovery guarantees.

The initial full matrix's restore measurement includes the fixture's final graceful Stop overhead. The shipping-default follow-up measures decoded-audio restoration before that final Stop; the reproduction harness now uses that measurement order for every case.

[Shipping-default evidence](issue-14-defaults-ubuntu24.json) separately covers connected-but-idle input with and without black video: roughly 15 seconds to detect failure and roughly 8 seconds to decoded audio after fixture restoration, using the shipped 30-second startup, 15-second stall and 10-second I/O settings.

## Service lifecycle and control boundary

[Systemd/helper evidence](issue-14-service-ubuntu24.json) records five passing scenarios against uniquely named test units and a root-owned helper/script installation under `/run`:

1. Stop cancels recovery even when the candidate is missing and preflight fails.
2. Killing the supervisor triggers a systemd restart, cleans the old process group and retains the applied route despite saved edits.
3. Restarting the helper leaves the live sender PID unchanged.
4. Direct `systemctl stop` remains stopped through helper restart and the backend's startup migration hook.
5. Stop during startup does not relaunch the path.

The same fixture verifies that duplicate Start is rejected, backend health matches the actual systemd MainPID/InvocationID, and saved configuration appears as pending while the applied route remains in use. Its units and root-owned files are removed in `finally`.

## Regression and reproduction

Backend tests cover stale/foreign process snapshots, malformed policies, monotonic stall decisions, bounded backoff, source-secret redaction, candidate migration and old portable-preset compatibility. Frontend tests cover active-without-media evidence, retry Stop availability, applied routing, and withdrawal of healthy status on polling errors/staleness. Ops tests cover packaging the supervisor and accepting a pre-supervisor rollback asset set while rejecting a new unit missing its supervisor.

On an isolated Ubuntu 24.04 host with FFmpeg and the locked backend environment:

```bash
python3 ops/validate-telemetry.py --report /tmp/easysrt-telemetry.json
uv run --project backend python ops/validate-recovery.py --report /tmp/easysrt-recovery.json
uv run --project backend python ops/validate-recovery.py --defaults --fault input_stall --report /tmp/easysrt-defaults.json
uv run --project backend python ops/validate-service-recovery.py --report /tmp/easysrt-service.json
```

The final command requires passwordless sudo and creates isolated, temporary systemd units. The GitHub Actions media-recovery job runs the telemetry, full fault matrix, and service-control harness on Ubuntu 24.04.

Real fault tests here use HTTP MPEG-TS input, SRT output, and generated MPEG-2 black video; finite-file input is also tested. Other accepted input transports and different receiver implementations need deployment-specific media acceptance. No OS reboot, production deployment, or complete fresh-install/update/rollback VM certification is claimed by these fixtures. Installer/updater regressions and isolated asset-copy tests cover this change's deployment paths.

The original incident's trigger remains unproven. These controlled faults establish recovery behavior without claiming to reproduce its exact cause.
