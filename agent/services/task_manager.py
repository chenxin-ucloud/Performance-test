"""Task manager: track and manage running tasks on the agent."""
from services.iperf3_runner import iperf3_runner
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
        cps_tester.stop()
        metrics_collector.stop_all()
        return {"status": "all_stopped"}

    def health(self):
        """Return agent health status."""
        import socket
        import time
        return {
            "status": "ok",
            "hostname": socket.gethostname(),
            "uptime_seconds": time.time(),  # placeholder; could track real start time
        }


task_manager = TaskManager()
