"""Collect local hardware metrics via psutil on the agent node."""
import json
import threading
import time
from datetime import datetime

import psutil

from config import METRICS_INTERVAL, METRICS_MAX_SNAPSHOTS


class MetricsCollector:
    """Collect CPU, memory, and network metrics in background."""

    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._snapshots = {}  # test_id -> list of snapshots
        self._last_net_counters = {}  # test_id -> last psutil.net_io_counters()
        self._lock = threading.Lock()

    def start(self, test_id, interval=None):
        """Start background metrics collection for a test."""
        interval = interval or METRICS_INTERVAL
        with self._lock:
            self._snapshots[test_id] = []
            self._last_net_counters[test_id] = None

        if self._thread and self._thread.is_alive():
            # Already running for another test; we still store per-test snapshots
            return {"status": "started", "test_id": test_id}

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._collect_loop,
            args=(interval,),
            daemon=True,
        )
        self._thread.start()
        return {"status": "started", "test_id": test_id}

    def stop(self, test_id):
        """Stop collecting metrics for a test."""
        with self._lock:
            # We don't stop the global thread; just clear this test's data eventually
            pass
        return {"status": "stopped", "test_id": test_id}

    def stop_all(self):
        """Stop the global collection thread."""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        return {"status": "stopped_all"}

    def get_current(self):
        """Get a one-shot current snapshot."""
        return self._take_snapshot()

    def get_series(self, test_id):
        """Return collected snapshots for a test."""
        with self._lock:
            snaps = list(self._snapshots.get(test_id, []))
        return {"snapshots": snaps}

    def _collect_loop(self, interval):
        """Background loop: collect metrics for all active tests."""
        while not self._stop_event.is_set():
            snap = self._take_snapshot()
            with self._lock:
                for test_id in list(self._snapshots.keys()):
                    test_snap = dict(snap)
                    test_snap["test_id"] = test_id
                    self._snapshots[test_id].append(test_snap)
                    if len(self._snapshots[test_id]) > METRICS_MAX_SNAPSHOTS:
                        self._snapshots[test_id].pop(0)
            time.sleep(interval)

    def _take_snapshot(self):
        """Capture a single metrics snapshot."""
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
        mem = psutil.virtual_memory()
        net = psutil.net_io_counters()
        now = time.time()

        # Calculate network rates (Mbps and pps) for each test
        with self._lock:
            for test_id in list(self._snapshots.keys()):
                last = self._last_net_counters.get(test_id)
                if last:
                    delta_t = now - last["time"]
                    if delta_t > 0:
                        delta_tx = net.bytes_sent - last["bytes_sent"]
                        delta_rx = net.bytes_recv - last["bytes_recv"]
                        delta_tx_pkt = net.packets_sent - last["packets_sent"]
                        delta_rx_pkt = net.packets_recv - last["packets_recv"]
                        self._snapshots[test_id][-1]["network_tx_mbps"] = round((delta_tx * 8) / (1024 * 1024) / delta_t, 2)
                        self._snapshots[test_id][-1]["network_rx_mbps"] = round((delta_rx * 8) / (1024 * 1024) / delta_t, 2)
                        self._snapshots[test_id][-1]["network_tx_pps"] = round(delta_tx_pkt / delta_t, 0)
                        self._snapshots[test_id][-1]["network_rx_pps"] = round(delta_rx_pkt / delta_t, 0)
                self._last_net_counters[test_id] = {
                    "bytes_sent": net.bytes_sent,
                    "bytes_recv": net.bytes_recv,
                    "packets_sent": net.packets_sent,
                    "packets_recv": net.packets_recv,
                    "time": now,
                }

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "cpu_percent": cpu_percent,
            "cpu_per_core": cpu_per_core,
            "memory_percent": mem.percent,
            "memory_used_mb": mem.used / (1024.0 * 1024.0),
            "memory_total_mb": mem.total / (1024.0 * 1024.0),
            "network_rx_mb": net.bytes_recv / (1024.0 * 1024.0),
            "network_tx_mb": net.bytes_sent / (1024.0 * 1024.0),
            "network_tx_mbps": 0,
            "network_rx_mbps": 0,
            "network_tx_pps": 0,
            "network_rx_pps": 0,
        }


metrics_collector = MetricsCollector()
