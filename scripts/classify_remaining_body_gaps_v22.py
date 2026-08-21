import argparse
import csv
import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path


def classify(title: str, publish_date: str) -> tuple[str, str, str, str]:
    title = title or ""
    if "结算参数" in title and publish_date < "2005-09-01":
        return (
            "official_pre_boundary_gap",
            "high",
            "unrecovered_documented",
            "月度结算参数官方结构化库的已确认起点为2005-09；该公告早于可用边界。",
        )
    if title == "上海期货交易所招标项目需求书—网络规划咨询项目":
        return (
            "archived_legacy_doc_unparsed",
            "low",
            "source_archived_text_unavailable",
            "原始OLE Word文档已归档，但当前环境缺少可靠的旧版DOC中文解析器；与参数事件研究无关。",
        )
    return (
        "obsolete_external_redirect_non_parameter",
        "low",
        "unrecovered_documented",
        "旧站外链或已失效动态页面；标题显示不属于结算、保证金、手续费或涨跌停参数事件。",
    )


def main() -> None:
    project = Path(__file__).resolve().parents[1]
    workspace = project.parent
    default_db = workspace / "SHFE 公告数据库" / "06_公告标签与参数事件数据库_v2.2_工作版_20260820" / "数据库与代码" / "SHFE多维公告标签数据库_v2.2_工作版.sqlite3"
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(default_db))
    parser.add_argument("--csv-out", default=str(project / "01_数据审计" / "剩余空正文缺口分类.csv"))
    parser.add_argument("--json-out", default=str(project / "01_数据审计" / "剩余空正文缺口分类.summary.json"))
    args = parser.parse_args()

    db_path = Path(args.db)
    csv_out = Path(args.csv_out)
    json_out = Path(args.json_out)
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT notice_id,publish_date,title,source_url FROM notices "
        "WHERE trim(coalesce(body_text,''))='' ORDER BY publish_date,notice_id"
    ).fetchall()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS body_gap_classification (
          notice_id TEXT PRIMARY KEY,
          gap_class TEXT NOT NULL,
          research_relevance TEXT NOT NULL,
          resolution_status TEXT NOT NULL,
          rationale TEXT NOT NULL,
          classified_at TEXT NOT NULL,
          FOREIGN KEY(notice_id) REFERENCES notices(notice_id)
        )
        """
    )
    conn.execute("DELETE FROM body_gap_classification")
    output = []
    for row in rows:
        gap_class, relevance, status, rationale = classify(row["title"], row["publish_date"])
        conn.execute(
            "INSERT INTO body_gap_classification VALUES (?,?,?,?,?,?)",
            (row["notice_id"], gap_class, relevance, status, rationale, now),
        )
        output.append({
            "notice_id": row["notice_id"],
            "publish_date": row["publish_date"],
            "title": row["title"],
            "source_url": row["source_url"],
            "gap_class": gap_class,
            "research_relevance": relevance,
            "resolution_status": status,
            "rationale": rationale,
        })
    conn.commit()
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    counts = dict(conn.execute("SELECT gap_class,count(*) FROM body_gap_classification GROUP BY gap_class"))
    relevance_counts = dict(conn.execute("SELECT research_relevance,count(*) FROM body_gap_classification GROUP BY research_relevance"))
    conn.close()

    csv_out.parent.mkdir(parents=True, exist_ok=True)
    with csv_out.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(output[0]) if output else ["notice_id"])
        writer.writeheader()
        writer.writerows(output)
    digest = hashlib.sha256(db_path.read_bytes()).hexdigest()
    summary = {
        "generated_at": now,
        "database": str(db_path),
        "database_sha256": digest,
        "integrity": integrity,
        "remaining_empty_bodies": len(output),
        "gap_class_counts": counts,
        "research_relevance_counts": relevance_counts,
        "interpretation": "空正文均已逐条分类；高相关缺口不得用于参数值估计，低相关缺口不影响参数事件样本构建。",
    }
    json_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
