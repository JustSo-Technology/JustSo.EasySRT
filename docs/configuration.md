# Configure EasySRT

[Documentation home](../README.md) · [Installation](installation.md) · [Configuration transfer](configuration-transfer.md)

## First stream checklist

1. Install on Ubuntu and open the printed management URL from your trusted network. Create the first owner account. There is no documented factory username/password; first-run setup creates the owner.
2. Obtain an audio source URL and the receiver's protocol, hostname/IP, port and required media format. For SRT output the receiver must accept a caller connection. Confirm routing/firewall/NAT permissions and receiver readiness with its operator.
3. Open **Config**. Enter the input, destination and stream profile described below. Name the configuration so another operator can identify the route.
4. Click **Save Site Config** and confirm any intentional overwrite. Saving regenerates the active configuration/runtime files. **Load Saved Config** also applies a preset to runtime files; it is not merely a preview.
5. Check diagnostics/preflight. Resolve failures before starting. **Control → Start** launches the sender; **Stop** stops it; **Restart** interrupts and relaunches it. Start/restart is blocked when preflight fails.
6. Confirm audio and receiver lock at the destination, not just a running sender process. Check the intended source, channels, codec, levels and stability.

Saving/loading configuration does not by itself restart an already-running FFmpeg process. Schedule a deliberate restart to apply changed runtime settings to a live sender. Coordinate this interruption with the receiving operator. This is distinct from importing presets, which does not activate them at all.

## Automatic path recovery

The sender supervisor checks source-audio samples and local output media separately. **Healthy** means these local counters are advancing; confirm receiver lock and audio separately. A live process, generated black video, or SRT keepalives alone cannot establish source-audio health. Silent audio with advancing samples is valid media.

The Control tab shows connecting, healthy, degraded, retrying, stopped, or unknown, with the current reason, progress age, retry timing and recent recovery history. Unknown/stale evidence is never shown as healthy. Stop cancels retries, including during startup or a prolonged outage. A successful finite file completes without replaying automatically.

Recovery restarts only this instance's FFmpeg child. It retains the **applied** source, destination, encoding and transport settings even when someone has since saved another configuration. The dashboard shows the applied route and indicates saved settings waiting for a deliberate Restart. Recovery continues with the browser closed and through backend/helper restarts. Journal events record failure, retry and recovery timestamps without source credentials.

When both media counters stop, the UI reports an unconfirmed media stall: output backpressure can also stop source processing, so the cause cannot always be assigned to one side. Local UDP output provides no receiver acknowledgement. SRT transport acceptance also does not prove receiver playback.

Recovery deadlines are host settings in `/etc/justso-easysrt/easysrt.env`. These defaults work without per-preset changes:

| Environment variable | Default | Valid range (seconds) |
| --- | --- | --- |
| `EASYSRT_RECOVERY__STARTUP_SECONDS` | 30 | 5–300 |
| `EASYSRT_RECOVERY__INPUT_STALL_SECONDS` | 15 | 3–300 |
| `EASYSRT_RECOVERY__OUTPUT_STALL_SECONDS` | 15 | 3–300 |
| `EASYSRT_RECOVERY__IO_TIMEOUT_SECONDS` | 10 | 1–120 |
| `EASYSRT_RECOVERY__RETRY_INITIAL_SECONDS` | 2 | 1–30 |
| `EASYSRT_RECOVERY__RETRY_MAX_SECONDS` | 30 | 1–300 |
| `EASYSRT_RECOVERY__STABLE_SECONDS` | 30 | 5–300 |

The initial retry delay must not exceed the maximum, and I/O timeout must not exceed startup timeout. SRT latency must be shorter than startup, output-stall and I/O deadlines. Set deadlines above the source cadence and intended buffering. FFmpeg's buffered media can continue progressing briefly after a network failure; stall deadlines measure time since the last observed media progress.

Retries use exponential backoff with jitter between 80% and 100% of the selected delay, never exceeding the maximum. Backoff resets after sustained media progress. A stuck child receives escalating termination signals before a replacement can start. If the OS cannot reap it, the supervisor reports cleanup failure and waits without launching duplicates.

After editing host policy, restart the backend to regenerate the candidate runtime, then deliberately Restart the sender when ready to apply it. Preset import/export remains compatible because host recovery policy is not part of portable presets. Read [the validation report](validation/issue-14-recovery.md) for the tested transports and evidence limits.

### Upgrading an existing live sender

An update installs the supervisor and service unit but leaves the live sender alone. Until its next explicit Start/Restart, a legacy sender reports media health unavailable. Start/Restart through the WebUI pins `applied_sender.json` and activates recovery. Direct `systemctl stop` is respected; use the WebUI Start/Restart to apply new saved settings. A direct systemd crash restart reuses the applied snapshot.

Systemd separately restarts a crashed supervisor, with a five-crash limit in sixty seconds. If the supervisor itself keeps crashing, inspect the sender journal and correct the runtime before using Start again. This crash limit does not cap the supervisor's ongoing media reconnect attempts.

## Input

Give the source a recognisable name and a URL the **Ubuntu VM** can reach. For example, `https://audio.example.com/live` (replace with your actual source). Supported URL schemes in the configuration model are HTTP, HTTPS, UDP, RTP, RTSP, RTMP, SRT and file. Actual decoding depends on the installed FFmpeg build and source format.

`file:///srv/audio/example.wav` refers to a file on the VM, readable by `easysrt`; it is not an upload from your browser. File playback is not automatically looped by the generated command. Device/microphone capture is not a documented source mode. URLs may include credentials: keep exports and diagnostics containing configuration private.

## Destination

| Field | Meaning |
| --- | --- |
| Name | Operator-friendly receiver/path name |
| Protocol | `srt` or `udp` |
| Host | Receiver DNS hostname or IP address, without a URL path |
| Port | Receiver port, 1–65535; use the receiver's actual port, not a default by assumption |

SRT output is generated with `mode=caller`. Configure the receiving side accordingly; EasySRT does not provide a general SRT listener/rendezvous destination selector. The current destination model has no SRT encryption/passphrase/stream-ID fields. Pasting query parameters into a destination URL does not configure those options: the endpoint parser extracts protocol, host and port. Do not assume encrypted output from a URL containing a passphrase.

SRT and UDP media traffic are separate from the TCP WebUI ports. Permit traffic to the configured receiver port; opening port 5173 alone does not establish a media path.

## Stream profile and units

The current generated audio is **MP2 inside MPEG-TS**, not an arbitrary codec/container selector. Agree settings with the receiver.

| Setting | Meaning / current model default |
| --- | --- |
| Audio bitrate | kbps; default 256 |
| Sample rate | Hz; supported values 32000, 44100 or 48000; default 48000 |
| Channels | 1 mono or 2 stereo; default 2 |
| SRT latency | milliseconds; default 120; current code converts 120 ms to FFmpeg `latency=120000` |
| Mux rate | kbps; default 600; must exceed the sum of enabled audio and video bitrates, with space for transport overhead |
| PCR period | milliseconds; default 20 |
| Video | Disabled by default; supported generated source is black test frames |
| Video encoding | `mpeg2video` or `libx264`; defaults: 1000 kbps, 1280x720, 25 fps |

These are model defaults, not a recommendation for every network or receiver. Increase latency according to measured network behavior and receiver requirements. When enabling video, select black test frames and increase mux rate above the combined audio/video rate; the audio-only 600 kbps default is insufficient for the default 1000 kbps video stream. This feature generates black video with source audio; it is not general source-video passthrough.

## Presets and importing older installations

Named configurations hold the input, destination and profile together. Saved inputs/destinations are reusable entries. Review the selected route after loading a preset, and restart deliberately if you intend to change a running sender.

Owners/engineers can use **Config → Import and export configurations**. Import validates and saves entries without activating a preset, writing runtime files or starting the sender. Review Add/Skip/Replace decisions and then deliberately load the chosen configuration. Older SRT presets require an explicit reviewed latency because earlier versions confused milliseconds and microseconds. Follow the [complete transfer guide](configuration-transfer.md).

An exported preset file is not a complete backup of users, sessions, environment secrets, database state or system services. Back up installations separately before maintenance.

## Host settings versus stream settings

Use the WebUI for stream configuration. Host/network settings live in `/etc/justso-easysrt/easysrt.env`: public origin, bind addresses, ports, trusted hosts, secure cookies and update settings. Keep this file root-owned with restricted service-account access. After an intentional host-setting change, restart the relevant control-plane services in a maintenance window; changing a file alone does not reconfigure running processes. Follow [deployment security](deployment-security.md), especially for HTTPS and the separate updater origin.

The app checkout is `/opt/justso-easysrt`; persisted data/runtime files are under its `backend/data/`. Privileged helper/updater scripts are under `/usr/local/lib/justso-easysrt`, and their update-source policy is `/etc/justso-easysrt/update-policy.json`. Do not edit generated `sender.env` or `runtime_config.json` as the normal configuration interface; subsequent saves regenerate them.

Partner pairing/authority and takeover are separate from configuring one sender. Validate both nodes and receiver behavior in an isolated rehearsal before relying on redundancy; this first-stream guide is not a failover acceptance procedure.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Browser cannot reach UI | Printed frontend port, VM address, binding choice, management firewall; localhost-only needs a tunnel/proxy |
| Login fails after proxy changes | Public origin, trusted hosts, HTTPS/cookie settings and proxy headers |
| Start unavailable or fails | Preflight output, input reachability from the VM, FFmpeg availability and runtime generation |
| Sender running but no audio received | Receiver mode/port, routing/firewall, media codec/container, source audio and receiver logs |
| Old route still on air | Configuration may be saved but running FFmpeg needs a deliberate restart |
| Imported presets seem inactive | Expected: explicitly load a reviewed imported preset before starting/restarting |
| Update refused | Owner access, GitHub connectivity, root-managed approved ref, separate updater origin and service health |

On the Ubuntu VM, collect service evidence without changing state:

```bash
sudo systemctl status justso-easysrt-helper justso-easysrt-backend justso-easysrt-frontend justso-easysrt-updater easysrt-sender --no-pager
sudo journalctl -u easysrt-sender -n 100 --no-pager
sudo journalctl -u justso-easysrt-backend -n 100 --no-pager
ffmpeg -protocols
```

Check for SRT support in FFmpeg's protocol listing. Redact source credentials, tokens and private endpoints before sharing evidence. For assistance contact EasySRT@JustSo.tech; report vulnerabilities through [SECURITY.md](../SECURITY.md).
