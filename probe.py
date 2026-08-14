import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

OUT = Path("output")
OUT.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
}

KEYWORDS = ["生活", "美食", "职场", "家庭", "科技"]
URLS = [("home", "https://www.toutiao.com/")]
URLS += [(f"search:{k}", f"https://www.toutiao.com/search/?keyword={quote(k)}") for k in KEYWORDS]

rows = []
links = set()
s = requests.Session()
s.headers.update(HEADERS)

for label, url in URLS:
    started = time.time()
    try:
        r = s.get(url, timeout=25, allow_redirects=True)
        text = r.text
        title = ""
        try:
            soup = BeautifulSoup(text, "lxml")
            title = soup.title.get_text(strip=True) if soup.title else ""
        except Exception:
            pass
        for pattern in [r'https?://www\.toutiao\.com/article/\d+/?', r'//www\.toutiao\.com/article/\d+/?']:
            for m in re.findall(pattern, text):
                if m.startswith("//"):
                    m = "https:" + m
                links.add(m)
        rows.append({
            "label": label,
            "requested_url": url,
            "final_url": r.url,
            "status": r.status_code,
            "bytes": len(r.content),
            "elapsed_s": round(time.time() - started, 2),
            "title": title[:200],
            "article_links_found": len(links),
            "contains_login": ("登录" in text),
            "contains_captcha": any(x in text.lower() for x in ["captcha", "验证码", "verify"]),
            "sample_prefix": re.sub(r"\s+", " ", text[:400]),
        })
    except Exception as e:
        rows.append({
            "label": label,
            "requested_url": url,
            "final_url": "",
            "status": "ERROR",
            "bytes": 0,
            "elapsed_s": round(time.time() - started, 2),
            "title": "",
            "article_links_found": len(links),
            "contains_login": False,
            "contains_captcha": False,
            "sample_prefix": repr(e),
        })
    time.sleep(2.0)

with (OUT / "probe.csv").open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys())
    w.writeheader()
    w.writerows(rows)

(OUT / "article_links.txt").write_text("\n".join(sorted(links)), encoding="utf-8")
summary = {
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "requests": len(rows),
    "successful_http": sum(isinstance(x["status"], int) and x["status"] < 400 for x in rows),
    "unique_article_links": len(links),
    "statuses": [{"label": x["label"], "status": x["status"], "bytes": x["bytes"], "title": x["title"]} for x in rows],
}
(OUT / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=2))

if not any(isinstance(x["status"], int) and x["status"] < 400 for x in rows):
    sys.exit(2)
