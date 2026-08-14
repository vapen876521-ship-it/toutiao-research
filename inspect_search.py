import json
import re
import time
from collections import Counter
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

OUT = Path("output_search")
OUT.mkdir(exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
}
KEYWORDS = ["生活", "美食", "家庭", "职场", "科技"]


def walk(obj):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from walk(v)


def first(d, *keys):
    for k in keys:
        if k in d and d[k] not in (None, "", [], {}):
            return d[k]
    return None


def normalize_candidate(d, keyword):
    title = first(d, "title", "articleTitle", "abstract")
    gid = first(d, "group_id", "groupId", "item_id", "itemId", "id")
    url = first(d, "article_url", "articleUrl", "url", "display_url")
    author = first(d, "media_name", "mediaName", "source", "author_name", "authorName", "user_name", "name")
    publish = first(d, "publish_time", "publishTime", "behot_time", "create_time", "createTime")
    comment = first(d, "comment_count", "commentCount", "comments_count")
    digg = first(d, "digg_count", "diggCount", "like_count", "likeCount")
    share = first(d, "share_count", "shareCount", "forward_count", "forwardCount")
    read = first(d, "read_count", "readCount", "impression_count", "impressionCount")
    media_user_id = first(d, "media_user_id", "mediaUserId", "user_id", "userId")

    # Require evidence this dict is content-like rather than a generic UI object.
    keyset = set(d.keys())
    signal = keyset.intersection({
        "group_id", "groupId", "item_id", "itemId", "article_url", "articleUrl",
        "comment_count", "commentCount", "digg_count", "diggCount", "media_name",
        "mediaName", "publish_time", "publishTime", "behot_time"
    })
    if not title or not signal:
        return None
    return {
        "keyword": keyword,
        "title": str(title)[:300],
        "group_id": str(gid) if gid is not None else "",
        "url": str(url)[:1000] if url is not None else "",
        "author": str(author)[:200] if author is not None else "",
        "publish_time": publish,
        "comment_count": comment,
        "digg_count": digg,
        "share_count": share,
        "read_count": read,
        "media_user_id": str(media_user_id) if media_user_id is not None else "",
        "source_keys": sorted(keyset)[:120],
    }


session = requests.Session()
session.headers.update(HEADERS)
report = []
all_candidates = []

for keyword in KEYWORDS:
    url = f"https://www.toutiao.com/search/?keyword={quote(keyword)}"
    r = session.get(url, timeout=30)
    text = r.text
    soup = BeautifulSoup(text, "lxml")
    scripts = soup.find_all("script")
    parsed_json_scripts = 0
    rawdata_scripts = 0
    key_counter = Counter()
    candidates = []
    parse_errors = []

    for idx, script in enumerate(scripts):
        body = script.string or script.get_text() or ""
        body = body.strip()
        if not body:
            continue
        if "rawData" in body:
            rawdata_scripts += 1
        payloads = []
        # Pure JSON script.
        if body.startswith("{") or body.startswith("["):
            payloads.append(body)
        # Common assignment wrappers.
        for marker in ("window.__INITIAL_STATE__=", "window._ROUTER_DATA=", "window.__data="):
            if marker in body:
                tail = body.split(marker, 1)[1].strip().rstrip(";")
                if tail.startswith("{") or tail.startswith("["):
                    payloads.append(tail)
        for payload in payloads:
            try:
                obj = json.loads(payload)
            except Exception as e:
                if "rawData" in payload:
                    parse_errors.append(f"script {idx}: {type(e).__name__}: {e}")
                continue
            parsed_json_scripts += 1
            for d in walk(obj):
                key_counter.update(d.keys())
                cand = normalize_candidate(d, keyword)
                if cand:
                    candidates.append(cand)

    # Fallback discovery directly from the returned HTML; no protected endpoint calls.
    group_ids = sorted(set(re.findall(r'(?:(?:group_id|groupId|item_id|itemId)[\\\"\':= ]{1,12})(\d{10,25})', text)))
    article_paths = sorted(set(re.findall(r'(?:https?:\\?/\\?/www\\?\.toutiao\\?\.com)?\\?/article\\?/(\d{10,25})', text)))
    interesting_terms = {
        term: text.count(term)
        for term in ["rawData", "group_id", "groupId", "item_id", "article_url", "comment_count", "digg_count", "share_count", "media_name", "publish_time"]
    }

    # Deduplicate candidates within a keyword.
    seen = set()
    unique_candidates = []
    for c in candidates:
        identity = (c.get("group_id"), c.get("title"), c.get("url"))
        if identity in seen:
            continue
        seen.add(identity)
        unique_candidates.append(c)
    all_candidates.extend(unique_candidates)

    report.append({
        "keyword": keyword,
        "status": r.status_code,
        "bytes": len(r.content),
        "script_count": len(scripts),
        "parsed_json_scripts": parsed_json_scripts,
        "rawdata_scripts": rawdata_scripts,
        "candidate_objects": len(unique_candidates),
        "regex_group_ids": len(group_ids),
        "regex_article_ids": len(article_paths),
        "interesting_term_counts": interesting_terms,
        "top_keys": key_counter.most_common(80),
        "parse_errors": parse_errors[:10],
        "sample_group_ids": group_ids[:20],
        "sample_article_ids": article_paths[:20],
        "sample_candidates": unique_candidates[:20],
    })
    time.sleep(2)

(OUT / "structure_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "candidates.json").write_text(json.dumps(all_candidates, ensure_ascii=False, indent=2), encoding="utf-8")
summary = {
    "keywords": len(KEYWORDS),
    "successful": sum(x["status"] == 200 for x in report),
    "candidate_objects_total": len(all_candidates),
    "per_keyword": [
        {
            "keyword": x["keyword"],
            "candidate_objects": x["candidate_objects"],
            "regex_group_ids": x["regex_group_ids"],
            "rawdata_scripts": x["rawdata_scripts"],
            "terms": x["interesting_term_counts"],
        }
        for x in report
    ],
}
print(json.dumps(summary, ensure_ascii=False, indent=2))
