#!/usr/bin/env python3
"""Unprivileged, dependency-free sender runtime. Systemd owns its lifecycle.

This file is installed atomically outside the mutable application checkout.
No backend import, HTTP request, or browser is needed for media recovery.
"""
from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import fcntl
import json
import math
import os
from pathlib import Path
import random
import re
import selectors
import signal
import subprocess
import tempfile
import threading
import time
import uuid


POLICY_BOUNDS = {
    "startup_seconds": (5, 300), "input_stall_seconds": (3, 300),
    "output_stall_seconds": (3, 300), "io_timeout_seconds": (1, 120),
    "retry_initial_seconds": (1, 30), "retry_max_seconds": (1, 300),
    "stable_seconds": (5, 300),
}


def timestamp(value=None):
    return datetime.fromtimestamp(time.time() if value is None else value, timezone.utc).isoformat()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=path.parent, prefix=".sender-", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(value, handle, allow_nan=False)
            handle.write("\n")
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def load_runtime(path):
    raw = Path(path).read_bytes()
    if len(raw) > 65536:
        raise ValueError("Runtime manifest exceeds 64 KiB")
    runtime = json.loads(raw)
    args = runtime.get("ffmpeg_args")
    if runtime.get("schema_version") != 1 or not isinstance(args, list) or not 2 <= len(args) <= 256:
        raise ValueError("Unsupported runtime manifest; save configuration and start again")
    if any(not isinstance(arg, str) or "\x00" in arg for arg in args):
        raise ValueError("Invalid FFmpeg arguments")
    policy = runtime.get("recovery", {})
    for key, (minimum, maximum) in POLICY_BOUNDS.items():
        value = policy.get(key)
        if type(value) not in {float, int} or not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError("Invalid recovery policy")
    if policy["retry_initial_seconds"] > policy["retry_max_seconds"] or policy["io_timeout_seconds"] > policy["startup_seconds"]:
        raise ValueError("Inconsistent recovery policy")
    if runtime.get("input_scheme") not in {"http", "https", "udp", "rtp", "rtsp", "rtmp", "srt", "file"}:
        raise ValueError("Invalid input scheme")
    return runtime


class Counter:
    def __init__(self):
        self.value = 0
        self.at = None
        self.utc = None

    def observe(self, value, now):
        if value > self.value:
            self.value, self.at, self.utc = value, now, timestamp()

    def stale(self, now, deadline):
        return self.at is None or now - self.at >= deadline

    def snapshot(self, now):
        return {"value": self.value, "last_progress_at": self.utc,
                "age_seconds": round(now - self.at, 3) if self.at is not None else None}


def stall_reason(source, output, now, started, policy):
    if source.at is None or output.at is None:
        return "startup_timeout" if now - started >= policy["startup_seconds"] else None
    input_stale = source.stale(now, policy["input_stall_seconds"])
    output_stale = output.stale(now, policy["output_stall_seconds"])
    if input_stale and output_stale:
        return "media_stalled"
    if input_stale:
        return "input_stalled"
    if output_stale:
        return "output_stalled"
    return None


def retry_delay(failures, policy, jitter=random.uniform):
    base = min(policy["retry_max_seconds"], policy["retry_initial_seconds"] * 2 ** min(failures, 16))
    # Jitter stays within the configured maximum, including at the cap.
    return jitter(base * .8, base)


REASONS = {
    "starting": "Waiting for source audio and local output media.",
    "media_progress": "Source audio and local output media are progressing; remote receipt is unverified.",
    "startup_timeout": "Required media did not start within the startup deadline.",
    "input_stalled": "Source audio samples stopped progressing.",
    "output_stalled": "Local output media stopped progressing.",
    "media_stalled": "Source audio and output stopped progressing; the failing side is unconfirmed.",
    "input_error": "FFmpeg reported an input/demux error.",
    "output_error": "FFmpeg reported an output/mux error.",
    "process_exited": "FFmpeg exited before the live stream was stopped.",
    "launch_failed": "FFmpeg could not be launched; check the installed binary and runtime configuration.",
    "cleanup_failed": "The old sender has not exited after termination; no replacement will be launched yet.",
    "operator_stop": "Sender stopped; automatic retries are cancelled.",
    "file_complete": "File playback completed; automatic replay is disabled.",
    "runtime_invalid": "Runtime manifest is unavailable or invalid; save configuration and start again.",
}


class Supervisor:
    def __init__(self, runtime, status_path):
        self.runtime = runtime
        self.policy = runtime["recovery"]
        self.status_path = Path(status_path)
        self.stop_event = threading.Event()
        self.child = None
        self.source, self.output = Counter(), Counter()
        self.events = deque(maxlen=20)
        self.stderr = deque(maxlen=8)
        self.status = {
            "schema_version": 1, "path_id": "default", "run_id": uuid.uuid4().hex,
            "supervisor_pid": os.getpid(), "invocation_id": os.environ.get("INVOCATION_ID", ""),
            "config_id": runtime["config_id"], "summary": runtime.get("summary", {}),
            "policy": self.policy, "state": "connecting", "reason": "starting",
            "attempt": 0, "retry_count": 0, "next_retry_at": None,
            "last_failure_at": None, "last_recovery_at": None, "last_exit_code": None,
            "remote_receipt": "unverified", "desired_running": True,
        }
        self.last_publish = 0

    def publish(self):
        now = time.monotonic()
        self.status.update(heartbeat_at=timestamp(), heartbeat_monotonic=now,
                           input=self.source.snapshot(now), output=self.output.snapshot(now),
                           child_pid=self.child.pid if self.child and self.child.poll() is None else None,
                           events=list(self.events), stderr_tail=list(self.stderr),
                           detail=REASONS.get(self.status["reason"], REASONS["process_exited"]))
        atomic_json(self.status_path, self.status)
        self.last_publish = now

    def transition(self, state, reason):
        self.status.update(state=state, reason=reason)
        event = {"at": timestamp(), "state": state, "reason": reason, "attempt": self.status["attempt"],
                 "run_id": self.status["run_id"], "child_pid": self.child.pid if self.child else None,
                 "error_context": list(self.stderr),
                 "retry_count": self.status["retry_count"], "next_retry_at": self.status["next_retry_at"],
                 "exit_code": self.status["last_exit_code"], "config_id": self.status["config_id"]}
        self.events.append(event)
        print(json.dumps({"event": "sender_transition", "path_id": "default", **event}), flush=True)
        self.publish()

    def stop_child(self):
        child = self.child
        if child is None:
            return
        for sig, timeout in [(signal.SIGINT, 3), (signal.SIGTERM, 3), (signal.SIGKILL, 2)]:
            if child.poll() is not None:
                break
            try:
                os.killpg(child.pid, sig)
            except ProcessLookupError:
                pass
            try:
                child.wait(timeout)
            except subprocess.TimeoutExpired:
                continue
        if child.poll() is None:
            self.transition("degraded", "cleanup_failed")
            while child.poll() is None and not self.stop_event.wait(.25):
                if time.monotonic() - self.last_publish >= 1:
                    self.publish()
        if child.poll() is not None:
            self.status["last_exit_code"] = child.returncode
        for stream in (child.stdout, child.stderr):
            if stream:
                stream.close()

    def observe_line(self, kind, line, now):
        if kind == "input":
            fields = line.split()
            if len(fields) == 3 and fields[1].isdigit():
                self.source.observe(int(fields[1]), now)
        elif kind == "output" and line.startswith(b"total_size="):
            value = line.split(b"=", 1)[1]
            if value.isdigit():
                self.output.observe(int(value), now)
        elif kind == "error":
            # Never persist source URLs, credentials, protocol query options, or
            # arbitrary FFmpeg stderr. Recognised context is enough for recovery.
            message = line.decode(errors="replace")
            if "Error during demuxing" in message or "Error retrieving a packet from demuxer" in message:
                self.stderr.append(REASONS["input_error"])
            elif "Error muxing a packet" in message or "Error writing trailer" in message:
                self.stderr.append(REASONS["output_error"])
            else:
                http_error = re.search(r"(?:HTTP error|Server returned)\s+([1-5][0-9]{2})\b", message)
                if http_error:
                    self.stderr.append(REASONS["input_error"])
                    self.stderr.append(f"Input server returned HTTP {http_error.group(1)}.")
                elif "Unrecognized option" in message and "stats_enc_pre" in message:
                    self.stderr.append("Installed FFmpeg lacks the required audio telemetry option.")
                elif "Unknown encoder" in message or "Encoder not found" in message:
                    self.stderr.append("The configured FFmpeg encoder is unavailable.")
                elif "Connection refused" in message:
                    self.stderr.append("A network connection was refused; the endpoint is unconfirmed.")
                elif "Connection timed out" in message:
                    self.stderr.append("A network operation timed out; the endpoint is unconfirmed.")

    def attempt(self):
        self.source, self.output = Counter(), Counter()
        self.stderr.clear()
        self.status["attempt"] += 1
        self.status["next_retry_at"] = None
        self.transition("connecting", "starting")
        read_fd, write_fd = os.pipe()
        selector = selectors.DefaultSelector()
        stable_at = None
        started = time.monotonic()
        try:
            args = self.runtime["ffmpeg_args"]
            command = [args[0], "-nostdin", "-nostats", "-stats_period", "1", "-progress", "pipe:1",
                       *args[1:-1], "-stats_enc_pre:a", f"/dev/fd/{write_fd}",
                       "-stats_enc_pre_fmt:a", "{ni} {sn} {ti}", args[-1]]
            if self.stop_event.is_set():
                return "operator_stop", False
            try:
                self.child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                              stderr=subprocess.PIPE, pass_fds=(write_fd,), start_new_session=True)
            except OSError:
                return "launch_failed", False
            finally:
                os.close(write_fd)
                write_fd = None
            buffers = {}
            for fd, kind in [(read_fd, "input"), (self.child.stdout.fileno(), "output"), (self.child.stderr.fileno(), "error")]:
                os.set_blocking(fd, False)
                selector.register(fd, selectors.EVENT_READ, kind)
                buffers[fd] = b""
            while not self.stop_event.is_set():
                for key, _ in selector.select(.25):
                    chunk = os.read(key.fd, 65536)
                    if not chunk:
                        selector.unregister(key.fd)
                        continue
                    lines = (buffers[key.fd] + chunk).split(b"\n")
                    buffers[key.fd] = lines.pop()[-65536:]
                    for line in lines:
                        self.observe_line(key.data, line, time.monotonic())
                now = time.monotonic()
                if self.child.poll() is not None:
                    self.status["last_exit_code"] = self.child.returncode
                    if self.runtime["input_scheme"] == "file" and self.child.returncode == 0:
                        return "file_complete", False
                    reason = "output_error" if REASONS["output_error"] in self.stderr else (
                        "input_error" if REASONS["input_error"] in self.stderr else "process_exited")
                    return reason, self.sustained_progress(stable_at)
                reason = stall_reason(self.source, self.output, now, started, self.policy)
                if reason:
                    return reason, self.sustained_progress(stable_at)
                if self.source.at is not None and self.output.at is not None and self.status["state"] != "healthy":
                    stable_at = now
                    if self.status["last_failure_at"]:
                        self.status["last_recovery_at"] = timestamp()
                    self.transition("healthy", "media_progress")
                if now - self.last_publish >= 1:
                    self.publish()
            return "operator_stop", False
        finally:
            selector.close()
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)

    def sustained_progress(self, stable_at):
        if stable_at is None or self.source.at is None or self.output.at is None:
            return False
        return min(self.source.at, self.output.at) - stable_at >= self.policy["stable_seconds"]

    def run(self):
        failures = 0
        try:
            while not self.stop_event.is_set():
                reason, stable = self.attempt()
                if reason in {"operator_stop", "file_complete"} or self.stop_event.is_set():
                    self.stop_child()
                    self.status.update(desired_running=False, next_retry_at=None)
                    self.transition("stopped", "operator_stop" if self.stop_event.is_set() else reason)
                    return 0
                self.status["last_failure_at"] = timestamp()
                self.transition("degraded", reason)
                self.stop_child()
                if self.stop_event.is_set():
                    break
                if stable:
                    failures = 0
                delay = retry_delay(failures, self.policy)
                failures += 1
                self.status["retry_count"] += 1
                self.status["next_retry_at"] = timestamp(time.time() + delay)
                self.transition("retrying", reason)
                deadline = time.monotonic() + delay
                while not self.stop_event.wait(min(1, max(0, deadline - time.monotonic()))):
                    if time.monotonic() >= deadline:
                        break
                    self.publish()
            self.status.update(desired_running=False, next_retry_at=None)
            self.transition("stopped", "operator_stop")
            return 0
        finally:
            self.stop_event.set()
            self.stop_child()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--status", type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    args.status.parent.mkdir(parents=True, exist_ok=True)
    with args.status.with_suffix(".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('{"event":"sender_already_supervised"}', flush=True)
            return 1
        try:
            runtime = load_runtime(args.runtime)
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            print('{"event":"runtime_invalid"}', flush=True)
            return 1
        supervisor = Supervisor(runtime, args.status)
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda *_: supervisor.stop_event.set())
        return supervisor.run()


if __name__ == "__main__":
    raise SystemExit(main())
