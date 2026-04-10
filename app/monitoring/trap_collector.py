"""
SNMP Trap receiver (UDP port 162, configurable).
Listens for SNMP v1 and v2c traps, matches sender IP to known devices,
stores traps in snmp_traps table and triggers widget notifications.
"""
import logging
import socket
import threading
from datetime import datetime

log = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_running = False


def _decode_trap(data: bytes) -> dict:
    """
    Decode an SNMP v1 or v2c trap PDU.
    Returns dict: version, community, trap_oid, varbinds (list of {oid, value}).
    Falls back to raw-hex on parse errors.
    """
    result = {
        "version": "unknown",
        "community": "",
        "trap_oid": "unknown",
        "varbinds": [],
        "error": None,
    }
    try:
        from pysnmp.proto import api
        from pyasn1.codec.ber import decoder as ber_decoder

        ver_id = api.decodeMessageVersion(data)
        p_mod = api.protoModules.get(ver_id)
        if p_mod is None:
            result["error"] = f"unsupported SNMP version id {ver_id}"
            return result

        req_msg, _ = ber_decoder.decode(data, asn1Spec=p_mod.Message())
        community = bytes(req_msg.getComponentByPosition(1)).decode("ascii", errors="replace")
        req_pdu = p_mod.apiMessage.getPDU(req_msg)
        result["community"] = community

        if ver_id == api.protoVersion1:
            # SNMPv1 Trap-PDU
            result["version"] = "v1"
            enterprise = str(p_mod.apiTrapPDU.getEnterprise(req_pdu))
            generic    = int(p_mod.apiTrapPDU.getGenericTrap(req_pdu))
            specific   = int(p_mod.apiTrapPDU.getSpecificTrap(req_pdu))
            _generic_names = [
                "coldStart", "warmStart", "linkDown", "linkUp",
                "authenticationFailure", "egpNeighborLoss",
            ]
            if generic == 6:
                result["trap_oid"] = f"{enterprise}.{specific}"
            elif generic < len(_generic_names):
                result["trap_oid"] = _generic_names[generic]
            else:
                result["trap_oid"] = str(generic)
            for oid, val in p_mod.apiTrapPDU.getVarBinds(req_pdu):
                result["varbinds"].append({"oid": str(oid), "value": str(val)})

        else:
            # SNMPv2c Trap (or Inform)
            result["version"] = "v2c"
            for oid, val in p_mod.apiPDU.getVarBinds(req_pdu):
                oid_str = str(oid)
                val_str = str(val)
                result["varbinds"].append({"oid": oid_str, "value": val_str})
                # snmpTrapOID.0
                if oid_str == "1.3.6.1.6.3.1.1.4.1.0":
                    result["trap_oid"] = val_str

    except Exception as exc:
        result["error"] = str(exc)
        log.debug("Trap decode error: %s", exc)

    return result


def _listen(port: int, crud_module):
    global _running
    log.info("SNMP Trap collector listening on UDP :%d", port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(2.0)
    try:
        sock.bind(("0.0.0.0", port))
    except OSError as e:
        log.error(
            "Cannot bind SNMP Trap UDP port %d: %s "
            "(try running as root, use port >1024, or set up iptables redirect)",
            port, e,
        )
        return

    while _running:
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            break

        sender_ip = addr[0]
        trap = _decode_trap(data)

        # Match sender IP to a known device
        devices = crud_module.get_all_devices()
        device = next(
            (d for d in devices if d["ip_address"] == sender_ip), None
        )
        device_id = device["id"] if device else None

        now = datetime.utcnow().isoformat()
        crud_module.add_snmp_trap(
            device_id, sender_ip,
            trap["community"], trap["version"],
            trap["trap_oid"], trap["varbinds"],
        )

        log.debug(
            "SNMP Trap from %s (device=%s) ver=%s oid=%s varbinds=%d",
            sender_ip,
            device["name"] if device else "unknown",
            trap["version"], trap["trap_oid"], len(trap["varbinds"]),
        )

        # Widget notification / active alert
        rule = crud_module.get_widget_notification_rule("snmp_trap")
        if rule and rule.get("enabled"):
            from app.monitoring.scheduler import _evaluate_widget_notification
            entity_name = device["name"] if device else sender_ip
            _evaluate_widget_notification(
                "snmp_trap",
                triggered=True,
                subject=f"FoxEx Monitor – SNMP Trap: {entity_name}",
                body_text=(
                    f"SNMP Trap empfangen von '{entity_name}' ({sender_ip}).\n\n"
                    f"Trap-OID:  {trap['trap_oid']}\n"
                    f"Version:   {trap['version']}\n"
                    f"Community: {trap['community']}\n\n"
                    "FoxEx Network Monitor"
                ),
                exception_value=sender_ip,
                entity_name=entity_name,
            )

    sock.close()
    log.info("SNMP Trap collector stopped.")


def start_trap_collector(port: int = 162):
    """Start the SNMP Trap UDP listener in a background thread."""
    global _thread, _running
    if _running:
        return
    from app import crud
    _running = True
    _thread = threading.Thread(
        target=_listen, args=(port, crud), daemon=True, name="trap-collector"
    )
    _thread.start()


def stop_trap_collector():
    global _running
    _running = False
