"""Collect local hardware metrics via psutil + ethtool + sysfs on the agent node.

SR-IOV environments: psutil reads /proc/net/dev (kernel stack), which misses
SR-IOV bypass traffic. We fall back to ethtool -S (NIC driver stats) or sysfs
/sys/class/net/<iface>/statistics/ (driver-maintained counters).
"""
import os
import subprocess
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional

import psutil

from config import METRICS_INTERVAL, METRICS_MAX_SNAPSHOTS


class NetworkStats:
    """Read network counters from multiple sources."""

    # Driver-specific stat names from ethtool -S
    STAT_NAME_MAP = {
        # Mellanox ConnectX
        "tx_bytes_phy": "tx_bytes",
        "rx_bytes_phy": "rx_bytes",
        "tx_packets_phy": "tx_packets",
        "rx_packets_phy": "rx_packets",
        "tx_bytes": "tx_bytes",
        "rx_bytes": "rx_bytes",
        "tx_packets": "tx_packets",
        "rx_packets": "rx_packets",
        # Intel ixgbe/i40e
        "tx_bytes": "tx_bytes",
        "rx_bytes": "rx_bytes",
        "tx_packets": "tx_packets",
        "rx_packets": "rx_packets",
        "tx_packets_phy": "tx_packets",
        "rx_packets_phy": "rx_packets",
    }

    def __init__(self):
        self._last: Optional[Dict[str, int]] = None
        self._last_time: float = 0.0
        self._iface: Optional[str] = None
        self._method: str = "unknown"

    @property
    def iface(self) -> str:
        """Auto-detect primary interface if not set."""
        if self._iface is not None:
            return self._iface
        # Prefer non-loopback, non-docker interfaces with traffic
        best = None
        best_score = -1
        for name, _ in psutil.net_if_stats().items():
            if name.startswith("lo") or name.startswith("docker") or name.startswith("br-"):
                continue
            # Score: longer name + digits = physical NIC
            score = len(name)
            if best is None or score > best_score:
                best = name
                best_score = score
        self._iface = best or "eth0"
        return self._iface

    @iface.setter
    def iface(self, name: str):
        self._iface = name

    def read(self) -> Optional[Dict[str, int]]:
        """Read counters. Returns dict or None on failure."""
        # Try 1: ethtool -S (most accurate for SR-IOV)
        stats = self._read_ethtool()
        if stats:
            self._method = "ethtool"
            return stats

        # Try 2: sysfs /sys/class/net/<iface>/statistics/
        stats = self._read_sysfs()
        if stats:
            self._method = "sysfs"
            return stats

        # Try 3: psutil (fallback, may miss SR-IOV traffic)
        stats = self._read_psutil()
        if stats:
            self._method = "psutil"
            return stats

        return None

    def _read_ethtool(self) -> Optional[Dict[str, int]]:
        """Use ethtool -S to read driver-level counters (works for SR-IOV)."""
        try:
            result = subprocess.run(
                ["ethtool", "-S", self.iface],
                capture_output=True, text=True, timeout=2,
            )
            if result.returncode != 0:
                return None
            data: Dict[str, int] = {}
            for line in result.stdout.splitlines():
                # Parse "    stat_name: 12345"
                parts = line.strip().rsplit(":", 1)
                if len(parts) != 2:
                    continue
                key = parts[0].strip()
                val = parts[1].strip()
                if key in self.STAT_NAME_MAP and val.lstrip("-").isdigit():
                    mapped = self.STAT_NAME_MAP[key]
                    data[mapped] = data.get(mapped, 0) + int(val)
            if "tx_bytes" in data and "rx_bytes" in data:
                data["tx_packets"] = data.get("tx_packets", 0)
                data["rx_packets"] = data.get("rx_packets", 0)
                return data
            return None
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return None

    def _read_sysfs(self) -> Optional[Dict[str, int]]:
        """Read /sys/class/net/<iface>/statistics/ counters."""
        base = f"/sys/class/net/{self.iface}/statistics/"
        try:
            keys = ["tx_bytes", "rx_bytes", "tx_packets", "rx_packets"]
            data: Dict[str, int] = {}
            for key in keys:
                path = os.path.join(base, key)
                if os.path.exists(path):
                    with open(path, "r") as f:
                        data[key] = int(f.read().strip())
                else:
                    return None
            return data
        except (OSError, ValueError):
            return None

    def _read_psutil(self) -> Optional[Dict[str, int]]:
        """Fallback to psutil net_io_counters."""
        try:
            net = psutil.net_io_counters(pernic=False)
            return {
                "tx_bytes": net.bytes_sent,
                "rx_bytes": net.bytes_recv,
                "tx_packets": net.packets_sent,
                "rx_packets": net.packets_recv,
            }
        except Exception:
            return None

    def get_rates(self) -> Dict[str, float]:
        """Calculate tx/rx rates since last call."""
        current = self.read()
        now = time.time()
        if current is None:
            return self._zero_rates()

        if self._last is not None:
            delta_t = now - self._last_time
            if delta_t > 0:
                tx_mbps = max(
                    (current["tx_bytes"] - self._last["tx_bytes"]) * 8 / (1024 * 1024) / delta_t, 0
                )
                rx_mbps = max(
                    (current["rx_bytes"] - self._last["rx_bytes"]) * 8 / (1024 * 1024) / delta_t, 0
                )
                tx_pps = max(
                    (current["tx_packets"] - self._last["tx_packets"]) / delta_t, 0
                )
                rx_pps = max(
                    (current["rx_packets"] - self._last["rx_packets"]) / delta_t, 0
                )
                self._last = current
                self._last_time = now
                return {
                    "network_tx_mbps": round(tx_mbps, 2),
                    "network_rx_mbps": round(rx_mbps, 2),
                    "network_tx_pps": round(tx_pps, 0),
                    "network_rx_pps": round(rx_pps, 0),
                    "network_method": self._method,
                }

        self._last = current
        self._last_time = now
        return self._zero_rates()

    @staticmethod
    def _zero_rates() -> Dict[str, float]:
        return {
            "network_tx_mbps": 0.0,
            "network_rx_mbps": 0.0,
            "network_tx_pps": 0.0,
            "network_rx_pps": 0.0,
            "network_method": "none",
        }


class MetricsCollector:
    """Collect CPU, memory, and NIC metrics using driver-level counters."""

    def __init__(self):
        self._thread = None
        self._stop_event = threading.Event()
        self._snapshots: Dict[int, List[dict]] = {}
        self._lock = threading.Lock()
        self._net_stats = NetworkStats()

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
        return self._take_absolute_snapshot()

    def get_series(self, test_id):
        with self._lock:
            snaps = list(self._snapshots.get(test_id, []))
        return {"snapshots": snaps}

    def _collect_loop(self, interval):
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
        cpu_percent = psutil.cpu_percent(interval=None)
        cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
        mem = psutil.virtual_memory()
        net = psutil.net_io_counters()
        rates = self._net_stats.get_rates()

        return {
            "timestamp": datetime.utcnow().isoformat(),
            "cpu_percent": cpu_percent,
            "cpu_per_core": cpu_per_core,
            "memory_percent": mem.percent,
            "memory_used_mb": mem.used / (1024.0 * 1024.0),
            "memory_total_mb": mem.total / (1024.0 * 1024.0),
            "network_rx_mb": net.bytes_recv / (1024.0 * 1024.0),
            "network_tx_mb": net.bytes_sent / (1024.0 * 1024.0),
            **rates,
        }

    def _take_absolute_snapshot(self):
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
            "network_tx_mbps": 0.0,
            "network_rx_mbps": 0.0,
            "network_tx_pps": 0.0,
            "network_rx_pps": 0.0,
            "network_method": "none",
        }


metrics_collector = MetricsCollector()
