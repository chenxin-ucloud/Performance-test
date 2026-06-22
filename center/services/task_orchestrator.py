"""Task orchestrator: dispatches tests to agents and collects results."""
import json
import threading
import time
from datetime import datetime
import requests

from models import db, TestRun, IperfResult, CpsResult, HardwareSnapshot
from services.sse_manager import sse_manager
from utils.iperf3_parser import parse_iperf3_json, extract_summary_metrics
from config import AGENT_HEALTH_TIMEOUT, DEFAULT_IPERF3_PORT, AGENT_POLL_INTERVAL


class TaskOrchestrator:
    """Manages the lifecycle of a performance test across remote nodes."""

    def __init__(self):
        self._running_tests = {}
        self._lock = threading.Lock()
        self._app = None

    def set_app(self, app):
        """Set the Flask app reference for app_context."""
        self._app = app

    def dispatch_test(self, test_id):
        """Dispatch a test to remote nodes and manage its lifecycle."""
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
        """Signal a running test to stop."""
        with self._lock:
            event = self._running_tests.get(test_id)
        if event:
            event.set()

    def _agent_url(self, node, path):
        """Build agent URL for a node."""
        return f"http://{node.host}:{node.agent_port}{path}"

    def _agent_post(self, node, path, json_data=None, timeout=AGENT_HEALTH_TIMEOUT):
        """POST to an agent. Returns response JSON or None on failure."""
        try:
            url = self._agent_url(node, path)
            resp = requests.post(url, json=json_data or {}, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"HTTP {resp.status_code}", "detail": resp.text}
        except requests.RequestException as e:
            return {"error": str(e)}

    def _agent_get(self, node, path, timeout=AGENT_HEALTH_TIMEOUT):
        """GET from an agent. Returns response JSON or None on failure."""
        try:
            url = self._agent_url(node, path)
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp.json()
            return {"error": f"HTTP {resp.status_code}", "detail": resp.text}
        except requests.RequestException as e:
            return {"error": str(e)}

    def _run_test(self, test, stop_event):
        """Execute a single test run."""
        client = test.client_node
        server = test.server_node

        # Update status
        test.status = "running"
        test.started_at = datetime.utcnow()
        db.session.commit()

        sse_manager.publish(test.id, {
            "type": "status",
            "status": "running",
            "message": f"Starting test {test.id}: {client.name} -> {server.name}"
        })

        try:
            # Phase 1: Start iperf3 server on server node
            srv_port = DEFAULT_IPERF3_PORT
            srv_start = self._agent_post(server, "/agent/iperf3/server/start", {
                "port": srv_port
            })
            if srv_start and srv_start.get("error"):
                raise RuntimeError(f"Failed to start iperf3 server on {server.name}: {srv_start['error']}")

            time.sleep(0.5)  # Give server time to bind

            # Phase 2: Start metrics collection on both nodes
            self._agent_post(client, "/agent/metrics/start", {"test_id": test.id})
            self._agent_post(server, "/agent/metrics/start", {"test_id": test.id})

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
            client_start = self._agent_post(client, "/agent/iperf3/client/start", client_params)
            if client_start and client_start.get("error"):
                raise RuntimeError(f"Failed to start iperf3 client on {client.name}: {client_start['error']}")

            # Phase 4: Poll for progress
            self._poll_progress(test, client, server, stop_event)

            # Phase 5: Fetch client result
            client_result_raw = self._agent_get(client, "/agent/iperf3/client/result")
            if client_result_raw and not client_result_raw.get("error"):
                self._save_iperf_result(test, client, "client", client_result_raw.get("raw_json", ""))

            # Phase 6: Bidirectional if requested
            if test.bidirectional and not stop_event.is_set():
                sse_manager.publish(test.id, {
                    "type": "status",
                    "status": "running",
                    "message": f"Bidirectional phase: {server.name} -> {client.name}"
                })
                # Start server on client
                self._agent_post(client, "/agent/iperf3/server/start", {"port": srv_port})
                time.sleep(0.5)
                # Start client on server
                server_params = {
                    "target_host": client.host,
                    "target_port": srv_port,
                    "duration": test.duration_sec,
                    "streams": test.parallel_streams,
                    "bandwidth": test.bandwidth_limit,
                    "reverse": False,
                    "udp": test.test_type == "udp",
                }
                self._agent_post(server, "/agent/iperf3/client/start", server_params)
                self._poll_progress(test, server, client, stop_event)
                server_result_raw = self._agent_get(server, "/agent/iperf3/client/result")
                if server_result_raw and not server_result_raw.get("error"):
                    self._save_iperf_result(test, server, "client", server_result_raw.get("raw_json", ""))

            # Phase 7: CPS measurement if requested
            if test.measure_cps and not stop_event.is_set():
                sse_manager.publish(test.id, {
                    "type": "status",
                    "status": "running",
                    "message": "Running CPS measurement..."
                })
                cps_result = self._agent_post(client, "/agent/cps/start", {
                    "target_host": server.host,
                    "target_port": srv_port,
                    "duration": 5,
                })
                if cps_result and not cps_result.get("error"):
                    self._save_cps_result(test, client, server, cps_result)

            # Cleanup: stop metrics collection
            self._agent_post(client, "/agent/metrics/stop", {"test_id": test.id})
            self._agent_post(server, "/agent/metrics/stop", {"test_id": test.id})

            # Cleanup: stop iperf3 server
            self._agent_post(server, "/agent/iperf3/server/stop")
            self._agent_post(client, "/agent/iperf3/server/stop")

            # Fetch hardware snapshots
            self._fetch_hardware_snapshots(test, client)
            self._fetch_hardware_snapshots(test, server)

            if stop_event.is_set():
                test.status = "interrupted"
                sse_manager.publish(test.id, {"type": "status", "status": "interrupted"})
            else:
                test.status = "completed"
                sse_manager.publish(test.id, {"type": "status", "status": "completed"})

        except Exception as e:
            test.status = "failed"
            db.session.commit()
            sse_manager.publish(test.id, {"type": "status", "status": "failed", "error": str(e)})
            # Attempt cleanup
            try:
                self._agent_post(server, "/agent/iperf3/server/stop")
                self._agent_post(client, "/agent/iperf3/client/stop")
                self._agent_post(client, "/agent/metrics/stop", {"test_id": test.id})
                self._agent_post(server, "/agent/metrics/stop", {"test_id": test.id})
            except Exception:
                pass
        finally:
            test.completed_at = datetime.utcnow()
            db.session.commit()
            sse_manager.publish(test.id, None)  # Signal SSE stream to close

    def _poll_progress(self, test, client_node, server_node, stop_event):
        """Poll agents for progress during a test."""
        start_time = time.time()
        while time.time() - start_time < test.duration_sec + 5:
            if stop_event.is_set():
                self._agent_post(client_node, "/agent/iperf3/client/stop")
                break

            # Poll client metrics
            client_metrics = self._agent_get(client_node, "/agent/metrics/current", timeout=3)
            # Poll server metrics
            server_metrics = self._agent_get(server_node, "/agent/metrics/current", timeout=3)

            data = {
                "type": "metrics",
                "elapsed": round(time.time() - start_time, 1),
                "client": client_metrics if client_metrics and not client_metrics.get("error") else {},
                "server": server_metrics if server_metrics and not server_metrics.get("error") else {},
            }
            sse_manager.publish(test.id, data)
            time.sleep(AGENT_POLL_INTERVAL)

    def _save_iperf_result(self, test, node, role, raw_json):
        """Parse and save iperf3 result."""
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
        """Save CPS measurement result."""
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
        """Fetch and save hardware snapshot series from a node."""
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
