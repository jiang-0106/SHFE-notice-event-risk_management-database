import csv
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup


def decode_html(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def extract_body(path: Path) -> tuple[str, str]:
    soup = BeautifulSoup(decode_html(path), "html.parser")
    node = None
    selector_used = ""
    for selector in (
        ".notice_contain",
        ".article-detail-text",
        ".article-content",
        ".content-detail",
        "article",
    ):
        node = soup.select_one(selector)
        if node is not None:
            selector_used = selector
            break
    if node is None:
        generator = soup.find("meta", attrs={"name": "Generator"})
        generator_value = generator.get("content", "") if generator else ""
        table_cells = len(soup.find_all(["td", "th"]))
        if soup.body is not None and ("Microsoft Excel" in generator_value or table_cells >= 10):
            node = soup.body
            selector_used = "body[spreadsheet_or_table_fallback]"
    if node is None:
        return "", "no_supported_selector"
    for unwanted in node.select("script,style,noscript"):
        unwanted.decompose()
    text = "\n".join(line.strip() for line in node.get_text("\n").splitlines() if line.strip())
    return text, selector_used


def main() -> None:
    workspace = Path(__file__).resolve().parents[2]
    project = Path(__file__).resolve().parents[1]
    source_db = (
        workspace
        / "SHFE 公告数据库"
        / "04_公告标签与参数事件数据库_v2.1_正式版_20260817"
        / "数据库与代码"
        / "SHFE多维公告标签数据库_正式版.sqlite3"
    )
    v22_root = (
        workspace
        / "SHFE 公告数据库"
        / "06_公告标签与参数事件数据库_v2.2_工作版_20260820"
    )
    manifest_path = v22_root / "正文补全" / "legacy_body_backfill_manifest.json"
    audit_path = project / "01_数据审计" / "空正文逐条审计.csv"
    output_db = v22_root / "数据库与代码" / "SHFE多维公告标签数据库_v2.2_工作版.sqlite3"
    output_db.parent.mkdir(parents=True, exist_ok=True)
    stage_db = workspace / "v22_build_work.sqlite3"
    shutil.copy2(source_db, stage_db)

    audit = {row["notice_id"]: row for row in csv.DictReader(audit_path.open(encoding="utf-8-sig"))}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recovered = {}
    records = []
    for item in manifest:
        notice_id = item["notice_id"]
        record = {
            "notice_id": notice_id,
            "source_notice_url": item["source_notice_url"],
            "recovery_url": item["target_url"],
            "recovery_status": item["status"],
            "http_status": item["http_status"],
            "local_path": item["local_path"],
            "sha256": item["sha256"],
            "content_kind": None,
            "selector_used": None,
            "recovered_text_chars": 0,
            "applied_to_body_text": 0,
            "note": item["error"],
        }
        if item["status"] == "ok" and item["local_path"]:
            path = Path(item["local_path"])
            suffix = path.suffix.lower()
            if suffix in {".html", ".htm"}:
                text, selector = extract_body(path)
                record["content_kind"] = "html"
                record["selector_used"] = selector
                record["recovered_text_chars"] = len(text)
                if len(text) >= 40:
                    recovered[notice_id] = text
                    record["applied_to_body_text"] = 1
                else:
                    record["note"] = "HTML retrieved but supported body selector yielded insufficient text"
            elif suffix in {".gif", ".jpg", ".jpeg", ".png"}:
                record["content_kind"] = "image"
                record["note"] = "Source body image archived; OCR still required"
            elif suffix in {".doc", ".docx", ".pdf"}:
                record["content_kind"] = "document"
                record["note"] = "Source document archived; document text extraction still required"
            else:
                record["content_kind"] = "binary"
        records.append(record)

    conn = sqlite3.connect(stage_db)
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS body_recovery(
          notice_id TEXT PRIMARY KEY,
          source_notice_url TEXT,
          recovery_url TEXT,
          recovery_status TEXT,
          http_status INTEGER,
          local_path TEXT,
          sha256 TEXT,
          content_kind TEXT,
          selector_used TEXT,
          recovered_text_chars INTEGER,
          applied_to_body_text INTEGER,
          note TEXT,
          recovered_at TEXT
        )
        """
    )
    recovered_at = datetime.now().astimezone().isoformat(timespec="seconds")
    for record in records:
        conn.execute(
            """INSERT OR REPLACE INTO body_recovery VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (*record.values(), recovered_at),
        )
    for notice_id, text in recovered.items():
        conn.execute(
            "UPDATE notices SET body_text=? WHERE notice_id=? AND trim(coalesce(body_text,''))=''",
            (text, notice_id),
        )
    conn.commit()
    remaining_empty = conn.execute(
        "SELECT count(*) FROM notices WHERE trim(coalesce(body_text,''))=''"
    ).fetchone()[0]
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    applied = conn.execute("SELECT count(*) FROM body_recovery WHERE applied_to_body_text=1").fetchone()[0]
    conn.close()
    shutil.copy2(stage_db, output_db)
    output_hash = hashlib.sha256(output_db.read_bytes()).hexdigest()
    summary = {
        "generated_at": recovered_at,
        "source_version": "v2.1_20260817",
        "empty_body_baseline": len(audit),
        "retrieval_ok": sum(x["status"] == "ok" for x in manifest),
        "retrieval_failed": sum(x["status"] != "ok" for x in manifest),
        "html_bodies_applied": applied,
        "remaining_empty_bodies": remaining_empty,
        "database_integrity": integrity,
        "database_sha256": output_hash,
        "output_database": str(output_db.resolve()),
    }
    (v22_root / "正文补全" / "v22_body_recovery_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
