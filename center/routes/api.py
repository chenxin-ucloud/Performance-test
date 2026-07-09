"""Center REST API routes and SSE endpoint."""
import json
import statistics
import threading
from datetime import datetime
from flask import Blueprint, request, jsonify, Response, render_template

from models import db, Node, TestRun, IperfResult, DperfResult, CpsResult, HardwareSnapshot
from services.task_orchestrator import orchestrator
from services.sse_manager import sse_manager
from utils.formatters import format_bits, format_pps, format_cps, format_percent

api_bp = Blueprint("api", __name__)


def _summarize_hardware_pps(test_id):
    """Aggregate NIC PPS samples across both nodes for a finished test.

    Returns (avg_pps, peak_pps) measured in raw packets/sec, or (None, None)
    when no hardware snapshots with PPS data exist. We take the max of client
    tx_pps and server rx_pps per snapshot — matching how the live dashboard
    computes PPS — then average / max across the test.
    """
    snaps = HardwareSnapshot.query.filter_by(test_id=test_id).all()
    pps_samples = []
    for s in snaps:
        # tx from client side, rx from server side; take the larger
        vals = [v for v in (s.network_tx_pps, s.network_rx_pps) if v is not None]
        if vals:
            pps_samples.append(max(vals))
    if not pps_samples:
        return None, None
    avg = sum(pps_samples) / len(pps_samples)
    peak = max(pps_samples)
    return avg, peak


# ==================== Page Routes ====================

@api_bp.route("/")
def index():
    """Serve the main dashboard."""
    return render_template("index.html")


# ==================== Node Routes ====================

@api_bp.route("/api/nodes", methods=["GET"])
def list_nodes():
    nodes = Node.query.order_by(Node.created_at.desc()).all()
    return jsonify([n.to_dict() for n in nodes])


@api_bp.route("/api/nodes", methods=["POST"])
def create_node():
    data = request.get_json() or {}
    node = Node(
        name=data.get("name", "").strip(),
        host=data.get("host", "").strip(),
        agent_port=int(data.get("agent_port", 5001)),
        description=data.get("description", "").strip(),
    )
    if not node.name or not node.host:
        return jsonify({"error": "name and host are required"}), 400
    db.session.add(node)
    db.session.commit()
    return jsonify(node.to_dict()), 201


@api_bp.route("/api/nodes/<int:node_id>", methods=["PUT"])
def update_node(node_id):
    """Update an existing node's name / host / port / description."""
    node = Node.query.get_or_404(node_id)
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    host = data.get("host", "").strip()
    if not name or not host:
        return jsonify({"error": "name and host are required"}), 400

    # If the address changed, the cached online/offline status is stale.
    address_changed = host != node.host or int(data.get("agent_port", node.agent_port)) != node.agent_port

    node.name = name
    node.host = host
    node.agent_port = int(data.get("agent_port", node.agent_port))
    node.description = data.get("description", "").strip()
    if address_changed:
        node.status = "unknown"
    db.session.commit()
    return jsonify(node.to_dict())


@api_bp.route("/api/nodes/<int:node_id>", methods=["DELETE"])
def delete_node(node_id):
    node = Node.query.get_or_404(node_id)
    db.session.delete(node)
    db.session.commit()
    return jsonify({"message": "deleted"})


@api_bp.route("/api/nodes/<int:node_id>/health", methods=["GET"])
def node_health(node_id):
    """Check agent health on a node."""
    node = Node.query.get_or_404(node_id)
    import requests
    try:
        url = f"http://{node.host}:{node.agent_port}/agent/health"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            node.status = "online"
            node.last_seen_at = datetime.utcnow()
            db.session.commit()
            return jsonify({"status": "online", "agent": resp.json()})
        else:
            node.status = "offline"
            db.session.commit()
            return jsonify({"status": "offline", "http_code": resp.status_code}), 503
    except Exception as e:
        node.status = "offline"
        db.session.commit()
        return jsonify({"status": "offline", "error": str(e)}), 503


# ==================== Test Routes ====================

@api_bp.route("/api/tests", methods=["GET"])
def list_tests():
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    node_id = request.args.get("node_id", type=int)
    sort_field = request.args.get("sort", "started_at")
    sort_order = request.args.get("order", "desc")
    protocol = request.args.get("protocol", "", type=str).strip().lower()
    status = request.args.get("status", "", type=str).strip().lower()

    q = TestRun.query
    if node_id:
        q = q.filter((TestRun.client_node_id == node_id) | (TestRun.server_node_id == node_id))
    if protocol in ("tcp", "udp"):
        q = q.filter(TestRun.test_type == protocol)
    if status and status != "all":
        q = q.filter(TestRun.status == status)

    # Sorting: whitelist allowed columns to avoid injection via arbitrary field names.
    sort_columns = {
        "name": TestRun.name,
        "started_at": TestRun.started_at,
        "created_at": TestRun.created_at,
    }
    col = sort_columns.get(sort_field, TestRun.started_at)
    q = q.order_by(col.desc() if sort_order == "desc" else col.asc())

    pagination = q.paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for test in pagination.items:
        item = test.to_dict()
        # Summarize results
        iperf_results = IperfResult.query.filter_by(test_id=test.id).all()
        cps_results = CpsResult.query.filter_by(test_id=test.id).all()

        if iperf_results:
            bws = [r.summary_bits_per_sec for r in iperf_results if r.summary_bits_per_sec]
            # Prefer hardware NIC PPS (driver-level, accurate for SR-IOV) over
            # iperf3 avg_pps (which is 0 for TCP tests — iperf3 doesn't report
            # packet counts for TCP, only for UDP).
            avg_pps, peak_pps = _summarize_hardware_pps(test.id)
            item["avg_bw_mbps"] = round(sum(bws) / len(bws) / 1e6, 2) if bws else None
            item["peak_bw_mbps"] = round(max(bws) / 1e6, 2) if bws else None
            if avg_pps is None:
                # Fallback to iperf3 avg_pps (UDP only)
                pps_vals = [r.avg_pps for r in iperf_results if r.avg_pps]
                avg_pps = sum(pps_vals) / len(pps_vals) if pps_vals else None
            item["avg_pps_kpps"] = round(avg_pps / 1000, 2) if avg_pps else None
            item["peak_pps_kpps"] = round(peak_pps / 1000, 2) if peak_pps else None
        else:
            item["avg_bw_mbps"] = None
            item["peak_bw_mbps"] = None
            item["avg_pps_kpps"] = None
            item["peak_pps_kpps"] = None

        if cps_results:
            cps_vals = [r.cps for r in cps_results if r.cps]
            item["cps"] = round(sum(cps_vals) / len(cps_vals), 0) if cps_vals else None
            item["conns_attempted"] = sum(r.connections_attempted or 0 for r in cps_results)
            item["conns_succeeded"] = sum(r.connections_succeeded or 0 for r in cps_results)
        else:
            item["cps"] = None
            item["conns_attempted"] = None
            item["conns_succeeded"] = None

        items.append(item)

    return jsonify({
        "items": items,
        "total": pagination.total,
        "page": pagination.page,
        "per_page": pagination.per_page,
        "pages": pagination.pages,
    })


@api_bp.route("/api/tests/<int:test_id>", methods=["GET"])
def get_test(test_id):
    test = TestRun.query.get_or_404(test_id)
    return jsonify(test.to_dict())


@api_bp.route("/api/tests/<int:test_id>", methods=["DELETE"])
def delete_test(test_id):
    test = TestRun.query.get_or_404(test_id)
    db.session.delete(test)
    db.session.commit()
    return jsonify({"message": "deleted"})


@api_bp.route("/api/tests/start", methods=["POST"])
def start_test():
    data = request.get_json() or {}
    client_node_id = data.get("client_node_id")
    server_node_id = data.get("server_node_id")

    if not client_node_id or not server_node_id:
        return jsonify({"error": "client_node_id and server_node_id are required"}), 400

    test = TestRun(
        name=(data.get("name") or "").strip(),
        client_node_id=client_node_id,
        server_node_id=server_node_id,
        test_type=data.get("test_type", "tcp"),
        engine=data.get("engine", "iperf3"),
        duration_sec=int(data.get("duration_sec", 10)),
        parallel_streams=int(data.get("parallel_streams", 1)),
        bandwidth_limit=data.get("bandwidth_limit"),
        reverse_mode=bool(data.get("reverse_mode", False)),
        bidirectional=bool(data.get("bidirectional", False)),
        measure_cps=bool(data.get("measure_cps", False)),
        measure_pps=bool(data.get("measure_pps", False)),
        measure_concurrent=bool(data.get("measure_concurrent", False)),
        packet_size=int(data.get("packet_size", 64)),
        cps_rate=int(data.get("cps_rate", 10000)),
        concurrent_count=int(data.get("concurrent_count", 10000)),
    )
    db.session.add(test)
    db.session.commit()

    # Start orchestration in background thread
    thread = threading.Thread(target=orchestrator.dispatch_test, args=(test.id,), daemon=True)
    thread.start()

    return jsonify({"test_id": test.id, "status": "started"}), 202


@api_bp.route("/api/tests/<int:test_id>/stop", methods=["POST"])
def stop_test(test_id):
    test = TestRun.query.get_or_404(test_id)
    if test.status != "running":
        return jsonify({"error": "test is not running"}), 400
    orchestrator.stop_test(test_id)
    return jsonify({"message": "stop signal sent"})


# ==================== Results Routes ====================

@api_bp.route("/api/tests/<int:test_id>/results", methods=["GET"])
def get_results(test_id):
    test = TestRun.query.get_or_404(test_id)
    iperf_results = IperfResult.query.filter_by(test_id=test_id).all()
    dperf_results = DperfResult.query.filter_by(test_id=test_id).all()
    cps_results = CpsResult.query.filter_by(test_id=test_id).all()

    # Aggregated summaries for the dashboard cards
    avg_pps, peak_pps = _summarize_hardware_pps(test_id)
    pps_summary = {
        "avg_pps": round(avg_pps, 0) if avg_pps is not None else None,
        "peak_pps": round(peak_pps, 0) if peak_pps is not None else None,
        "avg_pps_kpps": round(avg_pps / 1000, 2) if avg_pps is not None else None,
        "peak_pps_kpps": round(peak_pps / 1000, 2) if peak_pps is not None else None,
    }

    cps_summary = None
    if cps_results:
        cps_vals = [r.cps for r in cps_results if r.cps]
        cps_summary = {
            "cps": round(sum(cps_vals) / len(cps_vals), 0) if cps_vals else None,
            "conns_attempted": sum(r.connections_attempted or 0 for r in cps_results),
            "conns_succeeded": sum(r.connections_succeeded or 0 for r in cps_results),
        }

    return jsonify({
        "test": test.to_dict(),
        "iperf_results": [r.to_dict() for r in iperf_results],
        "dperf_results": [r.to_dict() for r in dperf_results],
        "cps_results": [r.to_dict() for r in cps_results],
        "pps_summary": pps_summary,
        "cps_summary": cps_summary,
    })


@api_bp.route("/api/tests/<int:test_id>/results/<int:result_id>/raw", methods=["GET"])
def get_raw_json(test_id, result_id):
    """Download raw iperf3 JSON output."""
    result = IperfResult.query.get_or_404(result_id)
    if result.test_id != test_id:
        return jsonify({"error": "result does not belong to test"}), 400
    return Response(
        result.raw_json or "{}",
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=iperf3_test{test_id}_node{result.node_id}.json"}
    )


@api_bp.route("/api/tests/<int:test_id>/cps", methods=["GET"])
def get_cps(test_id):
    results = CpsResult.query.filter_by(test_id=test_id).all()
    return jsonify([r.to_dict() for r in results])


@api_bp.route("/api/tests/<int:test_id>/hardware", methods=["GET"])
def get_hardware(test_id):
    node_id = request.args.get("node_id", type=int)
    limit = request.args.get("limit", 1000, type=int)

    q = HardwareSnapshot.query.filter_by(test_id=test_id)
    if node_id:
        q = q.filter_by(node_id=node_id)

    snapshots = q.order_by(HardwareSnapshot.timestamp.asc()).limit(limit).all()
    return jsonify([s.to_dict() for s in snapshots])


# ==================== SSE Stream ====================

@api_bp.route("/api/stream/<int:test_id>")
def stream(test_id):
    """Server-Sent Events stream for real-time test metrics."""
    test = TestRun.query.get_or_404(test_id)
    return Response(
        sse_manager.generator(test_id),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
