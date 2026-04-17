"""Shared Docker utility functions for container inspection and management."""
from __future__ import annotations

import subprocess
import time


def docker_run(cmd: list[str], timeout: int = 10, cwd: str | None = None) -> tuple[int, str]:
    """Run a subprocess command with timeout, return (returncode, stdout+stderr)."""
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd or None)
        return proc.returncode, ((proc.stdout or "") + (proc.stderr or "")).strip()
    except subprocess.TimeoutExpired:
        return -1, "timeout"
    except Exception as e:
        return -1, str(e)


def get_container_name(instance_id: str, product: str) -> str:
    """Derive docker container name from instance_id and product type.

    Returns empty string for products without a server-side container
    (e.g. local_agent, which runs on the user's own machine).
    """
    if product == "local_agent":
        return ""
    if product == "hermes":
        return f"hermes_{instance_id}"
    if product == "zylos":
        return f"zylos_{instance_id}"
    project_raw = f"hire_{instance_id.replace('-', '')}"
    project = project_raw[:24]
    return f"{project}-openclaw-gateway-1"


def get_compose_project(instance_id: str, product: str) -> str:
    """Derive docker compose project name (empty for container-less products)."""
    if product == "local_agent":
        return ""
    if product == "hermes":
        return f"hermes_{instance_id}"
    if product == "zylos":
        return f"zylos_{instance_id}"
    project_raw = f"hire_{instance_id.replace('-', '')}"
    return project_raw[:24]


def get_resource_usage(container_name: str) -> dict:
    """Get live CPU and memory usage via docker stats."""
    result: dict = {"cpu_percent": None, "mem_used_mb": None, "mem_total_mb": None}
    rc, out = docker_run([
        "docker", "stats", "--no-stream", "--format",
        "{{.CPUPerc}} {{.MemUsage}}", container_name,
    ])
    if rc != 0 or not out:
        return result
    try:
        parts = out.split()
        cpu_str = parts[0].rstrip("%")
        result["cpu_percent"] = float(cpu_str)

        def _parse_mem(s: str) -> int:
            s = s.strip()
            if s.upper().endswith("GIB"):
                return int(float(s[:-3]) * 1024)
            if s.upper().endswith("MIB"):
                return int(float(s[:-3]))
            if s.upper().endswith("KIB"):
                return max(1, int(float(s[:-3]) / 1024))
            return int(float(s) / (1024 * 1024))

        result["mem_used_mb"] = _parse_mem(parts[1])
        result["mem_total_mb"] = _parse_mem(parts[3])
    except (IndexError, ValueError):
        pass
    return result


def get_claude_info(container_name: str) -> dict:
    """Get Claude process info from inside the container."""
    result: dict = {"running": False, "pid": None, "uptime_seconds": None, "memory_mb": None, "command_line": None}
    rc, out = docker_run(["docker", "exec", container_name, "ps", "aux"])
    if rc != 0 or not out:
        return result

    for line in out.splitlines():
        if "claude" in line and "grep" not in line and "--dangerously" in line:
            parts = line.split()
            if len(parts) >= 11:
                result["running"] = True
                result["command_line"] = " ".join(parts[10:])
                try:
                    result["pid"] = int(parts[1])
                except (ValueError, IndexError):
                    pass
                try:
                    rss_kb = int(parts[5])
                    result["memory_mb"] = round(rss_kb / 1024)
                except (ValueError, IndexError):
                    pass
                if result["pid"]:
                    rc2, out2 = docker_run([
                        "docker", "exec", container_name,
                        "sh", "-c",
                        f"stat -c %Y /proc/{result['pid']} 2>/dev/null || echo ''"
                    ])
                    if rc2 == 0 and out2.strip().isdigit():
                        start_time = int(out2.strip())
                        result["uptime_seconds"] = int(time.time()) - start_time
            break

    return result


def get_container_info(container_name: str) -> dict:
    """Get container running status, disk usage, and resource limits."""
    result: dict = {
        "running": False,
        "disk_usage_mb": None,
        "memory_limit_mb": None,
        "cpu_limit": None,
    }

    rc, out = docker_run([
        "docker", "inspect", "--format", "{{.State.Running}}", container_name
    ])
    if rc != 0:
        return result
    result["running"] = out.strip().lower() == "true"

    if not result["running"]:
        return result

    rc, out = docker_run([
        "docker", "exec", container_name, "du", "-sm", "/home"
    ])
    if rc == 0 and out:
        try:
            result["disk_usage_mb"] = int(out.split()[0])
        except (ValueError, IndexError):
            pass

    rc, out = docker_run([
        "docker", "inspect", "--format",
        "{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}", container_name
    ])
    if rc == 0 and out:
        parts = out.split()
        try:
            mem_bytes = int(parts[0])
            if mem_bytes > 0:
                result["memory_limit_mb"] = round(mem_bytes / (1024 * 1024))
        except (ValueError, IndexError):
            pass
        try:
            nano_cpus = int(parts[1])
            if nano_cpus > 0:
                result["cpu_limit"] = round(nano_cpus / 1e9, 2)
        except (ValueError, IndexError):
            pass

    return result
