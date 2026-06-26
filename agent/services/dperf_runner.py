"""dperf runner: High-performance PPS/CPS/concurrency tester.

dperf is a DPDK-based high performance network tester, suitable for
measuring PPS (64-byte small packets), CPS (connections per second),
and concurrent connections. It requires DPDK and root privileges.

If dperf is not installed, falls back to iperf3 for bandwidth and
a custom Python CPS tester.

Reference: https://github.com/baidu/dperf
"""
import json
import os
import socket
import subprocess
import threading
import time
from typing import Optional


class DperfRunner:
    """Manages dperf server and client processes."""

    def __init__(self):
        self._server_proc = None
        self._client_proc = None
        self._lock = threading.Lock()
        self._last_client_result = None
        self._check_dperf()

    def _check_dperf(self):
        """Check if dperf is available."""
        self._dperf_available = False
        try:
            result = subprocess.run(
                ["dperf", "-v"], capture_output=True, text=True, timeout=2,
            )
            if result.returncode == 0:
                self._dperf_available = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass

    # ----- Server -----

    def start_server(self, port=80):
        """Start dperf server."""
        if not self._dperf_available:
            return {"error": "dperf not installed"}

        with self._lock:
            if self._server_proc and self._server_proc.poll() is None:
                return {"status": "already_running", "pid": self._server_proc.pid}

            # dperf server config
            config_file = "/tmp/dperf_server.conf"
            with open(config_file, "w") as f:
                f.write("mode        server\n")
                f.write("cpu         1\n")
                f.write(f"port        0 0 0.0.0.0 {port}\n")
                f.write("duration    120s\n")

            self._server_proc = subprocess.Popen(
                ["dperf", "-c", config_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        # Wait up to 3 seconds for port to open
        for _ in range(30):
            if self._check_port(port):
                return {"status": "started", "pid": self._server_proc.pid, "port": port}
            time.sleep(0.1)

        self._kill_server()
        return {"status": "error", "error": f"dperf server failed to bind port {port}"}

    def stop_server(self):
        with self._lock:
            self._kill_server()
        return {"status": "stopped"}

    def _kill_server(self):
        if self._server_proc:
            try:
                self._server_proc.terminate()
                self._server_proc.wait(timeout=3)
            except Exception:
                try:
                    self._server_proc.kill()
                except Exception:
                    pass
            self._server_proc = None

    # ----- Client / Test Runners -----

    def run_pps_test(self, target_host, target_port=80, duration=10, packet_size=64):
        """Run dperf PPS test with 64-byte packets."""
        if not self._dperf_available:
            return {"error": "dperf not installed", "fallback": "use iperf3 for bandwidth"}

        config_file = "/tmp/dperf_pps.conf"
        with open(config_file, "w") as f:
            f.write("mode        client\n")
            f.write("cpu         1\n")
            f.write(f"port        0 0 {target_host} {target_port}\n")
            f.write(f"duration    {duration}s\n")
            f.write(f"send        1\n")  # flood mode
            f.write(f"payload     {packet_size}\n")
            f.write("lport_range 1000 65535\n")

        return self._run_dperf_client(config_file)

    def run_cps_test(self, target_host, target_port=80, duration=5, rate=10000):
        """Run dperf CPS test (--cps)."""
        if not self._dperf_available:
            return {"error": "dperf not installed", "fallback": "use custom CPS tester"}

        config_file = "/tmp/dperf_cps.conf"
        with open(config_file, "w") as f:
            f.write("mode        client\n")
            f.write("cpu         1\n")
            f.write(f"port        0 0 {target_host} {target_port}\n")
            f.write(f"duration    {duration}s\n")
            f.write(f"cps         {rate}\n")
            f.write("cc          10000\n")

        return self._run_dperf_client(config_file)

    def run_concurrent_test(self, target_host, target_port=80, duration=10, concurrent=10000):
        """Run dperf concurrent connection test."""
        if not self._dperf_available:
            return {"error": "dperf not installed", "fallback": "use custom CPS tester"}

        config_file = "/tmp/dperf_concurrent.conf"
        with open(config_file, "w") as f:
            f.write("mode        client\n")
            f.write("cpu         1\n")
            f.write(f"port        0 0 {target_host} {target_port}\n")
            f.write(f"duration    {duration}s\n")
            f.write(f"cc          {concurrent}\n")

        return self._run_dperf_client(config_file)

    def _run_dperf_client(self, config_file):
        """Run dperf client and parse output."""
        with self._lock:
            if self._client_proc and self._client_proc.poll() is None:
                return {"error": "client already running"}

            self._client_proc = subprocess.Popen(
                ["dperf", "-c", config_file],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )

        try:
            stdout, stderr = self._client_proc.communicate(timeout=120)
            with self._lock:
                self._client_proc = None

            # Parse dperf output (very basic - dperf output format is text-based)
            # dperf outputs summary lines like:
            # "sndPackets 123456, sndBytes 7890123"
            result = {"status": "completed", "raw_output": stdout, "raw_stderr": stderr}
            for line in stdout.splitlines():
                if "sndPackets" in line:
                    parts = line.split(",")
                    for part in parts:
                        kv = part.strip().split()
                        if len(kv) >= 2:
                            key = kv[0].strip()
                            val = kv[-1].strip()
                            if val.isdigit():
                                result[key] = int(val)
            return result
        except subprocess.TimeoutExpired:
            return {"status": "running"}

    @staticmethod
    def _check_port(port, host="127.0.0.1"):
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (OSError, ConnectionRefusedError):
            return False


dperf_runner = DperfRunner()
