from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path


CONTRACT_MONTH = re.compile(r"^\d{4}$")


def number(value):
    if value is None or str(value).strip() == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def product_id(value: object) -> str:
    return str(value or "").strip().lower().removesuffix("_f").upper()


def load_payload(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def integrate_market(connection: sqlite3.Connection, item: dict, products: set[str]) -> tuple[int, int]:
    payload = load_payload(item["saved_path"])
    trade_date = item["report_date"]
    contracts = []
    summaries = {}
    for row in payload["o_curinstrument"]:
        product = product_id(row.get("PRODUCTGROUPID") or row.get("PRODUCTID"))
        if product not in products:
            continue
        month = str(row.get("DELIVERYMONTH") or "").strip()
        if CONTRACT_MONTH.fullmatch(month):
            contracts.append((
                trade_date, product, product.lower() + month, month,
                number(row.get("OPENPRICE")), number(row.get("HIGHESTPRICE")),
                number(row.get("LOWESTPRICE")), number(row.get("CLOSEPRICE")),
                number(row.get("SETTLEMENTPRICE")), number(row.get("PRESETTLEMENTPRICE")),
                number(row.get("VOLUME")), number(row.get("TURNOVER")),
                number(row.get("OPENINTEREST")), number(row.get("OPENINTERESTCHG")),
                item["saved_path"],
            ))
        elif month and number(row.get("VOLUME")) is not None:
            candidate = (
                trade_date, product, number(row.get("VOLUME")), number(row.get("TURNOVER")),
                number(row.get("OPENINTEREST")), number(row.get("OPENINTERESTCHG")), item["saved_path"],
            )
            summaries[product] = candidate
    connection.executemany("INSERT OR REPLACE INTO market_contract_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", contracts)
    connection.executemany("INSERT OR REPLACE INTO market_product_daily VALUES (?,?,?,?,?,?,?)", summaries.values())
    return len(contracts), len(summaries)


def integrate_settlement(connection: sqlite3.Connection, item: dict, products: set[str]) -> int:
    payload = load_payload(item["saved_path"])
    trade_date = item["report_date"]
    values = []
    for row in payload["o_cursor"]:
        product = product_id(row.get("PRODUCTID"))
        contract = str(row.get("INSTRUMENTID") or "").strip().lower()
        if product not in products or not contract:
            continue
        values.append((
            trade_date, product, contract, number(row.get("SETTLEMENTPRICE")),
            number(row.get("SPECLONGMARGINRATIO")), number(row.get("SPECSHORTMARGINRATIO")),
            number(row.get("HEDGLONGMARGINRATIO")), number(row.get("HEDGSHORTMARGINRATIO")),
            number(row.get("TRADEFEERATIO")), row.get("TRADEFEEUNIT"),
            number(row.get("TTRADEFEERATIO")), row.get("TTRADEFEEUNIT"),
            number(row.get("COMMODITYDELIVFEERATIO")), row.get("COMMODITYDELIVFEEUNIT"),
            item["saved_path"],
        ))
    connection.executemany("INSERT OR REPLACE INTO settlement_parameter_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
    return len(values)


def integrate_trade_parameters(connection: sqlite3.Connection, item: dict, products: set[str]) -> int:
    payload = load_payload(item["saved_path"])
    trade_date = item["report_date"]
    manifest_values = (
        item["requested_date"], "期货交易参数", item["official_url"], item["http_status"],
        item["validation_status"], item["report_date"], item["trade_date_basis"], item["row_count"],
        item["file_bytes"], item["sha256"], item["saved_path"], item["error"],
    )
    connection.execute("INSERT OR REPLACE INTO official_trade_parameter_file_manifest VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", manifest_values)
    values = []
    for row in payload["ContractDailyTradeArgument"]:
        contract = str(row.get("INSTRUMENTID") or "").strip().lower()
        match = re.match(r"^[a-z]+", contract)
        product = match.group(0).upper() if match else ""
        if product not in products:
            continue
        values.append((
            trade_date, item["trade_date_basis"], product, "derived_from_contract_code_prefix", contract,
            number(row.get("SPEC_LONGMARGINRATIO")), number(row.get("SPEC_SHORTMARGINRATIO")),
            number(row.get("HDEGE_LONGMARGINRATIO")), number(row.get("HDEGE_SHORTMARGINRATIO")),
            number(row.get("UPPER_VALUE")), number(row.get("LOWER_VALUE")), row.get("PRICE_LIMITS"),
            row.get("UPDATE_DATE") or payload.get("update_date"), item["requested_date"],
        ))
    connection.executemany("INSERT OR REPLACE INTO official_trade_parameter_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
    if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='trade_parameter_source_file_audit'").fetchone():
        connection.execute(
            "INSERT OR REPLACE INTO trade_parameter_source_file_audit VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                item["requested_date"], item["saved_path"], item["report_date"], item["trade_date_basis"],
                json.dumps([item["report_date"]], ensure_ascii=False), item["row_count"], len(values),
                item["row_count"] - len(values), item["sha256"], item["sha256"], "valid_loaded", "",
            ),
        )
    return len(values)


def rebuild_dominant(connection: sqlite3.Connection) -> int:
    connection.execute("DELETE FROM market_dominant_daily")
    rows = connection.execute("SELECT * FROM market_contract_daily ORDER BY product_code,trade_date,contract_code").fetchall()
    by_day = defaultdict(list)
    for row in rows:
        by_day[(row["product_code"], row["trade_date"])].append(row)
    previous = {}
    output = []
    for (product, trade_date), day_rows in sorted(by_day.items()):
        eligible = [row for row in day_rows if row["settlement"] is not None and row["settlement"] > 0]
        if not eligible:
            continue
        chosen = max(eligible, key=lambda row: (row["open_interest"] if row["open_interest"] is not None else -1, row["volume"] if row["volume"] is not None else -1, row["contract_code"]))
        prior = previous.get(product)
        same = bool(prior and prior["contract_code"] == chosen["contract_code"])
        log_return = math.log(chosen["settlement"] / prior["settlement"]) if same and prior["settlement"] and chosen["settlement"] else None
        day_range = math.log(chosen["high"] / chosen["low"]) if chosen["high"] and chosen["low"] and chosen["high"] > 0 and chosen["low"] > 0 else None
        output.append((trade_date, product, chosen["contract_code"], chosen["close"], chosen["settlement"], chosen["volume"], chosen["turnover"], chosen["open_interest"], log_return, abs(log_return) if log_return is not None else None, day_range, 0 if prior is None or same else 1, "max_open_interest_then_volume_then_contract"))
        previous[product] = chosen
    connection.executemany("INSERT INTO market_dominant_daily VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", output)
    return len(output)


def rebuild_parameter_audits(connection: sqlite3.Connection) -> dict[str, int]:
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    connection.execute("DELETE FROM trade_parameter_market_alignment_daily")
    connection.execute(
        """
        INSERT INTO trade_parameter_market_alignment_daily
        WITH p AS (
          SELECT trade_date,COUNT(*) parameter_rows FROM official_trade_parameter_daily GROUP BY trade_date
        ), m AS (
          SELECT trade_date,COUNT(*) market_rows FROM market_contract_daily GROUP BY trade_date
        ), j AS (
          SELECT p.trade_date,COUNT(*) matched_rows
          FROM official_trade_parameter_daily p JOIN market_contract_daily m
            ON m.trade_date=p.trade_date AND m.contract_code=p.contract_code
          GROUP BY p.trade_date
        )
        SELECT p.trade_date,p.parameter_rows,COALESCE(m.market_rows,0),COALESCE(j.matched_rows,0),
               p.parameter_rows-COALESCE(j.matched_rows,0),
               COALESCE(m.market_rows,0)-COALESCE(j.matched_rows,0),
               CASE WHEN p.parameter_rows=COALESCE(m.market_rows,0)
                          AND p.parameter_rows=COALESCE(j.matched_rows,0)
                    THEN 'exact' ELSE 'mismatch_preserved' END,?
        FROM p LEFT JOIN m USING(trade_date) LEFT JOIN j USING(trade_date)
        """,
        (generated_at,),
    )
    connection.execute("DELETE FROM trade_parameter_settlement_mismatch")
    fields = (
        ("spec_long_margin_ratio", "spec_long_margin_ratio"),
        ("spec_short_margin_ratio", "spec_short_margin_ratio"),
        ("hedge_long_margin_ratio", "hedge_long_margin_ratio"),
        ("hedge_short_margin_ratio", "hedge_short_margin_ratio"),
    )
    for parameter_field, settlement_field in fields:
        connection.execute(
            f"""
            INSERT INTO trade_parameter_settlement_mismatch
            SELECT p.trade_date,p.product_code,p.contract_code,?,p.{parameter_field},s.{settlement_field},
                   CASE WHEN p.{parameter_field} IS NOT NULL AND s.{settlement_field} IS NOT NULL
                        THEN p.{parameter_field}-s.{settlement_field} END
            FROM official_trade_parameter_daily p JOIN settlement_parameter_daily s
              ON s.trade_date=p.trade_date AND s.contract_code=p.contract_code
            WHERE NOT (
              (p.{parameter_field} IS NULL AND s.{settlement_field} IS NULL) OR
              (p.{parameter_field} IS NOT NULL AND s.{settlement_field} IS NOT NULL
               AND ABS(p.{parameter_field}-s.{settlement_field})<1e-12)
            )
            """,
            (parameter_field,),
        )
    connection.execute("DELETE FROM trade_parameter_settlement_reconciliation_daily")
    connection.execute(
        """
        INSERT INTO trade_parameter_settlement_reconciliation_daily
        WITH p AS (
          SELECT trade_date,COUNT(*) parameter_rows FROM official_trade_parameter_daily GROUP BY trade_date
        ), s AS (
          SELECT trade_date,COUNT(*) settlement_rows FROM settlement_parameter_daily GROUP BY trade_date
        ), joined AS (
          SELECT p.trade_date,p.contract_code,
            CASE WHEN
              ((p.spec_long_margin_ratio IS NULL AND s.spec_long_margin_ratio IS NULL) OR ABS(p.spec_long_margin_ratio-s.spec_long_margin_ratio)<1e-12) AND
              ((p.spec_short_margin_ratio IS NULL AND s.spec_short_margin_ratio IS NULL) OR ABS(p.spec_short_margin_ratio-s.spec_short_margin_ratio)<1e-12) AND
              ((p.hedge_long_margin_ratio IS NULL AND s.hedge_long_margin_ratio IS NULL) OR ABS(p.hedge_long_margin_ratio-s.hedge_long_margin_ratio)<1e-12) AND
              ((p.hedge_short_margin_ratio IS NULL AND s.hedge_short_margin_ratio IS NULL) OR ABS(p.hedge_short_margin_ratio-s.hedge_short_margin_ratio)<1e-12)
            THEN 1 ELSE 0 END row_equal
          FROM official_trade_parameter_daily p JOIN settlement_parameter_daily s
            ON s.trade_date=p.trade_date AND s.contract_code=p.contract_code
        ), j AS (
          SELECT trade_date,COUNT(*) matched_rows,SUM(row_equal) equal_rows,
                 SUM(CASE WHEN row_equal=0 THEN 1 ELSE 0 END) different_rows
          FROM joined GROUP BY trade_date
        )
        SELECT p.trade_date,p.parameter_rows,COALESCE(s.settlement_rows,0),COALESCE(j.matched_rows,0),
               p.parameter_rows-COALESCE(j.matched_rows,0),
               COALESCE(s.settlement_rows,0)-COALESCE(j.matched_rows,0),
               COALESCE(j.equal_rows,0),COALESCE(j.different_rows,0),
               CASE WHEN p.parameter_rows=COALESCE(s.settlement_rows,0)
                          AND p.parameter_rows=COALESCE(j.matched_rows,0)
                          AND COALESCE(j.different_rows,0)=0 THEN 'exact_keys_and_margins'
                    WHEN COALESCE(j.different_rows,0)=0 THEN 'key_coverage_difference_only'
                    ELSE 'margin_difference_preserved' END,?
        FROM p LEFT JOIN s USING(trade_date) LEFT JOIN j USING(trade_date)
        """,
        (generated_at,),
    )
    return {
        "market_alignment_days": connection.execute("SELECT COUNT(*) FROM trade_parameter_market_alignment_daily").fetchone()[0],
        "settlement_reconciliation_days": connection.execute("SELECT COUNT(*) FROM trade_parameter_settlement_reconciliation_daily").fetchone()[0],
        "settlement_mismatch_fields": connection.execute("SELECT COUNT(*) FROM trade_parameter_settlement_mismatch").fetchone()[0],
    }


def store_availability(connection: sqlite3.Connection, manifest: list[dict]) -> None:
    connection.executescript("""
        DROP TABLE IF EXISTS official_data_availability_check;
        CREATE TABLE official_data_availability_check (
          requested_date TEXT NOT NULL, dataset TEXT NOT NULL, dataset_cn TEXT NOT NULL,
          official_url TEXT NOT NULL, http_status INTEGER NOT NULL, validation_status TEXT NOT NULL,
          report_date TEXT, row_count INTEGER NOT NULL, sha256 TEXT, saved_path TEXT,
          error TEXT, checked_at TEXT NOT NULL, PRIMARY KEY(requested_date,dataset)
        );
    """)
    connection.executemany(
        "INSERT INTO official_data_availability_check VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(item["requested_date"], item["dataset"], item["dataset_cn"], item["official_url"], item["http_status"], item["validation_status"], item["report_date"], item["row_count"], item["sha256"], item["saved_path"], item["error"], item["checked_at"]) for item in manifest],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Integrate a validated SHFE increment without overwriting the source database.")
    parser.add_argument("--source-db", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-db", type=Path, required=True)
    args = parser.parse_args()
    args.output_db.parent.mkdir(parents=True, exist_ok=True)
    building = args.output_db.with_suffix(args.output_db.suffix + ".building")
    if building.exists():
        building.unlink()
    shutil.copy2(args.source_db, building)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    valid = [item for item in manifest if item["validation_status"] in {"valid_saved", "valid_reused"}]
    counts = defaultdict(int)
    with sqlite3.connect(building) as connection:
        connection.row_factory = sqlite3.Row
        products = {row[0] for row in connection.execute("SELECT product_code FROM dim_product")}
        store_availability(connection, manifest)
        for item in valid:
            if item["dataset"] == "market":
                contract_rows, product_rows = integrate_market(connection, item, products)
                counts["market_contract_rows"] += contract_rows
                counts["market_product_rows"] += product_rows
            elif item["dataset"] == "settlement":
                counts["settlement_rows"] += integrate_settlement(connection, item, products)
            elif item["dataset"] == "trade_parameter":
                counts["trade_parameter_rows"] += integrate_trade_parameters(connection, item, products)
        counts["dominant_rows"] = rebuild_dominant(connection)
        counts.update(rebuild_parameter_audits(connection))
        connection.execute("PRAGMA optimize")
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        coverage = {
            table: connection.execute(f"SELECT MIN(trade_date),MAX(trade_date),COUNT(*) FROM {table}").fetchone()
            for table in ("market_contract_daily", "market_product_daily", "market_dominant_daily", "settlement_parameter_daily", "official_trade_parameter_daily")
        }
    connection.close()
    if args.output_db.exists():
        args.output_db.unlink()
    building.replace(args.output_db)
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_database": str(args.source_db), "output_database": str(args.output_db),
        "valid_files": len(valid), "integrated_rows": dict(counts), "integrity_check": integrity,
        "coverage": {name: {"first_date": value[0], "last_date": value[1], "rows": value[2]} for name, value in coverage.items()},
    }
    summary_path = args.output_db.with_suffix(".integration_summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
