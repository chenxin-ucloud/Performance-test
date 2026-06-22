"""CPS (Connections Per Second) tester."""
import socket
import threading
import time
from datetime import datetime

from config import CPS_CONNECTION_TIMEOUT, CPS_WORKER_THREADS


class CpsTester:
    """Measure TCP connection establishment rate to a target."""

    def __init__(self):
        self._stop_event = threading.Event()
        self._result = None
        self._lock = threading.Lock()
        self._thread = None

    def start(self, target_host, target_port, duration=5):
        """Start a CPS measurement in a background thread."""
        self._stop_event.clear()
        self._result = None
        self._thread = threading.Thread(
            target=self._run,
            args=(target_host, target_port, duration),
            daemon=True,
        )
        self._thread.start()
        return {"status": "started"}

    def stop(self):
        """Signal the CPS test to stop."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        return {"status": "stopped"}

    def get_result(self):
        """Return the CPS result if available."""
        with self._lock:
            return self._result

    def _run(self, target_host, target_port, duration):
        """Run the CPS measurement."""
        succeeded = 0
        attempted = 0
        start_time = time.time()

        def worker():
            nonlocal succeeded, attempted
            while not self._stop_event.is_set() and time.time() - start_time < duration:
                try:
                    attempted += 1
                    sock = socket.create_connection(
                        (target_host, target_port),
                        timeout=CPS_CONNECTION_TIMEOUT,
                    )
                    sock.close()
                    succeeded += 1
                except Exception:
                    pass

        threads = []
        for _ in range(CPS_WORKER_THREADS):
            t = threading.Thread(target=worker)
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        elapsed_ms = int((time.time() - start_time) * 1000)
        cps = succeeded / (elapsed_ms / 1000.0) if elapsed_ms > 0 else 0

        with self._lock:
            self._result = {
                "status": "completed",
                "attempted": attempted,
                "succeeded": succeeded,
                "duration_ms": elapsed_ms,
                "cps": round(cps, 2),
                "measured_at": datetime.utcnow().isoformat(),
            }


cps_tester = CpsTester()
