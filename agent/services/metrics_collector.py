"""Collect local hardware metrics via psutil on the agent node."""
import threading
import time
from datetime import datetime

import psutil

from config import METRICS_INTERVAL, METRICS_MAX_SNAPSHOTS


class MetricsCollector:
    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._snapshots = {}  # test_id -> list of snapshots with rates
        self._lock = threading.Lock()
        self._collect_last_net = None
        self._collect_last_time = None

    def start(self, test_id, interval=None):
        interval = interval or METRICS_INTERVAL
        with self._lock:
            self._snapshots[test_id] = []

        if self._thread and self._thread.is_alive():
            return {"status": "started", "test_id": test_id}

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._collect_loop, args=(interval,), daemon=True)
        self._thread.start()
        return {"status": "started", "test_id": test_id}

    def stop(self, test_id):
        with self._lock:
            if test_id in self._snapshots:
                self._snapshots[test_id] = []
        return {"status": "stopped", "test_id": test_id}

    def stop_all(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)
        return {"status": "stopped_all"}

    def get_current(self):
        """Return the most recent snapshot with rates from any active test."""
        with self._lock:
            latest = None
            for snaps in self._snapshots.values():
                if snaps:
                    if latest is None or snaps[-1].get("timestamp", "") > latest.get("timestamp", ""):
                        latest = snaps[-1]
            if latest:
                return dict(latest)
        # No active tests: return a fresh absolute-value snapshot
        return self._take_absolute_snapshot()

    def get_series(self, test_id):
        with self._lock:
            snaps = list(self._snapshots.get(test_id, []))
        return {"snapshots": snaps}

    def _collect_loop(self, interval):
        """Background loop: collect metrics with rate calculation."""
        while not self._stop_event.is_set():
            snap = self._take_snapshot_with_rates()
            with self._lock:
                for test_id in list(self._snapshots.keys()):
                    test_snap = dict(snap)
                    test_snap["test_id"] = test_id
                    self._snapshots[test_id].append(test_snap)
                    if len(self._snapshots[test_id]) > METRICS_MAX_SNAPSHOTS:
                        self._snapshots[test_id].pop(0)
            time.sleep(interval)

    def _take_snapshot_with_rates(self):
        """Capture metrics snapshot and calculate network rates."""
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
        mem = psutil.virtual_memory()
        net = psutil.net_io_counters()
        now = time.time()

        tx_mbps = rx_mbps = tx_pps = rx_pps = 0.0
        if self._collect_last_net is not None:
            delta_t = now - self._collect_last_time
            if delta_t > 0:
                tx_mbps = (net.bytes_sent - self._collect_last_net.bytes_sent) * 8 / (1024 * 1024) / delta_t
                rx_mbps = (net.bytes_recv - self._collect_last_net.bytes_recv) * 8 / (1024 * 1024) / delta_t
                tx_pps = (net.packets_sent - self._collect_last_net.packets_sent) / delta_t
                rx_pps = (net.packets_recv - self._collect_last_net.packets_recv) / delta_t

        self._collect_last_net = net
        self._collect_last_time = now

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "cpu_percent": cpu_percent,
            "cpu_per_core": cpu_per_core,
            "memory_percent": mem.percent,
            "memory_used_mb": mem.used / (1024.0 * 1024.0),
            "memory_total_mb": mem.total / (1024.0 * 1024.0),
            "network_rx_mb": net.bytes_recv / (1024.0 * 1024.0),
            "network_tx_mb": net.bytes_sent / (1024.0 * 1024.0),
            "network_tx_mbps": round(max(tx_mbps, 0), 2),
            "network_rx_mbps": round(max(rx_mbps, 0), 2),
            "network_tx_pps": round(max(tx_pps, 0), 0),
            "network_rx_pps": round(max(rx_pps, 0), 0),
        }

    def _take_absolute_snapshot(self):
        """Fallback: return current absolute values without rate calculation."""
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
        mem = psutil.virtual_memory()
        net = psutil.net_io_counters()

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
