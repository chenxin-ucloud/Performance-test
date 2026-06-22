"""Agent configuration."""
import os

# Agent server
AGENT_HOST = os.environ.get("AGENT_HOST", "0.0.0.0")
AGENT_PORT = int(os.environ.get("AGENT_PORT", 5002))

# Metrics collection
METRICS_INTERVAL = float(os.environ.get("METRICS_INTERVAL", "1.0"))
METRICS_MAX_SNAPSHOTS = int(os.environ.get("METRICS_MAX_SNAPSHOTS", "300"))

# CPS tester
CPS_CONNECTION_TIMEOUT = float(os.environ.get("CPS_CONNECTION_TIMEOUT", "2.0"))
CPS_WORKER_THREADS = int(os.environ.get("CPS_WORKER_THREADS", "50"))
