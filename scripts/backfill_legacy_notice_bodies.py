import argparse
import csv
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path


def main() -> None:
    workspace = Path(__file__).resolve().parents[2]
    project = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit", default=str(project / "01_数据审计" / "空正文逐条审计.csv"))
    parser.add_argument(
        "--out",
        default=str(
            workspace
            / "SHFE 公告数据库"
            / "06_公告标签与参数事件数据库_v2.2_工作版_20260820"
            / "正文补全"
        ),
    )
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(Path(args.audit).open(encoding="utf-8-sig")))
    results = []
    if args.limit:
        rows = rows[: args.limit]
    for row in rows:
        reason = row["likely_reason"]
        if reason == "image_only_body_not_archived_as_attachment":
            refs = [x for x in row["body_container_image_refs"].split("|") if x]
            urls = [urllib.parse.urljoin(row["source_url"], ref) for ref in refs]
        elif reason == "legacy_javascript_redirect_not_followed":
            urls = [urllib.parse.urljoin(row["source_url"], row["body_container_redirect_url"])]
        else:
            urls = []
        for index, url in enumerate(urls, start=1):
            item = {
                "notice_id": row["notice_id"],
                "publish_date": row["publish_date"],
                "reason": reason,
                "source_notice_url": row["source_url"],
                "target_url": url,
                "retrieved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "status": "failed",
                "http_status": None,
                "final_url": None,
                "local_path": None,
                "bytes": 0,
                "sha256": None,
                "error": None,
            }
            try:
                request = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 SHFE-NoticeEvent-research-archive/2.2"},
                )
                with urllib.request.urlopen(request, timeout=args.timeout) as response:
                    data = response.read()
                    final_url = response.geturl()
                    status = getattr(response, "status", 200)
                    content_type = response.headers.get_content_type()
                suffix = Path(urllib.parse.urlparse(final_url).path).suffix.lower()
                if not suffix:
                    suffix = {"text/html": ".html", "image/gif": ".gif", "image/jpeg": ".jpg", "image/png": ".png"}.get(content_type, ".bin")
                target_dir = out / row["publish_date"][:4] / row["notice_id"]
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / f"body_source_{index}{suffix}"
                target.write_bytes(data)
                item.update(
                    status="ok",
                    http_status=status,
                    final_url=final_url,
                    local_path=str(target.resolve()),
                    bytes=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                )
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError) as exc:
                item["error"] = f"{type(exc).__name__}: {exc}"
                if isinstance(exc, urllib.error.HTTPError):
                    item["http_status"] = exc.code
            results.append(item)
            time.sleep(args.delay)
    manifest = out / "legacy_body_backfill_manifest.json"
    manifest.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "attempted": len(results),
        "ok": sum(x["status"] == "ok" for x in results),
        "failed": sum(x["status"] != "ok" for x in results),
        "manifest": str(manifest.resolve()),
    }
    (out / "legacy_body_backfill_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
