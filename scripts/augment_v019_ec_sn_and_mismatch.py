from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


EVENT_TYPES = {
    "fee": ("Fee adjustment", "手续费调整"),
    "margin_and_price_limit": ("Margin and price-limit adjustment", "保证金及涨跌停板调整"),
    "intraday_open_limit": ("Intraday opening-limit adjustment", "日内开仓限额调整"),
    "holiday_temporary_margin_and_limit": ("Temporary holiday margin and price-limit adjustment", "节假日临时保证金及涨跌停板调整"),
    "routine_fee_relief": ("Routine fee relief", "常规手续费减免"),
}
DIRECTIONS = {
    "tightening": ("Tightening", "收紧"),
    "loosening": ("Loosening", "放松"),
    "mixed": ("Mixed", "混合调整"),
    "uncertain": ("Uncertain", "方向待判定"),
}
PRODUCTS = {"EC": ("Containerized Freight Index (Europe Service)", "集运指数（欧线）"), "SN": ("Tin", "锡")}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def notice_id(episode_id: str) -> str:
    return re.sub(r"_(EC|SN)$", "", episode_id)


def english_values(text: str, event_en: str | None = None, direction_en: str | None = None) -> str:
    if event_en and direction_en:
        numeric = re.findall(
            r"[A-Z]{1,3}\d+(?:/\d+)*|\d+(?:\.\d+)?(?:%|‱)?(?:→\d+(?:\.\d+)?(?:%|‱)?)?",
            text,
        )
        notation = ", ".join(dict.fromkeys(numeric)) if numeric else "not separately extractable"
        return (
            f"{event_en}; direction: {direction_en}; official numeric notation: {notation}. "
            "See the paired Chinese field for the exact contract scope and original wording."
        )
    replacements = [
        ("相关套保交易手续费减半", "hedge-related trading fees halved"),
        ("标准仓单作为保证金手续费免收", "fee waived for standard warrants used as margin"),
        ("交易手续费", "trading fee"), ("日内平今", "intraday close-today fee"),
        ("平今仓", "close-today position"), ("日内开仓上限", "intraday opening limit"),
        ("日内开仓", "intraday opening"), ("保证金", "margin"),
        ("涨跌停板", "price limit"), ("上限", "limit"), ("调至", "adjusted to "),
        ("主要由", "mainly from "), ("相关", "related "), ("手", " lots"),
        ("减半", "halved"), ("免收", "waived"),
    ]
    result = text
    for source, target in replacements:
        result = result.replace(source, target)
    return result


def import_ec_sn(connection: sqlite3.Connection, episodes_path: Path, evidence_path: Path) -> int:
    with episodes_path.open(encoding="utf-8-sig", newline="") as stream:
        episodes = list(csv.DictReader(stream))
    with evidence_path.open(encoding="utf-8-sig", newline="") as stream:
        evidence = {row["notice_episode_id"]: row for row in csv.DictReader(stream)}
    connection.executescript("""
      DROP TABLE IF EXISTS verified_notice_episode_ec_sn;
      CREATE TABLE verified_notice_episode_ec_sn (
        notice_episode_id TEXT PRIMARY KEY,
        notice_id TEXT NOT NULL,
        product_code TEXT NOT NULL,
        product_name_en TEXT NOT NULL,
        product_name_cn TEXT NOT NULL,
        announcement_date TEXT NOT NULL,
        policy_reference_date TEXT NOT NULL,
        analysis_event_trade_day TEXT NOT NULL,
        effective_timing TEXT NOT NULL,
        episode_direction TEXT NOT NULL,
        direction_en TEXT NOT NULL,
        direction_cn TEXT NOT NULL,
        event_type TEXT NOT NULL,
        event_type_en TEXT NOT NULL,
        event_type_cn TEXT NOT NULL,
        event_name_en TEXT NOT NULL,
        event_name_cn TEXT NOT NULL,
        routine_or_holiday TEXT NOT NULL,
        parameter_values_verified_en TEXT NOT NULL,
        parameter_values_verified_cn TEXT NOT NULL,
        coding_confidence TEXT NOT NULL,
        policy_date_cluster_id TEXT NOT NULL,
        official_title_cn TEXT NOT NULL,
        official_source_url TEXT NOT NULL,
        official_body_excerpt_cn TEXT NOT NULL,
        source_sha256 TEXT NOT NULL,
        body_sha256 TEXT NOT NULL,
        source_layer TEXT NOT NULL,
        checked_at TEXT NOT NULL,
        source_row_json TEXT NOT NULL
      );
    """)
    checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
    rows = []
    for item in episodes:
        episode_id = item["notice_episode_id"]
        proof = evidence.get(episode_id, {})
        product = item["product_code"]
        product_en, product_cn = PRODUCTS[product]
        event_en, event_cn = EVENT_TYPES.get(item["source_verified_event_type"], (item["source_verified_event_type"], item["source_verified_event_type"]))
        direction_en, direction_cn = DIRECTIONS.get(item["episode_direction"], (item["episode_direction"], item["episode_direction"]))
        event_name_en = f"{product_en}: {event_en} ({item['announcement_date']})"
        event_name_cn = f"{product_cn}：{event_cn}（{item['announcement_date']}）"
        rows.append((
            episode_id, notice_id(episode_id), product, product_en, product_cn,
            item["announcement_date"], item["policy_reference_date"], item["analysis_event_trade_day"],
            item["effective_timing"], item["episode_direction"], direction_en, direction_cn,
            item["source_verified_event_type"], event_en, event_cn, event_name_en, event_name_cn,
            item["routine_or_holiday"], english_values(item["parameter_values_verified"], event_en, direction_en),
            item["parameter_values_verified"], item["coding_confidence"], item["policy_date_cluster_id"],
            proof.get("title", ""), proof.get("source_url", ""), proof.get("official_body_product_extract", ""),
            proof.get("source_sha256", ""), proof.get("body_sha256", ""),
            "ec_sn_source_verified_specialized_database", checked_at, json.dumps(item, ensure_ascii=False),
        ))
    connection.executemany("INSERT INTO verified_notice_episode_ec_sn VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    return len(rows)


def classify_mismatches(connection: sqlite3.Connection) -> dict:
    connection.executescript("""
      DROP TABLE IF EXISTS trade_parameter_settlement_mismatch_classified;
      CREATE TABLE trade_parameter_settlement_mismatch_classified (
        trade_date TEXT NOT NULL,
        product_code TEXT NOT NULL,
        contract_code TEXT NOT NULL,
        field_name TEXT NOT NULL,
        trade_parameter_value REAL,
        settlement_parameter_value REAL,
        difference REAL,
        absolute_difference REAL,
        mismatch_pattern_code TEXT NOT NULL,
        mismatch_pattern_en TEXT NOT NULL,
        mismatch_pattern_cn TEXT NOT NULL,
        near_parameter_change INTEGER NOT NULL,
        review_priority TEXT NOT NULL,
        interpretation_limit_cn TEXT NOT NULL,
        PRIMARY KEY(trade_date,contract_code,field_name)
      );
      DROP TABLE IF EXISTS trade_parameter_settlement_mismatch_summary;
      CREATE TABLE trade_parameter_settlement_mismatch_summary (
        product_code TEXT NOT NULL,
        mismatch_pattern_code TEXT NOT NULL,
        review_priority TEXT NOT NULL,
        mismatch_field_rows INTEGER NOT NULL,
        affected_contract_days INTEGER NOT NULL,
        first_date TEXT NOT NULL,
        last_date TEXT NOT NULL,
        average_absolute_difference REAL,
        PRIMARY KEY(product_code,mismatch_pattern_code,review_priority)
      );
    """)
    change_dates = defaultdict(set)
    for row in connection.execute("SELECT product_code,trade_date FROM official_product_parameter_change_cluster"):
        change_dates[row[0]].add(row[1])
    raw = connection.execute("SELECT * FROM trade_parameter_settlement_mismatch ORDER BY trade_date,contract_code,field_name").fetchall()
    groups = defaultdict(list)
    for row in raw:
        groups[(row[0], row[2])].append(row)
    values = []
    counts = Counter()
    for (trade_date, contract), rows in groups.items():
        numeric = [row[6] for row in rows if row[6] is not None]
        parallel = len(rows) >= 2 and numeric and max(numeric) - min(numeric) < 1e-12
        for row in rows:
            difference = row[6]
            absolute = abs(difference) if difference is not None else None
            near_change = int(trade_date in change_dates[row[1]])
            if difference is None:
                code = "one_source_value_missing"
                en, cn, priority = "One source value missing", "单一来源字段缺失", "high"
            elif absolute is not None and absolute < 1e-6:
                code = "rounding_scale_difference"
                en, cn, priority = "Rounding-scale difference", "舍入量级差异", "low"
            elif near_change:
                code = "same_day_parameter_change_difference"
                en, cn, priority = "Difference on a parameter-change date", "参数变更日来源差异", "high"
            elif parallel:
                code = "parallel_margin_level_difference"
                en, cn, priority = "Parallel margin-level difference", "多保证金字段同步水平差异", "medium"
            elif difference > 0:
                code = "trade_parameter_above_settlement"
                en, cn, priority = "Trade-parameter value above settlement value", "交易参数值高于结算参数值", "medium"
            else:
                code = "trade_parameter_below_settlement"
                en, cn, priority = "Trade-parameter value below settlement value", "交易参数值低于结算参数值", "medium"
            counts[(code, priority)] += 1
            values.append((*row, absolute, code, en, cn, near_change, priority,
                "该分类描述可观测差异形态，不自动判定哪一来源正确，也不将时点、合约阶段或从高执行解释为已证实原因。"))
    connection.executemany("INSERT INTO trade_parameter_settlement_mismatch_classified VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
    connection.execute("""
      INSERT INTO trade_parameter_settlement_mismatch_summary
      SELECT product_code,mismatch_pattern_code,review_priority,COUNT(*),
             COUNT(DISTINCT trade_date||'|'||contract_code),MIN(trade_date),MAX(trade_date),AVG(absolute_difference)
      FROM trade_parameter_settlement_mismatch_classified
      GROUP BY product_code,mismatch_pattern_code,review_priority
    """)
    return {"classified_rows": len(values), "pattern_counts": {f"{key[0]}|{key[1]}": value for key, value in sorted(counts.items())}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Add EC/SN verified episodes and mismatch classification for v0.19.")
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--output-db", type=Path, required=True)
    parser.add_argument("--episodes", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    args.output_db.parent.mkdir(parents=True, exist_ok=True)
    building = args.output_db.with_suffix(args.output_db.suffix + ".building")
    if building.exists():
        building.unlink()
    shutil.copy2(args.source_db, building)
    connection = sqlite3.connect(building)
    try:
        episodes = import_ec_sn(connection, args.episodes, args.evidence)
        mismatch = classify_mismatches(connection)
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        connection.close()
    if args.output_db.exists():
        args.output_db.unlink()
    building.replace(args.output_db)
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_database": str(args.source_db), "source_sha256": sha256(args.source_db),
        "output_database": str(args.output_db), "output_sha256": sha256(args.output_db),
        "verified_ec_sn_episodes": episodes, "mismatch_classification": mismatch,
        "integrity_check": integrity,
    }
    args.output_db.with_suffix(".augmentation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
