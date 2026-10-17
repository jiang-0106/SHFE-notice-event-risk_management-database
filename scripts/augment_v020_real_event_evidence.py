from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


DEFAULT_INPUT = Path(
    r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\outputs\SHFE市场研究助手_v0.19_20261016"
    r"\SHFE公告参数市场同步数据库_公告参数变更点对应_v0.19_final.sqlite3"
)
DEFAULT_OUTPUT = Path(
    r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\outputs\SHFE市场研究助手_v0.20_20261017"
    r"\SHFE公告参数市场同步数据库_公告参数变更点对应_v0.20_final.sqlite3"
)
DEFAULT_RESEARCH_ROOT = Path(r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\EC_SN专题研究_波动现实事件公告调整")


CATEGORY_CN = {
    "capacity_supply": "运力供给",
    "carrier_rerouting": "航线绕行",
    "demand_disruption": "需求扰动",
    "geopolitical_security": "地缘政治与安全",
    "geopolitical_shipping": "地缘政治与航运安全",
    "indonesia_export": "印度尼西亚出口政策",
    "mine_supply": "矿山供应",
    "myanmar_policy": "缅甸政策",
    "port_disruption": "港口中断或拥堵",
    "smelter_disruption": "冶炼厂生产扰动",
}

CATEGORY_EN = {key: key.replace("_", " ").title() for key in CATEGORY_CN}

CHANNEL_EN = {
    "capacity_supply": "Effective transport capacity and freight supply",
    "carrier_rerouting": "Route distance, transit time, and effective vessel capacity",
    "demand_disruption": "Downstream demand and inventory expectations",
    "geopolitical_security": "Security risk, logistics continuity, and risk premium",
    "geopolitical_shipping": "Shipping-route security, transit distance, and effective capacity utilization",
    "indonesia_export": "Export availability and international refined-nickel supply expectations",
    "mine_supply": "Nickel ore availability, input costs, and refined-nickel supply expectations",
    "myanmar_policy": "Cross-border raw-material availability and regional supply expectations",
    "port_disruption": "Port throughput, delivery delays, and effective transport capacity",
    "smelter_disruption": "Refined-nickel output, inventory expectations, and deliverable supply",
}

DIRECTION_CN = {"up": "偏上行", "down": "偏下行", "mixed": "方向不确定或混合"}
DIRECTION_EN = {"up": "upward", "down": "downward", "mixed": "mixed or uncertain"}


def args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add verified EC/SN real-event evidence to the synchronized SHFE database.")
    parser.add_argument("--input-db", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-db", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--research-root", type=Path, default=DEFAULT_RESEARCH_ROOT)
    return parser.parse_args()


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def add_raw_table(conn: sqlite3.Connection, table: str, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise ValueError(f"No rows for {table}")
    columns = list(rows[0])
    if any(not name.replace("_", "").isalnum() for name in columns):
        raise ValueError(f"Unsafe CSV column in {table}")
    conn.execute(f"DROP TABLE IF EXISTS {table}")
    definition = ",".join(f'"{name}" TEXT' for name in columns)
    conn.execute(f"CREATE TABLE {table} ({definition}, source_row_json TEXT NOT NULL)")
    placeholders = ",".join("?" for _ in range(len(columns) + 1))
    conn.executemany(
        f"INSERT INTO {table} VALUES ({placeholders})",
        [tuple(row.get(name, "") for name in columns) + (json.dumps(row, ensure_ascii=False, sort_keys=True),) for row in rows],
    )


def main() -> None:
    cfg = args()
    source = cfg.input_db.resolve()
    target = cfg.output_db.resolve()
    root = cfg.research_root.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    building = target.with_suffix(target.suffix + ".building")
    if building.exists():
        building.unlink()
    shutil.copy2(source, building)

    event_rows = read_csv(root / "01_数据" / "real_world_events_frozen_v0.1.csv")
    chain_rows = read_csv(root / "04_双向推断表" / "verified_mechanism_chain_event_market_policy_postmarket_v0.1.csv")
    forward_rows = read_csv(root / "04_双向推断表" / "verified_forward_real_event_market_policy_v0.1.csv")
    backward_rows = read_csv(root / "04_双向推断表" / "verified_backward_policy_market_real_event_v0.1.csv")
    event_by_id = {row["real_event_id"]: row for row in event_rows}
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    conn = sqlite3.connect(building)
    try:
        conn.executescript(
            """
            DROP TABLE IF EXISTS verified_real_world_event_ec_sn;
            DROP TABLE IF EXISTS verified_event_policy_chain_ec_sn;
            DROP TABLE IF EXISTS real_event_evidence_metadata;

            CREATE TABLE verified_real_world_event_ec_sn (
              real_event_id TEXT PRIMARY KEY,
              product_code TEXT NOT NULL,
              event_date TEXT NOT NULL,
              event_end_date TEXT,
              event_trade_day TEXT,
              event_category_code TEXT NOT NULL,
              event_category_en TEXT NOT NULL,
              event_category_cn TEXT NOT NULL,
              event_name_en TEXT NOT NULL,
              event_name_cn TEXT NOT NULL,
              transmission_channel_en TEXT NOT NULL,
              transmission_channel_cn TEXT NOT NULL,
              expected_direction_code TEXT,
              expected_direction_en TEXT,
              expected_direction_cn TEXT,
              geographic_scope TEXT,
              source_title TEXT NOT NULL,
              source_organization TEXT NOT NULL,
              source_url TEXT NOT NULL,
              source_date TEXT,
              source_level TEXT NOT NULL,
              independent_source_2 TEXT,
              coding_status TEXT NOT NULL,
              evidence_status_en TEXT NOT NULL,
              evidence_status_cn TEXT NOT NULL,
              reviewer TEXT,
              review_date TEXT,
              notes_cn TEXT,
              event_cluster_id_20d TEXT,
              cluster_role TEXT,
              severity_precode_score INTEGER,
              severity_precode_label TEXT,
              severity_precode_reason_cn TEXT,
              manual_include TEXT,
              sample_status TEXT,
              interpretation_limit_en TEXT NOT NULL,
              interpretation_limit_cn TEXT NOT NULL,
              source_row_json TEXT NOT NULL,
              imported_at TEXT NOT NULL
            );

            CREATE TABLE verified_event_policy_chain_ec_sn (
              chain_id TEXT PRIMARY KEY,
              real_event_id TEXT,
              product_code TEXT NOT NULL,
              real_event_date TEXT,
              real_event_trade_day TEXT,
              event_category_code TEXT,
              event_category_en TEXT,
              event_category_cn TEXT,
              event_name_en TEXT,
              event_name_cn TEXT,
              transmission_channel_en TEXT,
              transmission_channel_cn TEXT,
              expected_direction_en TEXT,
              expected_direction_cn TEXT,
              event_source_url TEXT,
              event_to_policy_gap_trading_days INTEGER,
              intermediate_market_days INTEGER,
              intermediate_anomaly_days INTEGER,
              intermediate_max_anomaly_count INTEGER,
              return_anomaly_days INTEGER,
              range_anomaly_days INTEGER,
              volume_anomaly_days INTEGER,
              open_interest_anomaly_days INTEGER,
              policy_date_cluster_id TEXT NOT NULL,
              policy_trade_day TEXT NOT NULL,
              policy_direction TEXT,
              policy_event_types TEXT,
              parameter_values_verified_cn TEXT,
              post20_abs_return_change REAL,
              post20_intraday_range_change REAL,
              post20_log_volume_change REAL,
              post20_open_interest_change REAL,
              chain_completeness_grade TEXT NOT NULL,
              real_event_evidence_status TEXT NOT NULL,
              interpretation_limit_en TEXT NOT NULL,
              interpretation_limit_cn TEXT NOT NULL,
              source_row_json TEXT NOT NULL,
              imported_at TEXT NOT NULL,
              FOREIGN KEY(real_event_id) REFERENCES verified_real_world_event_ec_sn(real_event_id)
            );

            CREATE TABLE real_event_evidence_metadata (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );
            """
        )

        event_values = []
        for row in event_rows:
            category = row["event_category"]
            direction = row.get("expected_direction", "")
            has_second = bool(row.get("independent_source_2", "").strip())
            evidence_en = "primary source plus independent corroboration" if has_second else "primary source verified"
            evidence_cn = "主要来源并有独立第二来源佐证" if has_second else "主要来源已核验"
            event_values.append((
                row["real_event_id"], row["product_code"], row["event_date"], row["event_end_date"] or None,
                row["event_trade_day"] or None, category, CATEGORY_EN.get(category, category), CATEGORY_CN.get(category, category),
                row["source_title"], row["event_description"], CHANNEL_EN.get(category, "See the paired Chinese field for the coded transmission channel"),
                row["transmission_channel"], direction or None, DIRECTION_EN.get(direction, direction), DIRECTION_CN.get(direction, direction),
                row["geographic_scope"], row["source_title"], row["source_organization"], row["source_url"], row["source_date"],
                row["source_level"], row["independent_source_2"] or None, row["coding_status"], evidence_en, evidence_cn,
                row["reviewer"], row["review_date"], row["notes"], row["event_cluster_id_20d"], row["cluster_role"],
                int(row["severity_precode_score"]) if row["severity_precode_score"] else None, row["severity_precode_label"],
                row["severity_precode_reason"], row["manual_include"], row["sample_status"],
                "A verified historical event record; temporal matching does not by itself establish causality.",
                "该记录为已核验的历史现实事件；与市场或公告在时间上对应并不自动构成因果证据。",
                json.dumps(row, ensure_ascii=False, sort_keys=True), generated_at,
            ))
        conn.executemany("INSERT INTO verified_real_world_event_ec_sn VALUES (" + ",".join("?" for _ in range(39)) + ")", event_values)

        chain_values = []
        for index, row in enumerate(chain_rows, start=1):
            event = event_by_id.get(row["real_event_id"], {})
            category = row["event_category"]
            direction = row["expected_direction"]
            grade = row["chain_completeness_grade"]
            chain_values.append((
                f"CHAIN_{index:04d}", row["real_event_id"] or None, row["product_code"], row["real_event_date"] or None,
                row["real_event_trade_day"] or None, category or None, CATEGORY_EN.get(category, category) or None,
                CATEGORY_CN.get(category, category) or None, event.get("source_title") or None, row["event_description"] or None,
                CHANNEL_EN.get(category) if category else None, row["transmission_channel"] or None,
                DIRECTION_EN.get(direction, direction) or None, DIRECTION_CN.get(direction, direction) or None,
                row["event_source_url"] or None, int(row["event_to_policy_gap_trading_days"]) if row["event_to_policy_gap_trading_days"] else None,
                int(row["intermediate_market_days"]), int(row["intermediate_anomaly_days"]), int(row["intermediate_max_anomaly_count"]),
                int(row["return_anomaly_days"]), int(row["range_anomaly_days"]), int(row["volume_anomaly_days"]), int(row["open_interest_anomaly_days"]),
                row["policy_date_cluster_id"], row["policy_trade_day"], row["policy_direction"], row["policy_event_types"],
                row["parameter_values_verified"], float(row["post20_abs_return_change"]) if row["post20_abs_return_change"] else None,
                float(row["post20_intraday_range_change"]) if row["post20_intraday_range_change"] else None,
                float(row["post20_log_volume_change"]) if row["post20_log_volume_change"] else None,
                float(row["post20_open_interest_change"]) if row["post20_open_interest_change"] else None,
                grade, "verified_real_event_link" if row["real_event_id"] else "no_verified_real_event_link_in_window",
                "Temporal mechanism-chain evidence only; not a causal estimate or deterministic prediction.",
                "仅表示历史时间顺序与机制链候选关系，不是因果估计，也不能作为确定性预测。",
                json.dumps(row, ensure_ascii=False, sort_keys=True), generated_at,
            ))
        conn.executemany("INSERT INTO verified_event_policy_chain_ec_sn VALUES (" + ",".join("?" for _ in range(38)) + ")", chain_values)

        add_raw_table(conn, "verified_forward_event_policy_ec_sn_raw", forward_rows)
        add_raw_table(conn, "verified_backward_policy_event_ec_sn_raw", backward_rows)
        metadata = {
            "layer_version": "v0.20-real-event-evidence",
            "imported_at": generated_at,
            "real_event_rows": str(len(event_rows)),
            "mechanism_chain_rows": str(len(chain_rows)),
            "forward_rows": str(len(forward_rows)),
            "backward_rows": str(len(backward_rows)),
            "real_event_scope": "EC_SN_only",
            "causal_boundary": "temporal_correspondence_not_causal_identification",
        }
        conn.executemany("INSERT INTO real_event_evidence_metadata VALUES (?,?)", metadata.items())
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite integrity check failed")
        conn.commit()
    finally:
        conn.close()
    os.replace(building, target)
    print(json.dumps({"output_db": str(target), "real_events": len(event_rows), "chains": len(chain_rows), "forward": len(forward_rows), "backward": len(backward_rows)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
