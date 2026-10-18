from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import shutil
import sqlite3
import statistics
from collections import defaultdict, deque
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable


VERSION = "v0.16-market-research-assistant"
DEFAULT_SOURCE = Path(
    r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\outputs\SHFE公告参数市场同步数据库_20260909"
    r"\03_全品种扩展\SHFE公告参数市场同步数据库_全品种_公告参数变更点对应_v0.15.sqlite3"
)
DEFAULT_OUTPUT_DIR = Path(
    r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\outputs\SHFE市场研究助手_v0.16_20261002"
)


LITERATURE = [
    {
        "literature_id": "bessembinder_seguin_1993",
        "indicator_name": "异常成交量、持仓量与市场深度",
        "formula_or_use": "成交量、成交额、持仓量及其历史分位数；成交量/持仓量比率",
        "research_role": "识别交易活跃度，并把成交量与持仓深度分开解释",
        "authors": "Hendrik Bessembinder; Paul J. Seguin",
        "year": 1993,
        "title": "Price Volatility, Trading Volume, and Market Depth: Evidence from Futures Markets",
        "doi": "10.2307/2331149",
        "url": "https://doi.org/10.2307/2331149",
        "adaptation_limit": "原文研究多个期货市场的量价与市场深度关系；本库只做历史异常识别，不据此推断收益方向。",
    },
    {
        "literature_id": "parkinson_1980",
        "indicator_name": "Parkinson日内区间波动率",
        "formula_or_use": "abs(log(high/low))/sqrt(4*log(2))",
        "research_role": "利用最高价和最低价衡量日内价格波动强度",
        "authors": "Michael Parkinson",
        "year": 1980,
        "title": "The Extreme Value Method for Estimating the Variance of the Rate of Return",
        "doi": "10.1086/296071",
        "url": "https://doi.org/10.1086/296071",
        "adaptation_limit": "受涨跌停、跳空和价格缺失影响；这里只作为日内波动代理变量。",
    },
    {
        "literature_id": "amihud_2002",
        "indicator_name": "Amihud价格冲击非流动性",
        "formula_or_use": "abs(log_return)/turnover",
        "research_role": "用单位成交额对应的价格变化近似价格冲击",
        "authors": "Yakov Amihud",
        "year": 2002,
        "title": "Illiquidity and Stock Returns: Cross-section and Time-series Effects",
        "doi": "10.1016/S1386-4181(01)00024-6",
        "url": "https://doi.org/10.1016/S1386-4181(01)00024-6",
        "adaptation_limit": "原指标来自股票市场；本库仅在同一品种内部做历史分位比较，不跨品种直接比较绝对值。",
    },
    {
        "literature_id": "andersen_et_al_2003",
        "indicator_name": "波动率历史状态",
        "formula_or_use": "日收益绝对值与区间波动的历史滚动分位数",
        "research_role": "以可获得的日频数据近似刻画波动状态和持续性",
        "authors": "Torben G. Andersen; Tim Bollerslev; Francis X. Diebold; Paul Labys",
        "year": 2003,
        "title": "Modeling and Forecasting Realized Volatility",
        "doi": "10.1111/1468-0262.00418",
        "url": "https://doi.org/10.1111/1468-0262.00418",
        "adaptation_limit": "原文使用高频实现波动率；当前数据库是日频，不能把日频代理量称为严格的实现波动率。",
    },
]


WEIGHTS = {
    "abs_return_percentile": 0.25,
    "range_vol_percentile": 0.20,
    "volume_percentile": 0.20,
    "turnover_percentile": 0.10,
    "abs_oi_change_percentile": 0.10,
    "illiquidity_percentile": 0.10,
    "volume_oi_percentile": 0.05,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the SHFE v0.16 market research assistant layer.")
    parser.add_argument("--source-db", type=Path, default=Path(os.environ.get("SHFE_V016_SOURCE_DB", DEFAULT_SOURCE)))
    parser.add_argument("--output-dir", type=Path, default=Path(os.environ.get("SHFE_V016_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)))
    parser.add_argument("--build-date", default=date.today().isoformat(), help="Research reference date (YYYY-MM-DD).")
    parser.add_argument("--version", default=VERSION)
    parser.add_argument("--artifact-tag", default="v016", help="Filename tag, for example v016 or v017.")
    return parser.parse_args()


def ymd(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def ymd_text(value: date) -> str:
    return value.strftime("%Y%m%d")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def percentile(current: float | None, history: Iterable[float | None], minimum: int = 60) -> float | None:
    if current is None or not math.isfinite(current):
        return None
    values = [v for v in history if v is not None and math.isfinite(v)]
    if len(values) < minimum:
        return None
    below = sum(v < current for v in values)
    equal = sum(v == current for v in values)
    return 100.0 * (below + 0.5 * equal) / len(values)


def zscore(current: float | None, history: Iterable[float | None], minimum: int = 20) -> float | None:
    if current is None or not math.isfinite(current):
        return None
    values = [v for v in history if v is not None and math.isfinite(v)]
    if len(values) < minimum:
        return None
    std = statistics.stdev(values)
    if std == 0:
        return 0.0
    return (current - statistics.mean(values)) / std


def safe_log1p(value: float | None) -> float | None:
    if value is None or value < 0:
        return None
    return math.log1p(value)


def ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den in (None, 0):
        return None
    return num / den


def score_components(components: dict[str, float | None]) -> float | None:
    usable = [(WEIGHTS[key], value) for key, value in components.items() if value is not None]
    if len(usable) < 4:
        return None
    weight_total = sum(weight for weight, _ in usable)
    return sum(weight * value for weight, value in usable) / weight_total


def intensity_level(score: float | None, signal_count: int, history_count: int) -> str:
    if score is None or history_count < 60:
        return "insufficient_history"
    if score >= 97.5 and signal_count >= 4:
        return "extreme"
    if score >= 90 and signal_count >= 3:
        return "intense"
    if score >= 80 and signal_count >= 2:
        return "active"
    return "normal"


def save_manual_overrides(output_db: Path) -> list[tuple[Any, ...]]:
    if not output_db.exists():
        return []
    try:
        conn = sqlite3.connect(output_db)
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='policy_interval_manual_override'"
        ).fetchone()
        if not exists:
            return []
        return conn.execute(
            """
            SELECT interval_id,manual_start_date,manual_end_date,manual_end_inclusive,
                   override_reason,reviewer,updated_at
            FROM policy_interval_manual_override
            """
        ).fetchall()
    finally:
        try:
            conn.close()
        except UnboundLocalError:
            pass


USER_INPUT_TABLES = (
    "user_notice_entry",
    "user_notice_parameter_record",
    "user_input_audit_log",
)


def save_user_input_tables(output_db: Path) -> dict[str, tuple[list[str], list[tuple[Any, ...]]]]:
    if not output_db.exists():
        return {}
    conn = sqlite3.connect(output_db)
    try:
        saved: dict[str, tuple[list[str], list[tuple[Any, ...]]]] = {}
        for table in USER_INPUT_TABLES:
            if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                continue
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]
            saved[table] = (columns, conn.execute(f"SELECT * FROM {table}").fetchall())
        return saved
    finally:
        conn.close()


def restore_user_input_tables(
    conn: sqlite3.Connection,
    saved: dict[str, tuple[list[str], list[tuple[Any, ...]]]],
) -> None:
    for table, (columns, rows) in saved.items():
        if not rows:
            continue
        target_columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        usable = [column for column in columns if column in target_columns]
        positions = [columns.index(column) for column in usable]
        conn.executemany(
            f"INSERT OR REPLACE INTO {table} ({','.join(usable)}) VALUES ({','.join('?' for _ in usable)})",
            [tuple(row[position] for position in positions) for row in rows],
        )


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP VIEW IF EXISTS v_all_policy_interval_effective;
        DROP VIEW IF EXISTS v_policy_interval_effective;
        DROP TABLE IF EXISTS research_assistant_build_metadata;
        DROP TABLE IF EXISTS indicator_literature_registry;
        DROP TABLE IF EXISTS notice_parameter_policy_interval;
        DROP TABLE IF EXISTS product_trading_intensity_daily;
        DROP TABLE IF EXISTS product_research_snapshot;
        DROP TABLE IF EXISTS notice_parameter_market_real_event_master;
        DROP TABLE IF EXISTS unique_policy_event_summary;
        DROP TABLE IF EXISTS policy_market_window_statistics;
        DROP TABLE IF EXISTS policy_event_overlap_audit;

        CREATE TABLE research_assistant_build_metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE indicator_literature_registry (
          literature_id TEXT PRIMARY KEY,
          indicator_name TEXT NOT NULL,
          formula_or_use TEXT NOT NULL,
          research_role TEXT NOT NULL,
          authors TEXT NOT NULL,
          year INTEGER NOT NULL,
          title TEXT NOT NULL,
          doi TEXT NOT NULL,
          url TEXT NOT NULL,
          adaptation_limit TEXT NOT NULL
        );

        CREATE TABLE notice_parameter_policy_interval (
          interval_id TEXT PRIMARY KEY,
          product_code TEXT NOT NULL,
          parameter_code TEXT NOT NULL,
          announced_value REAL NOT NULL,
          start_date TEXT NOT NULL,
          end_date TEXT,
          end_date_inclusive INTEGER NOT NULL DEFAULT 1,
          start_boundary TEXT NOT NULL,
          start_date_basis TEXT NOT NULL,
          end_date_basis TEXT NOT NULL,
          interval_status TEXT NOT NULL,
          source_notice_ids TEXT NOT NULL,
          source_notice_titles TEXT NOT NULL,
          instrument_scopes TEXT NOT NULL,
          source_notice_count INTEGER NOT NULL,
          derivation_limit_cn TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS policy_interval_manual_override (
          interval_id TEXT PRIMARY KEY,
          manual_start_date TEXT,
          manual_end_date TEXT,
          manual_end_inclusive INTEGER NOT NULL DEFAULT 1,
          override_reason TEXT NOT NULL,
          reviewer TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(interval_id) REFERENCES notice_parameter_policy_interval(interval_id)
        );

        CREATE TABLE IF NOT EXISTS user_notice_entry (
          user_notice_id TEXT PRIMARY KEY,
          product_code TEXT NOT NULL,
          notice_title_cn TEXT NOT NULL,
          notice_title_en TEXT,
          announcement_date TEXT NOT NULL,
          official_source_url TEXT,
          event_description_cn TEXT,
          created_by TEXT NOT NULL,
          review_status TEXT NOT NULL DEFAULT 'pending_review',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_notice_parameter_record (
          record_id TEXT PRIMARY KEY,
          user_notice_id TEXT NOT NULL,
          parameter_code TEXT NOT NULL,
          announced_value REAL NOT NULL,
          value_unit TEXT NOT NULL,
          start_date TEXT NOT NULL,
          end_date TEXT,
          end_date_inclusive INTEGER NOT NULL DEFAULT 1,
          instrument_scope TEXT,
          direction_code TEXT,
          source_excerpt_cn TEXT,
          notes_cn TEXT,
          FOREIGN KEY(user_notice_id) REFERENCES user_notice_entry(user_notice_id)
        );

        CREATE TABLE IF NOT EXISTS user_input_audit_log (
          audit_id TEXT PRIMARY KEY,
          entity_type TEXT NOT NULL,
          entity_id TEXT NOT NULL,
          action TEXT NOT NULL,
          before_json TEXT,
          after_json TEXT NOT NULL,
          actor TEXT NOT NULL,
          created_at TEXT NOT NULL
        );

        CREATE VIEW v_policy_interval_effective AS
        SELECT p.interval_id,p.product_code,p.parameter_code,p.announced_value,
               COALESCE(m.manual_start_date,p.start_date) AS start_date,
               COALESCE(m.manual_end_date,p.end_date) AS end_date,
               COALESCE(m.manual_end_inclusive,p.end_date_inclusive) AS end_date_inclusive,
               p.start_boundary,p.start_date_basis,
               CASE WHEN m.interval_id IS NOT NULL THEN 'manual_override' ELSE p.end_date_basis END AS end_date_basis,
               CASE WHEN m.interval_id IS NOT NULL THEN 'manual_override' ELSE p.interval_status END AS interval_status,
               p.source_notice_ids,p.source_notice_titles,p.instrument_scopes,p.source_notice_count,
               p.derivation_limit_cn,m.override_reason,m.reviewer,m.updated_at
        FROM notice_parameter_policy_interval p
        LEFT JOIN policy_interval_manual_override m USING(interval_id);

        CREATE VIEW v_all_policy_interval_effective AS
        SELECT interval_id,product_code,parameter_code,announced_value,start_date,end_date,
               end_date_inclusive,start_boundary,start_date_basis,end_date_basis,interval_status,
               source_notice_ids,source_notice_titles,instrument_scopes,source_notice_count,
               derivation_limit_cn,override_reason,reviewer,updated_at,
               'verified_database' AS source_layer,'reviewed_or_derived' AS review_status,
               'ratio' AS value_unit
        FROM v_policy_interval_effective
        UNION ALL
        SELECT p.record_id AS interval_id,n.product_code,p.parameter_code,p.announced_value,
               p.start_date,p.end_date,p.end_date_inclusive,
               'user_entered_effective_start' AS start_boundary,
               'user_entered_from_notice' AS start_date_basis,
               CASE WHEN p.end_date IS NULL THEN 'open_ended_user_entry' ELSE 'user_entered_from_notice' END AS end_date_basis,
               CASE WHEN p.end_date IS NULL THEN 'open' ELSE 'closed' END AS interval_status,
               n.user_notice_id AS source_notice_ids,n.notice_title_cn AS source_notice_titles,
               COALESCE(p.instrument_scope,'未填写') AS instrument_scopes,1 AS source_notice_count,
               '用户录入，尚待与官方原文及结构化数据库复核。' AS derivation_limit_cn,
               p.notes_cn AS override_reason,n.created_by AS reviewer,n.updated_at,
               'user_entry' AS source_layer,n.review_status,p.value_unit
        FROM user_notice_parameter_record p
        JOIN user_notice_entry n USING(user_notice_id);

        CREATE TABLE product_trading_intensity_daily (
          trade_date TEXT NOT NULL,
          product_code TEXT NOT NULL,
          dominant_contract_code TEXT NOT NULL,
          close REAL,
          settlement REAL,
          log_return REAL,
          absolute_log_return REAL,
          intraday_log_range REAL,
          parkinson_range_vol REAL,
          volume REAL,
          turnover REAL,
          open_interest REAL,
          open_interest_change REAL,
          open_interest_change_ratio REAL,
          volume_open_interest_ratio REAL,
          amihud_illiquidity REAL,
          contract_roll_flag INTEGER NOT NULL,
          history_count INTEGER NOT NULL,
          return_z60 REAL,
          range_z60 REAL,
          log_volume_z60 REAL,
          log_turnover_z60 REAL,
          abs_return_percentile REAL,
          range_vol_percentile REAL,
          volume_percentile REAL,
          turnover_percentile REAL,
          abs_oi_change_percentile REAL,
          illiquidity_percentile REAL,
          volume_oi_percentile REAL,
          composite_intensity_score REAL,
          signal_count_80 INTEGER NOT NULL,
          intensity_level TEXT NOT NULL,
          data_quality_note TEXT NOT NULL,
          PRIMARY KEY(trade_date,product_code)
        );

        CREATE INDEX idx_intensity_product_score
        ON product_trading_intensity_daily(product_code,composite_intensity_score DESC);

        CREATE TABLE product_research_snapshot (
          product_code TEXT PRIMARY KEY,
          database_last_date TEXT NOT NULL,
          analysis_date TEXT,
          data_age_calendar_days INTEGER NOT NULL,
          freshness_status TEXT NOT NULL,
          dominant_contract_code TEXT,
          composite_intensity_score REAL,
          intensity_level TEXT,
          volume_percentile REAL,
          turnover_percentile REAL,
          abs_return_percentile REAL,
          range_vol_percentile REAL,
          illiquidity_percentile REAL,
          recent_intense_days_20 INTEGER NOT NULL,
          recent_parameter_changes_60 INTEGER NOT NULL,
          verified_notice_records_365 INTEGER NOT NULL,
          historical_attention_level TEXT NOT NULL,
          current_assessment_status TEXT NOT NULL,
          liquidity_state TEXT NOT NULL,
          risk_state TEXT NOT NULL,
          conclusion_cn TEXT NOT NULL,
          evidence_boundary_cn TEXT NOT NULL,
          generated_at TEXT NOT NULL
        );

        CREATE TABLE product_data_completeness_dashboard (
          product_code TEXT PRIMARY KEY,
          market_first_date TEXT,
          market_last_date TEXT,
          market_trade_days INTEGER NOT NULL,
          market_contract_rows INTEGER NOT NULL,
          settlement_first_date TEXT,
          settlement_last_date TEXT,
          settlement_rows INTEGER NOT NULL,
          trade_parameter_first_date TEXT,
          trade_parameter_last_date TEXT,
          trade_parameter_rows INTEGER NOT NULL,
          trade_parameter_contract_coverage_pct REAL,
          settlement_contract_coverage_pct REAL,
          margin_agreement_pct REAL,
          verified_notice_records INTEGER NOT NULL,
          parameter_change_clusters INTEGER NOT NULL,
          derived_position_limit_rows INTEGER NOT NULL,
          availability_checked_through TEXT,
          latest_complete_sync_date TEXT,
          unresolved_availability_checks INTEGER NOT NULL,
          research_readiness_status TEXT NOT NULL,
          completeness_issues_cn TEXT NOT NULL,
          generated_at TEXT NOT NULL
        );

        CREATE TABLE notice_parameter_market_real_event_master (
          master_id TEXT PRIMARY KEY,
          source_policy_layer TEXT NOT NULL,
          policy_record_id TEXT NOT NULL,
          notice_id TEXT NOT NULL,
          product_code TEXT NOT NULL,
          product_name_en TEXT NOT NULL,
          product_name_cn TEXT NOT NULL,
          announcement_date TEXT NOT NULL,
          policy_reference_date TEXT,
          requested_analysis_trade_date TEXT,
          matched_market_trade_date TEXT,
          market_date_shift_calendar_days INTEGER,
          policy_event_type_code TEXT NOT NULL,
          policy_event_type_en TEXT NOT NULL,
          policy_event_type_cn TEXT NOT NULL,
          policy_event_name_en TEXT NOT NULL,
          policy_event_name_cn TEXT NOT NULL,
          policy_direction_code TEXT,
          policy_direction_en TEXT,
          policy_direction_cn TEXT,
          parameter_values_en TEXT,
          parameter_values_cn TEXT,
          official_notice_title_cn TEXT NOT NULL,
          official_source_url TEXT NOT NULL,
          policy_date_cluster_id TEXT,
          real_event_link_status TEXT NOT NULL,
          evidence_grade TEXT NOT NULL,
          evidence_status TEXT NOT NULL,
          evidence_source_count INTEGER NOT NULL,
          mentor_review_status TEXT NOT NULL,
          evidence_link_note_cn TEXT,
          chain_completeness_grade TEXT,
          real_event_ids TEXT,
          real_event_dates TEXT,
          real_event_categories_en TEXT,
          real_event_categories_cn TEXT,
          real_event_names_en TEXT,
          real_event_names_cn TEXT,
          real_event_source_urls TEXT,
          transmission_channels_en TEXT,
          transmission_channels_cn TEXT,
          expected_directions_en TEXT,
          expected_directions_cn TEXT,
          event_to_policy_gap_trading_days TEXT,
          intermediate_anomaly_days TEXT,
          intermediate_max_anomaly_count TEXT,
          event_day_intensity_score REAL,
          event_day_intensity_level TEXT,
          event_day_log_return REAL,
          event_day_parkinson_range_vol REAL,
          event_day_volume REAL,
          event_day_open_interest REAL,
          pre5_absolute_return_mean REAL,
          post5_absolute_return_mean REAL,
          post5_minus_pre5_absolute_return REAL,
          pre5_range_vol_mean REAL,
          post5_range_vol_mean REAL,
          post5_minus_pre5_range_vol REAL,
          pre5_log_volume_mean REAL,
          post5_log_volume_mean REAL,
          post5_minus_pre5_log_volume REAL,
          pre5_abs_oi_change_mean REAL,
          post5_abs_oi_change_mean REAL,
          post5_minus_pre5_abs_oi_change REAL,
          interpretation_limit_en TEXT NOT NULL,
          interpretation_limit_cn TEXT NOT NULL,
          generated_at TEXT NOT NULL
        );

        CREATE INDEX idx_master_product_date
        ON notice_parameter_market_real_event_master(product_code,matched_market_trade_date);

        CREATE TABLE unique_policy_event_summary (
          unique_policy_event_id TEXT PRIMARY KEY,
          product_code TEXT NOT NULL,
          notice_id TEXT NOT NULL,
          announcement_date TEXT NOT NULL,
          policy_reference_date TEXT,
          matched_market_trade_date TEXT,
          policy_parameter_row_count INTEGER NOT NULL,
          policy_event_type_codes TEXT NOT NULL,
          policy_event_types_en TEXT NOT NULL,
          policy_event_types_cn TEXT NOT NULL,
          policy_event_name_en TEXT NOT NULL,
          policy_event_name_cn TEXT NOT NULL,
          real_event_link_status TEXT NOT NULL,
          evidence_grade TEXT NOT NULL,
          mentor_review_status TEXT NOT NULL,
          official_source_url TEXT NOT NULL,
          interpretation_limit_cn TEXT NOT NULL,
          generated_at TEXT NOT NULL
        );

        CREATE TABLE policy_market_window_statistics (
          unique_policy_event_id TEXT NOT NULL,
          product_code TEXT NOT NULL,
          matched_market_trade_date TEXT NOT NULL,
          window_trading_days INTEGER NOT NULL,
          pre_observation_count INTEGER NOT NULL,
          post_observation_count INTEGER NOT NULL,
          complete_symmetric_window INTEGER NOT NULL,
          pre_absolute_return_mean REAL,
          post_absolute_return_mean REAL,
          post_minus_pre_absolute_return REAL,
          pre_range_vol_mean REAL,
          post_range_vol_mean REAL,
          post_minus_pre_range_vol REAL,
          pre_log_volume_mean REAL,
          post_log_volume_mean REAL,
          post_minus_pre_log_volume REAL,
          pre_abs_oi_change_mean REAL,
          post_abs_oi_change_mean REAL,
          post_minus_pre_abs_oi_change REAL,
          event_day_contract_roll_flag INTEGER,
          pre_window_roll_days INTEGER NOT NULL,
          post_window_roll_days INTEGER NOT NULL,
          method_note_cn TEXT NOT NULL,
          PRIMARY KEY(unique_policy_event_id,window_trading_days)
        );

        CREATE TABLE policy_event_overlap_audit (
          unique_policy_event_id TEXT PRIMARY KEY,
          product_code TEXT NOT NULL,
          matched_market_trade_date TEXT NOT NULL,
          other_policy_events_within_5d INTEGER NOT NULL,
          other_policy_events_within_10d INTEGER NOT NULL,
          other_policy_events_within_20d INTEGER NOT NULL,
          overlapping_policy_event_ids_20d TEXT,
          real_event_count_linked INTEGER NOT NULL,
          overlap_identification_status TEXT NOT NULL,
          interpretation_limit_cn TEXT NOT NULL
        );
        """
    )


def build_intervals(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT notice_id,notice_title,product_code,parameter_code,expected_new_value,
               effective_date,effective_rule,effective_date_basis,instrument_scope
        FROM verified_notice_parameter_change_alignment
        WHERE effective_date IS NOT NULL AND expected_new_value IS NOT NULL
        ORDER BY product_code,parameter_code,effective_date,notice_id
        """
    ).fetchall()
    grouped: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        grouped[(row[2], row[3])].append(row)

    intervals: list[dict[str, Any]] = []
    for (product, parameter), items in grouped.items():
        by_date_value: dict[tuple[str, float], dict[str, Any]] = {}
        for notice_id, title, _, _, value, effective, rule, basis, scope in items:
            key = (effective, float(value))
            item = by_date_value.setdefault(
                key,
                {
                    "effective": effective,
                    "value": float(value),
                    "notice_ids": set(),
                    "titles": set(),
                    "rules": set(),
                    "bases": set(),
                    "scopes": set(),
                },
            )
            item["notice_ids"].add(notice_id)
            item["titles"].add(title)
            item["rules"].add(rule)
            item["bases"].add(basis)
            item["scopes"].add(scope)

        current: dict[str, Any] | None = None
        for item in sorted(by_date_value.values(), key=lambda x: (x["effective"], x["value"])):
            if current is not None and abs(current["value"] - item["value"]) <= 1e-12:
                current["notice_ids"].update(item["notice_ids"])
                current["titles"].update(item["titles"])
                current["rules"].update(item["rules"])
                current["bases"].update(item["bases"])
                current["scopes"].update(item["scopes"])
                continue
            if current is not None:
                current["end"] = ymd_text(ymd(item["effective"]) - timedelta(days=1))
                current["end_basis"] = "derived_day_before_next_distinct_verified_level"
                current["status"] = "derived_closed"
                intervals.append(current)
            current = dict(item)
            current["end"] = None
            current["end_basis"] = "open_ended_no_later_distinct_verified_level"
            current["status"] = "open_ended"
        if current is not None:
            intervals.append(current)

        for item in intervals:
            if item.get("product") is None:
                item["product"] = product
                item["parameter"] = parameter

    insert_rows = []
    for item in intervals:
        boundary = "after_close_settlement" if any("收盘" in rule for rule in item["rules"]) else "date_effective_time_unspecified"
        stable = f"{item['product']}|{item['parameter']}|{item['effective']}|{item['value']:.12g}"
        interval_id = "pi_" + hashlib.sha1(stable.encode("utf-8")).hexdigest()[:16]
        insert_rows.append(
            (
                interval_id,
                item["product"],
                item["parameter"],
                item["value"],
                item["effective"],
                item["end"],
                1,
                boundary,
                "verified_notice_effective_date:" + "|".join(sorted(item["bases"])),
                item["end_basis"],
                item["status"],
                "|".join(sorted(item["notice_ids"])),
                "|".join(sorted(item["titles"])),
                "|".join(sorted(item["scopes"])),
                len(item["notice_ids"]),
                "区间按同品种同参数下一次不同已核验公告值推导；属于品种层公告基准，不替代临近交割等从高适用的合约级实际参数。",
            )
        )
    conn.executemany(
        "INSERT INTO notice_parameter_policy_interval VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        insert_rows,
    )
    return len(insert_rows)


def load_market_rows(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    query = """
    SELECT d.trade_date,d.product_code,d.contract_code,d.close,d.settlement,
           d.same_contract_log_return,d.absolute_log_return,d.intraday_log_range,
           COALESCE(p.volume,d.volume) AS volume,
           COALESCE(p.turnover,d.turnover) AS turnover,
           COALESCE(p.open_interest,d.open_interest) AS open_interest,
           p.open_interest_change,d.contract_roll_flag
    FROM market_dominant_daily d
    LEFT JOIN market_product_daily p
      ON p.trade_date=d.trade_date AND p.product_code=d.product_code
    ORDER BY d.product_code,d.trade_date
    """
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in conn.execute(query):
        output[row[1]].append(
            {
                "trade_date": row[0],
                "product_code": row[1],
                "contract_code": row[2],
                "close": row[3],
                "settlement": row[4],
                "return": row[5],
                "abs_return": row[6],
                "range": row[7],
                "volume": row[8],
                "turnover": row[9],
                "open_interest": row[10],
                "open_interest_change": row[11],
                "roll": int(row[12] or 0),
            }
        )
    return output


def build_intensity(conn: sqlite3.Connection) -> tuple[int, dict[str, list[dict[str, Any]]]]:
    products = load_market_rows(conn)
    insert_rows = []
    computed: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for product, rows in products.items():
        history: dict[str, deque[float | None]] = {
            key: deque(maxlen=252)
            for key in ["abs_return", "range_vol", "log_volume", "log_turnover", "abs_oi_change", "illiquidity", "volume_oi"]
        }
        previous_oi = None
        for row in rows:
            parkinson = None if row["range"] is None else abs(row["range"]) / math.sqrt(4 * math.log(2))
            oi_change_ratio = ratio(row["open_interest_change"], previous_oi)
            if oi_change_ratio is None and previous_oi not in (None, 0) and row["open_interest"] is not None:
                oi_change_ratio = (row["open_interest"] - previous_oi) / previous_oi
            volume_oi = ratio(row["volume"], row["open_interest"])
            illiquidity = ratio(row["abs_return"], row["turnover"])
            current = {
                "abs_return": row["abs_return"],
                "range_vol": parkinson,
                "log_volume": safe_log1p(row["volume"]),
                "log_turnover": safe_log1p(row["turnover"]),
                "abs_oi_change": None if oi_change_ratio is None else abs(oi_change_ratio),
                "illiquidity": illiquidity,
                "volume_oi": volume_oi,
            }
            pct = {
                "abs_return_percentile": percentile(current["abs_return"], history["abs_return"]),
                "range_vol_percentile": percentile(current["range_vol"], history["range_vol"]),
                "volume_percentile": percentile(current["log_volume"], history["log_volume"]),
                "turnover_percentile": percentile(current["log_turnover"], history["log_turnover"]),
                "abs_oi_change_percentile": percentile(current["abs_oi_change"], history["abs_oi_change"]),
                "illiquidity_percentile": percentile(current["illiquidity"], history["illiquidity"]),
                "volume_oi_percentile": percentile(current["volume_oi"], history["volume_oi"]),
            }
            score = score_components(pct)
            signal_count = sum(value is not None and value >= 80 for value in pct.values())
            history_count = len(history["log_volume"])
            level = intensity_level(score, signal_count, history_count)
            missing = [name for name, value in {"close": row["close"], "settlement": row["settlement"], "volume": row["volume"], "open_interest": row["open_interest"]}.items() if value is None]
            quality_note = "ok" if not missing else "missing:" + ",".join(missing)
            result = {
                **row,
                "parkinson": parkinson,
                "oi_change_ratio": oi_change_ratio,
                "volume_oi": volume_oi,
                "illiquidity": illiquidity,
                **pct,
                "score": score,
                "signal_count": signal_count,
                "history_count": history_count,
                "level": level,
                "quality_note": quality_note,
            }
            computed[product].append(result)
            insert_rows.append(
                (
                    row["trade_date"], product, row["contract_code"], row["close"], row["settlement"], row["return"], row["abs_return"], row["range"], parkinson,
                    row["volume"], row["turnover"], row["open_interest"], row["open_interest_change"], oi_change_ratio, volume_oi, illiquidity, row["roll"], history_count,
                    zscore(current["abs_return"], list(history["abs_return"])[-60:]),
                    zscore(current["range_vol"], list(history["range_vol"])[-60:]),
                    zscore(current["log_volume"], list(history["log_volume"])[-60:]),
                    zscore(current["log_turnover"], list(history["log_turnover"])[-60:]),
                    pct["abs_return_percentile"], pct["range_vol_percentile"], pct["volume_percentile"], pct["turnover_percentile"],
                    pct["abs_oi_change_percentile"], pct["illiquidity_percentile"], pct["volume_oi_percentile"], score, signal_count, level, quality_note,
                )
            )
            for key, value in current.items():
                history[key].append(value)
            if row["open_interest"] is not None:
                previous_oi = row["open_interest"]

    conn.executemany(
        """
        INSERT INTO product_trading_intensity_daily VALUES (
          ?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?
        )
        """,
        insert_rows,
    )
    return len(insert_rows), computed


PRODUCT_NAMES = {
    "AO": ("Alumina", "氧化铝"),
    "BU": ("Bitumen", "石油沥青"),
    "EC": ("Containerized Freight Index (Europe Service)", "集运指数（欧线）"),
    "SN": ("Tin", "锡"),
}

PARAMETER_TYPES = {
    "price_limit": ("Price limit adjustment", "涨跌停板幅度调整"),
    "margin_hedge": ("Hedging-position margin adjustment", "套期保值持仓交易保证金调整"),
    "margin_general": ("General-position margin adjustment", "一般持仓交易保证金调整"),
    "spec_margin_ratio": ("Speculative trading margin adjustment", "投机交易保证金调整"),
    "hedge_margin_ratio": ("Hedging trading margin adjustment", "套期保值交易保证金调整"),
    "fee": ("Trading fee adjustment", "交易手续费调整"),
    "intraday_open_limit": ("Intraday opening-position limit adjustment", "日内开仓限额调整"),
    "margin_and_price_limit": ("Margin and price-limit adjustment", "保证金与涨跌停板幅度调整"),
    "holiday_temporary": ("Temporary holiday adjustment", "节假日前后临时调整"),
    "routine_fee_relief": ("Routine fee relief", "常规手续费减免"),
}


def compact_date(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.replace("-", "").replace("/", "")
    return cleaned[:8] if len(cleaned) >= 8 else None


def finite_mean(values: Iterable[float | None]) -> float | None:
    usable = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return statistics.mean(usable) if usable else None


def difference(after: float | None, before: float | None) -> float | None:
    return None if after is None or before is None else after - before


def pipe_unique(values: Iterable[Any]) -> str | None:
    output: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in output:
            output.append(text)
    return " | ".join(output) if output else None


def market_window(series: list[dict[str, Any]], requested_date: str | None) -> dict[str, Any]:
    requested = compact_date(requested_date)
    if not requested or not series:
        return {}
    index = next((i for i, row in enumerate(series) if row["trade_date"] >= requested), None)
    if index is None:
        return {}
    event = series[index]
    pre = series[max(0, index - 5):index]
    post = series[index + 1:index + 6]
    pre_abs_return = finite_mean(row["abs_return"] for row in pre)
    post_abs_return = finite_mean(row["abs_return"] for row in post)
    pre_range = finite_mean(row["parkinson"] for row in pre)
    post_range = finite_mean(row["parkinson"] for row in post)
    pre_log_volume = finite_mean(safe_log1p(row["volume"]) for row in pre)
    post_log_volume = finite_mean(safe_log1p(row["volume"]) for row in post)
    pre_abs_oi = finite_mean(abs(row["oi_change_ratio"]) if row["oi_change_ratio"] is not None else None for row in pre)
    post_abs_oi = finite_mean(abs(row["oi_change_ratio"]) if row["oi_change_ratio"] is not None else None for row in post)
    shift = (ymd(event["trade_date"]) - ymd(requested)).days
    return {
        "matched_market_trade_date": event["trade_date"],
        "market_date_shift_calendar_days": shift,
        "event_day_intensity_score": event["score"],
        "event_day_intensity_level": event["level"],
        "event_day_log_return": event["return"],
        "event_day_parkinson_range_vol": event["parkinson"],
        "event_day_volume": event["volume"],
        "event_day_open_interest": event["open_interest"],
        "pre5_absolute_return_mean": pre_abs_return,
        "post5_absolute_return_mean": post_abs_return,
        "post5_minus_pre5_absolute_return": difference(post_abs_return, pre_abs_return),
        "pre5_range_vol_mean": pre_range,
        "post5_range_vol_mean": post_range,
        "post5_minus_pre5_range_vol": difference(post_range, pre_range),
        "pre5_log_volume_mean": pre_log_volume,
        "post5_log_volume_mean": post_log_volume,
        "post5_minus_pre5_log_volume": difference(post_log_volume, pre_log_volume),
        "pre5_abs_oi_change_mean": pre_abs_oi,
        "post5_abs_oi_change_mean": post_abs_oi,
        "post5_minus_pre5_abs_oi_change": difference(post_abs_oi, pre_abs_oi),
    }


def build_notice_market_event_master(conn: sqlite3.Connection, computed: dict[str, list[dict[str, Any]]]) -> int:
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    chains: dict[str, list[sqlite3.Row]] = defaultdict(list)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_event_policy_chain_ec_sn'").fetchone():
        for row in conn.execute("SELECT * FROM verified_event_policy_chain_ec_sn ORDER BY policy_date_cluster_id,chain_id"):
            chains[row["policy_date_cluster_id"]].append(row)
    ao_bu_evidence: dict[str, list[sqlite3.Row]] = defaultdict(list)
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ao_bu_policy_event_evidence_link'").fetchone():
        for row in conn.execute(
            """SELECT l.*,e.event_date,e.event_end_date,e.category_en,e.category_cn,e.event_name_en,e.event_name_cn,
                      e.transmission_en,e.transmission_cn,e.source_url,e.evidence_grade,e.evidence_status,e.independent_source_2
               FROM ao_bu_policy_event_evidence_link l JOIN ao_bu_real_event_evidence e USING(event_id)
               ORDER BY l.notice_id,e.event_date,e.event_id"""
        ):
            ao_bu_evidence[row["notice_id"]].append(row)
    verified_events: dict[str, sqlite3.Row] = {}
    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_real_world_event_ec_sn'").fetchone():
        verified_events = {row["real_event_id"]: row for row in conn.execute("SELECT * FROM verified_real_world_event_ec_sn")}

    columns = [row[1] for row in conn.execute("PRAGMA table_info(notice_parameter_market_real_event_master)")]
    records: list[dict[str, Any]] = []
    boundary_en = "Descriptive temporal correspondence only. Window differences are uncontrolled before/after summaries, not causal estimates or trading recommendations."
    boundary_cn = "仅作描述性时间对应。窗口差异是未经控制的前后期汇总，不是因果估计，也不构成交易建议。"

    for row in conn.execute(
        """SELECT verified_parameter_id,notice_id,announcement_date,notice_title,product_code,
                  parameter_code,change_stage,expected_new_value,effective_date,observation_trade_date,
                  interpretation_en,interpretation_cn,official_source_url,effective_date_basis
           FROM verified_notice_parameter_change_alignment WHERE product_code IN ('AO','BU')
           ORDER BY product_code,announcement_date,verified_parameter_id"""
    ):
        product = row[4]
        parameter_code = row[5]
        type_en, type_cn = PARAMETER_TYPES.get(parameter_code, (parameter_code.replace("_", " ").title(), parameter_code))
        requested = row[8] or row[9] or row[2]
        value = row[7]
        value_text = f"{value:.8g}" if value is not None else "not numerically coded"
        if value is not None and parameter_code in {"price_limit", "margin_hedge", "margin_general", "spec_margin_ratio", "hedge_margin_ratio"}:
            value_en = f"{100 * value:.2f}% (stored decimal {value:.8g})"
            value_cn = f"{100 * value:.2f}%（数据库小数值{value:.8g}）"
        else:
            value_en = value_text
            value_cn = value_text
        evidence = ao_bu_evidence.get(row[1], [])
        grades = [item["evidence_grade"] for item in evidence]
        grade = min(grades) if grades else "U"
        routine_listing = "listing" in (row[13] or "").lower()
        if any(item["link_status"] == "verified_administrative_link" for item in evidence):
            link_status = "verified_administrative_event_link"
        elif any(item["link_status"] == "strong_temporal_sector_link" for item in evidence):
            link_status = "strong_temporal_sector_event_link_not_causal"
        elif evidence:
            link_status = "contextual_real_event_candidate"
        elif routine_listing:
            link_status = "routine_contract_lifecycle_policy"
        else:
            link_status = "no_screened_real_event_or_routine_policy"
        record = {
            "master_id": f"AO_BU::{row[0]}", "source_policy_layer": "ao_bu_verified_parameter_alignment",
            "policy_record_id": row[0], "notice_id": row[1], "product_code": product,
            "product_name_en": PRODUCT_NAMES[product][0], "product_name_cn": PRODUCT_NAMES[product][1],
            "announcement_date": compact_date(row[2]), "policy_reference_date": compact_date(row[8]),
            "requested_analysis_trade_date": compact_date(requested), "policy_event_type_code": parameter_code,
            "policy_event_type_en": type_en, "policy_event_type_cn": type_cn,
            "policy_event_name_en": f"{PRODUCT_NAMES[product][0]} {type_en.lower()} announced on {row[2]}",
            "policy_event_name_cn": row[3], "policy_direction_code": row[6],
            "policy_direction_en": "Parameter adjustment; direction should be interpreted from the coded value and prior level",
            "policy_direction_cn": "参数调整；收紧或放松方向需结合公告值与前值判断",
            "parameter_values_en": f"Coded announced value: {value_en}", "parameter_values_cn": f"公告编码值：{value_cn}",
            "official_notice_title_cn": row[3], "official_source_url": row[12], "policy_date_cluster_id": None,
            "real_event_link_status": link_status, "evidence_grade": grade,
            "evidence_status": pipe_unique(item["evidence_status"] for item in evidence) or ("official_listing_rule_routine" if routine_listing else "not_linked_after_initial_screening"),
            "evidence_source_count": sum(1 + bool(item["independent_source_2"]) for item in evidence),
            "mentor_review_status": "pending_mentor_review" if evidence else ("rule_based_routine_classification" if routine_listing else "requires_event_research_or_routine_classification"),
            "evidence_link_note_cn": pipe_unique(item["link_note_cn"] for item in evidence), "chain_completeness_grade": None,
            "real_event_ids": pipe_unique(item["event_id"] for item in evidence),
            "real_event_dates": pipe_unique(item["event_date"] for item in evidence),
            "real_event_categories_en": pipe_unique(item["category_en"] for item in evidence),
            "real_event_categories_cn": pipe_unique(item["category_cn"] for item in evidence),
            "real_event_names_en": pipe_unique(item["event_name_en"] for item in evidence),
            "real_event_names_cn": pipe_unique(item["event_name_cn"] for item in evidence),
            "real_event_source_urls": pipe_unique(item["source_url"] for item in evidence),
            "transmission_channels_en": pipe_unique(item["transmission_en"] for item in evidence),
            "transmission_channels_cn": pipe_unique(item["transmission_cn"] for item in evidence),
            "interpretation_limit_en": boundary_en + " AO/BU contextual links require mentor review before research use.",
            "interpretation_limit_cn": boundary_cn + " AO/BU现实事件链接为初筛结果，须经导师复核后方可作为正式研究证据。", "generated_at": generated_at,
        }
        record.update(market_window(computed.get(product, []), requested))
        records.append(record)

    if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_notice_episode_ec_sn'").fetchone():
        for row in conn.execute("SELECT * FROM verified_notice_episode_ec_sn ORDER BY product_code,announcement_date,notice_episode_id"):
            product = row["product_code"]
            cluster = row["policy_date_cluster_id"]
            linked = chains.get(cluster, [])
            real = [item for item in linked if item["real_event_id"]]
            grades = pipe_unique(item["chain_completeness_grade"] for item in linked)
            if real:
                status = "verified_real_event_chain_link"
            elif any(item["chain_completeness_grade"] == "B_anomaly_policy_post" for item in linked):
                status = "market_anomaly_only_no_verified_real_event"
            elif linked:
                status = "policy_post_only_no_verified_real_event"
            else:
                status = "no_chain_row_for_policy_cluster"
            requested = row["analysis_event_trade_day"] or row["policy_reference_date"]
            event_evidence = [verified_events.get(item["real_event_id"]) for item in real if verified_events.get(item["real_event_id"])]
            independent_count = sum(bool(item["independent_source_2"]) for item in event_evidence)
            evidence_grade = "A" if real and independent_count == len(event_evidence) else "B" if real else "U"
            record = {
                "master_id": f"EC_SN::{row['notice_episode_id']}", "source_policy_layer": "ec_sn_source_verified_episode",
                "policy_record_id": row["notice_episode_id"], "notice_id": row["notice_id"], "product_code": product,
                "product_name_en": row["product_name_en"], "product_name_cn": row["product_name_cn"],
                "announcement_date": compact_date(row["announcement_date"]), "policy_reference_date": compact_date(row["policy_reference_date"]),
                "requested_analysis_trade_date": compact_date(requested), "policy_event_type_code": row["event_type"],
                "policy_event_type_en": row["event_type_en"], "policy_event_type_cn": row["event_type_cn"],
                "policy_event_name_en": row["event_name_en"], "policy_event_name_cn": row["event_name_cn"],
                "policy_direction_code": row["episode_direction"], "policy_direction_en": row["direction_en"],
                "policy_direction_cn": row["direction_cn"], "parameter_values_en": row["parameter_values_verified_en"],
                "parameter_values_cn": row["parameter_values_verified_cn"], "official_notice_title_cn": row["official_title_cn"],
                "official_source_url": row["official_source_url"], "policy_date_cluster_id": cluster,
                "real_event_link_status": status, "evidence_grade": evidence_grade,
                "evidence_status": "source_verified_real_event_chain" if real else "no_verified_real_event_in_chain_window",
                "evidence_source_count": len(event_evidence) + independent_count,
                "mentor_review_status": "existing_specialized_review" if real else "requires_event_research",
                "evidence_link_note_cn": "来自EC/SN专题研究的已核验时间机制链" if real else "现有机制链未关联已核验现实事件",
                "chain_completeness_grade": grades,
                "real_event_ids": pipe_unique(item["real_event_id"] for item in real),
                "real_event_dates": pipe_unique(item["real_event_date"] for item in real),
                "real_event_categories_en": pipe_unique(item["event_category_en"] for item in real),
                "real_event_categories_cn": pipe_unique(item["event_category_cn"] for item in real),
                "real_event_names_en": pipe_unique(item["event_name_en"] for item in real),
                "real_event_names_cn": pipe_unique(item["event_name_cn"] for item in real),
                "real_event_source_urls": pipe_unique(item["event_source_url"] for item in real),
                "transmission_channels_en": pipe_unique(item["transmission_channel_en"] for item in real),
                "transmission_channels_cn": pipe_unique(item["transmission_channel_cn"] for item in real),
                "expected_directions_en": pipe_unique(item["expected_direction_en"] for item in real),
                "expected_directions_cn": pipe_unique(item["expected_direction_cn"] for item in real),
                "event_to_policy_gap_trading_days": pipe_unique(item["event_to_policy_gap_trading_days"] for item in real),
                "intermediate_anomaly_days": pipe_unique(item["intermediate_anomaly_days"] for item in linked),
                "intermediate_max_anomaly_count": pipe_unique(item["intermediate_max_anomaly_count"] for item in linked),
                "interpretation_limit_en": boundary_en, "interpretation_limit_cn": boundary_cn, "generated_at": generated_at,
            }
            record.update(market_window(computed.get(product, []), requested))
            records.append(record)

    placeholders = ",".join("?" for _ in columns)
    conn.executemany(
        f"INSERT INTO notice_parameter_market_real_event_master ({','.join(columns)}) VALUES ({placeholders})",
        [tuple(record.get(column) for column in columns) for record in records],
    )
    return len(records)


def build_unique_policy_events_and_audits(conn: sqlite3.Connection, computed: dict[str, list[dict[str, Any]]]) -> tuple[int, int, int]:
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT * FROM notice_parameter_market_real_event_master ORDER BY product_code,announcement_date,policy_record_id"
    ).fetchall()
    grouped: dict[tuple[str, str, str, str], list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        key = (row["product_code"], row["notice_id"], row["announcement_date"], row["policy_reference_date"] or "")
        grouped[key].append(row)
    status_rank = {
        "verified_real_event_chain_link": 6,
        "verified_administrative_event_link": 5,
        "strong_temporal_sector_event_link_not_causal": 4,
        "contextual_real_event_candidate": 3,
        "market_anomaly_only_no_verified_real_event": 2,
        "policy_post_only_no_verified_real_event": 1,
        "no_screened_real_event_or_routine_policy": 0,
        "no_chain_row_for_policy_cluster": 0,
    }
    unique_records: list[dict[str, Any]] = []
    for (product, notice_id, announcement, reference), items in grouped.items():
        first = items[0]
        best_status = max((item["real_event_link_status"] for item in items), key=lambda value: status_rank.get(value, -1))
        grades = [item["evidence_grade"] for item in items if item["evidence_grade"] != "U"]
        unique_id = f"{product}::{notice_id}::{reference or announcement}"
        unique_records.append({
            "unique_policy_event_id": unique_id, "product_code": product, "notice_id": notice_id,
            "announcement_date": announcement, "policy_reference_date": reference or None,
            "matched_market_trade_date": first["matched_market_trade_date"], "policy_parameter_row_count": len(items),
            "policy_event_type_codes": pipe_unique(item["policy_event_type_code"] for item in items),
            "policy_event_types_en": pipe_unique(item["policy_event_type_en"] for item in items),
            "policy_event_types_cn": pipe_unique(item["policy_event_type_cn"] for item in items),
            "policy_event_name_en": first["policy_event_name_en"], "policy_event_name_cn": first["policy_event_name_cn"],
            "real_event_link_status": best_status, "evidence_grade": min(grades) if grades else "U",
            "mentor_review_status": pipe_unique(item["mentor_review_status"] for item in items),
            "official_source_url": first["official_source_url"], "interpretation_limit_cn": first["interpretation_limit_cn"],
            "generated_at": generated_at,
        })
    unique_columns = [row[1] for row in conn.execute("PRAGMA table_info(unique_policy_event_summary)")]
    conn.executemany(
        f"INSERT INTO unique_policy_event_summary ({','.join(unique_columns)}) VALUES ({','.join('?' for _ in unique_columns)})",
        [tuple(record.get(column) for column in unique_columns) for record in unique_records],
    )

    window_rows = []
    for record in unique_records:
        series = computed.get(record["product_code"], [])
        index_by_date = {row["trade_date"]: i for i, row in enumerate(series)}
        index = index_by_date.get(record["matched_market_trade_date"])
        if index is None:
            continue
        event = series[index]
        for window in (1, 5, 10, 20):
            pre = series[max(0, index - window):index]
            post = series[index + 1:index + 1 + window]
            pre_abs_return = finite_mean(row["abs_return"] for row in pre)
            post_abs_return = finite_mean(row["abs_return"] for row in post)
            pre_range = finite_mean(row["parkinson"] for row in pre)
            post_range = finite_mean(row["parkinson"] for row in post)
            pre_volume = finite_mean(safe_log1p(row["volume"]) for row in pre)
            post_volume = finite_mean(safe_log1p(row["volume"]) for row in post)
            pre_oi = finite_mean(abs(row["oi_change_ratio"]) if row["oi_change_ratio"] is not None else None for row in pre)
            post_oi = finite_mean(abs(row["oi_change_ratio"]) if row["oi_change_ratio"] is not None else None for row in post)
            window_rows.append((
                record["unique_policy_event_id"], record["product_code"], record["matched_market_trade_date"], window,
                len(pre), len(post), int(len(pre) == window and len(post) == window),
                pre_abs_return, post_abs_return, difference(post_abs_return, pre_abs_return),
                pre_range, post_range, difference(post_range, pre_range),
                pre_volume, post_volume, difference(post_volume, pre_volume),
                pre_oi, post_oi, difference(post_oi, pre_oi), int(event["roll"]),
                sum(int(row["roll"]) for row in pre), sum(int(row["roll"]) for row in post),
                "事件日不计入前后窗口；差值为后窗口均值减前窗口均值；未控制共同冲击、事件重叠和合约换月。",
            ))
    conn.executemany(
        "INSERT INTO policy_market_window_statistics VALUES (" + ",".join("?" for _ in range(23)) + ")",
        window_rows,
    )

    by_product: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in unique_records:
        by_product[record["product_code"]].append(record)
    overlap_rows = []
    master_event_ids = {
        (row["product_code"], row["notice_id"], row["policy_reference_date"] or ""): row["real_event_ids"]
        for row in rows
    }
    for product, events in by_product.items():
        series_index = {row["trade_date"]: i for i, row in enumerate(computed.get(product, []))}
        for event in events:
            event_index = series_index.get(event["matched_market_trade_date"])
            distances = []
            for other in events:
                if other["unique_policy_event_id"] == event["unique_policy_event_id"]:
                    continue
                other_index = series_index.get(other["matched_market_trade_date"])
                if event_index is not None and other_index is not None:
                    distances.append((abs(other_index - event_index), other["unique_policy_event_id"]))
            within20 = [item_id for distance_value, item_id in distances if distance_value <= 20]
            event_ids = master_event_ids.get((product, event["notice_id"], event["policy_reference_date"] or ""))
            real_event_count = len([part for part in (event_ids or "").split(" | ") if part])
            overlap_rows.append((
                event["unique_policy_event_id"], product, event["matched_market_trade_date"],
                sum(distance_value <= 5 for distance_value, _ in distances),
                sum(distance_value <= 10 for distance_value, _ in distances), len(within20),
                " | ".join(within20) if within20 else None, real_event_count,
                "overlapping_policy_events_present" if within20 else "isolated_within_20_trading_days",
                "窗口内存在其他政策事件时，前后差异不能归属于单一公告；现实事件数量仅统计已链接或候选事件。",
            ))
    conn.executemany("INSERT INTO policy_event_overlap_audit VALUES (?,?,?,?,?,?,?,?,?,?)", overlap_rows)
    return len(unique_records), len(window_rows), len(overlap_rows)


def state_from_percentile(value: float | None, high: str, middle: str, low: str) -> str:
    if value is None:
        return "数据不足"
    if value >= 80:
        return high
    if value >= 40:
        return middle
    return low


def availability_context(conn: sqlite3.Connection, database_last: str) -> dict[str, Any]:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='official_data_availability_check'"
    ).fetchone()
    if not exists:
        return {"status": None, "checked_through": None, "latest_complete": None, "unresolved": None}
    coverage = conn.execute(
        """
        SELECT dataset,MAX(requested_date),
               MAX(CASE WHEN validation_status IN ('valid_saved','valid_reused') THEN report_date END)
        FROM official_data_availability_check GROUP BY dataset
        """
    ).fetchall()
    checked_through = min((row[1] for row in coverage if row[1]), default=None)
    latest_complete = min((row[2] for row in coverage if row[2]), default=None)
    unresolved = conn.execute(
        """
        SELECT COUNT(*) FROM official_data_availability_check
        WHERE requested_date>? AND
          (http_status=0 OR validation_status IN
            ('invalid_json_not_saved','date_mismatch_not_saved','unhandled_error_not_saved'))
        """,
        (database_last,),
    ).fetchone()[0]
    status = (
        "current_to_latest_complete_official_available"
        if checked_through and checked_through >= database_last and latest_complete == database_last and unresolved == 0
        else "availability_check_incomplete"
    )
    return {"status": status, "checked_through": checked_through, "latest_complete": latest_complete, "unresolved": unresolved}


def build_snapshots(conn: sqlite3.Connection, computed: dict[str, list[dict[str, Any]]], build_date: date) -> int:
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = []
    for product, series in sorted(computed.items()):
        database_last = series[-1]["trade_date"]
        complete = [r for r in series if r["score"] is not None and r["close"] is not None and r["settlement"] is not None]
        latest = complete[-1] if complete else None
        age = (build_date - ymd(database_last)).days
        availability = availability_context(conn, database_last)
        freshness = availability["status"] or ("fresh" if age <= 3 else "lagged" if age <= 10 else "stale")
        recent20 = complete[-20:]
        intense_count = sum(r["level"] in {"intense", "extreme"} for r in recent20)
        cutoff60 = ymd_text(build_date - timedelta(days=60))
        parameter_changes = conn.execute(
            "SELECT COUNT(*) FROM official_product_parameter_change_cluster WHERE product_code=? AND trade_date>=?",
            (product, cutoff60),
        ).fetchone()[0]
        cutoff365 = ymd_text(build_date - timedelta(days=365))
        notices = conn.execute(
            "SELECT COUNT(*) FROM verified_notice_parameter_change_alignment WHERE product_code=? AND announcement_date>=?",
            (product, cutoff365),
        ).fetchone()[0]
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_notice_episode_ec_sn'").fetchone():
            notices += conn.execute(
                "SELECT COUNT(*) FROM verified_notice_episode_ec_sn WHERE product_code=? AND REPLACE(announcement_date,'-','')>=?",
                (product, cutoff365),
            ).fetchone()[0]
        score = latest["score"] if latest else None
        level = latest["level"] if latest else "insufficient_history"
        attention = "高关注" if score is not None and score >= 90 else "关注" if score is not None and score >= 80 else "常规跟踪"
        current_status = "不可作当前判断：官方可用性核验不完整" if freshness in {"stale", "availability_check_incomplete"} else "已核验至官方最新可用日；仅作研究关注判断，不构成交易建议"
        volume_pct = latest["volume_percentile"] if latest else None
        turnover_pct = latest["turnover_percentile"] if latest else None
        illiq_pct = latest["illiquidity_percentile"] if latest else None
        liquidity = state_from_percentile(
            None if volume_pct is None or turnover_pct is None else (volume_pct + turnover_pct + (100 - (illiq_pct or 50))) / 3,
            "活跃且价格冲击相对可控", "一般", "偏弱或价格冲击偏高",
        )
        risk_pct = None if latest is None or latest["abs_return_percentile"] is None or latest["range_vol_percentile"] is None else max(latest["abs_return_percentile"], latest["range_vol_percentile"])
        risk_state = state_from_percentile(risk_pct, "高波动风险", "中等波动", "低波动")
        conclusion = (
            f"截至数据库最后完整分析日{latest['trade_date'] if latest else '无'}，{product}交易强度评分为"
            f"{score:.1f}" if score is not None else f"{product}缺少足够历史数据生成交易强度评分"
        )
        if score is not None:
            conclusion += f"，历史状态为“{attention}”，近20个完整交易日出现{intense_count}个激烈或极端交易日。"
        else:
            conclusion += "。"
        checked_note = f"，三源完整同步至{availability['latest_complete']}，并已逐日检查官方接口至{availability['checked_through']}" if availability["checked_through"] else ""
        conclusion += f" 数据库最新有效交易日为{database_last}，距构建日{age}个自然日{checked_note}；{current_status}。"
        rows.append(
            (
                product, database_last, latest["trade_date"] if latest else None, age, freshness,
                latest["contract_code"] if latest else None, score, level,
                volume_pct, turnover_pct, latest["abs_return_percentile"] if latest else None,
                latest["range_vol_percentile"] if latest else None, illiq_pct,
                intense_count, parameter_changes, notices, attention, current_status, liquidity, risk_state,
                conclusion,
                "评分只衡量历史相对异常和研究关注度，不预测方向、不生成开仓/平仓指令；数据过期时禁止解释为当下交易状态。",
                generated_at,
            )
        )
    conn.executemany(
        "INSERT INTO product_research_snapshot VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    return len(rows)


def build_completeness_dashboard(conn: sqlite3.Connection) -> int:
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    source_last_dates = [
        conn.execute(f"SELECT MAX(trade_date) FROM {table}").fetchone()[0]
        for table in ("market_contract_daily", "settlement_parameter_daily", "official_trade_parameter_daily")
    ]
    global_last = max(source_last_dates)
    latest_complete = min(source_last_dates)
    availability_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='official_data_availability_check'"
    ).fetchone()
    checked_through = None
    unresolved = 0
    if availability_exists:
        checked_through = conn.execute(
            "SELECT MAX(requested_date) FROM official_data_availability_check WHERE dataset='market'"
        ).fetchone()[0]
        unresolved = conn.execute(
            """
            SELECT COUNT(*) FROM official_data_availability_check
            WHERE http_status=0 OR validation_status IN
              ('invalid_json_not_saved','date_mismatch_not_saved','unhandled_error_not_saved')
            """
        ).fetchone()[0]
    products = [row[0] for row in conn.execute("SELECT product_code FROM dim_product ORDER BY product_code")]
    output = []
    for product in products:
        market = conn.execute(
            "SELECT MIN(trade_date),MAX(trade_date),COUNT(DISTINCT trade_date),COUNT(*) FROM market_contract_daily WHERE product_code=?",
            (product,),
        ).fetchone()
        settlement = conn.execute(
            "SELECT MIN(trade_date),MAX(trade_date),COUNT(*) FROM settlement_parameter_daily WHERE product_code=?",
            (product,),
        ).fetchone()
        parameter = conn.execute(
            "SELECT MIN(trade_date),MAX(trade_date),COUNT(*) FROM official_trade_parameter_daily WHERE product_code=?",
            (product,),
        ).fetchone()
        overlap = conn.execute(
            """
            SELECT COUNT(*) total,
                   SUM(CASE WHEN p.contract_code IS NOT NULL THEN 1 ELSE 0 END) parameter_matched,
                   SUM(CASE WHEN s.contract_code IS NOT NULL THEN 1 ELSE 0 END) settlement_matched,
                   SUM(CASE WHEN p.contract_code IS NOT NULL AND s.contract_code IS NOT NULL AND
                     ((p.spec_long_margin_ratio IS NULL AND s.spec_long_margin_ratio IS NULL) OR ABS(p.spec_long_margin_ratio-s.spec_long_margin_ratio)<1e-12) AND
                     ((p.spec_short_margin_ratio IS NULL AND s.spec_short_margin_ratio IS NULL) OR ABS(p.spec_short_margin_ratio-s.spec_short_margin_ratio)<1e-12) AND
                     ((p.hedge_long_margin_ratio IS NULL AND s.hedge_long_margin_ratio IS NULL) OR ABS(p.hedge_long_margin_ratio-s.hedge_long_margin_ratio)<1e-12) AND
                     ((p.hedge_short_margin_ratio IS NULL AND s.hedge_short_margin_ratio IS NULL) OR ABS(p.hedge_short_margin_ratio-s.hedge_short_margin_ratio)<1e-12)
                   THEN 1 ELSE 0 END) margin_equal
            FROM market_contract_daily m
            LEFT JOIN official_trade_parameter_daily p
              ON p.trade_date=m.trade_date AND p.contract_code=m.contract_code
            LEFT JOIN settlement_parameter_daily s
              ON s.trade_date=m.trade_date AND s.contract_code=m.contract_code
            WHERE m.product_code=? AND m.trade_date>='20131008'
            """,
            (product,),
        ).fetchone()
        total = overlap[0] or 0
        parameter_coverage = round(100 * (overlap[1] or 0) / total, 3) if total else None
        settlement_coverage = round(100 * (overlap[2] or 0) / total, 3) if total else None
        both_matched = conn.execute(
            """
            SELECT COUNT(*) FROM market_contract_daily m
            JOIN official_trade_parameter_daily p ON p.trade_date=m.trade_date AND p.contract_code=m.contract_code
            JOIN settlement_parameter_daily s ON s.trade_date=m.trade_date AND s.contract_code=m.contract_code
            WHERE m.product_code=? AND m.trade_date>='20131008'
            """,
            (product,),
        ).fetchone()[0]
        margin_agreement = round(100 * (overlap[3] or 0) / both_matched, 3) if both_matched else None
        notices = conn.execute(
            "SELECT COUNT(*) FROM verified_notice_parameter_change_alignment WHERE product_code=?", (product,)
        ).fetchone()[0]
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_notice_episode_ec_sn'").fetchone():
            notices += conn.execute(
                "SELECT COUNT(*) FROM verified_notice_episode_ec_sn WHERE product_code=?", (product,)
            ).fetchone()[0]
        clusters = conn.execute(
            "SELECT COUNT(*) FROM official_product_parameter_change_cluster WHERE product_code=?", (product,)
        ).fetchone()[0]
        limits = conn.execute(
            "SELECT COUNT(*) FROM derived_position_limit_daily WHERE product_code=?", (product,)
        ).fetchone()[0]
        issues = []
        if market[1] < latest_complete:
            issues.append("行情未覆盖到三源最新完整同步日")
        if parameter[1] < latest_complete:
            issues.append("官方交易参数未覆盖到三源最新完整同步日")
        if settlement[1] < latest_complete:
            issues.append("结算参数未覆盖到三源最新完整同步日")
        if len(set(source_last_dates)) > 1:
            issues.append(f"最新单源日期尚未齐备；三源完整同步截止{latest_complete}")
        if notices == 0:
            issues.append("尚无人工核验公告记录")
        if margin_agreement is not None and margin_agreement < 99:
            issues.append("两类官方参数来源存在数值差异，原值已保留待解释")
        if unresolved:
            issues.append("存在未解决的官方接口检查失败")
        core_current = market[1] >= latest_complete and parameter[1] >= latest_complete and settlement[1] >= latest_complete and unresolved == 0
        if core_current and notices > 0:
            readiness = "公告—参数—市场同步研究可用"
        elif core_current:
            readiness = "市场与参数同步可用，公告待核验"
        else:
            readiness = "数据覆盖需复核"
        output.append((
            product, market[0], market[1], market[2] or 0, market[3] or 0,
            settlement[0], settlement[1], settlement[2] or 0,
            parameter[0], parameter[1], parameter[2] or 0,
            parameter_coverage, settlement_coverage, margin_agreement,
            notices, clusters, limits, checked_through, latest_complete, unresolved, readiness,
            "；".join(issues) if issues else "未发现阻断性完整性问题", generated_at,
        ))
    conn.executemany(
        "INSERT INTO product_data_completeness_dashboard VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        output,
    )
    return len(output)


def export_query(conn: sqlite3.Connection, sql: str, path: Path) -> int:
    cursor = conn.execute(sql)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([item[0] for item in cursor.description])
        count = 0
        for row in cursor:
            writer.writerow(row)
            count += 1
    return count


def main() -> None:
    args = parse_args()
    build_date = datetime.strptime(args.build_date, "%Y-%m-%d").date()
    source = args.source_db.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    dotted_tag = args.artifact_tag.replace("v0", "v0.") if args.artifact_tag.startswith("v0") and "." not in args.artifact_tag else args.artifact_tag
    output_db = output_dir / f"SHFE公告参数市场研究助手_{dotted_tag}.sqlite3"
    overrides = save_manual_overrides(output_db)
    user_input = save_user_input_tables(output_db)
    building = output_db.with_suffix(output_db.suffix + ".building")
    if building.exists():
        building.unlink()
    shutil.copy2(source, building)
    conn = sqlite3.connect(building)
    conn.row_factory = sqlite3.Row
    try:
        create_schema(conn)
        restore_user_input_tables(conn, user_input)
        conn.executemany(
            "INSERT INTO indicator_literature_registry VALUES (?,?,?,?,?,?,?,?,?,?)",
            [tuple(item.values()) for item in LITERATURE],
        )
        interval_count = build_intervals(conn)
        if overrides:
            valid_ids = {row[0] for row in conn.execute("SELECT interval_id FROM notice_parameter_policy_interval")}
            conn.executemany(
                "INSERT OR REPLACE INTO policy_interval_manual_override VALUES (?,?,?,?,?,?,?)",
                [row for row in overrides if row[0] in valid_ids],
            )
        intensity_count, computed = build_intensity(conn)
        master_count = build_notice_market_event_master(conn, computed)
        unique_policy_count, window_count, overlap_count = build_unique_policy_events_and_audits(conn, computed)
        snapshot_count = build_snapshots(conn, computed, build_date)
        completeness_count = build_completeness_dashboard(conn)
        metadata = {
            "version": args.version,
            "built_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "build_reference_date": build_date.isoformat(),
            "source_db": str(source),
            "source_sha256": sha256(source),
            "policy_interval_count": str(interval_count),
            "intensity_daily_count": str(intensity_count),
            "notice_market_real_event_master_count": str(master_count),
            "unique_policy_event_count": str(unique_policy_count),
            "policy_window_statistics_count": str(window_count),
            "policy_overlap_audit_count": str(overlap_count),
            "product_snapshot_count": str(snapshot_count),
            "product_completeness_count": str(completeness_count),
            "research_boundary": "descriptive_research_attention_only_no_trade_recommendation",
        }
        conn.executemany("INSERT INTO research_assistant_build_metadata VALUES (?,?)", metadata.items())
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity check failed: {integrity}")
        conn.commit()
    finally:
        conn.close()
    os.replace(building, output_db)

    conn = sqlite3.connect(output_db)
    try:
        exports = output_dir / "exports"
        export_query(conn, "SELECT * FROM v_all_policy_interval_effective ORDER BY product_code,parameter_code,start_date", exports / f"notice_parameter_policy_intervals_{args.artifact_tag}.csv")
        export_query(conn, "SELECT * FROM product_research_snapshot ORDER BY product_code", exports / f"product_research_snapshot_{args.artifact_tag}.csv")
        export_query(
            conn,
            "SELECT * FROM product_trading_intensity_daily WHERE intensity_level IN ('intense','extreme') ORDER BY product_code,trade_date",
            exports / f"intense_trading_days_{args.artifact_tag}.csv",
        )
        export_query(conn, "SELECT * FROM indicator_literature_registry ORDER BY year", exports / f"indicator_literature_registry_{args.artifact_tag}.csv")
        export_query(conn, "SELECT * FROM product_data_completeness_dashboard ORDER BY product_code", exports / f"product_data_completeness_{args.artifact_tag}.csv")
        export_query(conn, "SELECT * FROM trade_parameter_market_alignment_daily ORDER BY trade_date", exports / f"parameter_market_alignment_{args.artifact_tag}.csv")
        export_query(conn, "SELECT * FROM trade_parameter_settlement_reconciliation_daily ORDER BY trade_date", exports / f"parameter_settlement_reconciliation_{args.artifact_tag}.csv")
        export_query(
            conn,
            """SELECT product_code,field_name,COUNT(*) mismatch_field_rows,MIN(trade_date) first_date,
                      MAX(trade_date) last_date,AVG(ABS(difference)) average_absolute_difference
               FROM trade_parameter_settlement_mismatch
               GROUP BY product_code,field_name
               ORDER BY mismatch_field_rows DESC,product_code,field_name""",
            exports / f"parameter_source_mismatch_summary_{args.artifact_tag}.csv",
        )
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trade_parameter_settlement_mismatch_classified'").fetchone():
            export_query(conn, "SELECT * FROM trade_parameter_settlement_mismatch_summary ORDER BY review_priority,product_code,mismatch_pattern_code", exports / f"parameter_source_mismatch_classification_{args.artifact_tag}.csv")
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_notice_episode_ec_sn'").fetchone():
            export_query(conn, "SELECT * FROM verified_notice_episode_ec_sn ORDER BY product_code,announcement_date,notice_episode_id", exports / f"verified_notice_episodes_ec_sn_bilingual_{args.artifact_tag}.csv")
        export_query(conn, "SELECT * FROM notice_parameter_market_real_event_master ORDER BY product_code,announcement_date,policy_record_id", exports / f"notice_parameter_market_real_event_master_{args.artifact_tag}.csv")
        export_query(conn, "SELECT * FROM unique_policy_event_summary ORDER BY product_code,announcement_date,notice_id", exports / f"unique_policy_event_summary_{args.artifact_tag}.csv")
        export_query(conn, "SELECT * FROM policy_market_window_statistics ORDER BY product_code,matched_market_trade_date,window_trading_days", exports / f"policy_market_window_statistics_{args.artifact_tag}.csv")
        export_query(conn, "SELECT * FROM policy_event_overlap_audit ORDER BY product_code,matched_market_trade_date", exports / f"policy_event_overlap_audit_{args.artifact_tag}.csv")
        export_query(
            conn,
            """SELECT unique_policy_event_id,product_code,notice_id,announcement_date,policy_reference_date,
                      policy_event_name_cn,real_event_link_status,evidence_grade,mentor_review_status,
                      CASE WHEN mentor_review_status='pending_mentor_review' THEN '导师复核AO/BU初筛事件链接'
                           WHEN real_event_link_status='verified_real_event_chain_link' THEN '复核既有专题证据等级'
                           ELSE '补充或复核政策日前现实事件来源' END AS review_action_cn,
                      official_source_url,interpretation_limit_cn
               FROM unique_policy_event_summary
               WHERE mentor_review_status NOT IN ('existing_specialized_review','rule_based_routine_classification')
               ORDER BY product_code,announcement_date""",
            exports / f"real_event_evidence_review_queue_{args.artifact_tag}.csv",
        )
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='verified_real_world_event_ec_sn'").fetchone():
            export_query(conn, "SELECT * FROM verified_real_world_event_ec_sn ORDER BY product_code,event_date,real_event_id", exports / f"verified_real_world_events_ec_sn_bilingual_{args.artifact_tag}.csv")
            export_query(conn, "SELECT * FROM verified_event_policy_chain_ec_sn ORDER BY product_code,policy_trade_day,chain_id", exports / f"verified_event_policy_chains_ec_sn_{args.artifact_tag}.csv")
        summary = {
            "version": args.version,
            "database": str(output_db),
            "database_bytes": output_db.stat().st_size,
            "database_sha256": sha256(output_db),
            "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
            "policy_intervals": conn.execute("SELECT COUNT(*) FROM notice_parameter_policy_interval").fetchone()[0],
            "daily_indicator_rows": conn.execute("SELECT COUNT(*) FROM product_trading_intensity_daily").fetchone()[0],
            "notice_market_real_event_master_rows": conn.execute("SELECT COUNT(*) FROM notice_parameter_market_real_event_master").fetchone()[0],
            "unique_policy_event_rows": conn.execute("SELECT COUNT(*) FROM unique_policy_event_summary").fetchone()[0],
            "multiwindow_statistic_rows": conn.execute("SELECT COUNT(*) FROM policy_market_window_statistics").fetchone()[0],
            "overlapping_policy_events": conn.execute("SELECT COUNT(*) FROM policy_event_overlap_audit WHERE other_policy_events_within_20d>0").fetchone()[0],
            "verified_real_event_link_rows": conn.execute("SELECT COUNT(*) FROM notice_parameter_market_real_event_master WHERE real_event_link_status='verified_real_event_chain_link'").fetchone()[0],
            "intense_days": conn.execute("SELECT COUNT(*) FROM product_trading_intensity_daily WHERE intensity_level IN ('intense','extreme')").fetchone()[0],
            "product_snapshots": conn.execute("SELECT COUNT(*) FROM product_research_snapshot").fetchone()[0],
            "product_completeness_rows": conn.execute("SELECT COUNT(*) FROM product_data_completeness_dashboard").fetchone()[0],
            "latest_market_date": conn.execute("SELECT MAX(trade_date) FROM product_trading_intensity_daily").fetchone()[0],
        }
    finally:
        conn.close()
    (output_dir / f"{args.artifact_tag}_build_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
