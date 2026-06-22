"""Utility: Parse iperf3 JSON output."""
import json


def parse_iperf3_json(raw_json_text):
    """Parse iperf3 -J JSON output into a structured dict."""
    data = json.loads(raw_json_text)
    result = {
        "start_info": {},
        "intervals": [],
        "summary_sent": {},
        "summary_received": {},
        "cpu_utilization_percent": {},
    }

    start = data.get("start", {})
    result["start_info"] = {
        "version": start.get("version", ""),
        "system_info": start.get("system_info", ""),
        "timestamp": start.get("timestamp", {}),
        "test_start": start.get("test_start", {}),
    }

    # Intervals
    intervals = data.get("intervals", [])
    for interval in intervals:
        sums = interval.get("sum", {})
        interval_data = {
            "start": interval.get("sum", {}).get("start", 0),
            "end": interval.get("sum", {}).get("end", 0),
            "seconds": interval.get("sum", {}).get("seconds", 0),
            "bytes": sums.get("bytes", 0),
            "bits_per_second": sums.get("bits_per_second", 0),
            "packets": sums.get("packets", 0),
            "pps": calculate_pps(sums.get("packets", 0), sums.get("seconds", 1)),
            "omitted": sums.get("omitted", False),
        }
        if "jitter_ms" in sums:
            interval_data["jitter_ms"] = sums.get("jitter_ms", 0)
        if "lost_packets" in sums:
            interval_data["lost_packets"] = sums.get("lost_packets", 0)
        if "lost_percent" in sums:
            interval_data["lost_percent"] = sums.get("lost_percent", 0)
        result["intervals"].append(interval_data)

    # End summary
    end_data = data.get("end", {})
    if "sum_sent" in end_data:
        sent = end_data["sum_sent"]
        result["summary_sent"] = {
            "bytes": sent.get("bytes", 0),
            "bits_per_second": sent.get("bits_per_second", 0),
            "packets": sent.get("packets", 0),
            "pps": calculate_pps(sent.get("packets", 0), sent.get("seconds", 1)),
            "retransmits": sent.get("retransmits", 0),
        }
    if "sum_received" in end_data:
        received = end_data["sum_received"]
        result["summary_received"] = {
            "bytes": received.get("bytes", 0),
            "bits_per_second": received.get("bits_per_second", 0),
            "packets": received.get("packets", 0),
            "pps": calculate_pps(received.get("packets", 0), received.get("seconds", 1)),
            "jitter_ms": received.get("jitter_ms", 0),
            "lost_packets": received.get("lost_packets", 0),
            "lost_percent": received.get("lost_percent", 0),
        }

    # CPU utilization
    cpu = end_data.get("cpu_utilization_percent", {})
    if cpu:
        result["cpu_utilization_percent"] = {
            "host_total": cpu.get("host_total", 0),
            "remote_total": cpu.get("remote_total", 0),
        }

    return result


def calculate_pps(packets, seconds):
    """Calculate packets per second."""
    if seconds and seconds > 0:
        return packets / seconds
    return 0.0


def extract_summary_metrics(parsed_result):
    """Extract the most useful summary metrics from parsed iperf3 result."""
    sent = parsed_result.get("summary_sent", {})
    received = parsed_result.get("summary_received", {})

    # Prefer received (server-side) for bandwidth, fallback to sent
    bps = received.get("bits_per_second") or sent.get("bits_per_second", 0)
    total_bytes = received.get("bytes") or sent.get("bytes", 0)
    packets = received.get("packets") or sent.get("packets", 0)
    pps = received.get("pps") or sent.get("pps", 0)
    retransmits = sent.get("retransmits", 0)

    return {
        "bits_per_second": bps,
        "bytes": total_bytes,
        "packets": packets,
        "pps": pps,
        "retransmits": retransmits,
        "jitter_ms": received.get("jitter_ms", 0),
        "lost_packets": received.get("lost_packets", 0),
        "lost_percent": received.get("lost_percent", 0),
    }
