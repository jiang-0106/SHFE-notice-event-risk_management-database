import csv
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


UA = "Mozilla/5.0 SHFE-NoticeEvent-research-archive/2.2"


def fetch(url: str, timeout: float, retries: int) -> dict:
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/*,text/html,*/*;q=0.8"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read()
                return {
                    "status": "ok",
                    "http_status": getattr(response, "status", 200),
                    "final_url": response.geturl(),
                    "content_type": response.headers.get_content_type(),
                    "data": data,
                    "error": None,
                }
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            last_error = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code in {400, 401, 403, 404, 410}:
                break
            time.sleep(min(attempt * 0.5, 2.0))
    return {
        "status": "failed",
        "http_status": last_error.code if isinstance(last_error, urllib.error.HTTPError) else None,
        "final_url": None,
        "content_type": None,
        "data": None,
        "error": f"{type(last_error).__name__}: {last_error}" if last_error else "unknown error",
    }


def main() -> None:
    csv.field_size_limit(min(sys.maxsize, 2**31 - 1))
    workspace = Path(__file__).resolve().parents[2]
    project = Path(__file__).resolve().parents[1]
    catalog = project / "01_数据审计" / "正文资源全库审计.csv"
    out = workspace / "SHFE 公告数据库" / "06_公告标签与参数事件数据库_v2.2_工作版_20260820" / "正文资源全库"
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(catalog.open(encoding="utf-8-sig")))
    unresolved = [x for x in rows if x["coverage_status"] == "unresolved"]
    valid_urls = sorted(
        {
            x["resource_url"]
            for x in unresolved
            if urllib.parse.urlparse(x["resource_url"]).scheme.lower() in {"http", "https"}
        }
    )
    invalid_urls = sorted({x["resource_url"] for x in unresolved} - set(valid_urls))
    previous_path = out / "body_resource_download_manifest.json"
    previous = {}
    if previous_path.exists():
        previous = {x["resource_url"]: x for x in json.loads(previous_path.read_text(encoding="utf-8"))}
    results = {}
    pending = []
    for url in valid_urls:
        old = previous.get(url)
        if old and old.get("status") == "ok" and old.get("local_path") and Path(old["local_path"]).exists():
            results[url] = old
        else:
            pending.append(url)
    print(json.dumps({"unique_urls": len(valid_urls), "resumed_ok": len(results), "pending": len(pending), "invalid_urls": len(invalid_urls)}, ensure_ascii=False), flush=True)
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fetch, url, 25.0, 3): url for url in pending}
        for index, future in enumerate(as_completed(futures), start=1):
            url = futures[future]
            fetched = future.result()
            record = {
                "resource_url": url,
                "retrieved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "status": fetched["status"],
                "http_status": fetched["http_status"],
                "final_url": fetched["final_url"],
                "content_type": fetched["content_type"],
                "local_path": None,
                "bytes": 0,
                "sha256": None,
                "error": fetched["error"],
            }
            if fetched["status"] == "ok":
                data = fetched["data"]
                digest = hashlib.sha256(data).hexdigest()
                suffix = Path(urllib.parse.urlparse(fetched["final_url"]).path).suffix.lower()
                if not suffix or len(suffix) > 8:
                    suffix = {"image/gif": ".gif", "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "text/html": ".html"}.get(fetched["content_type"], ".bin")
                target = assets / f"{digest}{suffix}"
                if not target.exists():
                    target.write_bytes(data)
                record.update(local_path=str(target.resolve()), bytes=len(data), sha256=digest)
            results[url] = record
            if index % 100 == 0 or index == len(pending):
                print(json.dumps({"processed": index, "pending_total": len(pending), "ok": sum(x["status"] == "ok" for x in results.values()), "failed": sum(x["status"] != "ok" for x in results.values())}, ensure_ascii=False), flush=True)
    for url in invalid_urls:
        results[url] = {
            "resource_url": url,
            "retrieved_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "status": "invalid_url",
            "http_status": None,
            "final_url": None,
            "content_type": None,
            "local_path": None,
            "bytes": 0,
            "sha256": None,
            "error": "Resource reference is not an HTTP(S) URL",
        }
    manifest_rows = [results[url] for url in sorted(results)]
    previous_path.write_text(json.dumps(manifest_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    mapping = []
    for row in unresolved:
        download = results[row["resource_url"]]
        mapping.append({**row, **{f"download_{k}": v for k, v in download.items() if k != "resource_url"}})
    mapping_path = out / "notice_body_resource_mapping.csv"
    with mapping_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(mapping[0]))
        writer.writeheader()
        writer.writerows(mapping)
    summary = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "unresolved_resource_references": len(unresolved),
        "unique_resource_urls": len(results),
        "download_ok": sum(x["status"] == "ok" for x in results.values()),
        "download_failed": sum(x["status"] == "failed" for x in results.values()),
        "invalid_urls": sum(x["status"] == "invalid_url" for x in results.values()),
        "unique_content_hashes": len({x["sha256"] for x in results.values() if x.get("sha256")}),
        "manifest": str(previous_path.resolve()),
        "mapping": str(mapping_path.resolve()),
    }
    (out / "body_resource_archive_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
