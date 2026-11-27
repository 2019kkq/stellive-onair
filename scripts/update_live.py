#!/usr/bin/env python3
"""치지직 채널 14명의 방송 상태를 조회해 data/live.json 을 갱신한다.

GitHub Pages 는 정적 호스팅이라 브라우저가 api.chzzk.naver.com 을 직접 호출할 수 없다
(치지직이 해외/교차 출처 Origin 요청을 403 으로 막고 CORS 헤더를 주지 않음).
그래서 GitHub Actions 가 서버 측에서 수집해 JSON 스냅샷을 커밋하고, 사이트는 그 스냅샷을 읽는다.
"""
import json
import os
import time
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


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


def main():
    members = json.load(open(os.path.join(ROOT, "data", "members.json"), encoding="utf-8"))
    path = os.path.join(ROOT, "data", "live.json")
    previous = {}
    if os.path.exists(path):
        try:
            previous = json.load(open(path, encoding="utf-8")).get("channels") or {}
        except Exception:  # noqa: BLE001
            previous = {}

    channels = {}
    for member in members:
        cid = member["id"]
        try:
            data = fetch_json("https://api.chzzk.naver.com/service/v2/channels/%s/live-detail" % cid)
            content = data.get("content") or {}
            status = content.get("status")
            channels[cid] = {
                "status": "live" if status == "OPEN" else ("off" if status in ("CLOSE", "CLOSED") else "unknown"),
                "title": (content.get("liveTitle") or "").strip(),
                "start": content.get("openDate") or None,
            }
        except Exception as exc:  # noqa: BLE001
            print("warn: %s (%s) %s" % (member["name"], member["slug"], exc))
            channels[cid] = previous.get(cid) or {"status": "unknown", "title": "", "start": None}

    payload = {
        "updatedAt": datetime.now(KST).isoformat(timespec="seconds"),
        "channels": channels,
    }
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=1)
        fp.write("\n")
    live = [k for k, v in channels.items() if v["status"] == "live"]
    print("live.json updated — %d개 채널 중 %d개 방송 중" % (len(channels), len(live)))


if __name__ == "__main__":
    main()
