import argparse
import csv
import hashlib
import json
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path


def connect_copy(path: Path, temp_root: Path, name: str) -> sqlite3.Connection:
    copied = temp_root / name
    shutil.copy2(path, copied)
    conn = sqlite3.connect(copied)
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def file_check(root: Path, rows, full_hash: bool) -> list[dict]:
    issues = []
    total = len(rows)
    for index, (kind, url, relative_path, expected_hash, expected_size) in enumerate(rows, start=1):
        if not relative_path:
            issues.append({"kind": kind, "url": url, "issue": "missing_local_path"})
            continue
        path = root / relative_path
        if not path.exists():
            issues.append({"kind": kind, "url": url, "issue": "missing_file", "path": str(path)})
            continue
        if expected_size is not None and path.stat().st_size != expected_size:
            issues.append({"kind": kind, "url": url, "issue": "size_mismatch", "path": str(path)})
        if full_hash and expected_hash:
            hasher = hashlib.sha256()
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    hasher.update(chunk)
            digest = hasher.hexdigest()
            if digest != expected_hash:
                issues.append({"kind": kind, "url": url, "issue": "hash_mismatch", "path": str(path)})
        if full_hash and (index % 500 == 0 or index == total):
            print(json.dumps({"hash_progress": index, "hash_total": total}, ensure_ascii=False), flush=True)
    return issues


def main() -> None:
    workspace = Path(__file__).resolve().parents[2]
    project = Path(__file__).resolve().parents[1]
    default_raw = workspace / "SHFE 公告数据库" / "00_公共基础库" / "SHFE原始公告数据库_v1.0_20001008-20260811"
    default_tagged = workspace / "SHFE 公告数据库" / "06_公告标签与参数事件数据库_v2.2_工作版_20260820" / "数据库与代码" / "SHFE多维公告标签数据库_v2.2_工作版.sqlite3"
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", default=str(default_raw))
    parser.add_argument("--tagged-db", default=str(default_tagged))
    default_out = project / "01_数据审计" / "v22_completeness_gate.json"
    parser.add_argument("--out", default=str(default_out))
    parser.add_argument("--full-hash", action="store_true")
    args = parser.parse_args()
    raw_root = Path(args.raw_root)
    tagged_db = Path(args.tagged_db)
    out = Path(args.out)
    if args.full_hash and out.resolve() == default_out.resolve():
        out = project / "01_数据审计" / "v22_completeness_gate_full_hash.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    issues = []
    warnings = []

    with tempfile.TemporaryDirectory(prefix="shfe_gate_") as tmp:
        temp_root = Path(tmp)
        raw = connect_copy(raw_root / "archive.sqlite3", temp_root, "raw.sqlite3")
        raw.row_factory = sqlite3.Row
        raw_integrity = raw.execute("PRAGMA integrity_check").fetchone()[0]
        catalog_rows = list(csv.DictReader((raw_root / "reports" / "api_catalog.csv").open(encoding="utf-8-sig")))
        catalog_urls = {x["url"] for x in catalog_rows}
        db_urls = {x[0] for x in raw.execute("SELECT url FROM notices")}
        missing_from_db = sorted(catalog_urls - db_urls)
        absent_from_catalog = sorted(db_urls - catalog_urls)
        if missing_from_db:
            issues.append({"check": "catalog_to_database", "count": len(missing_from_db), "samples": missing_from_db[:20]})
        if absent_from_catalog:
            warnings.append({"check": "database_not_in_latest_catalog", "count": len(absent_from_catalog), "samples": absent_from_catalog[:20]})
        notice_ok = raw.execute("SELECT count(*) FROM notices WHERE download_status='ok'").fetchone()[0]
        notice_failed = raw.execute("SELECT count(*) FROM notices WHERE download_status!='ok'").fetchone()[0]
        attachment_ok = raw.execute("SELECT count(*) FROM attachments WHERE download_status='ok'").fetchone()[0]
        attachment_failed = raw.execute("SELECT count(*) FROM attachments WHERE download_status!='ok'").fetchone()[0]
        rows = []
        rows.extend(("notice", *x) for x in raw.execute("SELECT url,local_path,sha256,NULL FROM notices WHERE download_status='ok'"))
        rows.extend(("attachment", *x) for x in raw.execute("SELECT url,local_path,sha256,size FROM attachments WHERE download_status='ok'"))
        local_issues = file_check(raw_root, rows, args.full_hash)
        issues.extend(local_issues)
        failed_sources = [dict(x) for x in raw.execute("SELECT 'notice' kind,url,http_status,error FROM notices WHERE download_status!='ok' UNION ALL SELECT 'attachment',url,http_status,error FROM attachments WHERE download_status!='ok'")]
        if failed_sources:
            warnings.append({"check": "documented_source_failures", "count": len(failed_sources), "samples": failed_sources[:20]})

        tagged = connect_copy(tagged_db, temp_root, "tagged.sqlite3")
        tagged.row_factory = sqlite3.Row
        tagged_integrity = tagged.execute("PRAGMA integrity_check").fetchone()[0]
        notices = tagged.execute("SELECT count(*) FROM notices").fetchone()[0]
        duplicate_notice_ids = tagged.execute("SELECT count(*) FROM (SELECT notice_id FROM notices GROUP BY notice_id HAVING count(*)>1)").fetchone()[0]
        duplicate_source_urls = tagged.execute("SELECT count(*) FROM (SELECT source_url FROM notices GROUP BY source_url HAVING count(*)>1)").fetchone()[0]
        empty_bodies = tagged.execute("SELECT count(*) FROM notices WHERE trim(coalesce(body_text,''))='' ").fetchone()[0]
        events = tagged.execute("SELECT count(*) FROM parameter_events").fetchone()[0]
        duplicate_event_ids = tagged.execute("SELECT count(*) FROM (SELECT event_id FROM parameter_events GROUP BY event_id HAVING count(*)>1)").fetchone()[0]
        research_ready = tagged.execute("SELECT count(*) FROM v_event_research_ready").fetchone()[0]
        recovery = tagged.execute("SELECT count(*),sum(applied_to_body_text) FROM body_recovery").fetchone()
        body_resources = dict(tagged.execute("SELECT coverage_status,count(*) FROM notice_body_resources GROUP BY coverage_status"))
        body_text_provenance = dict(tagged.execute("SELECT method,count(*) FROM body_text_provenance GROUP BY method"))
        gap_table_exists = tagged.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='body_gap_classification'").fetchone()[0]
        body_gap_classification = dict(tagged.execute("SELECT gap_class,count(*) FROM body_gap_classification GROUP BY gap_class")) if gap_table_exists else {}
        classified_empty_bodies = tagged.execute("SELECT count(*) FROM body_gap_classification").fetchone()[0] if gap_table_exists else 0
        if duplicate_notice_ids or duplicate_source_urls or duplicate_event_ids:
            issues.append({"check": "duplicate_keys", "notice_ids": duplicate_notice_ids, "source_urls": duplicate_source_urls, "event_ids": duplicate_event_ids})
        if empty_bodies:
            warnings.append({"check": "remaining_empty_bodies", "count": empty_bodies, "classified": classified_empty_bodies})
        if empty_bodies != classified_empty_bodies:
            warnings.append({"check": "empty_body_classification_parity", "empty_bodies": empty_bodies, "classified": classified_empty_bodies})
        if research_ready == 0:
            warnings.append({"check": "research_ready_events", "count": 0, "note": "Manual validation not yet completed"})
        if body_resources.get("unresolved", 0):
            warnings.append({"check": "unresolved_body_resources", "count": body_resources["unresolved"]})
        if body_resources.get("invalid_source_reference", 0):
            warnings.append({"check": "invalid_source_body_references", "count": body_resources["invalid_source_reference"]})
        raw.close()
        tagged.close()

    hard_fail = bool(issues) or raw_integrity != "ok" or tagged_integrity != "ok" or notices != notice_ok
    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": "full_hash" if args.full_hash else "quick",
        "status": "FAIL" if hard_fail else ("PASS_WITH_DOCUMENTED_GAPS" if warnings else "PASS"),
        "raw_archive": {
            "integrity": raw_integrity,
            "catalog_unique_urls": len(catalog_urls),
            "database_notice_urls": len(db_urls),
            "notices_ok": notice_ok,
            "notices_failed": notice_failed,
            "attachments_ok": attachment_ok,
            "attachments_failed": attachment_failed,
            "local_files_checked": len(rows),
        },
        "tagged_database": {
            "integrity": tagged_integrity,
            "notices": notices,
            "events": events,
            "empty_bodies": empty_bodies,
            "research_ready_events": research_ready,
            "body_recovery_records": recovery[0],
            "body_recoveries_applied": recovery[1] or 0,
            "body_resource_coverage": body_resources,
            "body_text_provenance": body_text_provenance,
            "classified_empty_bodies": classified_empty_bodies,
            "body_gap_classification": body_gap_classification,
        },
        "issues": issues,
        "warnings": warnings,
    }
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(1 if hard_fail else 0)


if __name__ == "__main__":
    main()
