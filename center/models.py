"""SQLAlchemy database models for the center service."""
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
import json

db = SQLAlchemy()


class Node(db.Model):
    """A remote test node running the agent."""

    __tablename__ = "nodes"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(128), nullable=False)
    host = db.Column(db.String(256), nullable=False)
    agent_port = db.Column(db.Integer, default=5001, nullable=False)
    description = db.Column(db.Text, default="")
    status = db.Column(db.String(32), default="unknown")  # online, offline, unknown
    last_seen_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    client_tests = db.relationship(
        "TestRun", foreign_keys="TestRun.client_node_id", back_populates="client_node"
    )
    server_tests = db.relationship(
        "TestRun", foreign_keys="TestRun.server_node_id", back_populates="server_node"
    )
    hardware_snapshots = db.relationship("HardwareSnapshot", back_populates="node")
    iperf_results = db.relationship("IperfResult", back_populates="node")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "host": self.host,
            "agent_port": self.agent_port,
            "description": self.description,
            "status": self.status,
            "last_seen_at": self.last_seen_at.isoformat() if self.last_seen_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TestRun(db.Model):
    """A single performance test session."""

    __tablename__ = "test_runs"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(256), nullable=True)
    client_node_id = db.Column(db.Integer, db.ForeignKey("nodes.id"), nullable=False)
    server_node_id = db.Column(db.Integer, db.ForeignKey("nodes.id"), nullable=False)

    # Test configuration
    test_type = db.Column(db.String(16), default="tcp")  # tcp, udp
    duration_sec = db.Column(db.Integer, default=10)
    parallel_streams = db.Column(db.Integer, default=1)
    bandwidth_limit = db.Column(db.String(32), nullable=True)
    reverse_mode = db.Column(db.Boolean, default=False)
    bidirectional = db.Column(db.Boolean, default=False)
    measure_cps = db.Column(db.Boolean, default=False)

    # Status tracking
    status = db.Column(db.String(32), default="pending")
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    client_node = db.relationship("Node", foreign_keys=[client_node_id], back_populates="client_tests")
    server_node = db.relationship("Node", foreign_keys=[server_node_id], back_populates="server_tests")
    iperf_results = db.relationship("IperfResult", back_populates="test", cascade="all, delete-orphan")
    cps_results = db.relationship("CpsResult", back_populates="test", cascade="all, delete-orphan")
    hardware_snapshots = db.relationship("HardwareSnapshot", back_populates="test", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "client_node_id": self.client_node_id,
            "server_node_id": self.server_node_id,
            "client_node": self.client_node.to_dict() if self.client_node else None,
            "server_node": self.server_node.to_dict() if self.server_node else None,
            "test_type": self.test_type,
            "duration_sec": self.duration_sec,
            "parallel_streams": self.parallel_streams,
            "bandwidth_limit": self.bandwidth_limit,
            "reverse_mode": self.reverse_mode,
            "bidirectional": self.bidirectional,
            "measure_cps": self.measure_cps,
            "status": self.status,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }


class IperfResult(db.Model):
    """Parsed iperf3 results per node per test."""

    __tablename__ = "iperf_results"

    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey("test_runs.id"), nullable=False)
    node_id = db.Column(db.Integer, db.ForeignKey("nodes.id"), nullable=False)
    role = db.Column(db.String(16), default="client")  # client, server

    raw_json = db.Column(db.Text, nullable=True)
    summary_bits_per_sec = db.Column(db.Float, nullable=True)
    summary_bytes = db.Column(db.BigInteger, nullable=True)
    summary_packets = db.Column(db.BigInteger, nullable=True)
    avg_pps = db.Column(db.Float, nullable=True)
    retransmits = db.Column(db.Integer, nullable=True)
    jitter_ms = db.Column(db.Float, nullable=True)
    lost_packets = db.Column(db.Integer, nullable=True)
    lost_percent = db.Column(db.Float, nullable=True)

    # Relationships
    test = db.relationship("TestRun", back_populates="iperf_results")
    node = db.relationship("Node", back_populates="iperf_results")

    def to_dict(self):
        return {
            "id": self.id,
            "test_id": self.test_id,
            "node_id": self.node_id,
            "node_name": self.node.name if self.node else None,
            "role": self.role,
            "summary_bits_per_sec": self.summary_bits_per_sec,
            "summary_bytes": self.summary_bytes,
            "summary_packets": self.summary_packets,
            "avg_pps": self.avg_pps,
            "retransmits": self.retransmits,
            "jitter_ms": self.jitter_ms,
            "lost_packets": self.lost_packets,
            "lost_percent": self.lost_percent,
        }


class CpsResult(db.Model):
    """CPS measurement results."""

    __tablename__ = "cps_results"

    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey("test_runs.id"), nullable=False)
    source_node_id = db.Column(db.Integer, db.ForeignKey("nodes.id"), nullable=False)
    target_node_id = db.Column(db.Integer, db.ForeignKey("nodes.id"), nullable=False)

    connections_attempted = db.Column(db.Integer, nullable=True)
    connections_succeeded = db.Column(db.Integer, nullable=True)
    duration_ms = db.Column(db.Integer, nullable=True)
    cps = db.Column(db.Float, nullable=True)
    measured_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    test = db.relationship("TestRun", back_populates="cps_results")
    source_node = db.relationship("Node", foreign_keys=[source_node_id])
    target_node = db.relationship("Node", foreign_keys=[target_node_id])

    def to_dict(self):
        return {
            "id": self.id,
            "test_id": self.test_id,
            "source_node_id": self.source_node_id,
            "source_node_name": self.source_node.name if self.source_node else None,
            "target_node_id": self.target_node_id,
            "target_node_name": self.target_node.name if self.target_node else None,
            "connections_attempted": self.connections_attempted,
            "connections_succeeded": self.connections_succeeded,
            "duration_ms": self.duration_ms,
            "cps": self.cps,
            "measured_at": self.measured_at.isoformat() if self.measured_at else None,
        }


class HardwareSnapshot(db.Model):
    """Per-second hardware metrics from each node during a test."""

    __tablename__ = "hardware_snapshots"

    id = db.Column(db.Integer, primary_key=True)
    test_id = db.Column(db.Integer, db.ForeignKey("test_runs.id"), nullable=False)
    node_id = db.Column(db.Integer, db.ForeignKey("nodes.id"), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    cpu_percent = db.Column(db.Float, nullable=True)
    cpu_per_core = db.Column(db.Text, nullable=True)  # JSON string
    memory_percent = db.Column(db.Float, nullable=True)
    memory_used_mb = db.Column(db.Float, nullable=True)
    memory_total_mb = db.Column(db.Float, nullable=True)
    network_rx_mb = db.Column(db.Float, nullable=True)
    network_tx_mb = db.Column(db.Float, nullable=True)

    # Relationships
    test = db.relationship("TestRun", back_populates="hardware_snapshots")
    node = db.relationship("Node", back_populates="hardware_snapshots")

    def to_dict(self):
        return {
            "id": self.id,
            "test_id": self.test_id,
            "node_id": self.node_id,
            "node_name": self.node.name if self.node else None,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "cpu_percent": self.cpu_percent,
            "cpu_per_core": json.loads(self.cpu_per_core) if self.cpu_per_core else None,
            "memory_percent": self.memory_percent,
            "memory_used_mb": self.memory_used_mb,
            "memory_total_mb": self.memory_total_mb,
            "network_rx_mb": self.network_rx_mb,
            "network_tx_mb": self.network_tx_mb,
        }
