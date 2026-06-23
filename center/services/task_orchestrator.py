"""Task orchestrator: dispatches tests to agents and collects results."""
import json
import logging
import threading
import time
from datetime import datetime
import requests

from models import db, TestRun, IperfResult, CpsResult, HardwareSnapshot
from services.sse_manager import sse_manager
from utils.iperf3_parser import parse_iperf3_json, extract_summary_metrics
from config import AGENT_HEALTH_TIMEOUT, AGENT_CONNECT_TIMEOUT, DEFAULT_IPERF3_PORT, AGENT_POLL_INTERVAL

logger = logging.getLogger(__name__)


class TaskOrchestrator:
    """Manages the lifecycle of a performance test across remote nodes."""

    def __init__(self):
        self._running_tests = {}
        self._lock = threading.Lock()
        self._app = None

    def set_app(self, app):
        self._app = app

    def dispatch_test(self, test_id):
        if not self._app:
            return
        with self._app.app_context():
            test = TestRun.query.get(test_id)
            if not test:
                return

            stop_event = threading.Event()
            with self._lock:
                self._running_tests[test_id] = stop_event

            try:
                self._run_test(test, stop_event)
            finally:
                with self._lock:
                    self._running_tests.pop(test_id, None)

    def stop_test(self, test_id):
        with self._lock:
            event = self._running_tests.get(test_id)
        if event:
            event.set()

    def _agent_url(self, node, path):
        return f"http://{node.host}:{node.agent_port}{path}"

    # ===== Robust HTTP Client with Retry =====

    def _agent_request(self, method, node, path, json_data=None, timeout=None, retries=3):
        """Make HTTP request with retry logic."""
        url = self._agent_url(node, path)
        # Short connect timeout for fast retry, longer read timeout for slow ops
        connect_t = min(AGENT_CONNECT_TIMEOUT, 5.0)
        read_t = timeout or AGENT_HEALTH_TIMEOUT
        total_t = (connect_t, read_t)

        last_err = None
        for attempt in range(retries):
            try:
                t0 = time.time()
                if method == "POST":
                    resp = requests.post(url, json=json_data or {}, timeout=total_t)
                else:
                    resp = requests.get(url, timeout=total_t)
                elapsed = time.time() - t0
                if resp.status_code == 200:
                    logger.info(f"[{node.name}] {method} {path} OK in {elapsed:.2f}s")
                    return resp.json()
                return {"error": f"HTTP {resp.status_code}", "detail": resp.text}
            except requests.ConnectionError as e:
                last_err = str(e)
                logger.warning(f"[{node.name}] {method} {path} connection error (attempt {attempt+1}/{retries}): {last_err}")
                if attempt < retries - 1:
                    time.sleep(1.5)
            except requests.Timeout as e:
                last_err = str(e)
                logger.warning(f"[{node.name}] {method} {path} timeout (attempt {attempt+1}/{retries}): {last_err}")
                if attempt < retries - 1:
                    time.sleep(1.5)
            except requests.RequestException as e:
                last_err = str(e)
                logger.warning(f"[{node.name}] {method} {path} request error (attempt {attempt+1}/{retries}): {last_err}")
                if attempt < retries - 1:
                    time.sleep(1.5)

        return {"error": f"Max retries ({retries}) exceeded: {last_err}"}

    def _agent_post(self, node, path, json_data=None, timeout=None):
        return self._agent_request("POST", node, path, json_data, timeout)

    def _agent_get(self, node, path, timeout=None):
        return self._agent_request("GET", node, path, None, timeout)

    # ===== Test Orchestration =====

    def _run_test(self, test, stop_event):
        client = test.client_node
        server = test.server_node

        test.status = "running"
        test.started_at = datetime.utcnow()
        db.session.commit()

        sse_manager.publish(test.id, {
            "type": "status",
            "status": "running",
            "message": f"Starting test {test.id}: {client.name} -> {server.name}"
        })

        try:
            srv_port = DEFAULT_IPERF3_PORT

            # Phase 1: Start metrics collection on both nodes in parallel
            self._start_metrics_parallel(test, client, server)

            # Phase 2: Start iperf3 server on server node
            srv_start = self._agent_post(server, "/agent/iperf3/server/start", {
                "port": srv_port
            }, timeout=10)
            if srv_start and srv_start.get("error"):
                raise RuntimeError(f"Failed to start iperf3 server on {server.name}: {srv_start['error']}")

            # Phase 3: Start iperf3 client on client node
            client_params = {
                "target_host": server.host,
                "target_port": srv_port,
                "duration": test.duration_sec,
                "streams": test.parallel_streams,
                "bandwidth": test.bandwidth_limit,
                "reverse": test.reverse_mode,
                "udp": test.test_type == "udp",
            }
            client_start = self._agent_post(client, "/agent/iperf3/client/start", client_params, timeout=10)
            if client_start and client_start.get("error"):
                raise RuntimeError(f"Failed to start iperf3 client on {client.name}: {client_start['error']}")

            # Phase 4: Poll for progress during test
            self._poll_progress(test, client, server, stop_event)

            # Phase 5: Fetch client result
            client_result_raw = self._agent_get(client, "/agent/iperf3/client/result", timeout=60)
            if client_result_raw and not client_result_raw.get("error"):
                raw_json = client_result_raw.get("raw_json", "")
                if raw_json:
                    self._save_iperf_result(test, client, "client", raw_json)
                else:
                    sse_manager.publish(test.id, {
                        "type": "status",
                        "status": "warning",
                        "message": f"Client on {client.name} returned empty result"
                    })

            # Phase 6: Bidirectional if requested
            if test.bidirectional and not stop_event.is_set():
                self._run_bidirectional(test, client, server, srv_port, stop_event)

            # Phase 7: CPS measurement if requested
            if test.measure_cps and not stop_event.is_set():
                self._run_cps(test, client, server, srv_port)

            # Cleanup
            self._cleanup(test, client, server)

            if stop_event.is_set():
                test.status = "interrupted"
                sse_manager.publish(test.id, {"type": "status", "status": "interrupted"})
            else:
                test.status = "completed"
                sse_manager.publish(test.id, {"type": "status", "status": "completed"})

        except Exception as e:
            test.status = "failed"
            db.session.commit()
            logger.error(f"Test {test.id} failed: {e}", exc_info=True)
            sse_manager.publish(test.id, {"type": "status", "status": "failed", "error": str(e)})
            self._cleanup(test, client, server)
        finally:
            test.completed_at = datetime.utcnow()
            db.session.commit()
            sse_manager.publish(test.id, None)

    def _start_metrics_parallel(self, test, client, server):
        """Start metrics collection on both nodes concurrently."""
        results = {}
        errors = []

        def start_metrics(node):
            result = self._agent_post(node, "/agent/metrics/start", {"test_id": test.id}, timeout=10)
            results[node.name] = result
            if result and result.get("error"):
                errors.append(f"{node.name}: {result['error']}")

        t1 = threading.Thread(target=start_metrics, args=(client,), daemon=True)
        t2 = threading.Thread(target=start_metrics, args=(server,), daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=15)
        t2.join(timeout=15)

        if errors:
            logger.warning(f"Metrics start warnings: {'; '.join(errors)}")

    def _run_bidirectional(self, test, client, server, srv_port, stop_event):
        sse_manager.publish(test.id, {
            "type": "status",
            "status": "running",
            "message": f"Bidirectional phase: {server.name} -> {client.name}"
        })
        self._agent_post(client, "/agent/iperf3/server/start", {"port": srv_port}, timeout=10)
        time.sleep(0.5)
        server_params = {
            "target_host": client.host,
            "target_port": srv_port,
            "duration": test.duration_sec,
            "streams": test.parallel_streams,
            "bandwidth": test.bandwidth_limit,
            "reverse": False,
            "udp": test.test_type == "udp",
        }
        self._agent_post(server, "/agent/iperf3/client/start", server_params, timeout=10)
        self._poll_progress(test, server, client, stop_event)
        server_result_raw = self._agent_get(server, "/agent/iperf3/client/result", timeout=60)
        if server_result_raw and not server_result_raw.get("error"):
            raw_json = server_result_raw.get("raw_json", "")
            if raw_json:
                self._save_iperf_result(test, server, "client", raw_json)

    def _run_cps(self, test, client, server, srv_port):
        sse_manager.publish(test.id, {
            "type": "status",
            "status": "running",
            "message": "Running CPS measurement..."
        })
        cps_result = self._agent_post(client, "/agent/cps/start", {
            "target_host": server.host,
            "target_port": srv_port,
            "duration": 5,
        }, timeout=10)
        if cps_result and not cps_result.get("error"):
            self._save_cps_result(test, client, server, cps_result)

    def _cleanup(self, test, client, server):
        """Cleanup resources on both nodes."""
        logger.info(f"Cleaning up test {test.id}")
        try:
            self._agent_post(server, "/agent/iperf3/server/stop", timeout=5)
            self._agent_post(client, "/agent/iperf3/server/stop", timeout=5)
            self._agent_post(client, "/agent/iperf3/client/stop", timeout=5)
            self._agent_post(server, "/agent/iperf3/client/stop", timeout=5)
            self._agent_post(client, "/agent/metrics/stop", {"test_id": test.id}, timeout=5)
            self._agent_post(server, "/agent/metrics/stop", {"test_id": test.id}, timeout=5)
        except Exception as e:
            logger.warning(f"Cleanup warning: {e}")

        # Fetch hardware snapshots even if test failed
        try:
            self._fetch_hardware_snapshots(test, client)
            self._fetch_hardware_snapshots(test, server)
        except Exception as e:
            logger.warning(f"Hardware fetch warning: {e}")

    def _poll_progress(self, test, client_node, server_node, stop_event):
        start_time = time.time()
        while time.time() - start_time < test.duration_sec + 5:
            if stop_event.is_set():
                self._agent_post(client_node, "/agent/iperf3/client/stop", timeout=5)
                break

            client_metrics = self._agent_get(client_node, "/agent/metrics/current", timeout=5)
            server_metrics = self._agent_get(server_node, "/agent/metrics/current", timeout=5)

            cm = client_metrics if client_metrics and not client_metrics.get("error") else {}
            sm = server_metrics if server_metrics and not server_metrics.get("error") else {}

            data = {
                "type": "metrics",
                "elapsed": round(time.time() - start_time, 1),
                "client": {
                    "cpu_percent": cm.get("cpu_percent", 0),
                    "memory_percent": cm.get("memory_percent", 0),
                    "network_tx_mbps": cm.get("network_tx_mbps", 0),
                    "network_rx_mbps": cm.get("network_rx_mbps", 0),
                    "network_tx_pps": cm.get("network_tx_pps", 0),
                    "network_rx_pps": cm.get("network_rx_pps", 0),
                },
                "server": {
                    "cpu_percent": sm.get("cpu_percent", 0),
                    "memory_percent": sm.get("memory_percent", 0),
                    "network_tx_mbps": sm.get("network_tx_mbps", 0),
                    "network_rx_mbps": sm.get("network_rx_mbps", 0),
                    "network_tx_pps": sm.get("network_tx_pps", 0),
                    "network_rx_pps": sm.get("network_rx_pps", 0),
                },
            }
            sse_manager.publish(test.id, data)
            time.sleep(AGENT_POLL_INTERVAL)

    def _save_iperf_result(self, test, node, role, raw_json):
        try:
            parsed = parse_iperf3_json(raw_json)
            summary = extract_summary_metrics(parsed)

            result = IperfResult(
                test_id=test.id,
                node_id=node.id,
                role=role,
                raw_json=raw_json,
                summary_bits_per_sec=summary.get("bits_per_second"),
                summary_bytes=summary.get("bytes"),
                summary_packets=summary.get("packets"),
                avg_pps=summary.get("pps"),
                retransmits=summary.get("retransmits"),
                jitter_ms=summary.get("jitter_ms"),
                lost_packets=summary.get("lost_packets"),
                lost_percent=summary.get("lost_percent"),
            )
            db.session.add(result)
            db.session.commit()
        except Exception:
            db.session.rollback()

    def _save_cps_result(self, test, source_node, target_node, cps_data):
        try:
            result = CpsResult(
                test_id=test.id,
                source_node_id=source_node.id,
                target_node_id=target_node.id,
                connections_attempted=cps_data.get("attempted"),
                connections_succeeded=cps_data.get("succeeded"),
                duration_ms=cps_data.get("duration_ms"),
                cps=cps_data.get("cps"),
            )
            db.session.add(result)
            db.session.commit()
        except Exception:
            db.session.rollback()

    def _fetch_hardware_snapshots(self, test, node):
        try:
            series = self._agent_get(node, f"/agent/metrics/series?test_id={test.id}", timeout=10)
            if not series or series.get("error"):
                return
            snapshots = series.get("snapshots", [])
            for snap in snapshots:
                hs = HardwareSnapshot(
                    test_id=test.id,
                    node_id=node.id,
                    timestamp=datetime.fromisoformat(snap["timestamp"]) if snap.get("timestamp") else datetime.utcnow(),
                    cpu_percent=snap.get("cpu_percent"),
                    cpu_per_core=json.dumps(snap.get("cpu_per_core")) if snap.get("cpu_per_core") else None,
                    memory_percent=snap.get("memory_percent"),
                    memory_used_mb=snap.get("memory_used_mb"),
                    memory_total_mb=snap.get("memory_total_mb"),
                    network_rx_mb=snap.get("network_rx_mb"),
                    network_tx_mb=snap.get("network_tx_mb"),
                )
                db.session.add(hs)
            db.session.commit()
        except Exception:
            db.session.rollback()


orchestrator = TaskOrchestrator()
