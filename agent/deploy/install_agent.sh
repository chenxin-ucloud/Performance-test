#!/bin/bash
# PerfTest Agent One-Line Install Script
set -e

INSTALL_DIR="/opt/perftest-agent"
SERVICE_FILE="/etc/systemd/system/perftest-agent.service"

DPKG=""
if command -v dpkg &> /dev/null; then
    DPKG=$(which dpkg)
fi

echo "=== PerfTest Agent Installer ==="

# Check root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo)"
    exit 1
fi

# Install dependencies
if command -v apt-get &> /dev/null; then
    apt-get update -qq
    apt-get install -y -qq python3 python3-pip iperf3 ethtool
elif command -v yum &> /dev/null; then
    yum install -y -q python3 python3-pip iperf3 ethtool
elif command -v dnf &> /dev/null; then
    dnf install -y -q python3 python3-pip iperf3 ethtool
else
    echo "Unsupported package manager. Please install python3, pip, iperf3, ethtool manually."
    exit 1
fi

# Create install directory
mkdir -p "$INSTALL_DIR"

# Determine agent source directory
AGENT_SRC=""
if [ -f "agent.py" ]; then
    AGENT_SRC="."
    echo "Detected agent.py in current directory."
elif [ -d "agent" ] && [ -f "agent/agent.py" ]; then
    AGENT_SRC="agent"
    echo "Detected agent/ subdirectory."
else
    echo "ERROR: agent.py not found."
    echo "Please run this script from the agent/ directory or the project root."
    exit 1
fi

cp -r "$AGENT_SRC/"* "$INSTALL_DIR/"

# Install Python dependencies
pip3 install -q -r "$INSTALL_DIR/requirements.txt"

# ==================== Optional: Build and install dperf ====================
DPERF_INSTALL=${DPERF_INSTALL:-"auto"}  # auto, yes, no

install_dperf() {
    echo "=== Installing dperf (DPDK-based high-performance tester) ==="

    # Install DPDK dependencies
    if command -v apt-get &> /dev/null; then
        apt-get install -y -qq meson ninja-build pkg-config libnuma-dev python3-pyelftools \
            build-essential libibverbs-dev librdmacm-dev libpcap-dev 2>/dev/null || true
    elif command -v yum &> /dev/null || command -v dnf &> /dev/null; then
        dnf install -y -q meson ninja-build pkgconfig numactl-devel python3-pyelftools \
            gcc gcc-c++ make libibverbs-devel librdmacm-devel libpcap-devel 2>/dev/null || true
    fi

    # Clone and build dperf
    DPERF_BUILD_DIR="/tmp/dperf-build"
    rm -rf "$DPERF_BUILD_DIR"
    mkdir -p "$DPERF_BUILD_DIR"
    cd "$DPERF_BUILD_DIR"

    # Try git clone; if network fails, skip
    if git clone --depth 1 https://github.com/baidu/dperf.git 2>/dev/null; then
        cd dperf
        make
        if [ -f "build/dperf" ]; then
            cp build/dperf /usr/local/bin/dperf
            chmod +x /usr/local/bin/dperf
            echo "dperf installed to /usr/local/bin/dperf"
        else
            echo "WARNING: dperf build failed. PPS/CPS/concurrent tests will fall back to Python."
        fi
    else
        echo "WARNING: Could not clone dperf repository. Skipping."
    fi

    # Cleanup
    rm -rf "$DPERF_BUILD_DIR"
    cd "$INSTALL_DIR"
}

if [ "$DPERF_INSTALL" = "yes" ]; then
    install_dperf
elif [ "$DPERF_INSTALL" = "auto" ]; then
    # Check if we have a compiler and meson
    if command -v gcc &> /dev/null && command -v meson &> /dev/null; then
        install_dperf
    else
        echo "Compiler or meson not available, skipping dperf build."
    fi
fi

# ==================== Install systemd service ====================
SERVICE_SRC=""
if [ -f "$INSTALL_DIR/deploy/agent.service" ]; then
    SERVICE_SRC="$INSTALL_DIR/deploy/agent.service"
elif [ -f "$AGENT_SRC/deploy/agent.service" ]; then
    SERVICE_SRC="$AGENT_SRC/deploy/agent.service"
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

# Verify engines
if command -v dperf &> /dev/null; then
    echo "Engines: iperf3 + dperf"
else
    echo "Engines: iperf3 (dperf not installed - run with DPERF_INSTALL=yes to build)"
fi
