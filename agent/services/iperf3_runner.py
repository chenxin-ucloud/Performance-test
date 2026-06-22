"""Execute iperf3 locally on the agent node."""
import json
import subprocess
import threading
import signal
import os


class Iperf3Runner:
    """Manages iperf3 server and client processes."""

    def __init__(self):
        self._server_proc = None
        self._client_proc = None
        self._lock = threading.Lock()
        self._last_client_result = None

    # ----- Server -----

    def start_server(self, port=5201):
        """Start iperf3 server in background."""
        with self._lock:
            if self._server_proc and self._server_proc.poll() is None:
                return {"status": "already_running", "pid": self._server_proc.pid}

            cmd = ["iperf3", "-s", "-p", str(port), "-J"]
            self._server_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return {"status": "started", "pid": self._server_proc.pid}

    def stop_server(self):
        """Stop the iperf3 server."""
        with self._lock:
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
        return {"status": "stopped"}

    # ----- Client -----

    def start_client(self, target_host, target_port=5201, duration=10,
                     streams=1, bandwidth=None, reverse=False, udp=False):
        """Start iperf3 client and capture JSON output."""
        with self._lock:
            if self._client_proc and self._client_proc.poll() is None:
                return {"error": "client already running"}

            cmd = [
                "iperf3",
                "-c", str(target_host),
                "-p", str(target_port),
                "-t", str(duration),
                "-P", str(streams),
                "-J",
            ]
            if bandwidth:
                cmd.extend(["-b", str(bandwidth)])
            if reverse:
                cmd.append("-R")
            if udp:
                cmd.append("-u")

            self._client_proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            return {"status": "started", "pid": self._client_proc.pid}

    def stop_client(self):
        """Stop the iperf3 client."""
        with self._lock:
            if self._client_proc:
                try:
                    self._client_proc.terminate()
                    self._client_proc.wait(timeout=3)
                except Exception:
                    try:
                        self._client_proc.kill()
                    except Exception:
                        pass
                self._client_proc = None
        return {"status": "stopped"}

    def get_client_result(self):
        """Get the last client result (raw JSON). Blocks if still running."""
        with self._lock:
            proc = self._client_proc

        if proc is None:
            if self._last_client_result:
                return self._last_client_result
            return {"error": "no client has been run"}

        try:
            stdout, stderr = proc.communicate(timeout=60)
            with self._lock:
                self._client_proc = None
                try:
                    # Validate it's JSON
                    json.loads(stdout)
                    self._last_client_result = {"status": "completed", "raw_json": stdout}
                except json.JSONDecodeError:
                    self._last_client_result = {
                        "status": "error",
                        "error": "invalid json output",
                        "stdout": stdout,
                        "stderr": stderr,
                    }
                return self._last_client_result
        except subprocess.TimeoutExpired:
            return {"status": "running"}


iperf3_runner = Iperf3Runner()
