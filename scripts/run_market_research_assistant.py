from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
import uuid
import webbrowser
from threading import Lock
from contextlib import closing
from datetime import datetime, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


DEFAULT_DB = Path(
    r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\outputs\SHFE市场研究助手_v0.16_20261002"
    r"\SHFE公告参数市场研究助手_v0.16.sqlite3"
)
WEB_FILE = Path(__file__).resolve().parents[1] / "web" / "market_research_assistant.html"
AI_RESPONSE_CACHE: dict[str, dict] = {}
AI_CACHE_LOCK = Lock()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local SHFE market research assistant.")
    parser.add_argument("--db", type=Path, default=Path(os.environ.get("SHFE_RESEARCH_ASSISTANT_DB", DEFAULT_DB)))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def row_dict(row: sqlite3.Row | None) -> dict | None:
    return None if row is None else dict(row)


def query_dicts(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def build_ai_context(payload: dict) -> dict:
    snapshot = payload["snapshot"]
    latest = payload["series"][-1] if payload["series"] else None
    return {
        "product_code": payload["product_code"],
        "database_freshness": {
            "database_last_date": snapshot["database_last_date"],
            "analysis_date": snapshot["analysis_date"],
            "data_age_calendar_days": snapshot["data_age_calendar_days"],
            "freshness_status": snapshot["freshness_status"],
            "current_assessment_status": snapshot["current_assessment_status"],
        },
        "latest_available_quantitative_state": {
            "composite_intensity_score": snapshot["composite_intensity_score"],
            "intensity_level": snapshot["intensity_level"],
            "historical_attention_level": snapshot["historical_attention_level"],
            "liquidity_state": snapshot["liquidity_state"],
            "risk_state": snapshot["risk_state"],
            "recent_intense_days_20": snapshot["recent_intense_days_20"],
            "recent_parameter_changes_60": snapshot["recent_parameter_changes_60"],
            "verified_notice_records_365": snapshot["verified_notice_records_365"],
            "latest_metric_row": latest,
        },
        "recent_intense_days": payload["intense_days"][:10],
        "verified_policy_intervals": payload["intervals"],
        "recent_parameter_changes": payload["parameter_changes"][:12],
        "verified_notices": payload["notices"][:12],
        "notice_market_real_event_correspondence": payload.get("event_master", [])[:12],
        "unique_policy_events": payload.get("unique_policy_events", [])[:12],
        "multiwindow_statistics": payload.get("window_statistics", [])[:24],
        "policy_overlap_audit": payload.get("overlap_audit", [])[:12],
        "data_completeness": payload.get("completeness"),
        "notice_parameter_correspondence_summary": payload.get("correspondence_summary"),
        "high_priority_correspondence_review": [
            row for row in payload.get("correspondence_audit", []) if row.get("review_priority") == "high"
        ][:20],
        "trade_research_assessment": payload.get("trade_research_assessment"),
        "evidence_boundary": snapshot["evidence_boundary_cn"],
    }


def build_prompt(context: dict) -> str:
    return (
        "你是期货市场研究助手。只根据下方JSON证据进行解释，不得补充未提供的实时行情、新闻或基本面信息。\n"
        "任务：说明该品种的历史交易状态、最近可用数据所处的强度/流动性/风险状态、值得进一步关注的原因、"
        "数据限制、客观交易研究条件和下一步应核验的研究问题。\n"
        "约束：不得给出买入、卖出、开仓、平仓、止盈止损或收益保证；数据滞后时必须明确不能判断当前是否适合交易；"
        "参数变化与市场异常只能描述同步或时间顺序，不得直接表述为因果。\n\n证据JSON：\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
    )


def parse_yyyymmdd(value: object, field_name: str, *, required: bool = True) -> str | None:
    text = str(value or "").strip()
    if not text and not required:
        return None
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"{field_name}必须为YYYYMMDD")
    datetime.strptime(text, "%Y%m%d")
    return text


def ensure_runtime_schema(conn: sqlite3.Connection) -> None:
    """Apply small, idempotent migrations without rebuilding the large database."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_notice_entry'").fetchone():
        return
    columns = {row[1] for row in conn.execute("PRAGMA table_info(user_notice_entry)")}
    additions = {
        "reviewed_by": "TEXT", "reviewed_at": "TEXT", "review_note": "TEXT",
        "validation_warnings_json": "TEXT NOT NULL DEFAULT '[]'",
        "record_version": "INTEGER NOT NULL DEFAULT 1",
    }
    migration_applied = (
        conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='research_assistant_schema_migration'").fetchone()
        and conn.execute(
            "SELECT 1 FROM research_assistant_schema_migration WHERE migration_id='v023_user_review_workflow'"
        ).fetchone()
    )
    view_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='view' AND name='v_all_policy_interval_effective'"
    ).fetchone()
    required_indexes = {"ix_user_notice_product_status", "ix_user_parameter_notice", "ix_user_audit_entity"}
    existing_indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    if (migration_applied and set(additions) <= columns and view_row and "user_approved" in (view_row[0] or "")
            and required_indexes <= existing_indexes):
        return
    for column, definition in additions.items():
        if column not in columns:
            conn.execute(f"ALTER TABLE user_notice_entry ADD COLUMN {column} {definition}")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS research_assistant_schema_migration (
          migration_id TEXT PRIMARY KEY,applied_at TEXT NOT NULL,description_cn TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_user_notice_product_status
          ON user_notice_entry(product_code,review_status,announcement_date);
        CREATE INDEX IF NOT EXISTS ix_user_parameter_notice
          ON user_notice_parameter_record(user_notice_id,parameter_code,start_date);
        CREATE INDEX IF NOT EXISTS ix_user_audit_entity
          ON user_input_audit_log(entity_type,entity_id,created_at);
        DROP VIEW IF EXISTS v_all_policy_interval_effective;
        CREATE VIEW v_all_policy_interval_effective AS
        SELECT interval_id,product_code,parameter_code,announced_value,start_date,end_date,
               end_date_inclusive,start_boundary,start_date_basis,end_date_basis,interval_status,
               source_notice_ids,source_notice_titles,instrument_scopes,source_notice_count,
               derivation_limit_cn,override_reason,reviewer,updated_at,
               'verified_database' AS source_layer,'reviewed_or_derived' AS review_status,
               'ratio' AS value_unit
        FROM v_policy_interval_effective
        UNION ALL
        SELECT p.record_id,n.product_code,p.parameter_code,p.announced_value,p.start_date,p.end_date,
               p.end_date_inclusive,'user_entered_effective_start','user_entered_from_notice',
               CASE WHEN p.end_date IS NULL THEN 'open_ended_user_entry' ELSE 'user_entered_from_notice' END,
               CASE WHEN p.end_date IS NULL THEN 'open' ELSE 'closed' END,
               n.user_notice_id,n.notice_title_cn,COALESCE(p.instrument_scope,'未填写'),1,
               CASE WHEN n.review_status='approved' THEN '用户录入且已人工复核。' ELSE '用户录入，尚待与官方原文及结构化数据库复核。' END,
               p.notes_cn,COALESCE(n.reviewed_by,n.created_by),n.updated_at,
               CASE WHEN n.review_status='approved' THEN 'user_approved' ELSE 'user_pending' END,
               n.review_status,p.value_unit
        FROM user_notice_parameter_record p JOIN user_notice_entry n USING(user_notice_id)
        WHERE n.review_status IN ('pending_review','approved');
        """
    )
    conn.execute(
        "INSERT OR IGNORE INTO research_assistant_schema_migration VALUES (?,?,?)",
        ("v023_user_review_workflow", datetime.now().astimezone().isoformat(timespec="seconds"),
         "增加用户公告审批、校验警告、记录版本及检索索引"),
    )


def backup_user_work(db_path: Path, reason: str) -> str:
    """Create a small recovery snapshot of mutable tables instead of copying the full 800MB database."""
    backup_dir = db_path.parent / f"{db_path.stem}_user_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%f")
    safe_reason = "".join(ch for ch in reason if ch.isalnum() or ch in "-_")[:40] or "write"
    target = backup_dir / f"{stamp}_{safe_reason}.json"
    temporary = target.with_suffix(".json.building")
    snapshot = {"database": str(db_path), "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "reason": reason, "tables": {}}
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        for table in ("user_notice_entry", "user_notice_parameter_record", "user_input_audit_log", "policy_interval_manual_override"):
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                snapshot["tables"][table] = [dict(row) for row in conn.execute(f"SELECT * FROM {table}")]
    finally:
        conn.close()
    temporary.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)
    return str(target)


def notice_snapshot(conn: sqlite3.Connection, notice_id: str) -> dict | None:
    notice = row_dict(conn.execute("SELECT * FROM user_notice_entry WHERE user_notice_id=?", (notice_id,)).fetchone())
    if notice is None:
        return None
    notice["parameters"] = query_dicts(
        conn, "SELECT * FROM user_notice_parameter_record WHERE user_notice_id=? ORDER BY record_id", (notice_id,)
    )
    return notice


def normalize_notice_payload(conn: sqlite3.Connection, body: dict, *, exclude_notice_id: str | None = None) -> dict:
    product = str(body.get("product_code", "")).upper().strip()
    title_cn = str(body.get("notice_title_cn", "")).strip()
    title_en = str(body.get("notice_title_en", "")).strip() or None
    announcement_date = parse_yyyymmdd(body.get("announcement_date"), "announcement_date")
    source_url = str(body.get("official_source_url", "")).strip() or None
    description = str(body.get("event_description_cn", "")).strip() or None
    actor = str(body.get("created_by") or body.get("actor") or "").strip()
    parameters = body.get("parameters")
    if not product or not title_cn or not actor:
        raise ValueError("品种、公告中文标题、公告日期和操作人不能为空")
    if source_url and urlparse(source_url).scheme not in {"http", "https"}:
        raise ValueError("官方原文链接必须以http://或https://开头")
    if not conn.execute("SELECT 1 FROM product_research_snapshot WHERE product_code=?", (product,)).fetchone():
        raise ValueError(f"未知品种代码：{product}")
    duplicate = conn.execute(
        """SELECT user_notice_id FROM user_notice_entry
           WHERE product_code=? AND announcement_date=? AND notice_title_cn=?
             AND review_status<>'withdrawn' AND (? IS NULL OR user_notice_id<>?)""",
        (product, announcement_date, title_cn, exclude_notice_id, exclude_notice_id),
    ).fetchone()
    if duplicate:
        raise ValueError(f"疑似重复公告，已存在记录：{duplicate[0]}")
    if not isinstance(parameters, list) or not parameters:
        raise ValueError("至少录入一条参数调整")
    normalized, warnings = [], []
    allowed_units = {"ratio", "yuan_per_lot", "lots", "other"}
    for index, item in enumerate(parameters, 1):
        if not isinstance(item, dict):
            raise ValueError(f"第{index}条参数格式错误")
        code = str(item.get("parameter_code", "")).strip().upper()
        unit = str(item.get("value_unit", "ratio")).strip() or "ratio"
        if unit not in allowed_units:
            raise ValueError(f"第{index}条value_unit不在允许范围内")
        start = parse_yyyymmdd(item.get("start_date"), f"第{index}条start_date")
        end = parse_yyyymmdd(item.get("end_date"), f"第{index}条end_date", required=False)
        if end and end < start:
            raise ValueError(f"第{index}条结束日不能早于起始日")
        try:
            value = float(item.get("announced_value"))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"第{index}条announced_value必须为数字") from exc
        if not code:
            raise ValueError(f"第{index}条parameter_code不能为空")
        if unit == "ratio" and not 0 <= value <= 1:
            raise ValueError(f"第{index}条ratio必须在0到1之间；12%应录入0.12")
        scope = str(item.get("instrument_scope", "")).strip() or None
        overlaps = conn.execute(
            """SELECT n.user_notice_id FROM user_notice_entry n
               JOIN user_notice_parameter_record p USING(user_notice_id)
               WHERE n.product_code=? AND p.parameter_code=? AND COALESCE(p.instrument_scope,'')=COALESCE(?, '')
                 AND n.review_status IN ('pending_review','approved')
                 AND (? IS NULL OR n.user_notice_id<>?)
                 AND COALESCE(p.end_date,'99991231')>=? AND COALESCE(?, '99991231')>=p.start_date""",
            (product, code, scope, exclude_notice_id, exclude_notice_id, start, end),
        ).fetchall()
        if overlaps:
            warnings.append(f"第{index}条与已有用户区间重叠：{','.join(row[0] for row in overlaps)}")
        normalized.append({
            "record_id": str(item.get("record_id") or ("UPR-" + uuid.uuid4().hex[:16].upper())),
            "parameter_code": code, "announced_value": value, "value_unit": unit,
            "start_date": start, "end_date": end,
            "end_date_inclusive": 1 if item.get("end_date_inclusive", True) else 0,
            "instrument_scope": scope,
            "direction_code": str(item.get("direction_code", "")).strip() or None,
            "source_excerpt_cn": str(item.get("source_excerpt_cn", "")).strip() or None,
            "notes_cn": str(item.get("notes_cn", "")).strip() or None,
        })
    return {"product_code": product, "notice_title_cn": title_cn, "notice_title_en": title_en,
            "announcement_date": announcement_date, "official_source_url": source_url,
            "event_description_cn": description, "actor": actor, "parameters": normalized,
            "validation_warnings": warnings}


def build_trade_research_assessment(snapshot: dict, latest: dict | None) -> dict:
    as_of = snapshot.get("database_last_date")
    current = snapshot.get("freshness_status") == "current_to_latest_complete_official_available"
    basis = [
        f"最近可用完整交易日：{as_of}",
        f"历史强度分：{snapshot.get('composite_intensity_score')}",
        f"流动性状态：{snapshot.get('liquidity_state')}",
        f"波动风险状态：{snapshot.get('risk_state')}",
    ]
    if not current or latest is None:
        code = "data_unavailable"
        attention = "不能用于当前关注判断"
        condition = "数据未同步到最新官方完整可用日，不能判断当前是否具备进一步交易研究条件。"
    elif (latest.get("history_count") or 0) < 60:
        code = "insufficient_history"
        attention = "样本不足，继续积累"
        condition = "历史样本不足，暂不形成交易研究条件判断。"
    elif (
        snapshot.get("risk_state") == "high"
        or "高" in str(snapshot.get("risk_state") or "")
        or snapshot.get("liquidity_state") in {"weak", "stressed"}
        or "偏弱" in str(snapshot.get("liquidity_state") or "")
        or "冲击偏高" in str(snapshot.get("liquidity_state") or "")
    ):
        code = "watch_only_risk_elevated"
        attention = "需要关注，但仅限风险观察"
        condition = "异常或流动性风险偏高，仅适合继续核验，不支持据此形成交易方向。"
    elif float(snapshot.get("composite_intensity_score") or 0) >= 80:
        code = "supports_further_trade_research"
        attention = "建议进入进一步研究清单"
        condition = "历史强度达到预设阈值且数据时点合格，可进入进一步交易研究；仍不等于值得买入或卖出。"
    else:
        code = "no_exceptional_signal"
        attention = "常规跟踪"
        condition = "最近数据未达到异常强度阈值，维持常规跟踪。"
    return {
        "assessment_code": code,
        "attention_cn": attention,
        "trade_research_condition_cn": condition,
        "basis_cn": basis,
        "data_as_of": as_of,
        "personalized_trade_suitability": "not_assessed",
        "boundary_cn": "这是可复核的研究筛选，不是个性化投资建议，不输出买卖方向或收益判断。",
    }


def create_user_notice(conn: sqlite3.Connection, body: dict) -> dict:
    data = normalize_notice_payload(conn, body)
    notice_id = "USER-" + uuid.uuid4().hex[:16].upper()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn.execute(
        """INSERT INTO user_notice_entry(
             user_notice_id,product_code,notice_title_cn,notice_title_en,announcement_date,
             official_source_url,event_description_cn,created_by,review_status,reviewed_by,
             reviewed_at,review_note,validation_warnings_json,record_version,created_at,updated_at
           ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (notice_id, data["product_code"], data["notice_title_cn"], data["notice_title_en"],
         data["announcement_date"], data["official_source_url"], data["event_description_cn"],
         data["actor"], "pending_review", None, None, None,
         json.dumps(data["validation_warnings"], ensure_ascii=False), 1, now, now),
    )
    conn.executemany(
        "INSERT INTO user_notice_parameter_record VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(row["record_id"], notice_id, row["parameter_code"], row["announced_value"], row["value_unit"],
          row["start_date"], row["end_date"], row["end_date_inclusive"], row["instrument_scope"],
          row["direction_code"], row["source_excerpt_cn"], row["notes_cn"]) for row in data["parameters"]],
    )
    audit_payload = notice_snapshot(conn, notice_id)
    conn.execute(
        "INSERT INTO user_input_audit_log VALUES (?,?,?,?,?,?,?,?)",
        ("AUD-" + uuid.uuid4().hex[:16].upper(), "user_notice_entry", notice_id, "create", None,
         json.dumps(audit_payload, ensure_ascii=False, sort_keys=True), data["actor"], now),
    )
    return {"ok": True, "user_notice_id": notice_id,
            "parameter_record_ids": [row["record_id"] for row in data["parameters"]],
            "review_status": "pending_review", "validation_warnings": data["validation_warnings"]}


def update_user_notice(conn: sqlite3.Connection, body: dict) -> dict:
    notice_id = str(body.get("user_notice_id", "")).strip()
    before = notice_snapshot(conn, notice_id)
    if before is None:
        raise ValueError("用户公告记录不存在")
    if before["review_status"] not in {"pending_review", "rejected"}:
        raise ValueError("只有待复核或已驳回记录可以修改")
    expected_version = int(body.get("record_version", before["record_version"]))
    if expected_version != before["record_version"]:
        raise ValueError("记录已被其他操作更新，请重新加载后再修改")
    data = normalize_notice_payload(conn, body, exclude_notice_id=notice_id)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn.execute(
        """UPDATE user_notice_entry SET product_code=?,notice_title_cn=?,notice_title_en=?,announcement_date=?,
                  official_source_url=?,event_description_cn=?,review_status='pending_review',reviewed_by=NULL,
                  reviewed_at=NULL,review_note=NULL,validation_warnings_json=?,record_version=record_version+1,updated_at=?
           WHERE user_notice_id=?""",
        (data["product_code"], data["notice_title_cn"], data["notice_title_en"], data["announcement_date"],
         data["official_source_url"], data["event_description_cn"],
         json.dumps(data["validation_warnings"], ensure_ascii=False), now, notice_id),
    )
    conn.execute("DELETE FROM user_notice_parameter_record WHERE user_notice_id=?", (notice_id,))
    conn.executemany(
        "INSERT INTO user_notice_parameter_record VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(row["record_id"], notice_id, row["parameter_code"], row["announced_value"], row["value_unit"],
          row["start_date"], row["end_date"], row["end_date_inclusive"], row["instrument_scope"],
          row["direction_code"], row["source_excerpt_cn"], row["notes_cn"]) for row in data["parameters"]],
    )
    after = notice_snapshot(conn, notice_id)
    conn.execute(
        "INSERT INTO user_input_audit_log VALUES (?,?,?,?,?,?,?,?)",
        ("AUD-" + uuid.uuid4().hex[:16].upper(), "user_notice_entry", notice_id, "update",
         json.dumps(before, ensure_ascii=False, sort_keys=True), json.dumps(after, ensure_ascii=False, sort_keys=True),
         data["actor"], now),
    )
    return {"ok": True, "user_notice_id": notice_id, "review_status": "pending_review",
            "record_version": after["record_version"], "validation_warnings": data["validation_warnings"]}


def review_user_notice(conn: sqlite3.Connection, body: dict) -> dict:
    notice_id = str(body.get("user_notice_id", "")).strip()
    action = str(body.get("action", "")).strip()
    reviewer = str(body.get("reviewer", "")).strip()
    note = str(body.get("review_note", "")).strip()
    if action not in {"approve", "reject", "withdraw"}:
        raise ValueError("action必须为approve、reject或withdraw")
    if not reviewer or not note:
        raise ValueError("复核人和复核意见不能为空")
    before = notice_snapshot(conn, notice_id)
    if before is None:
        raise ValueError("用户公告记录不存在")
    expected_version = int(body.get("record_version", before["record_version"]))
    if expected_version != before["record_version"]:
        raise ValueError("记录已被其他操作更新，请重新加载后再操作")
    if action == "approve" and not before.get("official_source_url"):
        raise ValueError("复核通过前必须补充官方原文链接")
    if action in {"approve", "reject"} and before["review_status"] not in {"pending_review", "rejected"}:
        raise ValueError("当前状态不允许执行该复核操作")
    if action == "withdraw" and before["review_status"] == "withdrawn":
        raise ValueError("该记录已经撤销")
    status = {"approve": "approved", "reject": "rejected", "withdraw": "withdrawn"}[action]
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn.execute(
        """UPDATE user_notice_entry SET review_status=?,reviewed_by=?,reviewed_at=?,review_note=?,
                  record_version=record_version+1,updated_at=? WHERE user_notice_id=?""",
        (status, reviewer, now, note, now, notice_id),
    )
    after = notice_snapshot(conn, notice_id)
    conn.execute(
        "INSERT INTO user_input_audit_log VALUES (?,?,?,?,?,?,?,?)",
        ("AUD-" + uuid.uuid4().hex[:16].upper(), "user_notice_entry", notice_id, action,
         json.dumps(before, ensure_ascii=False, sort_keys=True), json.dumps(after, ensure_ascii=False, sort_keys=True),
         reviewer, now),
    )
    return {"ok": True, "user_notice_id": notice_id, "review_status": status,
            "record_version": after["record_version"]}


def product_payload(conn: sqlite3.Connection, product: str, days: int = 252) -> dict:
    product = product.upper().strip()
    snapshot = row_dict(
        conn.execute("SELECT * FROM product_research_snapshot WHERE product_code=?", (product,)).fetchone()
    )
    if snapshot is None:
        raise ValueError(f"未知品种代码：{product}")
    series = query_dicts(
        conn,
        """
        SELECT trade_date,dominant_contract_code,close,settlement,log_return,
               parkinson_range_vol,volume,turnover,open_interest,
               open_interest_change_ratio,volume_open_interest_ratio,amihud_illiquidity,
               abs_return_percentile,range_vol_percentile,volume_percentile,
               turnover_percentile,abs_oi_change_percentile,illiquidity_percentile,
               history_count,composite_intensity_score,signal_count_80,intensity_level,data_quality_note
        FROM product_trading_intensity_daily
        WHERE product_code=? AND composite_intensity_score IS NOT NULL
        ORDER BY trade_date DESC LIMIT ?
        """,
        (product, max(20, min(days, 2000))),
    )
    series.reverse()
    intense = query_dicts(
        conn,
        """
        SELECT trade_date,dominant_contract_code,close,settlement,
               ROUND(composite_intensity_score,2) AS composite_intensity_score,
               intensity_level,ROUND(abs_return_percentile,2) AS abs_return_percentile,
               ROUND(range_vol_percentile,2) AS range_vol_percentile,
               ROUND(volume_percentile,2) AS volume_percentile,
               ROUND(abs_oi_change_percentile,2) AS abs_oi_change_percentile
        FROM product_trading_intensity_daily
        WHERE product_code=? AND intensity_level IN ('intense','extreme')
        ORDER BY trade_date DESC LIMIT 30
        """,
        (product,),
    )
    has_all_interval_view = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='view' AND name='v_all_policy_interval_effective'"
    ).fetchone()
    interval_view = "v_all_policy_interval_effective" if has_all_interval_view else "v_policy_interval_effective"
    interval_extra = (
        "value_unit,source_layer,review_status"
        if has_all_interval_view
        else "'ratio' AS value_unit,'verified_database' AS source_layer,'legacy_reviewed_or_derived' AS review_status"
    )
    intervals = query_dicts(
        conn,
        f"""
        SELECT interval_id,parameter_code,announced_value,{interval_extra},start_date,end_date,
               start_boundary,start_date_basis,end_date_basis,interval_status,
               source_notice_ids,source_notice_titles,instrument_scopes,
               derivation_limit_cn,override_reason,reviewer,updated_at
        FROM {interval_view}
        WHERE product_code=? ORDER BY parameter_code,start_date
        """,
        (product,),
    )
    changes = query_dicts(
        conn,
        """
        SELECT trade_date,parameter_code,old_value,new_value,affected_contract_count,
               active_contract_count,affected_contract_share,scope_class,interpretation_limit
        FROM official_product_parameter_change_cluster
        WHERE product_code=? ORDER BY trade_date DESC LIMIT 40
        """,
        (product,),
    )
    notices = query_dicts(
        conn,
        """
        SELECT notice_id,notice_title,announcement_date,effective_date,parameter_code,
               expected_new_value,level_alignment_status,change_point_alignment_status,
               interpretation_cn,timing_note_cn,official_source_url
        FROM verified_notice_parameter_change_alignment
        WHERE product_code=? ORDER BY announcement_date DESC,parameter_code LIMIT 40
        """,
        (product,),
    )
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_notice_episode_ec_sn'").fetchone():
        ec_sn_notices = query_dicts(
            conn,
            """
            SELECT notice_id,official_title_cn AS notice_title,announcement_date,
                   policy_reference_date AS effective_date,event_type AS parameter_code,
                   NULL AS expected_new_value,'source_verified_episode' AS level_alignment_status,
                   'specialized_database_verified' AS change_point_alignment_status,
                   event_name_cn||'；'||parameter_values_verified_cn AS interpretation_cn,
                   '政策参考日：'||policy_reference_date||'；生效时点：'||effective_timing AS timing_note_cn,
                   official_source_url,event_name_en,parameter_values_verified_en,
                   direction_cn,direction_en,coding_confidence
            FROM verified_notice_episode_ec_sn
            WHERE product_code=? ORDER BY announcement_date DESC,notice_episode_id LIMIT 80
            """,
            (product,),
        )
        notices.extend(ec_sn_notices)
        notices.sort(key=lambda row: (row.get("announcement_date") or "", row.get("notice_id") or ""), reverse=True)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_notice_entry'").fetchone():
        notices.extend(query_dicts(
            conn,
            """SELECT n.user_notice_id AS notice_id,n.notice_title_cn AS notice_title,n.announcement_date,
                      MIN(p.start_date) AS effective_date,GROUP_CONCAT(DISTINCT p.parameter_code) AS parameter_code,
                      NULL AS expected_new_value,'user_entry' AS level_alignment_status,
                      n.review_status AS change_point_alignment_status,
                      COALESCE(n.event_description_cn,'用户录入，待复核') AS interpretation_cn,
                      '用户录入区间，待官方来源复核' AS timing_note_cn,n.official_source_url
               FROM user_notice_entry n JOIN user_notice_parameter_record p USING(user_notice_id)
               WHERE n.product_code=? GROUP BY n.user_notice_id""", (product,)
        ))
        notices.sort(key=lambda row: (row.get("announcement_date") or "", row.get("notice_id") or ""), reverse=True)
    literature = query_dicts(conn, "SELECT * FROM indicator_literature_registry ORDER BY year")
    completeness = None
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='product_data_completeness_dashboard'").fetchone():
        completeness = row_dict(
            conn.execute("SELECT * FROM product_data_completeness_dashboard WHERE product_code=?", (product,)).fetchone()
        )
    correspondence_summary = None
    correspondence_audit = []
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='product_correspondence_completeness'").fetchone():
        correspondence_summary = row_dict(conn.execute(
            "SELECT * FROM product_correspondence_completeness WHERE product_code=?", (product,)
        ).fetchone())
        correspondence_audit = query_dicts(
            conn,
            """SELECT * FROM notice_parameter_correspondence_audit
               WHERE product_code=?
               ORDER BY CASE review_priority WHEN 'high' THEN 1 WHEN 'medium' THEN 2 WHEN 'corpus_gap' THEN 3 ELSE 4 END,
                        reference_date DESC LIMIT 200""",
            (product,),
        )
    event_master = []
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='notice_parameter_market_real_event_master'").fetchone():
        master_columns = {row[1] for row in conn.execute("PRAGMA table_info(notice_parameter_market_real_event_master)")}
        evidence_fields = (
            "evidence_grade,evidence_status,evidence_source_count,mentor_review_status,evidence_link_note_cn,"
            if "evidence_grade" in master_columns
            else "'U' AS evidence_grade,'legacy_v020_no_evidence_grade' AS evidence_status,0 AS evidence_source_count,"
                 "'legacy_version' AS mentor_review_status,NULL AS evidence_link_note_cn,"
        )
        event_master = query_dicts(
            conn,
            f"""SELECT master_id,announcement_date,policy_reference_date,matched_market_trade_date,
                      policy_event_type_en,policy_event_type_cn,policy_event_name_en,policy_event_name_cn,
                      policy_direction_en,policy_direction_cn,parameter_values_en,parameter_values_cn,
                      real_event_link_status,chain_completeness_grade,real_event_dates,
                      real_event_categories_en,real_event_categories_cn,real_event_names_en,real_event_names_cn,
                      transmission_channels_en,transmission_channels_cn,event_to_policy_gap_trading_days,
                      {evidence_fields}
                      event_day_intensity_score,event_day_intensity_level,
                      post5_minus_pre5_absolute_return,post5_minus_pre5_range_vol,
                      post5_minus_pre5_log_volume,post5_minus_pre5_abs_oi_change,
                      official_source_url,real_event_source_urls,interpretation_limit_cn
               FROM notice_parameter_market_real_event_master
               WHERE product_code=? ORDER BY announcement_date DESC,policy_record_id LIMIT 80""",
            (product,),
        )
    unique_policy_events = []
    window_statistics = []
    overlap_audit = []
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='unique_policy_event_summary'").fetchone():
        unique_policy_events = query_dicts(
            conn, "SELECT * FROM unique_policy_event_summary WHERE product_code=? ORDER BY announcement_date DESC,notice_id", (product,)
        )
        window_statistics = query_dicts(
            conn, "SELECT * FROM policy_market_window_statistics WHERE product_code=? ORDER BY matched_market_trade_date DESC,window_trading_days", (product,)
        )
        overlap_audit = query_dicts(
            conn, "SELECT * FROM policy_event_overlap_audit WHERE product_code=? ORDER BY matched_market_trade_date DESC", (product,)
        )
    user_notices = []
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_notice_entry'").fetchone():
        user_notice_ids = [row[0] for row in conn.execute(
            "SELECT user_notice_id FROM user_notice_entry WHERE product_code=? ORDER BY announcement_date DESC,created_at DESC",
            (product,),
        )]
        user_notices = [notice_snapshot(conn, notice_id) for notice_id in user_notice_ids]
    payload = {
        "product_code": product,
        "snapshot": snapshot,
        "series": series,
        "intense_days": intense,
        "intervals": intervals,
        "parameter_changes": changes,
        "notices": notices,
        "literature": literature,
        "completeness": completeness,
        "correspondence_summary": correspondence_summary,
        "correspondence_audit": correspondence_audit,
        "event_master": event_master,
        "unique_policy_events": unique_policy_events,
        "window_statistics": window_statistics,
        "overlap_audit": overlap_audit,
        "user_notices": user_notices,
    }
    payload["trade_research_assessment"] = build_trade_research_assessment(snapshot, series[-1] if series else None)
    context = build_ai_context(payload)
    payload["ai_context"] = context
    payload["ai_prompt"] = build_prompt(context)
    return payload


def intense_day_context(conn: sqlite3.Connection, product: str, trade_date: str) -> dict:
    product = product.upper().strip()
    trade_date = parse_yyyymmdd(trade_date, "trade_date")
    if not conn.execute("SELECT 1 FROM dim_product WHERE product_code=?", (product,)).fetchone():
        raise ValueError(f"未知品种代码：{product}")
    center = datetime.strptime(trade_date, "%Y%m%d")
    start = (center - timedelta(days=7)).strftime("%Y%m%d")
    end = (center + timedelta(days=7)).strftime("%Y%m%d")
    metrics = row_dict(conn.execute(
        "SELECT * FROM product_trading_intensity_daily WHERE product_code=? AND trade_date=?", (product, trade_date)
    ).fetchone())
    if metrics is None:
        raise ValueError("该品种在所选日期没有交易强度记录")
    changes = query_dicts(conn, """SELECT * FROM official_product_parameter_change_cluster
                                     WHERE product_code=? AND trade_date BETWEEN ? AND ?
                                     ORDER BY trade_date,parameter_code""", (product, start, end))
    notices = query_dicts(conn, """SELECT notice_id,notice_title,announcement_date,effective_date,
                                            parameter_code,interpretation_cn,official_source_url
                                     FROM verified_notice_parameter_change_alignment
                                     WHERE product_code=? AND (announcement_date BETWEEN ? AND ? OR effective_date BETWEEN ? AND ?)
                                     ORDER BY announcement_date""", (product, start, end, start, end))
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_notice_episode_ec_sn'").fetchone():
        notices.extend(query_dicts(conn, """SELECT notice_id,official_title_cn AS notice_title,
                                                     REPLACE(announcement_date,'-','') AS announcement_date,
                                                     REPLACE(policy_reference_date,'-','') AS effective_date,
                                                     event_type AS parameter_code,event_name_cn AS interpretation_cn,
                                                     official_source_url
                                              FROM verified_notice_episode_ec_sn
                                              WHERE product_code=? AND (REPLACE(announcement_date,'-','') BETWEEN ? AND ?
                                                OR REPLACE(policy_reference_date,'-','') BETWEEN ? AND ?)
                                              ORDER BY announcement_date""", (product, start, end, start, end)))
    audit = []
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='notice_parameter_correspondence_audit'").fetchone():
        audit = query_dicts(conn, """SELECT audit_direction_cn,reference_date,parameter_code,
                                              correspondence_status,review_priority,explanation_cn
                                       FROM notice_parameter_correspondence_audit
                                       WHERE product_code=? AND reference_date BETWEEN ? AND ?
                                       ORDER BY reference_date,audit_direction""", (product, start, end))
    return {"product_code": product, "trade_date": trade_date, "window_start": start, "window_end": end,
            "metrics": metrics, "nearby_parameter_changes": changes, "nearby_notices": notices,
            "nearby_correspondence_audit": audit,
            "interpretation_boundary_cn": "前后7个自然日仅用于同步核验和人工下钻，不表示公告、参数与市场异常之间存在因果关系。"}


def extract_response_text(response: dict) -> str:
    texts = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                texts.append(content["text"])
    if not texts:
        raise RuntimeError("OpenAI response did not contain output text")
    return "\n".join(texts)


def call_openai(context: dict) -> dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("未配置OPENAI_API_KEY；量化报告可以正常使用，AI解读暂不可调用。")
    model = os.environ.get("OPENAI_MODEL", "gpt-6-astra")
    schema = {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "historical_state": {"type": "string"},
            "latest_available_state": {"type": "string"},
            "attention_level": {"type": "string", "enum": ["high", "medium", "routine", "unavailable"]},
            "attention_reasons": {"type": "array", "items": {"type": "string"}},
            "risk_reasons": {"type": "array", "items": {"type": "string"}},
            "data_limits": {"type": "array", "items": {"type": "string"}},
            "next_research_actions": {"type": "array", "items": {"type": "string"}},
            "trade_research_condition": {"type": "string", "enum": ["supports_further_research", "watch_only", "routine_tracking", "unavailable"]},
            "trade_decision": {"type": "string", "enum": ["not_assessed"]},
        },
        "required": [
            "summary", "historical_state", "latest_available_state", "attention_level",
            "attention_reasons", "risk_reasons", "data_limits", "next_research_actions",
            "trade_research_condition", "trade_decision",
        ],
        "additionalProperties": False,
    }
    body = {
        "model": model,
        "instructions": (
            "你是审慎的期货市场研究助手。只解释用户提供的结构化数据。"
            "不得提供个性化投资建议、收益承诺或买卖指令；数据滞后时必须把attention_level设为unavailable。"
            "参数与市场异常只能描述同步关系或时间顺序，不能自行宣称因果。输出中文。"
        ),
        "input": json.dumps(context, ensure_ascii=False),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "shfe_product_research_interpretation",
                "strict": True,
                "schema": schema,
            },
            "verbosity": "medium",
        },
        "store": False,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"OpenAI API returned HTTP {exc.code}: {detail[:800]}") from exc
    return {"model": model, "analysis": json.loads(extract_response_text(raw)), "response_id": raw.get("id")}


class AppHandler(BaseHTTPRequestHandler):
    db_path: Path
    web_html: bytes

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def json_response(self, payload: dict | list, status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def csv_response(self, rows: list[dict], filename: str) -> None:
        stream = io.StringIO(newline="")
        if rows:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        data = ("\ufeff" + stream.getvalue()).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/csv; charset=utf-8")
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def open_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(self.web_html)))
            self.end_headers()
            self.wfile.write(self.web_html)
            return
        try:
            with closing(self.open_db()) as conn:
                if parsed.path == "/api/config":
                    self.json_response({"ai_enabled": bool(os.environ.get("OPENAI_API_KEY")),
                                        "ai_model": os.environ.get("OPENAI_MODEL", "gpt-6-astra"),
                                        "auto_ai_default": False,
                                        "research_boundary_cn": "AI只解释数据库证据，不提供买卖指令。"})
                    return
                if parsed.path == "/api/products":
                    self.json_response(query_dicts(conn, "SELECT * FROM product_research_snapshot ORDER BY product_code"))
                    return
                if parsed.path == "/api/product":
                    params = parse_qs(parsed.query)
                    product = params.get("code", [""])[0]
                    days = int(params.get("days", ["252"])[0])
                    self.json_response(product_payload(conn, product, days))
                    return
                if parsed.path == "/api/day-context":
                    params = parse_qs(parsed.query)
                    self.json_response(intense_day_context(conn, params.get("code", [""])[0],
                                                           params.get("date", [""])[0]))
                    return
                if parsed.path == "/api/export/correspondence":
                    params = parse_qs(parsed.query)
                    product = params.get("code", [""])[0].upper().strip()
                    if not product or not conn.execute("SELECT 1 FROM dim_product WHERE product_code=?", (product,)).fetchone():
                        raise ValueError("请提供有效品种代码")
                    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='notice_parameter_correspondence_audit'").fetchone():
                        raise ValueError("当前数据库版本尚无双向核验表")
                    rows = query_dicts(conn, """SELECT * FROM notice_parameter_correspondence_audit
                                                  WHERE product_code=? ORDER BY reference_date,audit_direction""", (product,))
                    self.csv_response(rows, f"{product}_notice_parameter_correspondence.csv")
                    return
                if parsed.path == "/api/user-notices":
                    params = parse_qs(parsed.query)
                    product = params.get("product", [""])[0].upper().strip()
                    status = params.get("status", [""])[0].strip()
                    clauses, values = [], []
                    if product:
                        clauses.append("product_code=?")
                        values.append(product)
                    if status:
                        clauses.append("review_status=?")
                        values.append(status)
                    where = " WHERE " + " AND ".join(clauses) if clauses else ""
                    ids = [row[0] for row in conn.execute(
                        "SELECT user_notice_id FROM user_notice_entry" + where + " ORDER BY announcement_date DESC,created_at DESC",
                        tuple(values),
                    )]
                    self.json_response([notice_snapshot(conn, notice_id) for notice_id in ids])
                    return
            self.json_response({"error": "not_found"}, 404)
        except (ValueError, sqlite3.Error) as exc:
            self.json_response({"error": str(exc)}, 400)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
            if parsed.path == "/api/notice-entry":
                backup_path = backup_user_work(self.db_path, "before_create")
                with closing(self.open_db()) as conn:
                    result = create_user_notice(conn, body)
                    conn.commit()
                result["backup_path"] = backup_path
                self.json_response(result, 201)
                return
            if parsed.path == "/api/notice-update":
                backup_path = backup_user_work(self.db_path, "before_update")
                with closing(self.open_db()) as conn:
                    result = update_user_notice(conn, body)
                    conn.commit()
                result["backup_path"] = backup_path
                self.json_response(result)
                return
            if parsed.path == "/api/notice-review":
                backup_path = backup_user_work(self.db_path, "before_review")
                with closing(self.open_db()) as conn:
                    result = review_user_notice(conn, body)
                    conn.commit()
                result["backup_path"] = backup_path
                self.json_response(result)
                return
            if parsed.path == "/api/interval-override":
                interval_id = str(body.get("interval_id", "")).strip()
                start_date = str(body.get("start_date", "")).strip() or None
                end_date = str(body.get("end_date", "")).strip() or None
                reason = str(body.get("reason", "")).strip()
                reviewer = str(body.get("reviewer", "")).strip()
                start_date = parse_yyyymmdd(start_date, "start_date", required=False)
                end_date = parse_yyyymmdd(end_date, "end_date", required=False)
                if start_date and end_date and end_date < start_date:
                    raise ValueError("结束日不能早于起始日")
                if not interval_id or not reason or not reviewer:
                    raise ValueError("interval_id、修改原因和复核人不能为空")
                backup_path = backup_user_work(self.db_path, "before_interval_override")
                with closing(self.open_db()) as conn:
                    exists = conn.execute("SELECT 1 FROM notice_parameter_policy_interval WHERE interval_id=?", (interval_id,)).fetchone()
                    if not exists:
                        raise ValueError("interval_id不存在")
                    conn.execute(
                        """
                        INSERT INTO policy_interval_manual_override(
                          interval_id,manual_start_date,manual_end_date,manual_end_inclusive,
                          override_reason,reviewer,updated_at
                        ) VALUES (?,?,?,?,?,?,?)
                        ON CONFLICT(interval_id) DO UPDATE SET
                          manual_start_date=excluded.manual_start_date,
                          manual_end_date=excluded.manual_end_date,
                          manual_end_inclusive=excluded.manual_end_inclusive,
                          override_reason=excluded.override_reason,
                          reviewer=excluded.reviewer,
                          updated_at=excluded.updated_at
                        """,
                        (interval_id, start_date, end_date, 1, reason, reviewer, datetime.now().astimezone().isoformat(timespec="seconds")),
                    )
                    conn.commit()
                self.json_response({"ok": True, "interval_id": interval_id, "backup_path": backup_path})
                return
            if parsed.path == "/api/ai":
                product = str(body.get("product_code", "")).upper().strip()
                with closing(self.open_db()) as conn:
                    payload = product_payload(conn, product, 252)
                cache_key = hashlib.sha256(json.dumps(payload["ai_context"], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
                with AI_CACHE_LOCK:
                    cached = AI_RESPONSE_CACHE.get(cache_key)
                if cached is not None:
                    self.json_response({**cached, "cached": True})
                    return
                result = call_openai(payload["ai_context"])
                with AI_CACHE_LOCK:
                    AI_RESPONSE_CACHE[cache_key] = result
                self.json_response({**result, "cached": False})
                return
            self.json_response({"error": "not_found"}, 404)
        except (ValueError, RuntimeError, sqlite3.Error, json.JSONDecodeError) as exc:
            self.json_response({"error": str(exc)}, 400)


def main() -> None:
    args = parse_args()
    db = args.db.resolve()
    if not db.is_file():
        raise SystemExit(f"Database not found: {db}")
    if not WEB_FILE.is_file():
        raise SystemExit(f"Web UI not found: {WEB_FILE}")
    migration_connection = sqlite3.connect(db)
    try:
        ensure_runtime_schema(migration_connection)
        migration_connection.commit()
    finally:
        migration_connection.close()
    AppHandler.db_path = db
    AppHandler.web_html = WEB_FILE.read_bytes()
    server = ThreadingHTTPServer((args.host, args.port), AppHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"SHFE market research assistant: {url}")
    print(f"Database: {db}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
