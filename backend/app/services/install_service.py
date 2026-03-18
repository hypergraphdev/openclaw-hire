from __future__ import annotations

import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path

from ..database import get_connection

RUNTIME_ROOT = Path("/home/wwwroot/openclaw-hire/runtime")
COMPOSE_CANDIDATES = [
    "docker-compose.yml",
    "compose.yml",
    "docker/docker-compose.yml",
    "docker/compose.yml",
]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _set_instance_state(instance_id: str, state: str, status: str | None = None) -> None:
    with get_connection() as conn:
        if status is None:
            conn.execute(
                "UPDATE instances SET install_state = ?, updated_at = ? WHERE id = ?",
                (state, _utc_now(), instance_id),
            )
        else:
            conn.execute(
                "UPDATE instances SET install_state = ?, status = ?, updated_at = ? WHERE id = ?",
                (state, status, _utc_now(), instance_id),
            )
        conn.commit()


def _add_install_event(instance_id: str, state: str, message: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO install_events (instance_id, state, message, created_at) VALUES (?, ?, ?, ?)",
            (instance_id, state, message, _utc_now()),
        )
        conn.commit()


def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    out = (proc.stdout or "").strip()
    return proc.returncode, out


def _compose_up(compose_file: Path, project: str, workdir: Path) -> tuple[int, str]:
    # Prefer docker compose plugin, fallback to docker-compose binary.
    rc, out = _run(["docker", "compose", "-f", str(compose_file), "-p", project, "up", "-d", "--build"], cwd=workdir)
    if rc == 0:
        return rc, out
    rc2, out2 = _run(["docker-compose", "-f", str(compose_file), "-p", project, "up", "-d", "--build"], cwd=workdir)
    if rc2 == 0:
        return rc2, out2
    return rc2, f"docker compose failed:\n{out}\n\ndocker-compose failed:\n{out2}"


def _compose_control(compose_file: str, project: str, workdir: str, action: str) -> tuple[int, str]:
    wd = Path(workdir)
    rc, out = _run(["docker", "compose", "-f", compose_file, "-p", project, action], cwd=wd)
    if rc == 0:
        return rc, out
    rc2, out2 = _run(["docker-compose", "-f", compose_file, "-p", project, action], cwd=wd)
    if rc2 == 0:
        return rc2, out2
    return rc2, f"docker compose {action} failed:\n{out}\n\ndocker-compose {action} failed:\n{out2}"


def compose_logs(compose_file: str, project: str, workdir: str, lines: int = 200) -> tuple[int, str]:
    wd = Path(workdir)
    rc, out = _run(["docker", "compose", "-f", compose_file, "-p", project, "logs", "--tail", str(lines)], cwd=wd)
    if rc == 0:
        return rc, out
    rc2, out2 = _run(["docker-compose", "-f", compose_file, "-p", project, "logs", "--tail", str(lines)], cwd=wd)
    if rc2 == 0:
        return rc2, out2
    return rc2, f"docker compose logs failed:\n{out}\n\ndocker-compose logs failed:\n{out2}"


def _find_compose_file(repo_dir: Path) -> Path | None:
    for rel in COMPOSE_CANDIDATES:
        p = repo_dir / rel
        if p.exists():
            return p
    return None


def _sync_runtime_status(instance_id: str, project: str) -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT install_state FROM instances WHERE id = ?", (instance_id,)).fetchone()
    current_state = row["install_state"] if row else None

    rc, out = _run([
        "docker",
        "ps",
        "-a",
        "--filter",
        f"label=com.docker.compose.project={project}",
        "--format",
        "{{.Status}}",
    ])
    if rc != 0:
        if current_state != "failed":
            _add_install_event(instance_id, "failed", f"Unable to query docker status: {out[:400]}")
        _set_instance_state(instance_id, "failed", status="failed")
        return

    lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
    if not lines:
        if current_state != "failed":
            _add_install_event(instance_id, "failed", "No containers found after compose up.")
        _set_instance_state(instance_id, "failed", status="failed")
        return

    if any("Up" in ln for ln in lines):
        if current_state != "running":
            _add_install_event(instance_id, "running", f"Install finished. Containers: {len(lines)}. Project: {project}")
        _set_instance_state(instance_id, "running", status="active")
        return

    if current_state != "failed":
        _add_install_event(instance_id, "failed", "Containers were created but not running: " + " | ".join(lines[:4]))
    _set_instance_state(instance_id, "failed", status="failed")


def _run_install(instance_id: str) -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT id, product, repo_url FROM instances WHERE id = ?", (instance_id,)).fetchone()
    if row is None:
        return

    product = row["product"]
    repo_url = row["repo_url"]
    project = f"hire_{instance_id.replace('-', '')[:16]}"
    workdir = RUNTIME_ROOT / instance_id
    repo_dir = workdir / "repo"

    try:
        RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
        workdir.mkdir(parents=True, exist_ok=True)

        _set_instance_state(instance_id, "pulling", status="installing")
        _add_install_event(instance_id, "pulling", f"Preparing source for {product}: {repo_url}")

        if repo_dir.exists():
            if (repo_dir / ".git").exists():
                rc, out = _run(["git", "-C", str(repo_dir), "fetch", "--all", "--prune"])
                if rc != 0:
                    raise RuntimeError(f"git fetch failed: {out[:800]}")
                rc, out = _run(["git", "-C", str(repo_dir), "reset", "--hard", "origin/HEAD"])
                if rc != 0:
                    rc, out = _run(["git", "-C", str(repo_dir), "pull", "--ff-only"])
                    if rc != 0:
                        raise RuntimeError(f"git pull failed: {out[:800]}")
            else:
                shutil.rmtree(repo_dir, ignore_errors=True)
                rc, out = _run(["git", "clone", "--depth", "1", repo_url, str(repo_dir)])
                if rc != 0:
                    raise RuntimeError(f"git clone failed: {out[:800]}")
        else:
            rc, out = _run(["git", "clone", "--depth", "1", repo_url, str(repo_dir)])
            if rc != 0:
                raise RuntimeError(f"git clone failed: {out[:800]}")

        _set_instance_state(instance_id, "configuring")
        _add_install_event(instance_id, "configuring", "Detecting docker compose file...")

        compose_file = _find_compose_file(repo_dir)
        if compose_file is None:
            raise RuntimeError("No docker compose file found (checked docker-compose.yml/compose.yml and docker/* variants).")

        with get_connection() as conn:
            conn.execute(
                "UPDATE instances SET compose_project = ?, compose_file = ?, runtime_dir = ?, updated_at = ? WHERE id = ?",
                (project, str(compose_file), str(workdir), _utc_now(), instance_id),
            )
            conn.commit()

        _set_instance_state(instance_id, "starting")
        _add_install_event(instance_id, "starting", f"Running docker compose up for project {project}...")

        rc, out = _compose_up(compose_file, project, repo_dir)
        if rc != 0:
            raise RuntimeError(out[:2000])

        _add_install_event(instance_id, "starting", "docker compose command finished, verifying containers...")
        _sync_runtime_status(instance_id, project)

    except Exception as exc:
        _add_install_event(instance_id, "failed", f"Install failed: {exc}")
        _set_instance_state(instance_id, "failed", status="failed")


def sync_instance_status(instance_id: str) -> None:
    with get_connection() as conn:
        row = conn.execute("SELECT compose_project FROM instances WHERE id = ?", (instance_id,)).fetchone()
    if row and row["compose_project"]:
        _sync_runtime_status(instance_id, row["compose_project"])


def trigger_install(instance_id: str) -> None:
    """Kick off real install in a background daemon thread."""
    threading.Thread(target=_run_install, args=(instance_id,), daemon=True).start()


def stop_instance(instance_id: str, compose_file: str, project: str, runtime_dir: str) -> tuple[bool, str]:
    rc, out = _compose_control(compose_file, project, runtime_dir, "stop")
    if rc == 0:
        _set_instance_state(instance_id, "idle", status="inactive")
        _add_install_event(instance_id, "idle", "Instance stopped.")
        return True, out
    _add_install_event(instance_id, "failed", f"Stop failed: {out[:1200]}")
    return False, out


def restart_instance(instance_id: str, compose_file: str, project: str, runtime_dir: str) -> tuple[bool, str]:
    rc, out = _compose_control(compose_file, project, runtime_dir, "restart")
    if rc == 0:
        _sync_runtime_status(instance_id, project)
        _add_install_event(instance_id, "running", "Instance restarted.")
        return True, out
    _add_install_event(instance_id, "failed", f"Restart failed: {out[:1200]}")
    return False, out


def uninstall_instance(instance_id: str, compose_file: str, project: str, runtime_dir: str) -> tuple[bool, str]:
    rc, out = _compose_control(compose_file, project, runtime_dir, "down")
    if rc == 0:
        _set_instance_state(instance_id, "idle", status="inactive")
        _add_install_event(instance_id, "idle", "Instance removed with docker compose down.")
        return True, out
    _add_install_event(instance_id, "failed", f"Uninstall failed: {out[:1200]}")
    return False, out
