import csv
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def structured_month_text(files: list[Path]) -> str:
    sections = []
    for path in sorted(files):
        rows = list(csv.DictReader(path.open(encoding="utf-8-sig")))
        lines = []
        for row in rows:
            cells = [row.get(f"column_{i}", "").strip() for i in range(1, 30)]
            cells = [x for x in cells if x]
            if cells:
                lines.append("\t".join(cells))
        if lines:
            sections.append("\n".join(lines))
    return "\n\n".join(sections)


def main() -> None:
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    workspace = Path(__file__).resolve().parents[2]
    project = Path(__file__).resolve().parents[1]
    v22_root = workspace / "SHFE 公告数据库" / "06_公告标签与参数事件数据库_v2.2_工作版_20260820"
    database = v22_root / "数据库与代码" / "SHFE多维公告标签数据库_v2.2_工作版.sqlite3"
    ocr_path = v22_root / "正文补全" / "body_image_ocr_results.json"
    monthly_root = workspace / "SHFE 期货数据库" / "01_正式数据库" / "按业务主题数据库" / "03_月度结算参数调整表_202606向前" / "structured"
    stage = workspace / "v22_text_integration.sqlite3"
    shutil.copy2(database, stage)
    conn = sqlite3.connect(stage)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS body_text_provenance(
          notice_id TEXT NOT NULL,
          method TEXT NOT NULL,
          source_paths TEXT NOT NULL,
          source_sha256 TEXT NOT NULL,
          text_chars INTEGER NOT NULL,
          confidence TEXT NOT NULL,
          requires_manual_review INTEGER NOT NULL,
          applied_to_body_text INTEGER NOT NULL,
          note TEXT,
          processed_at TEXT NOT NULL,
          PRIMARY KEY(notice_id,method),
          FOREIGN KEY(notice_id) REFERENCES notices(notice_id)
        )
        """
    )
    processed_at = datetime.now().astimezone().isoformat(timespec="seconds")
    applied_ocr = 0
    ocr_results = json.loads(ocr_path.read_text(encoding="utf-8-sig"))
    for item in ocr_results:
        text = (item.get("ocr_text") or "").strip()
        if not text:
            continue
        source = Path(item["image_path"])
        conn.execute(
            """INSERT OR REPLACE INTO body_text_provenance VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                item["notice_id"],
                "windows_ocr_zh_hans",
                json.dumps([str(source.resolve())], ensure_ascii=False),
                item["image_sha256"],
                len(text),
                "unverified_ocr",
                1,
                1,
                "OCR text is searchable but numeric fields require manual comparison with the image.",
                processed_at,
            ),
        )
        changed = conn.execute(
            "UPDATE notices SET body_text=? WHERE notice_id=? AND trim(coalesce(body_text,''))=''",
            (text, item["notice_id"]),
        ).rowcount
        applied_ocr += changed
        conn.execute(
            "UPDATE body_recovery SET recovered_text_chars=?,applied_to_body_text=1,note=? WHERE notice_id=?",
            (len(text), "Source body image archived and OCR applied; manual review required", item["notice_id"]),
        )

    applied_alternative = 0
    alternative_notices = []
    empty = conn.execute(
        "SELECT notice_id,title FROM notices WHERE trim(coalesce(body_text,''))=''"
    ).fetchall()
    for row in empty:
        match = re.search(r"(20\d{2})\s*年\s*(\d{1,2})\s*月", row["title"] or "")
        if not match:
            continue
        period = f"{match.group(1)}{int(match.group(2)):02d}"
        folder = monthly_root / period[:4]
        files = sorted(folder.glob(f"monthly_settlement_source_{period}_*.csv")) if folder.exists() else []
        if not files:
            continue
        text = structured_month_text(files)
        if not text:
            continue
        combined_hash = hashlib.sha256("".join(file_hash(x) for x in files).encode()).hexdigest()
        source_paths = [str(x.resolve()) for x in files]
        conn.execute(
            """INSERT OR REPLACE INTO body_text_provenance VALUES(?,?,?,?,?,?,?,?,?,?)""",
            (
                row["notice_id"],
                "official_parallel_monthly_dataset",
                json.dumps(source_paths, ensure_ascii=False),
                combined_hash,
                len(text),
                "high_period_match_requires_record_review",
                1,
                1,
                f"Matched by notice title to official monthly settlement dataset period {period}; not a byte-identical recovery of the original redirect target.",
                processed_at,
            ),
        )
        changed = conn.execute(
            "UPDATE notices SET body_text=? WHERE notice_id=? AND trim(coalesce(body_text,''))=''",
            (text, row["notice_id"]),
        ).rowcount
        applied_alternative += changed
        alternative_notices.append({"notice_id": row["notice_id"], "period": period, "files": len(files), "text_chars": len(text)})

    conn.commit()
    remaining = conn.execute("SELECT count(*) FROM notices WHERE trim(coalesce(body_text,''))='' ").fetchone()[0]
    provenance = conn.execute("SELECT count(*) FROM body_text_provenance").fetchone()[0]
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    conn.close()
    shutil.copy2(stage, database)
    stage.unlink()
    digest = file_hash(database)
    summary = {
        "generated_at": processed_at,
        "ocr_records_applied": applied_ocr,
        "official_parallel_dataset_records_applied": applied_alternative,
        "alternative_notices": alternative_notices,
        "body_text_provenance_records": provenance,
        "remaining_empty_bodies": remaining,
        "database_integrity": integrity,
        "database_sha256": digest,
    }
    (v22_root / "正文补全" / "ocr_and_alternative_integration_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
