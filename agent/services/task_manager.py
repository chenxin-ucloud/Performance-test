"""Task manager: track and manage running tasks on the agent."""
from services.iperf3_runner import iperf3_runner
from services.dperf_runner import dperf_runner
from services.cps_tester import cps_tester
from services.metrics_collector import metrics_collector


class TaskManager:
    """Centralized task management for the agent."""

    def __init__(self):
        self._running = False

    def stop_all(self):
        """Stop all running tasks."""
        iperf3_runner.stop_client()
        iperf3_runner.stop_server()
        dperf_runner.stop_server()
        cps_tester.stop()
        metrics_collector.stop_all()
        return {"status": "all_stopped"}

    def health(self):
        """Return agent health status including internal network IPs."""
        import socket
        import time

        # Get all non-loopback IPs
        ips = []
        try:
            for _, addrs in socket.getaddrinfo(socket.gethostname(), None):
                ip = addrs[4][0]
                if not ip.startswith("127.") and ":" not in ip:
                    ips.append(ip)
        except Exception:
            pass

        # Fallback: get primary interface IP
        if not ips:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.settimeout(2)
                s.connect(("8.8.8.8", 80))
                ips.append(s.getsockname()[0])
                s.close()
            except Exception:
                pass

        return {
            "status": "ok",
            "hostname": socket.gethostname(),
            "uptime_seconds": time.time(),
            "internal_ips": ips,
            "engines": {
                "iperf3": True,
                "dperf": dperf_runner._dperf_available,
            },
        }


task_manager = TaskManager()
