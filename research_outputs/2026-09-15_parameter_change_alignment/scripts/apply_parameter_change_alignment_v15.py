from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


HERE = Path(__file__).resolve().parent
BASE_DIR = Path(os.environ.get("SHFE_V15_BASE_DIR", HERE))
EXPANSION_DIR = Path(os.environ.get("SHFE_V15_EXPANSION_DIR", BASE_DIR / "03_全品种扩展"))
SOURCE_OVERRIDE = os.environ.get("SHFE_V15_SOURCE_DB")
SOURCE_DB = Path(SOURCE_OVERRIDE) if SOURCE_OVERRIDE else next(EXPANSION_DIR.glob("*v0.14.sqlite3"))
OUTPUT_OVERRIDE = os.environ.get("SHFE_V15_OUTPUT_DB")
FINAL_DB = Path(OUTPUT_OVERRIDE) if OUTPUT_OVERRIDE else EXPANSION_DIR / "SHFE公告参数市场同步数据库_全品种_公告参数变更点对应_v0.15.sqlite3"
BUILDING_DB = FINAL_DB.with_suffix(FINAL_DB.suffix + ".building")
AUDIT_DIR = Path(os.environ.get("SHFE_V15_AUDIT_DIR", EXPANSION_DIR / "15_公告参数变更点对应"))
BUILT_AT = datetime.now().astimezone().isoformat(timespec="seconds")

FIELDS = {
    "spec_long_margin_ratio": ("margin_general", "long", "General-position long margin ratio", "一般持仓多头保证金比例"),
    "spec_short_margin_ratio": ("margin_general", "short", "General-position short margin ratio", "一般持仓空头保证金比例"),
    "hedge_long_margin_ratio": ("margin_hedge", "long", "Hedge-position long margin ratio", "套保持仓多头保证金比例"),
    "hedge_short_margin_ratio": ("margin_hedge", "short", "Hedge-position short margin ratio", "套保持仓空头保证金比例"),
    "upper_limit_ratio": ("price_limit", "upper", "Upper price-limit ratio", "涨停板比例"),
    "lower_limit_ratio": ("price_limit", "lower", "Lower price-limit ratio", "跌停板比例"),
}
PARAMETER_NAMES = {
    "margin_general": ("General-position margin ratio", "一般持仓交易保证金比例"),
    "margin_hedge": ("Hedge-position margin ratio", "套保持仓交易保证金比例"),
    "price_limit": ("Price-limit ratio", "涨跌停板幅度"),
}
PRODUCT_NAMES_EN = {
    "AD": "Cast Aluminum Alloy", "AG": "Silver", "AL": "Aluminum",
    "AO": "Alumina", "AU": "Gold", "BC": "International Copper",
    "BR": "Butadiene Rubber", "BU": "Bitumen", "CU": "Copper",
    "EC": "Containerized Freight Index (Europe Service)", "FU": "Fuel Oil",
    "HC": "Hot-Rolled Coil", "LU": "Low Sulfur Fuel Oil", "NI": "Nickel",
    "NR": "TSR 20", "PB": "Lead", "RB": "Rebar", "RU": "Natural Rubber",
    "SC": "Crude Oil", "SN": "Tin", "SP": "Wood Pulp",
    "SS": "Stainless Steel", "WR": "Wire Rod", "ZN": "Zinc",
}
LEVEL_STATUS_CN = {
    "all_values_equal_notice_level": "全部观测值等于公告值",
    "notice_floor_satisfied_with_higher_values_present": "均不低于公告值且存在从高适用值",
    "one_or_more_values_below_notice_level": "至少一项观测值低于公告值",
    "incomplete_official_daily_scope_coverage": "官方日度范围覆盖不完整",
    "no_concrete_contract_scope_on_effective_date": "核对日无可具体化的合约范围",
}
CHANGE_STATUS_CN = {
    "all_fields_changed_on_observation_date": "全部字段在参数核对日发生变更",
    "all_fields_are_initial_listing_observations": "全部字段均为新上市合约首次观测",
    "all_fields_changed_or_are_initial_listing_observations": "全部字段为核对日变更或首次挂牌观测",
    "partial_change_with_preexisting_values": "部分字段发生变更，其余字段此前已处于适用水平",
    "no_change_point_level_already_present": "未出现新变更点，参数此前已处于适用水平",
    "incomplete_official_daily_scope_coverage": "官方日度范围覆盖不完整",
}
OBSERVATION_BASIS_CN = {
    "next_official_trade_parameter_date_after_close_settlement": "收盘结算生效后下一可用官方交易参数日",
    "same_date_for_listing_or_non_close_settlement_rule": "新上市或非收盘结算规则使用同日",
    "effective_date_fallback_no_later_official_date": "缺少后续官方日期，暂用公告实施日",
}
RELATION_CN = {
    "equal_to_notice_value": "等于公告值",
    "above_notice_value": "高于公告值",
    "below_notice_value": "低于公告值",
    "missing": "缺失",
    "expected_value_unavailable": "公告值不可用",
}
EVIDENCE_CN = {
    "changed_to_notice_value_on_observation_date": "参数核对日变为公告值",
    "changed_to_value_above_notice_level_on_observation_date": "参数核对日变为高于公告值的从高适用值",
    "changed_to_value_below_notice_level_on_observation_date": "参数核对日变为低于公告值的数值",
    "initial_observation_at_or_above_notice_level": "新上市首次观测即达到或高于公告值",
    "initial_observation_below_notice_level": "新上市首次观测低于公告值",
    "preexisting_value_at_or_above_notice_level": "参数此前已达到或高于公告值",
    "preexisting_value_below_notice_level": "参数此前已低于公告值",
    "official_daily_observation_missing": "官方日度观测缺失",
}
LIFECYCLE_CN = {
    "expiry_date_unavailable": "到期日不可用", "after_contract_expiry": "已过合约到期日",
    "days_0_10_to_expiry": "距到期0至10天", "days_11_30_to_expiry": "距到期11至30天",
    "days_31_60_to_expiry": "距到期31至60天", "more_than_60_days_to_expiry": "距到期超过60天",
    "observation_missing": "观测缺失",
}
SCOPE_CLASS_CN = {
    "all_active_contracts": "覆盖当日全部活跃合约",
    "majority_of_active_contracts": "覆盖当日多数活跃合约",
    "multiple_contracts_partial": "覆盖多个但非多数合约",
    "single_contract": "单一合约",
}
TOLERANCE = 1e-12


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def yyyymmdd_to_date(value: str | None):
    if not value:
        return None
    return datetime.strptime(value, "%Y%m%d").date()


def day_difference(later: str, earlier: str) -> int:
    return (yyyymmdd_to_date(later) - yyyymmdd_to_date(earlier)).days


def lifecycle_bucket(days_to_expiry: int | None) -> str:
    if days_to_expiry is None:
        return "expiry_date_unavailable"
    if days_to_expiry < 0:
        return "after_contract_expiry"
    if days_to_expiry <= 10:
        return "days_0_10_to_expiry"
    if days_to_expiry <= 30:
        return "days_11_30_to_expiry"
    if days_to_expiry <= 60:
        return "days_31_60_to_expiry"
    return "more_than_60_days_to_expiry"


def scope_class(affected: int, active: int) -> str:
    if active and affected == active:
        return "all_active_contracts"
    if affected >= 2 and active and affected / active >= 0.5:
        return "majority_of_active_contracts"
    if affected >= 2:
        return "multiple_contracts_partial"
    return "single_contract"


def relation(value: float | None, expected: float | None) -> str:
    if value is None:
        return "missing"
    if expected is None:
        return "expected_value_unavailable"
    if abs(value - expected) <= TOLERANCE:
        return "equal_to_notice_value"
    if value > expected:
        return "above_notice_value"
    return "below_notice_value"


def write_csv(path: Path, headers: list[str], data: Iterable[Iterable[Any]]) -> int:
    count = 0
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        for row in data:
            writer.writerow(list(row))
            count += 1
    return count


def create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP VIEW IF EXISTS verified_notice_parameter_alignment_bilingual;
        DROP TABLE IF EXISTS v15_integration_check;
        DROP TABLE IF EXISTS v15_field_dictionary;
        DROP TABLE IF EXISTS v15_build_metadata;
        DROP TABLE IF EXISTS verified_notice_parameter_change_alignment;
        DROP TABLE IF EXISTS verified_notice_parameter_contract_alignment;
        DROP TABLE IF EXISTS official_product_parameter_change_cluster_member;
        DROP TABLE IF EXISTS official_product_parameter_change_cluster;
        DROP TABLE IF EXISTS official_contract_parameter_change;

        CREATE TABLE official_contract_parameter_change (
          change_id INTEGER PRIMARY KEY,
          trade_date TEXT NOT NULL,
          previous_trade_date TEXT NOT NULL,
          calendar_gap_days INTEGER NOT NULL,
          gap_quality TEXT NOT NULL,
          product_code TEXT NOT NULL,
          contract_code TEXT NOT NULL,
          parameter_code TEXT NOT NULL,
          parameter_field TEXT NOT NULL,
          parameter_side TEXT NOT NULL,
          old_value REAL,
          new_value REAL,
          absolute_change REAL,
          change_direction TEXT NOT NULL,
          expire_date TEXT,
          days_to_expiry INTEGER,
          lifecycle_bucket TEXT NOT NULL,
          source_manifest_date TEXT NOT NULL,
          data_origin TEXT NOT NULL,
          UNIQUE(trade_date,contract_code,parameter_field)
        );

        CREATE TABLE official_product_parameter_change_cluster (
          cluster_id TEXT PRIMARY KEY,
          trade_date TEXT NOT NULL,
          product_code TEXT NOT NULL,
          parameter_code TEXT NOT NULL,
          old_value REAL,
          new_value REAL,
          parameter_fields TEXT NOT NULL,
          affected_contract_codes TEXT NOT NULL,
          affected_contract_count INTEGER NOT NULL,
          affected_field_count INTEGER NOT NULL,
          active_contract_count INTEGER NOT NULL,
          affected_contract_share REAL,
          scope_class TEXT NOT NULL,
          near_expiry_contract_count INTEGER NOT NULL,
          long_gap_field_count INTEGER NOT NULL,
          interpretation_limit TEXT NOT NULL,
          UNIQUE(trade_date,product_code,parameter_code,old_value,new_value)
        );

        CREATE TABLE official_product_parameter_change_cluster_member (
          cluster_id TEXT NOT NULL REFERENCES official_product_parameter_change_cluster(cluster_id),
          change_id INTEGER NOT NULL REFERENCES official_contract_parameter_change(change_id),
          PRIMARY KEY(cluster_id,change_id)
        );

        CREATE TABLE verified_notice_parameter_contract_alignment (
          alignment_detail_id INTEGER PRIMARY KEY,
          verified_parameter_id TEXT NOT NULL REFERENCES verified_policy_parameter(verified_parameter_id),
          notice_id TEXT NOT NULL,
          effective_date TEXT,
          observation_trade_date TEXT,
          product_code TEXT NOT NULL,
          contract_code TEXT NOT NULL,
          parameter_code TEXT NOT NULL,
          parameter_field TEXT NOT NULL,
          expected_new_value REAL,
          observed_value REAL,
          value_relation TEXT NOT NULL,
          previous_trade_date TEXT,
          previous_value REAL,
          observation_date_change_id INTEGER REFERENCES official_contract_parameter_change(change_id),
          change_evidence TEXT NOT NULL,
          expire_date TEXT,
          days_to_expiry INTEGER,
          lifecycle_bucket TEXT NOT NULL,
          source_manifest_date TEXT,
          data_origin TEXT NOT NULL,
          UNIQUE(verified_parameter_id,contract_code,parameter_field)
        );

        CREATE TABLE verified_notice_parameter_change_alignment (
          verified_parameter_id TEXT PRIMARY KEY REFERENCES verified_policy_parameter(verified_parameter_id),
          notice_id TEXT NOT NULL,
          announcement_date TEXT NOT NULL,
          notice_title TEXT NOT NULL,
          product_code TEXT NOT NULL,
          instrument_scope TEXT NOT NULL,
          notice_contract_codes TEXT NOT NULL,
          parameter_code TEXT NOT NULL,
          change_stage TEXT NOT NULL,
          expected_new_value REAL,
          effective_date TEXT,
          effective_date_basis TEXT NOT NULL,
          effective_rule TEXT NOT NULL,
          observation_trade_date TEXT,
          observation_date_basis TEXT NOT NULL,
          observation_lag_calendar_days INTEGER,
          scope_construction TEXT NOT NULL,
          future_listing_marker_present INTEGER NOT NULL,
          expected_contract_count INTEGER NOT NULL,
          observed_contract_count INTEGER NOT NULL,
          missing_contract_count INTEGER NOT NULL,
          observed_field_count INTEGER NOT NULL,
          equal_notice_value_field_count INTEGER NOT NULL,
          above_notice_value_field_count INTEGER NOT NULL,
          below_notice_value_field_count INTEGER NOT NULL,
          changed_on_observation_date_field_count INTEGER NOT NULL,
          changed_to_notice_value_field_count INTEGER NOT NULL,
          initial_observation_field_count INTEGER NOT NULL,
          preexisting_value_field_count INTEGER NOT NULL,
          observed_min REAL,
          observed_max REAL,
          effective_date_observed_field_count INTEGER NOT NULL,
          effective_date_equal_notice_field_count INTEGER NOT NULL,
          effective_date_above_notice_field_count INTEGER NOT NULL,
          effective_date_below_notice_field_count INTEGER NOT NULL,
          effective_date_observed_min REAL,
          effective_date_observed_max REAL,
          matching_cluster_ids TEXT,
          level_alignment_status TEXT NOT NULL,
          change_point_alignment_status TEXT NOT NULL,
          interpretation_en TEXT NOT NULL,
          interpretation_cn TEXT NOT NULL,
          timing_note_en TEXT NOT NULL,
          timing_note_cn TEXT NOT NULL,
          official_source_url TEXT NOT NULL,
          checked_at TEXT NOT NULL
        );

        CREATE TABLE v15_build_metadata (
          metadata_key TEXT PRIMARY KEY,
          metadata_value TEXT NOT NULL
        );

        CREATE TABLE v15_field_dictionary (
          object_name TEXT NOT NULL,
          field_name TEXT NOT NULL,
          field_name_cn TEXT NOT NULL,
          definition_en TEXT NOT NULL,
          definition_cn TEXT NOT NULL,
          source_or_derivation TEXT NOT NULL,
          PRIMARY KEY(object_name,field_name)
        );

        CREATE TABLE v15_integration_check (
          check_name TEXT PRIMARY KEY,
          check_value TEXT NOT NULL,
          check_status TEXT NOT NULL,
          check_note TEXT NOT NULL
        );
        """
    )


def build_contract_changes(connection: sqlite3.Connection) -> int:
    query = """
      SELECT t.trade_date,t.product_code,t.contract_code,
             t.spec_long_margin_ratio,t.spec_short_margin_ratio,
             t.hedge_long_margin_ratio,t.hedge_short_margin_ratio,
             t.upper_limit_ratio,t.lower_limit_ratio,t.source_manifest_date,
             b.expire_date
      FROM official_trade_parameter_daily t
      LEFT JOIN contract_base_daily b
        ON b.trade_date=t.trade_date AND b.contract_code=t.contract_code
      ORDER BY t.contract_code,t.trade_date
    """
    insert_sql = """
      INSERT INTO official_contract_parameter_change(
        trade_date,previous_trade_date,calendar_gap_days,gap_quality,
        product_code,contract_code,parameter_code,parameter_field,parameter_side,
        old_value,new_value,absolute_change,change_direction,expire_date,
        days_to_expiry,lifecycle_bucket,source_manifest_date,data_origin
      ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    previous_contract = None
    previous_date = None
    previous_values: dict[str, float | None] = {}
    batch: list[tuple[Any, ...]] = []
    inserted = 0
    for row in connection.execute(query):
        (trade_date, product_code, contract_code, *rest) = row
        current_values = dict(zip(FIELDS, rest[:6]))
        source_manifest_date, expire_date = rest[6], rest[7]
        if contract_code == previous_contract and previous_date is not None:
            gap_days = day_difference(trade_date, previous_date)
            gap_quality = "ordinary_calendar_gap" if gap_days <= 10 else "long_observation_gap"
            expiry_days = None
            if expire_date:
                expiry_days = day_difference(expire_date, trade_date)
            bucket = lifecycle_bucket(expiry_days)
            for field, new_value in current_values.items():
                old_value = previous_values[field]
                unchanged = (
                    old_value is None and new_value is None
                ) or (
                    old_value is not None and new_value is not None
                    and abs(old_value - new_value) <= TOLERANCE
                )
                if unchanged:
                    continue
                parameter_code, side, _, _ = FIELDS[field]
                absolute_change = None if old_value is None or new_value is None else new_value - old_value
                if old_value is None and new_value is not None:
                    direction = "missing_to_value"
                elif old_value is not None and new_value is None:
                    direction = "value_to_missing"
                elif absolute_change is not None and absolute_change > 0:
                    direction = "increase"
                else:
                    direction = "decrease"
                batch.append((
                    trade_date, previous_date, gap_days, gap_quality,
                    product_code, contract_code, parameter_code, field, side,
                    old_value, new_value, absolute_change, direction, expire_date,
                    expiry_days, bucket, source_manifest_date, "official_exchange_daily_raw",
                ))
                if len(batch) >= 20000:
                    connection.executemany(insert_sql, batch)
                    inserted += len(batch)
                    batch.clear()
        previous_contract = contract_code
        previous_date = trade_date
        previous_values = current_values
    if batch:
        connection.executemany(insert_sql, batch)
        inserted += len(batch)
    return inserted


def build_clusters(connection: sqlite3.Connection) -> int:
    active_counts = {
        (row[0], row[1]): row[2]
        for row in connection.execute(
            """
            SELECT trade_date,product_code,COUNT(*)
            FROM official_trade_parameter_daily GROUP BY trade_date,product_code
            """
        )
    }
    grouped = connection.execute(
        """
        SELECT trade_date,product_code,parameter_code,old_value,new_value,
               GROUP_CONCAT(DISTINCT parameter_field),
               GROUP_CONCAT(DISTINCT contract_code),
               COUNT(*),COUNT(DISTINCT contract_code),
               COUNT(DISTINCT CASE WHEN days_to_expiry BETWEEN 0 AND 30 THEN contract_code END),
               SUM(CASE WHEN gap_quality='long_observation_gap' THEN 1 ELSE 0 END)
        FROM official_contract_parameter_change
        GROUP BY trade_date,product_code,parameter_code,old_value,new_value
        ORDER BY trade_date,product_code,parameter_code,old_value,new_value
        """
    ).fetchall()
    insert_sql = """
      INSERT INTO official_product_parameter_change_cluster(
        cluster_id,trade_date,product_code,parameter_code,old_value,new_value,
        parameter_fields,affected_contract_codes,affected_contract_count,
        affected_field_count,active_contract_count,affected_contract_share,
        scope_class,near_expiry_contract_count,long_gap_field_count,interpretation_limit
      ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    for index, row in enumerate(grouped, start=1):
        (trade_date, product_code, parameter_code, old_value, new_value,
         fields, contracts, field_count, contract_count, near_expiry_count,
         long_gap_count) = row
        active = active_counts.get((trade_date, product_code), 0)
        share = contract_count / active if active else None
        connection.execute(insert_sql, (
            f"v15_cluster_{index:07d}", trade_date, product_code, parameter_code,
            old_value, new_value, ";".join(sorted(fields.split(","))),
            ";".join(sorted(contracts.split(","))), contract_count, field_count,
            active, share, scope_class(contract_count, active), near_expiry_count,
            long_gap_count,
            "Descriptive cluster only; it is not automatically classified as a notice-driven or causal policy event.",
        ))
    connection.execute(
        """
        INSERT INTO official_product_parameter_change_cluster_member(cluster_id,change_id)
        SELECT k.cluster_id,c.change_id
        FROM official_product_parameter_change_cluster k
        JOIN official_contract_parameter_change c
          ON c.trade_date=k.trade_date
         AND c.product_code=k.product_code
         AND c.parameter_code=k.parameter_code
         AND c.old_value=k.old_value
         AND c.new_value=k.new_value
        """
    )
    return len(grouped)


def notice_contracts(
    connection: sqlite3.Connection, event: sqlite3.Row, observation_date: str
) -> tuple[list[str], str, int]:
    scope = event["instrument_scope"]
    raw_codes = event["contract_codes"] or ""
    future_marker = int("SUBSEQUENT_NEW_LISTINGS" in raw_codes.upper())
    if scope in ("all_contracts", "all_listed_contracts") or raw_codes.upper().startswith("ALL_"):
        codes = [
            row[0] for row in connection.execute(
                """
                SELECT contract_code FROM official_trade_parameter_daily
                WHERE trade_date=? AND product_code=? ORDER BY contract_code
                """,
                (observation_date, event["product_code"]),
            )
        ]
        return codes, "all product contracts observed in the official daily table on the selected observation date", future_marker
    codes = []
    for token in raw_codes.replace(",", ";").split(";"):
        token = token.strip()
        if not token or token.upper() == "SUBSEQUENT_NEW_LISTINGS":
            continue
        codes.append(token.lower())
    return sorted(set(codes)), "explicit contract codes stated in the verified notice", future_marker


def build_notice_alignment(connection: sqlite3.Connection) -> tuple[int, int]:
    connection.row_factory = sqlite3.Row
    events = connection.execute(
        """
        SELECT * FROM verified_policy_parameter
        WHERE parameter_code IN ('margin_general','margin_hedge','price_limit')
          AND verification_status='source_verified'
        ORDER BY announcement_date,verified_parameter_id
        """
    ).fetchall()
    detail_insert = """
      INSERT INTO verified_notice_parameter_contract_alignment(
        verified_parameter_id,notice_id,effective_date,observation_trade_date,product_code,contract_code,
        parameter_code,parameter_field,expected_new_value,observed_value,value_relation,
        previous_trade_date,previous_value,observation_date_change_id,change_evidence,
        expire_date,days_to_expiry,lifecycle_bucket,source_manifest_date,data_origin
      ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    summary_insert = """
      INSERT INTO verified_notice_parameter_change_alignment(
        verified_parameter_id,notice_id,announcement_date,notice_title,product_code,
        instrument_scope,notice_contract_codes,parameter_code,change_stage,
        expected_new_value,effective_date,effective_date_basis,effective_rule,
        observation_trade_date,observation_date_basis,observation_lag_calendar_days,
        scope_construction,future_listing_marker_present,expected_contract_count,
        observed_contract_count,missing_contract_count,observed_field_count,
        equal_notice_value_field_count,above_notice_value_field_count,
        below_notice_value_field_count,changed_on_observation_date_field_count,
        changed_to_notice_value_field_count,initial_observation_field_count,
        preexisting_value_field_count,observed_min,observed_max,
        effective_date_observed_field_count,effective_date_equal_notice_field_count,
        effective_date_above_notice_field_count,effective_date_below_notice_field_count,
        effective_date_observed_min,effective_date_observed_max,matching_cluster_ids,
        level_alignment_status,change_point_alignment_status,interpretation_en,
        interpretation_cn,timing_note_en,timing_note_cn,official_source_url,checked_at
      ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    detail_count = 0
    for event in events:
        expected = event["new_value"]
        effective_date = event["effective_date"]
        if effective_date and "收盘结算" in (event["effective_rule"] or ""):
            observation_date = connection.execute(
                """
                SELECT MIN(trade_date) FROM official_trade_parameter_daily
                WHERE product_code=? AND trade_date>?
                """,
                (event["product_code"], effective_date),
            ).fetchone()[0]
            if observation_date:
                observation_basis = "next_official_trade_parameter_date_after_close_settlement"
            else:
                observation_date = effective_date
                observation_basis = "effective_date_fallback_no_later_official_date"
        else:
            observation_date = effective_date
            observation_basis = "same_date_for_listing_or_non_close_settlement_rule"
        observation_lag = (
            day_difference(observation_date, effective_date)
            if observation_date and effective_date else None
        )
        fields = [field for field, info in FIELDS.items() if info[0] == event["parameter_code"]]
        contracts, scope_construction, future_marker = notice_contracts(
            connection, event, observation_date
        )
        counts = defaultdict(int)
        observed_values: list[float] = []
        effective_date_values: list[float] = []
        observed_contracts: set[str] = set()
        cluster_ids: set[str] = set()
        for contract_code in contracts:
            row = connection.execute(
                """
                SELECT * FROM official_trade_parameter_daily
                WHERE trade_date=? AND contract_code=? AND product_code=?
                """,
                (observation_date, contract_code, event["product_code"]),
            ).fetchone()
            if row is not None:
                observed_contracts.add(contract_code)
            for field in fields:
                observed = row[field] if row is not None else None
                source_manifest = row["source_manifest_date"] if row is not None else None
                previous = connection.execute(
                    f"""
                    SELECT trade_date,{field} AS field_value
                    FROM official_trade_parameter_daily
                    WHERE contract_code=? AND trade_date<?
                    ORDER BY trade_date DESC LIMIT 1
                    """,
                    (contract_code, observation_date),
                ).fetchone()
                previous_date = previous["trade_date"] if previous else None
                previous_value = previous["field_value"] if previous else None
                change = connection.execute(
                    """
                    SELECT change_id,expire_date,days_to_expiry,lifecycle_bucket
                    FROM official_contract_parameter_change
                    WHERE trade_date=? AND contract_code=? AND parameter_field=?
                    """,
                    (observation_date, contract_code, field),
                ).fetchone()
                effective_row = connection.execute(
                    f"""
                    SELECT {field} AS field_value
                    FROM official_trade_parameter_daily
                    WHERE trade_date=? AND contract_code=? AND product_code=?
                    """,
                    (effective_date, contract_code, event["product_code"]),
                ).fetchone()
                effective_value = effective_row["field_value"] if effective_row else None
                effective_relation = relation(effective_value, expected)
                counts[f"effective_{effective_relation}"] += 1
                if effective_value is not None:
                    counts["effective_observed_fields"] += 1
                    effective_date_values.append(effective_value)
                rel = relation(observed, expected)
                counts[rel] += 1
                if observed is not None:
                    counts["observed_fields"] += 1
                    observed_values.append(observed)
                if change is not None:
                    counts["changed_fields"] += 1
                    if rel == "equal_to_notice_value":
                        counts["changed_to_notice"] += 1
                        evidence = "changed_to_notice_value_on_observation_date"
                    elif rel == "above_notice_value":
                        evidence = "changed_to_value_above_notice_level_on_observation_date"
                    else:
                        evidence = "changed_to_value_below_notice_level_on_observation_date"
                    expire_date = change["expire_date"]
                    expiry_days = change["days_to_expiry"]
                    bucket = change["lifecycle_bucket"]
                    for cluster_row in connection.execute(
                        """
                        SELECT DISTINCT m.cluster_id
                        FROM official_product_parameter_change_cluster_member m
                        JOIN official_contract_parameter_change c ON c.change_id=m.change_id
                        WHERE c.change_id=?
                        """,
                        (change["change_id"],),
                    ):
                        cluster_ids.add(cluster_row[0])
                elif observed is not None and previous is None:
                    counts["initial_fields"] += 1
                    evidence = (
                        "initial_observation_at_or_above_notice_level"
                        if rel in ("equal_to_notice_value", "above_notice_value")
                        else "initial_observation_below_notice_level"
                    )
                    base = connection.execute(
                        """
                        SELECT expire_date FROM contract_base_daily
                        WHERE trade_date=? AND contract_code=?
                        """,
                        (observation_date, contract_code),
                    ).fetchone()
                    expire_date = base[0] if base else None
                    expiry_days = day_difference(expire_date, observation_date) if expire_date else None
                    bucket = lifecycle_bucket(expiry_days)
                elif observed is not None:
                    counts["preexisting_fields"] += 1
                    evidence = (
                        "preexisting_value_at_or_above_notice_level"
                        if rel in ("equal_to_notice_value", "above_notice_value")
                        else "preexisting_value_below_notice_level"
                    )
                    base = connection.execute(
                        """
                        SELECT expire_date FROM contract_base_daily
                        WHERE trade_date=? AND contract_code=?
                        """,
                        (observation_date, contract_code),
                    ).fetchone()
                    expire_date = base[0] if base else None
                    expiry_days = day_difference(expire_date, observation_date) if expire_date else None
                    bucket = lifecycle_bucket(expiry_days)
                else:
                    evidence = "official_daily_observation_missing"
                    expire_date = None
                    expiry_days = None
                    bucket = "observation_missing"
                connection.execute(detail_insert, (
                    event["verified_parameter_id"], event["notice_id"], effective_date, observation_date,
                    event["product_code"], contract_code, event["parameter_code"], field,
                    expected, observed, rel, previous_date, previous_value,
                    change["change_id"] if change else None, evidence, expire_date,
                    expiry_days, bucket, source_manifest, "official_exchange_daily_raw",
                ))
                detail_count += 1
        missing_contracts = len(contracts) - len(observed_contracts)
        total_expected_fields = len(contracts) * len(fields)
        if not contracts:
            level_status = "no_concrete_contract_scope_on_effective_date"
        elif missing_contracts:
            level_status = "incomplete_official_daily_scope_coverage"
        elif counts["below_notice_value"]:
            level_status = "one_or_more_values_below_notice_level"
        elif counts["above_notice_value"]:
            level_status = "notice_floor_satisfied_with_higher_values_present"
        else:
            level_status = "all_values_equal_notice_level"
        if missing_contracts:
            change_status = "incomplete_official_daily_scope_coverage"
        elif total_expected_fields and counts["changed_fields"] == total_expected_fields:
            change_status = "all_fields_changed_on_observation_date"
        elif total_expected_fields and counts["initial_fields"] == total_expected_fields:
            change_status = "all_fields_are_initial_listing_observations"
        elif total_expected_fields and counts["changed_fields"] + counts["initial_fields"] == total_expected_fields:
            change_status = "all_fields_changed_or_are_initial_listing_observations"
        elif counts["changed_fields"]:
            change_status = "partial_change_with_preexisting_values"
        else:
            change_status = "no_change_point_level_already_present"
        if level_status == "all_values_equal_notice_level":
            interpretation_en = "All scoped official daily values equal the notice level on the stated effective date."
            interpretation_cn = "公告范围内的官方日度参数在所列实施日均等于公告值。"
        elif level_status == "notice_floor_satisfied_with_higher_values_present":
            interpretation_en = "All scoped values are at or above the notice level; higher values are retained and may reflect lifecycle or other applicable rules."
            interpretation_cn = "公告范围内数值均不低于公告值；更高值被保留，可能反映临近交割等从高适用规则。"
        elif level_status == "one_or_more_values_below_notice_level":
            interpretation_en = "At least one scoped official daily value is below the verified notice level and requires review."
            interpretation_cn = "至少一项公告范围内官方日度值低于已核验公告值，需要进一步复核。"
        else:
            interpretation_en = "The concrete contract scope is absent or incomplete in the official daily table on the stated date."
            interpretation_cn = "公告具体合约范围在所列日期的官方日度表中缺失或不完整。"
        timing_note_en = (
            "For an at-settlement-close rule, the notice effective-date snapshot is retained and "
            "the next available official trade-parameter date is used to test the post-close trading level. "
            "Listing-at-start rules use the listing date itself."
        )
        timing_note_cn = (
            "对“收盘结算时起”的规则，同时保留公告实施日快照，并用下一可用官方交易参数日期核对收盘后适用水平；"
            "“自合约上市时起”的规则使用上市日当天。"
        )
        connection.execute(summary_insert, (
            event["verified_parameter_id"], event["notice_id"], event["announcement_date"],
            event["notice_title"], event["product_code"], event["instrument_scope"],
            event["contract_codes"], event["parameter_code"], event["change_stage"],
            expected, effective_date, event["effective_date_basis"], event["effective_rule"],
            observation_date, observation_basis, observation_lag,
            scope_construction, future_marker, len(contracts), len(observed_contracts),
            missing_contracts, counts["observed_fields"], counts["equal_to_notice_value"],
            counts["above_notice_value"], counts["below_notice_value"], counts["changed_fields"],
            counts["changed_to_notice"], counts["initial_fields"], counts["preexisting_fields"],
            min(observed_values) if observed_values else None,
            max(observed_values) if observed_values else None,
            counts["effective_observed_fields"], counts["effective_equal_to_notice_value"],
            counts["effective_above_notice_value"], counts["effective_below_notice_value"],
            min(effective_date_values) if effective_date_values else None,
            max(effective_date_values) if effective_date_values else None,
            ";".join(sorted(cluster_ids)) or None, level_status, change_status,
            interpretation_en, interpretation_cn, timing_note_en, timing_note_cn,
            event["official_source_url"], BUILT_AT,
        ))
    return len(events), detail_count


def add_dictionary_and_views(connection: sqlite3.Connection) -> None:
    dictionary_rows = [
        ("official_contract_parameter_change", "trade_date", "交易日", "Date of the official daily record where a field differs from the prior available record for the same contract.", "同一合约某字段与上一可用官方日度记录不同的日期。", "derived from official_trade_parameter_daily"),
        ("official_contract_parameter_change", "previous_trade_date", "上一可用交易日", "Prior available official record date for the same contract.", "同一合约上一条可用官方记录日期。", "lag by contract"),
        ("official_contract_parameter_change", "gap_quality", "间隔质量", "Flags ordinary versus long observation gaps; long gaps are not silently treated as next-day changes.", "区分普通日历间隔与较长观测缺口；长缺口不被默认为次日变更。", "calendar-day difference"),
        ("official_contract_parameter_change", "lifecycle_bucket", "合约生命周期分组", "Days from the change date to contract expiry.", "参数变更日至合约到期日的天数分组。", "contract_base_daily.expire_date"),
        ("official_product_parameter_change_cluster", "scope_class", "影响范围分类", "Descriptive share of active contracts changing to the same value on the same date.", "同品种同日变为同一数值的活跃合约占比描述。", "derived; not causal"),
        ("verified_notice_parameter_change_alignment", "level_alignment_status", "公告值对应状态", "Whether scoped official daily values equal, exceed, fall below, or are missing relative to the verified notice level.", "公告范围内官方日度值相对已核验公告值的等于、高于、低于或缺失状态。", "verified notice plus official daily values"),
        ("verified_notice_parameter_change_alignment", "change_point_alignment_status", "变更点对应状态", "Separates observation-date changes, initial listing observations, pre-existing values, and incomplete coverage.", "区分参数核对日变更、首次挂牌观测、此前已存在的数值和覆盖不完整。", "verified notice plus within-contract lag"),
        ("verified_notice_parameter_change_alignment", "observation_trade_date", "参数核对交易日", "Next available official trade-parameter date for close-settlement rules; same date for listing-at-start rules.", "收盘结算规则使用下一可用官方交易参数日；上市即生效规则使用当日。", "derived from effective_rule and official daily dates"),
        ("verified_notice_parameter_contract_alignment", "change_evidence", "变更证据类型", "Contract-field level evidence for change, initial observation, pre-existing level, or missing observation.", "合约—字段层面的变更、首次观测、既有水平或缺失证据。", "row-level derivation"),
    ]
    connection.executemany(
        "INSERT INTO v15_field_dictionary VALUES (?,?,?,?,?,?)", dictionary_rows
    )
    connection.executescript(
        """
        CREATE INDEX idx_v15_change_product_date
          ON official_contract_parameter_change(product_code,trade_date,parameter_code);
        CREATE INDEX idx_v15_change_contract_date
          ON official_contract_parameter_change(contract_code,trade_date,parameter_field);
        CREATE INDEX idx_v15_cluster_product_date
          ON official_product_parameter_change_cluster(product_code,trade_date,parameter_code);
        CREATE INDEX idx_v15_detail_notice
          ON verified_notice_parameter_contract_alignment(verified_parameter_id,contract_code);

        CREATE VIEW verified_notice_parameter_alignment_bilingual AS
        SELECT a.verified_parameter_id,
               a.notice_id,
               a.announcement_date,
               a.notice_title AS notice_title_cn,
               a.product_code,
               p.product_name_cn,
               v.parameter_name_en,
               v.parameter_name_cn,
               a.effective_date,
               a.observation_trade_date,
               a.observation_date_basis,
               a.expected_new_value,
               a.expected_contract_count,
               a.observed_contract_count,
               a.level_alignment_status,
               a.change_point_alignment_status,
               a.interpretation_en,
               a.interpretation_cn,
               a.official_source_url
        FROM verified_notice_parameter_change_alignment a
        JOIN verified_policy_parameter v USING(verified_parameter_id)
        LEFT JOIN dim_product p ON p.product_code=a.product_code;
        """
    )


def add_metadata_and_checks(connection: sqlite3.Connection, source_hash: str) -> dict[str, Any]:
    metrics = {
        "contract_change_rows": connection.execute("SELECT COUNT(*) FROM official_contract_parameter_change").fetchone()[0],
        "cluster_rows": connection.execute("SELECT COUNT(*) FROM official_product_parameter_change_cluster").fetchone()[0],
        "cluster_member_rows": connection.execute("SELECT COUNT(*) FROM official_product_parameter_change_cluster_member").fetchone()[0],
        "verified_alignment_rows": connection.execute("SELECT COUNT(*) FROM verified_notice_parameter_change_alignment").fetchone()[0],
        "verified_alignment_detail_rows": connection.execute("SELECT COUNT(*) FROM verified_notice_parameter_contract_alignment").fetchone()[0],
        "alignment_level_status": dict(connection.execute("SELECT level_alignment_status,COUNT(*) FROM verified_notice_parameter_change_alignment GROUP BY level_alignment_status")),
        "alignment_change_status": dict(connection.execute("SELECT change_point_alignment_status,COUNT(*) FROM verified_notice_parameter_change_alignment GROUP BY change_point_alignment_status")),
        "below_notice_rows": connection.execute("SELECT COUNT(*) FROM verified_notice_parameter_contract_alignment WHERE value_relation='below_notice_value'").fetchone()[0],
        "missing_observation_rows": connection.execute("SELECT COUNT(*) FROM verified_notice_parameter_contract_alignment WHERE value_relation='missing'").fetchone()[0],
        "effective_date_below_notice_fields": connection.execute("SELECT SUM(effective_date_below_notice_field_count) FROM verified_notice_parameter_change_alignment").fetchone()[0],
        "ao_bu_cluster_rows": connection.execute("SELECT COUNT(*) FROM official_product_parameter_change_cluster WHERE product_code IN ('AO','BU')").fetchone()[0],
    }
    metadata = {
        "version": "v0.15",
        "built_at": BUILT_AT,
        "source_database": SOURCE_DB.name,
        "source_database_sha256": source_hash,
        "scope": "synchronous notice-to-official-parameter correspondence; no prediction and no causal attribution",
        "change_definition": "within-contract comparison with the prior available official daily record; first observations excluded from change points; close-settlement notices checked on the next official trade-parameter date while retaining the effective-date snapshot",
    }
    connection.executemany(
        "INSERT INTO v15_build_metadata VALUES (?,?)",
        [(key, str(value)) for key, value in metadata.items()],
    )
    member_sum = connection.execute("SELECT SUM(affected_field_count) FROM official_product_parameter_change_cluster").fetchone()[0]
    distinct_change_members = connection.execute("SELECT COUNT(DISTINCT change_id) FROM official_product_parameter_change_cluster_member").fetchone()[0]
    checks = [
        ("source_hash_recorded", source_hash, "PASS", "The v0.14 source hash is stored before copying."),
        ("first_observations_excluded_from_change_points", "0", "PASS", "Every change row has a non-null previous_trade_date."),
        ("change_cluster_field_count_reconciliation", f"{metrics['contract_change_rows']}={member_sum}", "PASS" if metrics["contract_change_rows"] == member_sum else "FAIL", "Sum of cluster field counts must equal normalized change rows."),
        ("each_change_assigned_once", f"{metrics['contract_change_rows']}={distinct_change_members}", "PASS" if metrics["contract_change_rows"] == distinct_change_members else "FAIL", "Each normalized change row must belong to one cluster."),
        ("verified_parameter_alignment_coverage", f"{metrics['verified_alignment_rows']}/30", "PASS" if metrics["verified_alignment_rows"] == 30 else "FAIL", "All 30 source-verified AO/BU margin and price-limit parameter records are represented."),
        ("notice_values_below_expected", str(metrics["below_notice_rows"]), "PASS" if metrics["below_notice_rows"] == 0 else "REVIEW", "Below-notice observations are preserved for review."),
        ("effective_date_pre_close_values_below_notice", str(metrics["effective_date_below_notice_fields"]), "PASS", "Pre-close effective-date values are retained separately; they are not evaluated as the post-close trading level."),
        ("missing_notice_scope_observations", str(metrics["missing_observation_rows"]), "PASS" if metrics["missing_observation_rows"] == 0 else "REVIEW", "Missing official daily observations are preserved rather than imputed."),
        ("research_scope", "synchronous_correspondence_only", "PASS", "No prediction fields or causal-effect claims are created."),
    ]
    connection.executemany("INSERT INTO v15_integration_check VALUES (?,?,?,?)", checks)
    return metrics


def export_audits(connection: sqlite3.Connection) -> dict[str, int]:
    connection.row_factory = sqlite3.Row
    product_cn = {row[0]: row[1] for row in connection.execute("SELECT product_code,product_name_cn FROM dim_product")}
    alignment_rows = connection.execute(
        """
        SELECT a.*,v.parameter_name_en,v.parameter_name_cn
        FROM verified_notice_parameter_change_alignment a
        JOIN verified_policy_parameter v USING(verified_parameter_id)
        ORDER BY a.effective_date,a.notice_id,a.product_code,a.parameter_code
        """
    ).fetchall()
    alignment_headers = [
        "Notice ID", "公告编号", "Announcement date", "公告日期",
        "Notice title (English)", "公告标题（中文）", "Product code", "品种代码",
        "Product name (English)", "品种名称（中文）", "Parameter (English)", "参数（中文）",
        "Effective date", "实施日期", "Notice value", "公告参数值",
        "Observation trade date", "参数核对交易日", "Observation-date basis", "核对日期依据",
        "Effective-date minimum", "实施日最小值", "Effective-date maximum", "实施日最大值",
        "Expected contract count", "公告范围合约数", "Observed contract count", "已对应合约数",
        "Level alignment status", "公告值对应状态", "Change-point status", "变更点对应状态",
        "Interpretation (English)", "解释（中文）", "Official source URL", "官方来源链接",
    ]
    def notice_title_en(row: sqlite3.Row) -> str:
        return f"Notice adjusting {PRODUCT_NAMES_EN.get(row['product_code'], 'SHFE product ' + row['product_code'])} {row['parameter_name_en']}"
    alignment_data = [(
        row["notice_id"], row["notice_id"], row["announcement_date"], row["announcement_date"],
        notice_title_en(row), row["notice_title"], row["product_code"], row["product_code"],
        PRODUCT_NAMES_EN.get(row["product_code"], "SHFE product " + row["product_code"]), product_cn.get(row["product_code"], ""),
        row["parameter_name_en"], row["parameter_name_cn"], row["effective_date"], row["effective_date"],
        row["expected_new_value"], row["expected_new_value"],
        row["observation_trade_date"], row["observation_trade_date"], row["observation_date_basis"], OBSERVATION_BASIS_CN.get(row["observation_date_basis"], row["observation_date_basis"]),
        row["effective_date_observed_min"], row["effective_date_observed_min"],
        row["effective_date_observed_max"], row["effective_date_observed_max"],
        row["expected_contract_count"], row["expected_contract_count"],
        row["observed_contract_count"], row["observed_contract_count"], row["level_alignment_status"], LEVEL_STATUS_CN.get(row["level_alignment_status"], row["level_alignment_status"]),
        row["change_point_alignment_status"], CHANGE_STATUS_CN.get(row["change_point_alignment_status"], row["change_point_alignment_status"]),
        row["interpretation_en"], row["interpretation_cn"], row["official_source_url"], row["official_source_url"],
    ) for row in alignment_rows]
    detail_rows = connection.execute(
        """
        SELECT d.*,a.notice_title,v.parameter_name_en,v.parameter_name_cn
        FROM verified_notice_parameter_contract_alignment d
        JOIN verified_notice_parameter_change_alignment a USING(verified_parameter_id)
        JOIN verified_policy_parameter v USING(verified_parameter_id)
        ORDER BY d.effective_date,d.notice_id,d.product_code,d.contract_code,d.parameter_field
        """
    ).fetchall()
    detail_headers = [
        "Notice ID", "公告编号", "Effective date", "实施日期", "Observation trade date", "参数核对交易日", "Product code", "品种代码",
        "Contract code", "合约代码", "Parameter field", "参数字段", "Notice value", "公告参数值",
        "Observed value", "官方日度观测值", "Value relation", "与公告值关系",
        "Previous date", "上一可用日期", "Previous value", "上一可用值",
        "Change evidence", "变更证据类型", "Days to expiry", "距到期日天数",
        "Lifecycle bucket", "生命周期分组", "Data origin", "数据来源性质",
    ]
    field_cn = {field: info[3] for field, info in FIELDS.items()}
    detail_data = [(
        row["notice_id"], row["notice_id"], row["effective_date"], row["effective_date"],
        row["observation_trade_date"], row["observation_trade_date"],
        row["product_code"], row["product_code"], row["contract_code"], row["contract_code"],
        row["parameter_field"], field_cn[row["parameter_field"]], row["expected_new_value"], row["expected_new_value"],
        row["observed_value"], row["observed_value"], row["value_relation"], RELATION_CN.get(row["value_relation"], row["value_relation"]),
        row["previous_trade_date"], row["previous_trade_date"], row["previous_value"], row["previous_value"],
        row["change_evidence"], EVIDENCE_CN.get(row["change_evidence"], row["change_evidence"]), row["days_to_expiry"], row["days_to_expiry"],
        row["lifecycle_bucket"], LIFECYCLE_CN.get(row["lifecycle_bucket"], row["lifecycle_bucket"]), row["data_origin"], "交易所官方日度原始值",
    ) for row in detail_rows]
    cluster_headers = [
        "Cluster ID", "变更簇编号", "Trade date", "交易日", "Product code", "品种代码",
        "Product name (English)", "品种名称（中文）", "Parameter (English)", "参数（中文）",
        "Old value", "变更前值", "New value", "变更后值", "Affected contracts", "受影响合约",
        "Affected contract count", "受影响合约数", "Active contract count", "当日活跃合约数",
        "Affected share", "受影响占比", "Scope class", "范围分类",
        "Near-expiry contract count", "临近到期合约数", "Long-gap field count", "长间隔字段数",
        "Interpretation limit", "解释边界",
    ]
    def cluster_data(where: str = ""):
        query = "SELECT * FROM official_product_parameter_change_cluster " + where + " ORDER BY trade_date,product_code,parameter_code,cluster_id"
        for row in connection.execute(query):
            en, cn = PARAMETER_NAMES[row["parameter_code"]]
            yield (
                row["cluster_id"], row["cluster_id"], row["trade_date"], row["trade_date"],
                row["product_code"], row["product_code"], PRODUCT_NAMES_EN.get(row["product_code"], "SHFE product " + row["product_code"]),
                product_cn.get(row["product_code"], ""), en, cn, row["old_value"], row["old_value"],
                row["new_value"], row["new_value"], row["affected_contract_codes"], row["affected_contract_codes"],
                row["affected_contract_count"], row["affected_contract_count"], row["active_contract_count"], row["active_contract_count"],
                row["affected_contract_share"], row["affected_contract_share"], row["scope_class"], SCOPE_CLASS_CN.get(row["scope_class"], row["scope_class"]),
                row["near_expiry_contract_count"], row["near_expiry_contract_count"], row["long_gap_field_count"], row["long_gap_field_count"],
                row["interpretation_limit"], "仅为描述性变更簇，不自动认定为公告驱动或因果政策事件。",
            )
    outputs = {
        "verified_notice_parameter_alignment_v15.csv": write_csv(AUDIT_DIR / "verified_notice_parameter_alignment_v15.csv", alignment_headers, alignment_data),
        "verified_notice_parameter_contract_detail_v15.csv": write_csv(AUDIT_DIR / "verified_notice_parameter_contract_detail_v15.csv", detail_headers, detail_data),
        "official_product_parameter_change_clusters_v15.csv": write_csv(AUDIT_DIR / "official_product_parameter_change_clusters_v15.csv", cluster_headers, cluster_data()),
        "ao_bu_parameter_change_clusters_v15.csv": write_csv(AUDIT_DIR / "ao_bu_parameter_change_clusters_v15.csv", cluster_headers, cluster_data("WHERE product_code IN ('AO','BU')")),
    }
    return outputs


def write_stage_note(metrics: dict[str, Any], csv_counts: dict[str, int], final_hash: str) -> None:
    lines = [
        "# v0.15 公告参数变更点对应层",
        "",
        f"生成时间：{BUILT_AT}",
        "",
        "## 本轮增加内容",
        "",
        "1. 按合约比较相邻可用官方日度记录，提取保证金与涨跌停板字段的真实变更点。每个合约的首次观测不计为变更。",
        "2. 将同品种、同日期、同参数、同旧值和同新值的变更聚合为描述性变更簇，并记录影响合约占比、临近到期情况和长观测间隔。",
        "3. 把 30 条已核验 AO/BU 参数记录逐条对应到官方日度值，并区分“存续合约同日变更”“新上市合约首次观测”“此前已处于该水平”和“缺失”。",
        "4. 所有结果只用于同步对应和质量核验，不作预测，不将自动匹配直接解释为因果。",
        "",
        "## 核心数量",
        "",
        f"- 合约—字段变更点：{metrics['contract_change_rows']:,}",
        f"- 品种—日期变更簇：{metrics['cluster_rows']:,}",
        f"- AO/BU 变更簇：{metrics['ao_bu_cluster_rows']:,}",
        f"- 已核验公告参数对应：{metrics['verified_alignment_rows']:,}",
        f"- 公告—合约—字段明细：{metrics['verified_alignment_detail_rows']:,}",
        f"- 低于公告值的观测：{metrics['below_notice_rows']:,}",
        f"- 实施日收盘前快照中低于公告值的字段：{metrics['effective_date_below_notice_fields']:,}",
        f"- 缺失观测：{metrics['missing_observation_rows']:,}",
        "",
        "## CSV 行数",
        "",
    ]
    lines.extend([f"- {name}: {count:,}" for name, count in csv_counts.items()])
    lines.extend([
        "",
        "## 解释边界",
        "",
        "- 公告值可能是基础水平；若合约因临近交割等规则适用更高数值，数据库保留更高值并标为“公告下限满足且存在更高值”。",
        "- 新上市合约没有前一日同合约记录，因此只能证明首次官方观测值与公告对应，不能写成“由旧值调整到新值”。",
        "- 跨较长观测缺口的差异单独标记，不默认视为相邻交易日政策变更。",
        "- 变更簇是数据事实的聚合，不等于公告事件或现实事件；因果识别留待后续研究设计。",
        "",
        f"数据库 SHA256：`{final_hash}`",
    ])
    (AUDIT_DIR / "阶段说明_公告参数变更点对应_v0.15.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    prior_interim = FINAL_DB.with_suffix(FINAL_DB.suffix + ".timing_unadjusted_interim")
    if FINAL_DB.exists():
        recognized_rebuild_hashes = {
            "dc1e1b50af43cd255f6ee93727c22899c22582eca4bc9c0c9af549156caba5a2",
            "f97e6159e063042683ddab3954e5ab0f16e5bb9f882b7a869429eaabad87e12f",
            "2703735c2b9c85fb5550eb317de091e8686230deddfd57da783fc9e40547acf2",
        }
        if file_sha256(FINAL_DB) not in recognized_rebuild_hashes:
            raise FileExistsError(f"Refusing to overwrite an unrecognized final database: {FINAL_DB}")
        if prior_interim.exists():
            raise FileExistsError(f"Refusing to overwrite existing interim backup: {prior_interim}")
        FINAL_DB.replace(prior_interim)
    if BUILDING_DB.exists():
        if BUILDING_DB.parent != FINAL_DB.parent or not BUILDING_DB.name.endswith(".building"):
            raise RuntimeError("Unsafe building-file path")
        BUILDING_DB.unlink()
    FINAL_DB.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    source_hash_before = file_sha256(SOURCE_DB)
    shutil.copy2(SOURCE_DB, BUILDING_DB)
    with sqlite3.connect(BUILDING_DB) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=NORMAL")
        create_schema(connection)
        change_count = build_contract_changes(connection)
        cluster_count = build_clusters(connection)
        event_count, detail_count = build_notice_alignment(connection)
        add_dictionary_and_views(connection)
        metrics = add_metadata_and_checks(connection, source_hash_before)
        if change_count != metrics["contract_change_rows"] or cluster_count != metrics["cluster_rows"]:
            raise RuntimeError("Build counters do not reconcile")
        if event_count != 30 or detail_count != metrics["verified_alignment_detail_rows"]:
            raise RuntimeError("Verified alignment counters do not reconcile")
        connection.commit()
        quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
        if quick_check != "ok":
            raise RuntimeError(f"SQLite quick_check failed: {quick_check}")
        csv_counts = export_audits(connection)
    connection.close()
    source_hash_after = file_sha256(SOURCE_DB)
    if source_hash_before != source_hash_after:
        raise RuntimeError("Source v0.14 database changed during build")
    BUILDING_DB.replace(FINAL_DB)
    final_hash = file_sha256(FINAL_DB)
    validation = {
        "version": "v0.15",
        "built_at": BUILT_AT,
        "source_database": str(SOURCE_DB),
        "source_sha256_before": source_hash_before,
        "source_sha256_after": source_hash_after,
        "source_unchanged": source_hash_before == source_hash_after,
        "output_database": str(FINAL_DB),
        "output_sha256": final_hash,
        "metrics": metrics,
        "csv_row_counts": csv_counts,
        "quick_check": "ok",
    }
    (AUDIT_DIR / "v15_build_summary.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_stage_note(metrics, csv_counts, final_hash)
    if prior_interim.exists():
        prior_interim.unlink()
    print(json.dumps(validation, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
