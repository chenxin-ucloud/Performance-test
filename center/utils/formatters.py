"""Data formatting helpers."""


def format_bits(bits):
    """Format bits per second to human readable string."""
    if bits is None:
        return "N/A"
    if bits >= 1e9:
        return f"{bits / 1e9:.2f} Gbps"
    elif bits >= 1e6:
        return f"{bits / 1e6:.2f} Mbps"
    elif bits >= 1e3:
        return f"{bits / 1e3:.2f} Kbps"
    return f"{bits:.2f} bps"


def format_bytes(value):
    """Format bytes to human readable string."""
    if value is None:
        return "N/A"
    if value >= 1024 ** 3:
        return f"{value / (1024 ** 3):.2f} GB"
    elif value >= 1024 ** 2:
        return f"{value / (1024 ** 2):.2f} MB"
    elif value >= 1024:
        return f"{value / 1024:.2f} KB"
    return f"{value:.2f} B"


def format_pps(pps):
    """Format packets per second."""
    if pps is None:
        return "N/A"
    if pps >= 1e6:
        return f"{pps / 1e6:.2f} Mpps"
    elif pps >= 1e3:
        return f"{pps / 1e3:.2f} Kpps"
    return f"{pps:.2f} pps"


def format_cps(cps):
    """Format connections per second."""
    if cps is None:
        return "N/A"
    if cps >= 1e6:
        return f"{cps / 1e6:.2f} Mcps"
    elif cps >= 1e3:
        return f"{cps / 1e3:.2f} Kcps"
    return f"{cps:.2f} cps"


def format_percent(value):
    """Format a percentage value."""
    if value is None:
        return "N/A"
    return f"{value:.1f}%"
