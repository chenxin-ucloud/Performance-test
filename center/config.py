"""Center service configuration."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Flask
SECRET_KEY = os.environ.get("SECRET_KEY", "perftest-secret-key-change-me")
DEBUG = os.environ.get("DEBUG", "true").lower() == "true"

# Database
SQLALCHEMY_DATABASE_URI = os.environ.get(
    "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'perftest.db')}"
)
SQLALCHEMY_TRACK_MODIFICATIONS = False

# Center server
CENTER_HOST = os.environ.get("CENTER_HOST", "0.0.0.0")
CENTER_PORT = int(os.environ.get("CENTER_PORT", 5002))

# Agent polling
AGENT_POLL_INTERVAL = float(os.environ.get("AGENT_POLL_INTERVAL", "1.0"))
AGENT_HEALTH_TIMEOUT = int(os.environ.get("AGENT_HEALTH_TIMEOUT", "10"))
AGENT_CONNECT_TIMEOUT = float(os.environ.get("AGENT_CONNECT_TIMEOUT", "10"))
AGENT_OFFLINE_THRESHOLD = int(os.environ.get("AGENT_OFFLINE_THRESHOLD", "30"))

# Test defaults
DEFAULT_IPERF3_PORT = 5201
