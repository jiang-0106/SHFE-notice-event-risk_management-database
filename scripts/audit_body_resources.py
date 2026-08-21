import csv
import json
import re
import urllib.parse
from collections import Counter
from datetime import datetime
from pathlib import Path

from bs4 import BeautifulSoup


def read_html(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", errors="replace")


def main() -> None:
    workspace = Path(__file__).resolve().parents[2]
    project = Path(__file__).resolve().parents[1]
    raw_root = workspace / "SHFE 公告数据库" / "00_公共基础库" / "SHFE原始公告数据库_v1.0_20001008-20260811"
    v22_root = workspace / "SHFE 公告数据库" / "06_公告标签与参数事件数据库_v2.2_工作版_20260820"
    notice_rows = list(csv.DictReader((raw_root / "reports" / "notices.csv").open(encoding="utf-8-sig")))
    attachment_rows = list(csv.DictReader((raw_root / "reports" / "attachments.csv").open(encoding="utf-8-sig")))
    tracked = {row["url"] for row in attachment_rows}
    recovered = set()
    manifest = v22_root / "正文补全" / "legacy_body_backfill_manifest.json"
    if manifest.exists():
        recovered = {x["target_url"] for x in json.loads(manifest.read_text(encoding="utf-8")) if x["status"] == "ok"}
    body_manifest = v22_root / "正文资源全库" / "body_resource_download_manifest.json"
    if body_manifest.exists():
        recovered.update(
            x["resource_url"]
            for x in json.loads(body_manifest.read_text(encoding="utf-8"))
            if x["status"] == "ok"
        )
    results = []
    parse_failures = []
    for index, row in enumerate(notice_rows, start=1):
        path = raw_root / row["local_path"]
        if not path.exists():
            parse_failures.append({"url": row["url"], "issue": "missing_detail_file"})
            continue
        try:
            soup = BeautifulSoup(read_html(path), "lxml")
        except Exception as exc:
            parse_failures.append({"url": row["url"], "issue": f"parse_error: {exc}"})
            continue
        container = soup.select_one(".notice_contain")
        if container is None:
            continue
        resources = []
        for image in container.find_all("img", src=True):
            resources.append(("body_image", urllib.parse.urljoin(row["url"], image["src"].strip())))
        for script in container.find_all("script"):
            match = re.search(r'(?is)location\s*=\s*["\']([^"\']+)', script.get_text(" "))
            if match:
                resources.append(("javascript_redirect", urllib.parse.urljoin(row["url"], match.group(1).strip())))
        for kind, resource_url in sorted(set(resources)):
            if resource_url.startswith("data:"):
                coverage_status = "embedded_data_uri"
            elif re.match(r"^[A-Za-z]:[\\/]", resource_url):
                coverage_status = "invalid_source_reference"
            elif resource_url in tracked:
                coverage_status = "tracked"
            elif resource_url in recovered:
                coverage_status = "v22_recovered"
            else:
                coverage_status = "unresolved"
            results.append(
                {
                    "notice_url": row["url"],
                    "notice_id": row["notice_id"],
                    "publish_date": row["publish_date"],
                    "resource_type": kind,
                    "resource_url": resource_url,
                    "tracked_as_attachment": int(resource_url in tracked),
                    "recovered_in_v22": int(resource_url in recovered),
                    "coverage_status": coverage_status,
                }
            )
        if index % 500 == 0 or index == len(notice_rows):
            print(json.dumps({"scan_progress": index, "scan_total": len(notice_rows)}, ensure_ascii=False), flush=True)
    out_csv = project / "01_数据审计" / "正文资源全库审计.csv"
    fields = list(results[0]) if results else []
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(results)
    counts = Counter(x["coverage_status"] for x in results)
    types = Counter(x["resource_type"] for x in results)
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "notices_scanned": len(notice_rows),
        "body_resources": len(results),
        "resource_type_counts": dict(types),
        "coverage_counts": dict(counts),
        "unresolved": sum(x["coverage_status"] == "unresolved" for x in results),
        "parse_failures": len(parse_failures),
        "parse_failure_samples": parse_failures[:20],
        "catalog": str(out_csv.resolve()),
    }
    out_json = project / "01_数据审计" / "正文资源全库审计.summary.json"
    out_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
