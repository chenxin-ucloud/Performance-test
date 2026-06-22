#!/bin/bash
# PerfTest Agent One-Line Install Script
set -e

INSTALL_DIR="/opt/perftest-agent"
SERVICE_FILE="/etc/systemd/system/perftest-agent.service"

echo "=== PerfTest Agent Installer ==="

# Check root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

# Install dependencies
if command -v apt-get &> /dev/null; then
    apt-get update -qq
    apt-get install -y -qq python3 python3-pip iperf3
elif command -v yum &> /dev/null; then
    yum install -y -q python3 python3-pip iperf3
elif command -v dnf &> /dev/null; then
    dnf install -y -q python3 python3-pip iperf3
else
    echo "Unsupported package manager. Please install python3, pip, and iperf3 manually."
    exit 1
fi

# Create install directory
mkdir -p "$INSTALL_DIR"

# NOTE: In production, you would download agent files from the center server or a git repo.
# For this installer to work, the agent directory should be copied/scp'd to the node first.
if [ ! -f "agent.py" ]; then
    echo "ERROR: agent.py not found in current directory."
    echo "Please copy the agent/ directory to this machine first, then run this script from inside it."
    exit 1
fi

cp -r . "$INSTALL_DIR/"

# Install Python dependencies
pip3 install -q -r "$INSTALL_DIR/requirements.txt"

# Install systemd service
SERVICE_SRC=""
if [ -f "./deploy/agent.service" ]; then
    SERVICE_SRC="./deploy/agent.service"
elif [ -f "../deploy/agent.service" ]; then
    SERVICE_SRC="../deploy/agent.service"
else
    echo "ERROR: deploy/agent.service not found."
    exit 1
fi
cp "$SERVICE_SRC" "$SERVICE_FILE"

# Reload and start
systemctl daemon-reload
systemctl enable perftest-agent
systemctl start perftest-agent

echo "=== Agent installed successfully ==="
echo "Status: $(systemctl is-active perftest-agent)"
echo "Logs: journalctl -u perftest-agent -f"
echo "Config: $INSTALL_DIR/config.py"
