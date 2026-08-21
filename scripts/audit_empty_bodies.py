import argparse
import csv
import json
import re
import sqlite3
from html import unescape
from pathlib import Path


def visible_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript).*?>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def classify(row: sqlite3.Row) -> dict:
    path = Path(row["local_path"])
    result = dict(row)
    result.update(
        file_exists=path.exists(),
        file_bytes=path.stat().st_size if path.exists() else 0,
        html_visible_chars=0,
        body_container_text_chars=0,
        body_container_image_count=0,
        body_container_image_refs="",
        body_container_redirect_url="",
        page_has_title=False,
        likely_reason="missing_local_file",
    )
    if not path.exists():
        return result
    raw = path.read_bytes()
    for encoding in ("utf-8", "gb18030", "utf-8-sig"):
        try:
            html = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        html = raw.decode("utf-8", errors="replace")
    text = visible_text(html)
    container_match = re.search(
        r'(?is)<div[^>]+class=["\'][^"\']*notice_contain[^"\']*["\'][^>]*>(.*?)</div>',
        html,
    )
    container_html = container_match.group(1) if container_match else ""
    container_text = visible_text(container_html)
    image_refs = re.findall(r'(?is)<img[^>]+src=["\']?([^"\'\s>]+)', container_html)
    redirect_match = re.search(r'(?is)location\s*=\s*["\']([^"\']+)', container_html)
    result["html_visible_chars"] = len(text)
    result["body_container_text_chars"] = len(container_text)
    result["body_container_image_count"] = len(image_refs)
    result["body_container_image_refs"] = "|".join(image_refs)
    result["body_container_redirect_url"] = redirect_match.group(1) if redirect_match else ""
    title = (row["title"] or "").strip()
    title_key = re.sub(r"\s+", "", title)[:20]
    result["page_has_title"] = bool(title_key and title_key in re.sub(r"\s+", "", text))
    lower = html.lower()
    if redirect_match:
        result["likely_reason"] = "legacy_javascript_redirect_not_followed"
    elif image_refs and len(container_text) < 40:
        result["likely_reason"] = "image_only_body_not_archived_as_attachment"
    elif len(text) < 80:
        result["likely_reason"] = "source_page_nearly_empty"
    elif "waf" in lower or "访问验证" in text or "验证码" in text:
        result["likely_reason"] = "blocked_or_challenge_page"
    elif result["page_has_title"]:
        result["likely_reason"] = "parser_selector_missed_content"
    else:
        result["likely_reason"] = "page_structure_or_metadata_mismatch"
    return result


def main() -> None:
    workspace = Path(__file__).resolve().parents[2]
    default_db = workspace / "SHFE 公告数据库" / "04_公告标签与参数事件数据库_v2.1_正式版_20260817" / "数据库与代码" / "SHFE多维公告标签数据库_正式版.sqlite3"
    default_out = Path(__file__).resolve().parents[1] / "01_数据审计" / "空正文逐条审计.csv"
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(default_db))
    parser.add_argument("--out", default=str(default_out))
    args = parser.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    db_path = Path(args.db).resolve()
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT n.notice_id,n.publish_date,n.title,n.source_url,n.local_path,
               COUNT(DISTINCT a.url) AS attachment_count
        FROM notices n
        LEFT JOIN attachments a ON a.notice_url=n.source_url
        WHERE trim(coalesce(n.body_text,''))=''
        GROUP BY n.notice_id
        ORDER BY n.publish_date,n.notice_id
        """
    ).fetchall()
    audited = [classify(row) for row in rows]
    fields = list(audited[0]) if audited else []
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(audited)
    summary = {
        "empty_body_records": len(audited),
        "file_missing": sum(not x["file_exists"] for x in audited),
        "with_attachments": sum(int(x["attachment_count"] or 0) > 0 for x in audited),
        "reason_counts": {},
    }
    for item in audited:
        reason = item["likely_reason"]
        summary["reason_counts"][reason] = summary["reason_counts"].get(reason, 0) + 1
    summary_path = out.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
