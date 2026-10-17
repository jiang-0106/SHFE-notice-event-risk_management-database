from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


DATASETS = {
    "market": {
        "name_cn": "期货日行情",
        "url": "https://www.shfe.com.cn/data/tradedata/future/dailydata/kx{date}.dat",
        "key": "o_curinstrument",
        "prefix": "kx",
    },
    "settlement": {
        "name_cn": "每日结算参数",
        "url": "https://www.shfe.com.cn/data/tradedata/future/dailydata/js{date}.dat",
        "key": "o_cursor",
        "prefix": "js",
    },
    "trade_parameter": {
        "name_cn": "期货交易参数",
        "url": "https://www.shfe.com.cn/data/busiparamdata/future/ContractDailyTradeArgument{date}.dat",
        "key": "ContractDailyTradeArgument",
        "prefix": "ContractDailyTradeArgument",
    },
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
    "Referer": "https://www.shfe.com.cn/",
    "Accept": "application/json,text/plain,*/*",
}


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def weekdays(start: date, end: date) -> list[str]:
    values = []
    current = start
    while current <= end:
        if current.weekday() < 5:
            values.append(current.strftime("%Y%m%d"))
        current += timedelta(days=1)
    return values


def fetch(url: str) -> tuple[int, bytes, str]:
    last_error = ""
    for attempt in range(1, 4):
        try:
            request = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(request, timeout=25) as response:
                return response.status, response.read(), ""
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return 404, exc.read(), f"HTTPError: {exc.reason}"
            last_error = f"attempt={attempt}; HTTPError {exc.code}: {exc.reason}"
        except Exception as exc:
            last_error = f"attempt={attempt}; {type(exc).__name__}: {exc}"
        time.sleep(0.5 * attempt)
    return 0, b"", last_error


def validate(token: str, dataset: str, data: bytes) -> tuple[str, str, int, str, str]:
    try:
        payload = json.loads(data.decode("utf-8-sig"))
    except Exception as exc:
        return "invalid_json_not_saved", "", 0, "", f"{type(exc).__name__}: {exc}"
    spec = DATASETS[dataset]
    records = payload.get(spec["key"])
    report_date = str(payload.get("report_date") or "").replace("-", "")
    if not isinstance(records, list) or not records:
        return "empty_or_nontrading_not_saved", report_date, 0, "", f"missing non-empty {spec['key']}"
    if dataset == "trade_parameter":
        record_dates = {
            str(row.get("TRADINGDAY") or "").replace("-", "")
            for row in records if str(row.get("TRADINGDAY") or "").strip()
        }
        if report_date == token and record_dates == {token}:
            return "valid_saved", report_date, len(records), "payload_report_date_plus_unanimous_record_tradingday", ""
        if not report_date and record_dates == {token}:
            return "valid_saved", token, len(records), "filename_plus_unanimous_record_tradingday", ""
        return "date_mismatch_not_saved", report_date, len(records), "", f"requested={token}; record_dates={sorted(record_dates)}"
    if report_date == token:
        return "valid_saved", report_date, len(records), "payload_report_date", ""
    return "date_mismatch_not_saved", report_date, len(records), "", f"requested={token}; report_date={report_date}"


def download_one(output: Path, token: str, dataset: str) -> dict:
    spec = DATASETS[dataset]
    folder = output / dataset
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{spec['prefix']}{token}.dat"
    url = spec["url"].format(date=token)
    if target.exists():
        data = target.read_bytes()
        status, report_date, rows, basis, error = validate(token, dataset, data)
        if status == "valid_saved":
            return record(token, dataset, url, 200, "valid_reused", report_date, basis, rows, data, target, "")
    http_status, data, request_error = fetch(url)
    if http_status != 200 or not data:
        status = "official_file_not_available" if http_status == 404 else "http_failure_not_saved"
        return record(token, dataset, url, http_status, status, "", "", 0, data, None, request_error)
    status, report_date, rows, basis, validation_error = validate(token, dataset, data)
    saved = None
    if status == "valid_saved":
        temporary = target.with_suffix(".dat.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, target)
        saved = target
    return record(token, dataset, url, http_status, status, report_date, basis, rows, data, saved, validation_error)


def record(token, dataset, url, http_status, validation_status, report_date, basis, rows, data, saved, error):
    return {
        "requested_date": token,
        "dataset": dataset,
        "dataset_cn": DATASETS[dataset]["name_cn"],
        "official_url": url,
        "http_status": http_status,
        "validation_status": validation_status,
        "report_date": report_date,
        "trade_date_basis": basis,
        "row_count": rows,
        "file_bytes": len(data),
        "sha256": sha256(data) if data else "",
        "saved_path": str(saved) if saved else "",
        "error": error,
        "checked_at": now(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and validate an incremental SHFE official-data window.")
    parser.add_argument("--start", default="20260910")
    parser.add_argument("--end", default=date.today().strftime("%Y%m%d"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    start = datetime.strptime(args.start, "%Y%m%d").date()
    end = datetime.strptime(args.end, "%Y%m%d").date()
    tokens = weekdays(start, end)
    args.output.mkdir(parents=True, exist_ok=True)
    jobs = [(token, dataset) for token in tokens for dataset in DATASETS]
    rows = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(download_one, args.output, token, dataset): (token, dataset) for token, dataset in jobs}
        for completed, future in enumerate(as_completed(futures), 1):
            token, dataset = futures[future]
            try:
                rows.append(future.result())
            except Exception as exc:
                spec = DATASETS[dataset]
                rows.append(record(token, dataset, spec["url"].format(date=token), 0, "unhandled_error_not_saved", "", "", 0, b"", None, f"{type(exc).__name__}: {exc}"))
            if completed % 25 == 0 or completed == len(jobs):
                print(f"completed={completed}/{len(jobs)}", flush=True)
    rows.sort(key=lambda item: (item["requested_date"], item["dataset"]))
    manifest_json = args.output / "official_incremental_manifest.json"
    manifest_csv = args.output / "official_incremental_manifest.csv"
    manifest_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with manifest_csv.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    valid = {"valid_saved", "valid_reused"}
    summary = {
        "generated_at": now(),
        "requested_start": args.start,
        "requested_end": args.end,
        "checked_weekdays": len(tokens),
        "records": len(rows),
        "unresolved_count": sum(item["http_status"] == 0 or item["validation_status"] in {"invalid_json_not_saved", "date_mismatch_not_saved", "unhandled_error_not_saved"} for item in rows),
        "datasets": {},
    }
    for dataset in DATASETS:
        subset = [item for item in rows if item["dataset"] == dataset]
        accepted = [item for item in subset if item["validation_status"] in valid]
        summary["datasets"][dataset] = {
            "dataset_cn": DATASETS[dataset]["name_cn"],
            "checked_through": max((item["requested_date"] for item in subset), default=None),
            "last_valid_date": max((item["report_date"] for item in accepted), default=None),
            "valid_date_count": len(accepted),
            "valid_row_count": sum(item["row_count"] for item in accepted),
            "status_counts": dict(Counter(item["validation_status"] for item in subset)),
        }
    (args.output / "official_incremental_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
