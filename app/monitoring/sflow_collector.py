"""
sFlow v5 UDP collector.
Listens on UDP port 6343, parses sFlow v5 sample datagrams,
and stores interface counter samples as metrics.
"""
import logging
import socket
import struct
import threading
from datetime import datetime

log = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_running = False


def _parse_sflow(data: bytes, agent_ip: str) -> dict | None:
    """
    Parse sFlow v5 datagram header.
    Returns agent info and number of samples or None on error.
    """
    if len(data) < 28:
        return None
    try:
        version = struct.unpack("!I", data[:4])[0]
        if version != 5:
            return None
        # agent IP type: 1=IPv4, 2=IPv6
        ip_version = struct.unpack("!I", data[4:8])[0]
        if ip_version == 1:
            agent_addr = socket.inet_ntoa(data[8:12])
            offset = 12
        else:
            # IPv6 - skip
            offset = 24
            agent_addr = agent_ip

        sub_agent = struct.unpack("!I", data[offset:offset + 4])[0]
        seq_num = struct.unpack("!I", data[offset + 4:offset + 8])[0]
        uptime = struct.unpack("!I", data[offset + 8:offset + 12])[0]
        num_samples = struct.unpack("!I", data[offset + 12:offset + 16])[0]
        return {
            "agent_ip": agent_addr,
            "seq": seq_num,
            "uptime_ms": uptime,
            "num_samples": num_samples,
        }
    except struct.error:
        return None


def _listen(port: int, crud_module):
    global _running
    log.info("sFlow v5 collector listening on UDP :%d", port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(2.0)
    try:
        sock.bind(("0.0.0.0", port))
    except OSError as e:
        log.error("Cannot bind sFlow UDP port %d: %s", port, e)
        return

    while _running:
        try:
            data, addr = sock.recvfrom(8192)
        except socket.timeout:
            continue
        except OSError:
            break

        sender_ip = addr[0]
        info = _parse_sflow(data, sender_ip)
        if not info:
            continue

        # Find device by source IP
        devices = crud_module.get_all_devices()
        device = next((d for d in devices if d["ip_address"] == sender_ip), None)
        if not device:
            continue

        now = datetime.utcnow().isoformat()
        crud_module.add_metric(device["id"], "sflow_samples",
                               float(info["num_samples"]),
                               f"{info['num_samples']} samples",
                               "samples", now)
        crud_module.add_metric(device["id"], "sflow_uptime_ms",
                               float(info["uptime_ms"]),
                               str(info["uptime_ms"]),
                               "ms", now)
        log.debug("sFlow from %s (%s): %d samples, uptime %dms",
                  sender_ip, device["name"], info["num_samples"], info["uptime_ms"])

    sock.close()
    log.info("sFlow collector stopped.")


def start_sflow_collector(port: int = 6343):
    """Start the sFlow v5 UDP listener in a background thread."""
    global _thread, _running
    if _running:
        return
    from app import crud
    _running = True
    _thread = threading.Thread(target=_listen, args=(port, crud), daemon=True, name="sflow-collector")
    _thread.start()


def stop_sflow_collector():
    global _running
    _running = False
