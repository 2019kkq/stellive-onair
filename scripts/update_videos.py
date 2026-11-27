#!/usr/bin/env python3
"""치지직 최근 다시보기를 확인해 data/videos.json 에 새 영상만 덧붙인다.

기존 기록(방송 시작 시각·썸네일 등)은 건드리지 않고, 아직 없는 videoNo 만 추가한다.
멤버당 최대 60개까지만 남겨 파일 크기를 억제한다.
"""
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
KEEP = 60


def fetch_json(url, timeout=15, tries=3):
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"), strict=False)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.8 * (attempt + 1))
    raise last


def iso(value):
    if not value:
        return None
    value = value.strip()
    if "T" in value and ("+" in value[10:] or value.endswith("Z")):
        return value
    return value.replace(" ", "T") + "+09:00"


def video_key(url):
    match = re.match(r"^https://chzzk\.naver\.com/video/(\d+)/?(?:[?#].*)?$", url or "")
    return match.group(1) if match else ""


def sort_key(row):
    try:
        return datetime.fromisoformat(iso(row["start"]))
    except Exception:  # noqa: BLE001
        return datetime.min.replace(tzinfo=KST)


def main():
    members = json.load(open(os.path.join(ROOT, "data", "members.json"), encoding="utf-8"))
    path = os.path.join(ROOT, "data", "videos.json")
    store = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    before = json.dumps(store, sort_keys=True, ensure_ascii=False)

    added = 0
    for member in members:
        rows = store.get(member["id"]) or []
        known = {video_key(r.get("url")) for r in rows}
        try:
            data = fetch_json(
                "https://api.chzzk.naver.com/service/v1/channels/%s/videos"
                "?size=20&videoType=REPLAY&pagingType=PAGE" % member["id"]
            )
        except Exception as exc:  # noqa: BLE001
            print("warn: %s %s" % (member["slug"], exc))
            continue
        for video in (data.get("content") or {}).get("data") or []:
            key = str(video.get("videoNo") or "")
            if not key or key in known:
                continue
            duration = video.get("duration") or 0
            rows.append({
                "title": (video.get("videoTitle") or "").strip(),
                "start": iso(video.get("publishDate")),
                "minutes": int(round(duration / 60.0)) if duration else None,
                "url": "https://chzzk.naver.com/video/%s" % key,
                "thumbnailImageUrl": video.get("thumbnailImageUrl") or "",
                "published": True,
            })
            known.add(key)
            added += 1
        rows.sort(key=sort_key, reverse=True)
        store[member["id"]] = rows[:KEEP]

    after = json.dumps(store, sort_keys=True, ensure_ascii=False)
    if after != before:
        with open(path, "w", encoding="utf-8") as fp:
            json.dump(store, fp, ensure_ascii=False, indent=1, sort_keys=True)
            fp.write("\n")
        print("videos.json updated — %d개 새 다시보기 추가" % added)
    else:
        print("videos.json 변경 없음")


if __name__ == "__main__":
    main()
