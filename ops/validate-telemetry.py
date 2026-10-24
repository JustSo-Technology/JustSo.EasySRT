#!/usr/bin/env python3
"""Real FFmpeg telemetry proof; all sockets bind to loopback, no service changes.

Run on Ubuntu 24.04: python3 ops/validate-telemetry.py --report /tmp/telemetry.json
The receiver can stop draining media while its SRT library remains running.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import selectors
import signal
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def stop(process):
    if process.poll() is None:
        process.send_signal(signal.SIGINT)
        try:
            process.wait(3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(3)


class Source:
    def __init__(self, media):
        self.mode = "flow"
        self.sent = 0
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "video/mp2t")
                self.end_headers()
                offset = 0
                try:
                    while offset < len(media):
                        if owner.mode == "disconnect":
                            return
                        if owner.mode == "stall":
                            time.sleep(.02)
                            continue
                        chunk = media[offset:offset + 1316]
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        owner.sent += len(chunk)
                        offset += len(chunk)
                        time.sleep(1316 / 75000)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/silent.ts"

    def close(self):
        self.mode = "disconnect"
        self.server.shutdown()
        self.server.server_close()


class Receiver:
    def __init__(self, port=None):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.bind(("127.0.0.1", port or 0))
            self.port = sock.getsockname()[1]
        self.flow = True
        self.bytes = 0
        self.process = subprocess.Popen([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-probesize", "32768", "-analyzeduration", "500000", "-i",
            f"srt://127.0.0.1:{self.port}?mode=listener&latency=120000&rcvbuf=65536&ffs=65536&tlpktdrop=0",
            "-map", "0:a:0", "-c:a", "pcm_s16le", "-flush_packets", "1", "-f", "s16le", "pipe:1",
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        def drain():
            while self.process.poll() is None:
                if not self.flow:
                    time.sleep(.02)
                    continue
                chunk = os.read(self.process.stdout.fileno(), 1316)
                if not chunk:
                    return
                self.bytes += len(chunk)

        threading.Thread(target=drain, daemon=True).start()
        time.sleep(.3)

    def close(self):
        self.flow = True
        stop(self.process)


class Observation:
    def __init__(self, source, receiver, video):
        read_fd, write_fd = os.pipe()
        args = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin", "-nostats",
                "-stats_period", "0.2", "-progress", "pipe:1", "-re", "-probesize", "32768",
                "-analyzeduration", "500000", "-i", source.url]
        if video:
            args += ["-f", "lavfi", "-i", "color=c=black:s=320x240:r=25",
                     "-map", "0:a:0", "-map", "1:v:0", "-c:v", "mpeg2video", "-b:v", "100k"]
        else:
            args += ["-map", "0:a:0", "-vn"]
        args += ["-c:a", "mp2", "-b:a", "256k", "-ar", "48000", "-ac", "2",
                 "-stats_enc_pre:a", f"/dev/fd/{write_fd}", "-stats_enc_pre_fmt:a", "{ni} {sn} {ti}",
                 "-f", "mpegts", "-muxrate", "600k", "-flush_packets", "1",
                 f"srt://127.0.0.1:{receiver.port}?mode=caller&latency=120000&sndbuf=65536&ffs=65536&tlpktdrop=0"]
        self.process = subprocess.Popen(args, pass_fds=(write_fd,), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        os.close(write_fd)
        self.input = 0
        self.output = 0
        self.input_at = 0
        self.output_at = 0
        self.records = 0
        self.errors = []
        self.selector = selectors.DefaultSelector()
        self.buffers = {}
        for fd, kind in [(read_fd, "input"), (self.process.stdout.fileno(), "output"), (self.process.stderr.fileno(), "error")]:
            os.set_blocking(fd, False)
            self.selector.register(fd, selectors.EVENT_READ, kind)
            self.buffers[fd] = b""
        self.read_fd = read_fd

    def sample(self, seconds, receiver, source):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            for key, _ in self.selector.select(.05):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    self.selector.unregister(key.fd)
                    continue
                lines = (self.buffers[key.fd] + chunk).split(b"\n")
                self.buffers[key.fd] = lines.pop()
                for line in lines:
                    now = time.monotonic()
                    if key.data == "input":
                        values = line.split()
                        if len(values) == 3:
                            count = int(values[1])
                            if count > self.input:
                                self.input, self.input_at = count, now
                    elif key.data == "output" and line.startswith(b"total_size="):
                        value = line.split(b"=", 1)[1]
                        if value.isdigit() and int(value) > self.output:
                            self.output, self.output_at = int(value), now
                            self.records += 1
                    elif key.data == "error":
                        self.errors = (self.errors + [line.decode(errors="replace")])[-8:]
        now = time.monotonic()
        return {"input_samples": self.input, "output_bytes": self.output,
                "input_age": round(now - self.input_at, 3), "output_age": round(now - self.output_at, 3),
                "receiver_bytes": receiver.bytes, "source_bytes": source.sent,
                "process_alive": self.process.poll() is None, "progress_records": self.records,
                "errors": self.errors}

    def close(self):
        stop(self.process)
        self.selector.close()
        os.close(self.read_fd)


def run_case(media, video, fault):
    source = Source(media)
    receiver = Receiver()
    observation = None
    try:
        observation = Observation(source, receiver, video)
        healthy = observation.sample(7, receiver, source)
        if fault.startswith("input"):
            source.mode = "stall" if fault == "input_stall" else "disconnect"
        elif fault == "output_stall":
            receiver.flow = False
        else:
            receiver.close()
        failed = observation.sample(12, receiver, source)
        good = healthy["input_samples"] > 0 and healthy["output_bytes"] > 0 and healthy["receiver_bytes"] > 0
        relevant_age = failed["input_age"] if fault.startswith("input") else failed["output_age"]
        detected = not failed["process_alive"] or relevant_age > 3
        result = {"video": video, "fault": fault, "healthy": healthy, "failed": failed,
                  "passed": good and detected}
        print(json.dumps(result), flush=True)
        return result
    finally:
        if observation:
            observation.close()
        receiver.close()
        source.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--fault", choices=["input_stall", "input_disconnect", "output_stall", "output_disconnect"])
    parser.add_argument("--video", action="store_true", help="Only test the video configuration")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="easysrt-telemetry-") as directory:
        media_path = Path(directory, "silence.ts")
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                        "anullsrc=r=48000:cl=stereo", "-t", "120", "-c:a", "mp2", "-b:a", "256k",
                        "-f", "mpegts", "-muxrate", "600k", str(media_path)], check=True)
        media = media_path.read_bytes()
        cases = [run_case(media, video, fault) for video in ([True] if args.video else [False, True])
                 for fault in ([args.fault] if args.fault else ["input_stall", "input_disconnect", "output_stall", "output_disconnect"])]
    report = {"platform": platform.platform(), "ffmpeg": subprocess.check_output(["ffmpeg", "-version"], text=True).splitlines()[0],
              "cases": cases, "passed": all(case["passed"] for case in cases)}
    args.report.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
