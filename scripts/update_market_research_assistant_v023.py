from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = Path(
    os.environ.get(
        "SHFE_RESEARCH_ASSISTANT_DB",
        r"E:\AAAAAAAAAAAAAAAAA\SW\SHFE\outputs\SHFE市场研究助手_v0.22_20261018"
        r"\SHFE公告参数市场研究助手_v0.22.sqlite3",
    )
)


def latest_complete_source_date(database: Path) -> str:
    connection = sqlite3.connect(database)
    try:
        values = []
        for table in ("market_contract_daily", "settlement_parameter_daily", "official_trade_parameter_daily"):
            if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                raise RuntimeError(f"缺少增量更新所需数据表：{table}")
            values.append(connection.execute(f"SELECT MAX(trade_date) FROM {table}").fetchone()[0])
    finally:
        connection.close()
    if not all(values):
        raise RuntimeError("至少一个官方数据源没有有效日期")
    return min(values)


def command_text(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


def main() -> None:
    parser = argparse.ArgumentParser(description="Safely update SHFE official daily data and rebuild the research assistant.")
    parser.add_argument("--source-db", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--through", default=date.today().strftime("%Y%m%d"))
    parser.add_argument("--lookback-days", type=int, default=3)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--artifact-tag", default="v024")
    parser.add_argument("--release-version", default="v0.24-bidirectional-completeness-audit")
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--resume", action="store_true", help="Reuse a completed integrated database after an interrupted build.")
    args = parser.parse_args()

    source = args.source_db.resolve()
    output = args.output_dir.resolve()
    if not source.is_file():
        raise SystemExit(f"Source database not found: {source}")
    through = datetime.strptime(args.through, "%Y%m%d").date()
    latest_complete = datetime.strptime(latest_complete_source_date(source), "%Y%m%d").date()
    start = latest_complete + timedelta(days=1) - timedelta(days=max(0, args.lookback_days))
    if start > through:
        print(json.dumps({"status": "already_current_for_requested_date", "latest_complete": latest_complete.strftime("%Y%m%d"),
                          "requested_through": args.through}, ensure_ascii=False, indent=2))
        return

    raw = output / "official_incremental_raw"
    manifest = raw / "official_incremental_manifest.json"
    dotted_tag = args.artifact_tag.replace("v0", "v0.") if args.artifact_tag.startswith("v0") and "." not in args.artifact_tag else args.artifact_tag
    integrated = output / f"SHFE公告参数市场同步数据库_增量_{dotted_tag}.sqlite3"
    assistant = output / f"SHFE公告参数市场研究助手_{dotted_tag}.sqlite3"
    if not args.plan_only and assistant.exists():
        raise SystemExit("目标研究助手数据库已存在。为避免覆盖，请换一个新的输出目录。")
    if not args.plan_only and integrated.exists() and not args.resume:
        raise SystemExit("已存在增量整合数据库。如需从中断处继续，请增加 --resume；否则换一个输出目录。")

    download = [sys.executable, str(ROOT / "scripts" / "download_shfe_incremental_v017.py"),
                "--start", start.strftime("%Y%m%d"), "--end", args.through,
                "--output", str(raw), "--workers", str(args.workers)]
    integrate = [sys.executable, str(ROOT / "scripts" / "integrate_shfe_incremental_v017.py"),
                 "--source-db", str(source), "--manifest", str(manifest), "--output-db", str(integrated)]
    build = [sys.executable, str(ROOT / "scripts" / "build_market_research_assistant_v016.py"),
             "--source-db", str(integrated), "--output-dir", str(output),
             "--build-date", through.isoformat(), "--version", args.release_version,
             "--artifact-tag", args.artifact_tag]
    plan = {
        "status": "plan_only" if args.plan_only else "running",
        "source_database": str(source), "source_latest_complete_date": latest_complete.strftime("%Y%m%d"),
        "download_start": start.strftime("%Y%m%d"), "download_end": args.through,
        "output_directory": str(output),
        "commands": [command_text(download), command_text(integrate), command_text(build)],
        "safety": "never_overwrite_source_or_existing_target_database",
        "notice_limit": "本流程更新行情、结算参数和交易参数；公告正文仍需独立核验后录入。",
    }
    if args.plan_only:
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return

    output.mkdir(parents=True, exist_ok=True)
    (output / "incremental_update_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    commands_to_run = (build,) if args.resume and integrated.exists() else (download, integrate, build)
    for command in commands_to_run:
        subprocess.run(command, cwd=ROOT, check=True)
    result = {
        **plan, "status": "completed", "completed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "assistant_database": str(assistant),
    }
    (output / "incremental_update_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
