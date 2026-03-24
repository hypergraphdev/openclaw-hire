from __future__ import annotations

import mysql.connector
import threading
import time
from datetime import datetime, timezone
from typing import Iterable
from uuid import uuid4

from fastapi import HTTPException

from .database import get_connection
from .schemas import (
    DEFAULT_MODEL_CONFIG,
    DEFAULT_STACK,
    STACK_REPOS,
    DashboardResponse,
    DashboardSummary,
    EmployeeDetailResponse,
    EmployeeResponse,
    StatusEventResponse,
    UserResponse,
    get_default_templates,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def row_to_user(row) -> UserResponse:
    return UserResponse(**dict(row))


def row_to_employee(row) -> EmployeeResponse:
    payload = dict(row)
    # backward-compatible payload mapping for older rows
    payload.setdefault("template_id", "audit-codex-base")
    payload.setdefault("stack", DEFAULT_STACK)
    payload.setdefault("repo_url", STACK_REPOS.get(payload["stack"], STACK_REPOS[DEFAULT_STACK]))
    return EmployeeResponse(**payload)


def get_user_or_404(user_id: str):
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return row


def get_employee_row_or_404(employee_id: str):
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM employees WHERE id = %s", (employee_id,))
        row = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="Employee not found.")
    return row


def add_status_event(cursor, employee_id: str, state: str, message: str, created_at: str = "") -> None:
    if not created_at:
        created_at = utc_now()
    cursor.execute(
        """
        INSERT INTO employee_status_events (employee_id, state, message, created_at)
        VALUES (%s, %s, %s, %s)
        """,
        (employee_id, state, message, created_at),
    )


def create_user(name: str, email: str, company_name: str | None) -> UserResponse:
    user_id = f"user_{uuid4().hex[:12]}"
    created_at = utc_now()
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                INSERT INTO users (id, name, email, company_name, created_at)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (user_id, name, email.lower(), company_name, created_at),
            )
        except mysql.connector.IntegrityError as exc:
            cursor.close()
            raise HTTPException(status_code=409, detail="Email already registered.") from exc
        cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()
    return row_to_user(row)


def create_employee(owner_id: str, name: str, role: str, brief: str | None, template_id: str, telegram_handle: str | None, stack: str) -> EmployeeResponse:
    get_user_or_404(owner_id)
    templates = {template.id: template for template in get_default_templates()}
    template = templates.get(template_id, templates["audit-codex-base"])
    selected_stack = stack if stack in STACK_REPOS else DEFAULT_STACK
    repo_url = STACK_REPOS[selected_stack]
    employee_id = f"emp_{uuid4().hex[:12]}"
    now = utc_now()

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            INSERT INTO employees (
                id, owner_id, name, role, brief, telegram_handle, model_config,
                current_state, created_at, updated_at, template_id, stack, repo_url
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                selected_stack,
                repo_url,
            ),
        )
        add_status_event(cursor, employee_id, "queued", "员工雇佣请求已提交。", now)
        add_status_event(cursor, employee_id, "preparing_workspace", f"已加载模板 {template.name} 并准备专属工作区。", now)
        add_status_event(cursor, employee_id, "preparing_workspace", f"已选择安装栈: {selected_stack} ({repo_url})", now)

        cursor.execute("SELECT * FROM employees WHERE id = %s", (employee_id,))
        row = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()

    # 启动异步初始化流程（模拟后台初始化任务）。
    threading.Thread(
        target=_simulate_init_workflow,
        args=(employee_id,),
        daemon=True,
    ).start()
    return row_to_employee(row)


def _simulate_init_workflow(employee_id: str) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT stack, repo_url FROM employees WHERE id = %s", (employee_id,))
        selected = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()
    stack = selected["stack"] if selected else DEFAULT_STACK
    repo_url = selected["repo_url"] if selected else STACK_REPOS[DEFAULT_STACK]

    steps = [
        ("writing_config", f"开始生成 {stack} 配置草案。"),
        ("creating_service", f"使用 Docker 准备安装 {stack}（仓库: {repo_url}），等待 Telegram token 提交。"),
    ]

    for state, message in steps:
        conn = get_connection()
        try:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT current_state FROM employees WHERE id = %s", (employee_id,))
            current = cursor.fetchone()
            if current is None:
                cursor.close()
                return
            state_value = current["current_state"]
            if state_value in {"ready", "failed", "waiting_bot_token"}:
                cursor.close()
                return

            cursor.execute(
                "UPDATE employees SET current_state = %s, updated_at = %s WHERE id = %s",
                (state, utc_now(), employee_id),
            )
            add_status_event(cursor, employee_id, state, message, utc_now())
            cursor.close()
        finally:
            conn.close()

        time.sleep(2)

    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        # 等待 bot token 的人工确认状态。
        cursor.execute("SELECT current_state FROM employees WHERE id = %s", (employee_id,))
        current = cursor.fetchone()
        if current is None or current["current_state"] in {"ready", "failed"}:
            cursor.close()
            return

        cursor.execute(
            "UPDATE employees SET current_state = %s, updated_at = %s WHERE id = %s",
            ("waiting_bot_token", utc_now(), employee_id),
        )
        add_status_event(cursor, employee_id, "waiting_bot_token", "等待用户提交 Telegram Bot Token。", utc_now())
        cursor.close()
    finally:
        conn.close()


def _mark_ready(employee_id: str) -> None:
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "UPDATE employees SET current_state = %s, updated_at = %s WHERE id = %s",
            ("ready", utc_now(), employee_id),
        )
        add_status_event(cursor, employee_id, "ready", "已完成 OpenClaw 初始化，进入可运行状态。", utc_now())
        cursor.close()
    finally:
        conn.close()


def _count_rows(rows: Iterable[dict], target_state: str) -> int:
    return sum(1 for row in rows if row["current_state"] == target_state)


def create_template_table_safe() -> None:
    """No-op for MySQL — tables already exist with all columns."""
    pass


def list_employees_by_owner(owner_id: str) -> list[EmployeeResponse]:
    get_user_or_404(owner_id)
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM employees WHERE owner_id = %s ORDER BY created_at DESC",
            (owner_id,),
        )
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()
    return [row_to_employee(row) for row in rows]


def get_employee_detail(employee_id: str) -> EmployeeDetailResponse:
    employee = get_employee_row_or_404(employee_id)
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT state, message, created_at
            FROM employee_status_events
            WHERE employee_id = %s
            ORDER BY id ASC
            """,
            (employee_id,),
        )
        events = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()
    return EmployeeDetailResponse(
        employee=row_to_employee(employee),
        timeline=[StatusEventResponse(**dict(row)) for row in events],
    )


def save_bot_token_placeholder(employee_id: str, token_placeholder: str) -> EmployeeDetailResponse:
    get_employee_row_or_404(employee_id)
    now = utc_now()
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT current_state FROM employees WHERE id = %s",
            (employee_id,),
        )
        row = cursor.fetchone()
        if row is None:
            cursor.close()
            raise HTTPException(status_code=404, detail="Employee not found.")
        current_state = row["current_state"]
        if current_state not in {"waiting_bot_token", "queued", "creating_service"}:
            cursor.close()
            raise HTTPException(
                status_code=409,
                detail="该员工当前不在等待 Telegram token 的阶段。",
            )

        cursor.execute(
            "UPDATE employees SET telegram_bot_token_placeholder = %s, updated_at = %s, current_state = %s WHERE id = %s",
            (token_placeholder, now, "creating_service", employee_id),
        )
        cursor.execute("SELECT stack, repo_url FROM employees WHERE id = %s", (employee_id,))
        stack_row = cursor.fetchone()
        stack = stack_row["stack"] if stack_row else DEFAULT_STACK
        repo_url = stack_row["repo_url"] if stack_row else STACK_REPOS[DEFAULT_STACK]
        add_status_event(cursor, employee_id, "creating_service", f"已接收 Telegram Token，开始通过 Docker 部署 {stack}（{repo_url}）。", now)
        cursor.close()
    finally:
        conn.close()

    threading.Thread(target=_finalize_after_token, args=(employee_id,), daemon=True).start()
    return get_employee_detail(employee_id)


def _finalize_after_token(employee_id: str) -> None:
    # 模拟后台脚本耗时；未来可替换为真实 CLI 调度。
    time.sleep(2)
    _mark_ready(employee_id)


def dashboard_for_owner(owner_id: str) -> DashboardResponse:
    owner = get_user_or_404(owner_id)
    conn = get_connection()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM employees WHERE owner_id = %s", (owner_id,))
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

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
