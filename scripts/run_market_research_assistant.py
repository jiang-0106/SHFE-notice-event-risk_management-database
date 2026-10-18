from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
import uuid
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


DEFAULT_DB = Path(
    r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\outputs\SHFE市场研究助手_v0.16_20261002"
    r"\SHFE公告参数市场研究助手_v0.16.sqlite3"
)
WEB_FILE = Path(__file__).resolve().parents[1] / "web" / "market_research_assistant.html"


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
    product = str(body.get("product_code", "")).upper().strip()
    title_cn = str(body.get("notice_title_cn", "")).strip()
    title_en = str(body.get("notice_title_en", "")).strip() or None
    announcement_date = parse_yyyymmdd(body.get("announcement_date"), "announcement_date")
    source_url = str(body.get("official_source_url", "")).strip() or None
    description = str(body.get("event_description_cn", "")).strip() or None
    actor = str(body.get("created_by", "")).strip()
    parameters = body.get("parameters")
    if not product or not title_cn or not actor:
        raise ValueError("品种、公告中文标题、公告日期和录入人不能为空")
    if not conn.execute("SELECT 1 FROM product_research_snapshot WHERE product_code=?", (product,)).fetchone():
        raise ValueError(f"未知品种代码：{product}")
    if not isinstance(parameters, list) or not parameters:
        raise ValueError("至少录入一条参数调整")
    notice_id = "USER-" + uuid.uuid4().hex[:16].upper()
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    normalized = []
    for index, item in enumerate(parameters, 1):
        if not isinstance(item, dict):
            raise ValueError(f"第{index}条参数格式错误")
        code = str(item.get("parameter_code", "")).strip().upper()
        unit = str(item.get("value_unit", "ratio")).strip() or "ratio"
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
        normalized.append({
            "record_id": "UPR-" + uuid.uuid4().hex[:16].upper(), "parameter_code": code,
            "announced_value": value, "value_unit": unit, "start_date": start, "end_date": end,
            "end_date_inclusive": 1 if item.get("end_date_inclusive", True) else 0,
            "instrument_scope": str(item.get("instrument_scope", "")).strip() or None,
            "direction_code": str(item.get("direction_code", "")).strip() or None,
            "source_excerpt_cn": str(item.get("source_excerpt_cn", "")).strip() or None,
            "notes_cn": str(item.get("notes_cn", "")).strip() or None,
        })
    conn.execute(
        "INSERT INTO user_notice_entry VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (notice_id, product, title_cn, title_en, announcement_date, source_url, description, actor,
         "pending_review", now, now),
    )
    conn.executemany(
        "INSERT INTO user_notice_parameter_record VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(row["record_id"], notice_id, row["parameter_code"], row["announced_value"], row["value_unit"],
          row["start_date"], row["end_date"], row["end_date_inclusive"], row["instrument_scope"],
          row["direction_code"], row["source_excerpt_cn"], row["notes_cn"]) for row in normalized],
    )
    audit_payload = {"notice": {"product_code": product, "notice_title_cn": title_cn,
                     "announcement_date": announcement_date, "official_source_url": source_url},
                     "parameters": normalized, "review_status": "pending_review"}
    conn.execute(
        "INSERT INTO user_input_audit_log VALUES (?,?,?,?,?,?,?,?)",
        ("AUD-" + uuid.uuid4().hex[:16].upper(), "user_notice_entry", notice_id, "create", None,
         json.dumps(audit_payload, ensure_ascii=False, sort_keys=True), actor, now),
    )
    return {"ok": True, "user_notice_id": notice_id,
            "parameter_record_ids": [row["record_id"] for row in normalized],
            "review_status": "pending_review"}


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
        "event_master": event_master,
        "unique_policy_events": unique_policy_events,
        "window_statistics": window_statistics,
        "overlap_audit": overlap_audit,
    }
    payload["trade_research_assessment"] = build_trade_research_assessment(snapshot, series[-1] if series else None)
    context = build_ai_context(payload)
    payload["ai_context"] = context
    payload["ai_prompt"] = build_prompt(context)
    return payload


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
            with self.open_db() as conn:
                if parsed.path == "/api/products":
                    self.json_response(query_dicts(conn, "SELECT * FROM product_research_snapshot ORDER BY product_code"))
                    return
                if parsed.path == "/api/product":
                    params = parse_qs(parsed.query)
                    product = params.get("code", [""])[0]
                    days = int(params.get("days", ["252"])[0])
                    self.json_response(product_payload(conn, product, days))
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
                with self.open_db() as conn:
                    result = create_user_notice(conn, body)
                    conn.commit()
                self.json_response(result, 201)
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
                with self.open_db() as conn:
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
                self.json_response({"ok": True, "interval_id": interval_id})
                return
            if parsed.path == "/api/ai":
                product = str(body.get("product_code", "")).upper().strip()
                with self.open_db() as conn:
                    payload = product_payload(conn, product, 252)
                self.json_response(call_openai(payload["ai_context"]))
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
