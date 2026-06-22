"""Execute iperf3 locally on the agent node."""
import json
import os
import socket
import subprocess
import threading
import time


class Iperf3Runner:
    """Manages iperf3 server and client processes."""

    def __init__(self):
        self._server_proc = None
        self._client_proc = None
        self._lock = threading.Lock()
        self._last_client_result = None
        self._server_port = 5201
        self._devnull = open(os.devnull, "w")

    # ----- Server -----

    def start_server(self, port=5201):
        """Start iperf3 server in background, verify port is listening."""
        with self._lock:
            if self._server_proc and self._server_proc.poll() is None:
                # Already running - verify it's actually listening
                if self._check_port(port):
                    return {"status": "already_running", "pid": self._server_proc.pid, "port": port}
                # Process exists but port not open, kill and restart
                self._kill_server()

            self._server_port = port
            cmd = ["iperf3", "-s", "-p", str(port), "-J"]
            self._server_proc = subprocess.Popen(
                cmd,
                stdout=self._devnull,
                stderr=self._devnull,
            )

        # Wait up to 3 seconds for the port to actually open
        for _ in range(30):
            if self._check_port(port):
                return {"status": "started", "pid": self._server_proc.pid, "port": port}
            time.sleep(0.1)

        # Port never opened - server failed to start
        self._kill_server()
        return {"status": "error", "error": f"iperf3 server failed to bind port {port}"}

    def stop_server(self):
        """Stop the iperf3 server."""
        with self._lock:
            self._kill_server()
        return {"status": "stopped"}

    def _kill_server(self):
        """Internal: kill server process."""
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

    @staticmethod
    def _check_port(port, host="127.0.0.1"):
        """Check if a TCP port is open and accepting connections."""
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (OSError, ConnectionRefusedError):
            return False

    # ----- Client -----

    def start_client(self, target_host, target_port=5201, duration=10,
                     streams=1, bandwidth=None, reverse=False, udp=False):
        """Start iperf3 client and capture JSON output."""
        with self._lock:
            if self._client_proc and self._client_proc.poll() is None:
                return {"error": "client already running"}

            # Verify target is reachable before starting
            if not self._check_port(target_port, target_host):
                return {
                    "error": f"iperf3 server not reachable at {target_host}:{target_port}"
                }

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
            returncode = proc.returncode
            with self._lock:
                self._client_proc = None

                # iperf3 returns non-zero on some errors or connection failures
                if returncode != 0 and not stdout.strip():
                    self._last_client_result = {
                        "status": "error",
                        "returncode": returncode,
                        "error": stderr.strip() or "iperf3 exited with error",
                    }
                    return self._last_client_result

                try:
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
