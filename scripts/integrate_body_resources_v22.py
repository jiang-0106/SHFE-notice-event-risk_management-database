import csv
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


def main() -> None:
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    workspace = Path(__file__).resolve().parents[2]
    project = Path(__file__).resolve().parents[1]
    v22_root = workspace / "SHFE 公告数据库" / "06_公告标签与参数事件数据库_v2.2_工作版_20260820"
    database = v22_root / "数据库与代码" / "SHFE多维公告标签数据库_v2.2_工作版.sqlite3"
    catalog = project / "01_数据审计" / "正文资源全库审计.csv"
    download_manifest = v22_root / "正文资源全库" / "body_resource_download_manifest.json"
    downloads = {
        x["resource_url"]: x
        for x in json.loads(download_manifest.read_text(encoding="utf-8"))
    }
    rows = list(csv.DictReader(catalog.open(encoding="utf-8-sig")))
    stage = workspace / "v22_resource_integration.sqlite3"
    shutil.copy2(database, stage)
    conn = sqlite3.connect(stage)
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("DROP TABLE IF EXISTS notice_body_resources")
    conn.execute(
        """
        CREATE TABLE notice_body_resources(
          notice_id TEXT NOT NULL,
          resource_url TEXT NOT NULL,
          resource_type TEXT NOT NULL,
          coverage_status TEXT NOT NULL,
          http_status INTEGER,
          final_url TEXT,
          content_type TEXT,
          local_path TEXT,
          bytes INTEGER,
          sha256 TEXT,
          error TEXT,
          audited_at TEXT NOT NULL,
          PRIMARY KEY(notice_id,resource_url,resource_type),
          FOREIGN KEY(notice_id) REFERENCES notices(notice_id)
        )
        """
    )
    conn.execute("CREATE INDEX ix_body_resources_status ON notice_body_resources(coverage_status,resource_type)")
    audited_at = datetime.now().astimezone().isoformat(timespec="seconds")
    for row in rows:
        download = downloads.get(row["resource_url"], {})
        conn.execute(
            """INSERT INTO notice_body_resources VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                row["notice_id"],
                row["resource_url"],
                row["resource_type"],
                row["coverage_status"],
                download.get("http_status"),
                download.get("final_url"),
                download.get("content_type"),
                download.get("local_path"),
                download.get("bytes"),
                download.get("sha256"),
                download.get("error"),
                audited_at,
            ),
        )
    conn.commit()
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    counts = dict(conn.execute("SELECT coverage_status,count(*) FROM notice_body_resources GROUP BY coverage_status"))
    total = conn.execute("SELECT count(*) FROM notice_body_resources").fetchone()[0]
    conn.close()
    shutil.copy2(stage, database)
    stage.unlink()
    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    summary = {
        "generated_at": audited_at,
        "database_integrity": integrity,
        "body_resource_records": total,
        "coverage_counts": counts,
        "database_sha256": digest,
        "database": str(database.resolve()),
    }
    (v22_root / "正文资源全库" / "body_resource_database_integration.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
