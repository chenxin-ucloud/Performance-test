"""Agent REST API routes."""
from flask import Blueprint, request, jsonify

from services.iperf3_runner import iperf3_runner
from services.dperf_runner import dperf_runner
from services.cps_tester import cps_tester
from services.metrics_collector import metrics_collector
from services.task_manager import task_manager

agent_api_bp = Blueprint("agent_api", __name__, url_prefix="/agent")


# ==================== Health ====================

@agent_api_bp.route("/health", methods=["GET"])
def health():
    return jsonify(task_manager.health())


# ==================== Test Engines ====================

@agent_api_bp.route("/engines", methods=["GET"])
def list_engines():
    """Return available test engines and their capabilities."""
    return jsonify({
        "iperf3": {"available": True, "capabilities": ["bps", "bandwidth"]},
        "dperf": {
            "available": dperf_runner._dperf_available,
            "capabilities": ["pps", "cps", "concurrent"],
        },
    })


# ==================== iperf3 ====================

@agent_api_bp.route("/iperf3/server/start", methods=["POST"])
def iperf3_server_start():
    data = request.get_json() or {}
    port = data.get("port", 5201)
    return jsonify(iperf3_runner.start_server(port))


@agent_api_bp.route("/iperf3/server/stop", methods=["POST"])
def iperf3_server_stop():
    return jsonify(iperf3_runner.stop_server())


@agent_api_bp.route("/iperf3/client/start", methods=["POST"])
def iperf3_client_start():
    data = request.get_json() or {}
    result = iperf3_runner.start_client(
        target_host=data.get("target_host"),
        target_port=data.get("target_port", 5201),
        duration=data.get("duration", 10),
        streams=data.get("streams", 1),
        bandwidth=data.get("bandwidth"),
        reverse=data.get("reverse", False),
        udp=data.get("udp", False),
    )
    return jsonify(result)


@agent_api_bp.route("/iperf3/client/stop", methods=["POST"])
def iperf3_client_stop():
    return jsonify(iperf3_runner.stop_client())


@agent_api_bp.route("/iperf3/client/result", methods=["GET"])
def iperf3_client_result():
    return jsonify(iperf3_runner.get_client_result())


# ==================== dperf ====================

@agent_api_bp.route("/dperf/server/start", methods=["POST"])
def dperf_server_start():
    data = request.get_json() or {}
    port = data.get("port", 80)
    return jsonify(dperf_runner.start_server(port))


@agent_api_bp.route("/dperf/server/stop", methods=["POST"])
def dperf_server_stop():
    return jsonify(dperf_runner.stop_server())


@agent_api_bp.route("/dperf/pps", methods=["POST"])
def dperf_pps():
    """Run dperf PPS (packets per second) test."""
    data = request.get_json() or {}
    result = dperf_runner.run_pps_test(
        target_host=data.get("target_host"),
        target_port=data.get("target_port", 80),
        duration=data.get("duration", 10),
        packet_size=data.get("packet_size", 64),
    )
    return jsonify(result)


@agent_api_bp.route("/dperf/cps", methods=["POST"])
def dperf_cps():
    """Run dperf CPS (connections per second) test."""
    data = request.get_json() or {}
    result = dperf_runner.run_cps_test(
        target_host=data.get("target_host"),
        target_port=data.get("target_port", 80),
        duration=data.get("duration", 5),
        rate=data.get("rate", 10000),
    )
    return jsonify(result)


@agent_api_bp.route("/dperf/concurrent", methods=["POST"])
def dperf_concurrent():
    """Run dperf concurrent connections test."""
    data = request.get_json() or {}
    result = dperf_runner.run_concurrent_test(
        target_host=data.get("target_host"),
        target_port=data.get("target_port", 80),
        duration=data.get("duration", 10),
        concurrent=data.get("concurrent", 10000),
    )
    return jsonify(result)


# ==================== CPS (legacy fallback) ====================

@agent_api_bp.route("/cps/start", methods=["POST"])
def cps_start():
    data = request.get_json() or {}
    cps_tester.start(
        target_host=data.get("target_host"),
        target_port=data.get("target_port", 5201),
        duration=data.get("duration", 5),
    )
    import time
    for _ in range(50):
        result = cps_tester.get_result()
        if result:
            return jsonify(result)
        time.sleep(0.1)
    return jsonify({"status": "timeout"}), 504


@agent_api_bp.route("/cps/stop", methods=["POST"])
def cps_stop():
    return jsonify(cps_tester.stop())


# ==================== Metrics ====================

@agent_api_bp.route("/metrics/start", methods=["POST"])
def metrics_start():
    data = request.get_json() or {}
    test_id = data.get("test_id", 0)
    return jsonify(metrics_collector.start(test_id))


@agent_api_bp.route("/metrics/stop", methods=["POST"])
def metrics_stop():
    data = request.get_json() or {}
    test_id = data.get("test_id", 0)
    return jsonify(metrics_collector.stop(test_id))


@agent_api_bp.route("/metrics/current", methods=["GET"])
def metrics_current():
    return jsonify(metrics_collector.get_current())


@agent_api_bp.route("/metrics/series", methods=["GET"])
def metrics_series():
    test_id = request.args.get("test_id", 0, type=int)
    return jsonify(metrics_collector.get_series(test_id))


# ==================== Stop All ====================

@agent_api_bp.route("/stop", methods=["POST"])
def stop_all():
    return jsonify(task_manager.stop_all())
