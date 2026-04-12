"""SSH service status check — connects via SSH and runs systemctl is-active."""
import time


def ssh_service_check(host: str, port: int, username: str, password: str,
                      service_name: str, timeout: int = 10) -> dict:
    """
    SSH into host and run `systemctl is-active <service>`.
    Returns:
        {
            "status":      "active" | "inactive" | "failed" | "error" | "unknown",
            "output":      str,      # raw command output or error message
            "response_ms": float,
        }
    """
    t0 = time.monotonic()
    try:
        import paramiko  # imported here so missing package gives clear error at call time
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            host, port=port,
            username=username, password=password,
            timeout=timeout, banner_timeout=timeout, auth_timeout=timeout,
            look_for_keys=False, allow_agent=False,
        )
        _, stdout, _ = client.exec_command(
            f"systemctl is-active {service_name}", timeout=timeout
        )
        output = stdout.read().decode("utf-8", errors="replace").strip()
        client.close()
        response_ms = round((time.monotonic() - t0) * 1000, 2)
        valid = {"active", "inactive", "failed", "activating", "deactivating"}
        status = output if output in valid else "unknown"
        return {"status": status, "output": output, "response_ms": response_ms}
    except Exception as exc:
        response_ms = round((time.monotonic() - t0) * 1000, 2)
        # Shorten verbose paramiko error messages
        err = str(exc)
        if len(err) > 120:
            err = err[:120] + "…"
        return {"status": "error", "output": err, "response_ms": response_ms}
