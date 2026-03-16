from __future__ import annotations

import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Iterable
from uuid import uuid4

from fastapi import HTTPException

from .database import get_connection
from .schemas import DEFAULT_MODEL_CONFIG, DashboardResponse, DashboardSummary, EmployeeDetailResponse, EmployeeResponse, StatusEventResponse, UserResponse, get_default_templates


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def row_to_user(row) -> UserResponse:
    return UserResponse(**dict(row))


def row_to_employee(row) -> EmployeeResponse:
    payload = dict(row)
    # backward-compatible payload mapping for older rows
    payload.setdefault("template_id", "audit-codex-base")
    return EmployeeResponse(**payload)


def get_user_or_404(user_id: str):
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return row


def get_employee_row_or_404(employee_id: str):
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return row


def add_status_event(connection, employee_id: str, state: str, message: str, created_at: str) -> None:
    connection.execute(
        """
        INSERT INTO employee_status_events (employee_id, state, message, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (employee_id, state, message, created_at),
    )


def create_user(name: str, email: str, company_name: str | None) -> UserResponse:
    user_id = f"user_{uuid4().hex[:12]}"
    created_at = utc_now()
    with get_connection() as connection:
        try:
            connection.execute(
                """
                INSERT INTO users (id, name, email, company_name, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, name, email.lower(), company_name, created_at),
            )
        except sqlite3.IntegrityError as exc:
            raise HTTPException(status_code=409, detail="Email already registered.") from exc
        row = connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return row_to_user(row)


def create_employee(owner_id: str, name: str, role: str, brief: str | None, template_id: str, telegram_handle: str | None) -> EmployeeResponse:
    get_user_or_404(owner_id)
    templates = {template.id: template for template in get_default_templates()}
    template = templates.get(template_id, templates["audit-codex-base"])
    employee_id = f"emp_{uuid4().hex[:12]}"
    now = utc_now()

    with get_connection() as connection:
        connection.execute(
            """
            INSERT INTO employees (
                id, owner_id, name, role, brief, telegram_handle, model_config,
                current_state, created_at, updated_at, template_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                employee_id,
                owner_id,
                name,
                role,
                brief,
                telegram_handle,
                template.codex_profile,
                "queued",
                now,
                now,
                template.id,
            ),
        )
        add_status_event(connection, employee_id, "queued", "员工雇佣请求已提交。")
        add_status_event(connection, employee_id, "preparing_workspace", f"已加载模板 {template.name} 并准备专属工作区。")

        row = connection.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()

    # 启动异步初始化流程（模拟后台初始化任务）。
    threading.Thread(
        target=_simulate_init_workflow,
        args=(employee_id,),
        daemon=True,
    ).start()
    return row_to_employee(row)


def _simulate_init_workflow(employee_id: str) -> None:
    steps = [
        ("writing_config", "开始生成 OpenClaw 配置草案。"),
        ("creating_service", "初始化服务编排，等待 Telegram token 提交。"),
    ]

    for state, message in steps:
        with get_connection() as connection:
            current = connection.execute("SELECT current_state FROM employees WHERE id = ?", (employee_id,)).fetchone()
            if current is None:
                return
            state_value = current["current_state"]
            if state_value in {"ready", "failed", "waiting_bot_token"}:
                return

            connection.execute(
                "UPDATE employees SET current_state = ?, updated_at = ? WHERE id = ?",
                (state, utc_now(), employee_id),
            )
            add_status_event(connection, employee_id, state, message, utc_now())

        time.sleep(2)

    with get_connection() as connection:
        # 等待 bot token 的人工确认状态。
        current = connection.execute("SELECT current_state FROM employees WHERE id = ?", (employee_id,)).fetchone()
        if current is None or current["current_state"] in {"ready", "failed"}:
            return

        connection.execute(
            "UPDATE employees SET current_state = ?, updated_at = ? WHERE id = ?",
            ("waiting_bot_token", utc_now(), employee_id),
        )
        add_status_event(connection, employee_id, "waiting_bot_token", "等待用户提交 Telegram Bot Token。", utc_now())


def _mark_ready(employee_id: str) -> None:
    with get_connection() as connection:
        connection.execute(
            "UPDATE employees SET current_state = ?, updated_at = ? WHERE id = ?",
            ("ready", utc_now(), employee_id),
        )
        add_status_event(connection, employee_id, "ready", "已完成 OpenClaw 初始化，进入可运行状态。", utc_now())



def _count_rows(rows: Iterable[sqlite3.Row], target_state: str) -> int:
    return sum(1 for row in rows if row["current_state"] == target_state)


def create_template_table_safe() -> None:
    # 前向兼容：补充 template_id 列（老库无此列时）。
    with get_connection() as connection:
        columns = [r[1] for r in connection.execute("PRAGMA table_info(employees)").fetchall()]
        if "template_id" not in columns:
            connection.execute(
                "ALTER TABLE employees ADD COLUMN template_id TEXT DEFAULT ?",
                ("audit-codex-base",),
            )
        connection.execute(
            "UPDATE employees SET template_id = COALESCE(template_id, 'audit-codex-base')",
        )


def list_employees_by_owner(owner_id: str) -> list[EmployeeResponse]:
    get_user_or_404(owner_id)
    create_template_table_safe()
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM employees WHERE owner_id = ? ORDER BY created_at DESC",
            (owner_id,),
        ).fetchall()
    return [row_to_employee(row) for row in rows]


def get_employee_detail(employee_id: str) -> EmployeeDetailResponse:
    employee = get_employee_row_or_404(employee_id)
    with get_connection() as connection:
        events = connection.execute(
            """
            SELECT state, message, created_at
            FROM employee_status_events
            WHERE employee_id = ?
            ORDER BY id ASC
            """,
            (employee_id,),
        ).fetchall()
    return EmployeeDetailResponse(
        employee=row_to_employee(employee),
        timeline=[StatusEventResponse(**dict(row)) for row in events],
    )


def save_bot_token_placeholder(employee_id: str, token_placeholder: str) -> EmployeeDetailResponse:
    get_employee_row_or_404(employee_id)
    now = utc_now()
    with get_connection() as connection:
        row = connection.execute(
            "SELECT current_state FROM employees WHERE id = ?",
            (employee_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Employee not found.")
        current_state = row["current_state"]
        if current_state not in {"waiting_bot_token", "queued", "creating_service"}:
            raise HTTPException(
                status_code=409,
                detail="该员工当前不在等待 Telegram token 的阶段。",
            )

        connection.execute(
            "UPDATE employees SET telegram_bot_token_placeholder = ?, updated_at = ?, current_state = ? WHERE id = ?",
            (token_placeholder, now, "creating_service", employee_id),
        )
        add_status_event(connection, employee_id, "creating_service", "已接收 Telegram Token 信息，开始构建并启动 OpenClaw 实例。", now)

    threading.Thread(target=_finalize_after_token, args=(employee_id,), daemon=True).start()
    return get_employee_detail(employee_id)


def _finalize_after_token(employee_id: str) -> None:
    # 模拟后台脚本耗时；未来可替换为真实 CLI 调度。
    time.sleep(2)
    _mark_ready(employee_id)


def dashboard_for_owner(owner_id: str) -> DashboardResponse:
    owner = get_user_or_404(owner_id)
    create_template_table_safe()
    with get_connection() as connection:
        rows = connection.execute("SELECT * FROM employees WHERE owner_id = ?", (owner_id,)).fetchall()

    total = len(rows)
    ready = _count_rows(rows, "ready")
    waiting = _count_rows(rows, "waiting_bot_token")
    failed = _count_rows(rows, "failed")
    in_progress = total - ready - waiting - failed
    summary = DashboardSummary(
        total=total,
        ready=ready,
        waiting_bot_token=waiting,
        provisioning=in_progress,
        failed=failed,
    )
    return DashboardResponse(owner=row_to_user(owner), summary=summary)
