"""
NetFlow v5 UDP collector.
Listens on UDP port 2055 (or configured port), parses v5 flow records,
and stores aggregated bytes/packets per source IP into metric_history.
"""
import logging
import socket
import struct
import threading
from datetime import datetime

log = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_running = False

# NetFlow v5 header: 24 bytes
# Flow record: 48 bytes
NF5_HEADER_FMT = "!HHIIIIBBH"  # 24 bytes
NF5_RECORD_FMT = "!IIIHHIIIIHHBBBBHHBBH"  # 48 bytes

def _parse_v5(data: bytes) -> list[dict]:
    """Parse a NetFlow v5 UDP packet. Returns list of flow dicts."""
    if len(data) < 24:
        return []
    try:
        header = struct.unpack(NF5_HEADER_FMT, data[:24])
        version, count = header[0], header[1]
        if version != 5:
            return []
        flows = []
        offset = 24
        for _ in range(min(count, 30)):  # cap at 30 records per packet
            if offset + 48 > len(data):
                break
            rec = struct.unpack(NF5_RECORD_FMT, data[offset:offset + 48])
            src_ip = socket.inet_ntoa(struct.pack("!I", rec[0]))
            dst_ip = socket.inet_ntoa(struct.pack("!I", rec[1]))
            packets = rec[7]
            octets = rec[8]
            src_port = rec[10]
            dst_port = rec[11]
            proto = rec[14]
            flows.append({
                "src_ip": src_ip, "dst_ip": dst_ip,
                "packets": packets, "octets": octets,
                "src_port": src_port, "dst_port": dst_port,
                "proto": proto,
            })
            offset += 48
        return flows
    except struct.error:
        return []


def _listen(port: int, crud_module):
    global _running
    log.info("NetFlow v5 collector listening on UDP :%d", port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(2.0)
    try:
        sock.bind(("0.0.0.0", port))
    except OSError as e:
        log.error("Cannot bind NetFlow UDP port %d: %s", port, e)
        return

    while _running:
        try:
            data, addr = sock.recvfrom(4096)
        except socket.timeout:
            continue
        except OSError:
            break

        flows = _parse_v5(data)
        if not flows:
            continue

        # Find device by source IP
        sender_ip = addr[0]
        devices = crud_module.get_all_devices()
        device = next((d for d in devices if d["ip_address"] == sender_ip), None)
        if not device:
            continue

        # Aggregate flows
        total_octets = sum(f["octets"] for f in flows)
        total_packets = sum(f["packets"] for f in flows)
        now = datetime.utcnow().isoformat()
        crud_module.add_metric(device["id"], "netflow_octets",
                               float(total_octets), f"{total_octets} B", "B", now)
        crud_module.add_metric(device["id"], "netflow_packets",
                               float(total_packets), str(total_packets), "pkt", now)
        log.debug("NetFlow from %s (%s): %d flows, %d octets",
                  sender_ip, device["name"], len(flows), total_octets)

    sock.close()
    log.info("NetFlow collector stopped.")


def start_netflow_collector(port: int = 2055):
    """Start the NetFlow v5 UDP listener in a background thread."""
    global _thread, _running
    if _running:
        return
    from app import crud
    _running = True
    _thread = threading.Thread(target=_listen, args=(port, crud), daemon=True, name="netflow-collector")
    _thread.start()


def stop_netflow_collector():
    global _running
    _running = False
