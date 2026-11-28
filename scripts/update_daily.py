#!/usr/bin/env python3
"""스텔라이브 공식 네이버 카페에서 공지와 멤버 방송 일정을 모아 data/daily.json 을 갱신한다.

사이트는 GitHub Pages 정적 호스팅이라 브라우저가 카페 API 를 직접 부를 수 없고,
카페 쪽도 교차 출처 요청에 CORS 헤더를 주지 않는다.
그래서 GitHub Actions 가 서버 측에서 카페를 훑어 JSON 스냅샷을 커밋하고, 사이트는 그 스냅샷을 읽는다.

카페 API 는 로그인 없이도 게시판 목록과 (전체 공개로 설정된) 본문을 읽을 수 있다.
멤버 게시판 중 일부는 본문이 회원 공개라 401 이 오는데, 그때는 제목만으로 판단하고
시각은 글 작성 시각을 쓴다. 본문을 한 번 확인한 글은 data/daily-cache.json 에 판정을 남겨
다음 실행에서 다시 부르지 않는다(카페에 반복 요청을 보내지 않기 위해서).
"""
import argparse
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DAILY_PATH = os.path.join(ROOT, "data", "daily.json")
CACHE_PATH = os.path.join(ROOT, "data", "daily-cache.json")

CAFE_ID = 29424353
NOTICE_MENU = 130  # 공지사항
ARTICLE_URL = "https://cafe.naver.com/ArticleRead.nhn?clubid=%d&articleid=%d"
LIST_API = ("https://apis.naver.com/cafe-web/cafe2/ArticleListV2dot1.json"
            "?search.clubid=%d&search.menuid=%d&search.page=1&search.boardtype=L")
ARTICLE_API = "https://apis.naver.com/cafe-web/cafe-articleapi/v2.1/cafes/%d/articles/%d"

# 멤버 개인 게시판 menuid. 카페 전체글보기에서 menuName "⭐│<멤버명>" 으로 확인한 값이다.
MEMBER_MENUS = {
    "아야츠노 유니": 134,
    "사키하네 후야": 382,
    "시라유키 히나": 149,
    "네네코 마시로": 150,
    "아카네 리제": 151,
    "아라하시 타비": 152,
    "텐코 시부키": 250,
    "아오쿠모 린": 251,
    "하나코 나나": 252,
    "유즈하 리코": 253,
    "시즈키 토아": 429,
    "코가네 랑": 430,
    "하나요 히요리": 431,
    "토키노 메리": 432,
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

MAX_AGE_DAYS = 3          # 이 기간 안에 올라온 글만 새로 판정한다
MAX_BODY_PER_RUN = 12     # 한 번에 본문을 확인하는 새 글 수 (카페 부담 제한)
MAX_RECORDS = 80          # daily.json 에 남기는 최대 레코드 수
RETENTION_NOTICE_DAYS = 14   # 자동 수집한 공지·휴방 소식을 남기는 기간
RETENTION_SCHEDULE_HOURS = 36  # 자동 수집한 일정은 지난 것부터 걷어낸다(사이트는 예정만 보여 줌)
CACHE_MAX_AGE_DAYS = 45   # 캐시에 남기는 판정의 수명
CACHE_MAX_ITEMS = 800
DELAY_SECONDS = 0.7       # 요청 간 지연

CANCEL_KEYWORDS = ("휴방", "결방", "방송없", "방송취소", "방송을취소", "쉬어갑니다", "쉬는날")
PLAN_KEYWORDS = ("방송", "방숑", "방소", "방성", "방쥐", "방공", "라이브", "일정", "합방", "생방",
                 "오늘", "오눌", "오느", "오뉼", "오뉴", "오누", "오능",
                 "이따", "곧 ", "만나", "봅시다", "봐요", "올게", "올께", "옵니", "켤게", "켜요")

TODAY_KEYWORDS = ("오늘", "오눌", "오느", "오뉼", "오뉴", "오누", "오능",
                  "방송공지", "방송일정", "일정")

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"[ \t\u00a0\u200b]+")
TIME_RE = re.compile(
    r"(?<![\d:])(?:(오전|오후|아침|점심|낮|저녁|밤|새벽)\s*)?"
    r"(\d{1,2})\s*(?:시|:|：)\s*(\d{1,2})?\s*분?"
)
DATE_RE = re.compile(r"(?:(\d{1,2})\s*월\s*)?(\d{1,2})\s*일")
PM_MARKS = {"오후", "낮", "저녁", "밤", "점심"}


# ---------------------------------------------------------------- helpers
def clean_text(raw):
    """HTML 조각을 사람이 읽는 텍스트로 바꾼다."""
    text = re.sub(r"<br\s*/?>", "\n", raw or "")
    text = re.sub(r"</p>", "\n", text)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = SPACE_RE.sub(" ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def clean_title(raw):
    text = SPACE_RE.sub(" ", html.unescape(raw or "")).strip()
    return text[:150]


def kst_iso(dt):
    return dt.astimezone(KST).isoformat(timespec="seconds")


def fetch_json(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Referer": "https://cafe.naver.com/stellive",
    })
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"), strict=False)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:  # noqa: BLE001
        return default


# ---------------------------------------------------------------- 시간·날짜 해석
def parse_time_matches(text):
    """(명시성, 시, 분) 목록. 명시성은 오전/오후 표기가 있으면 True."""
    out = []
    for match in TIME_RE.finditer(text):
        mark, hour, minute = match.group(1), match.group(2), match.group(3)
        try:
            hour = int(hour)
            minute = int(minute) if minute else 0
        except ValueError:
            continue
        if minute > 59 or hour > 24 or hour == 0:
            continue
        out.append((mark is not None, hour, minute, mark))
    return out


def resolve_date(text, ref):
    """글 안의 날짜 표현을 찾는다. 못 찾으면 작성일."""
    match = DATE_RE.search(text)
    if match:
        month = int(match.group(1)) if match.group(1) else ref.month
        day = int(match.group(2))
        year = ref.year
        try:
            found = date(year, month, day)
        except ValueError:
            return ref.date(), False
        if (found - ref.date()).days < -180:  # 12월 글에서 "1월 3일" 같은 경우
            try:
                found = date(year + 1, month, day)
            except ValueError:
                return ref.date(), False
        return found, True
    if "모레" in text:
        return ref.date() + timedelta(days=2), True
    if "내일" in text or "명일" in text:
        return ref.date() + timedelta(days=1), True
    return ref.date(), False


def resolve_start(text, ref):
    """글 본문에서 방송 시작 시각을 뽑는다. 실패하면 None(=작성 시각을 쓰라는 뜻)."""
    times = parse_time_matches(text)
    if not times:
        return None
    explicit = [t for t in times if t[0]]
    _, hour, minute, mark = (explicit or times)[0]
    day, pinned = resolve_date(text, ref)

    def at(target, h):
        return datetime.combine(target, datetime.min.time(), KST).replace(hour=h, minute=minute)

    if mark is not None:
        # 오전/오후 표기가 있으면 그 날 그 시각 그대로 본다.
        if mark in PM_MARKS:
            hours = [0 if (mark == "밤" and hour == 12) else (12 if hour == 12 else hour + 12)]
        else:
            hours = [0 if hour == 12 else hour]
        start = at(day, hours[0])
        # 자정 무렵 글의 "새벽 1시", "밤 12시" 는 다음 날로 넘긴다.
        if start < ref - timedelta(hours=2) and mark in ("새벽", "밤"):
            start = at(day + timedelta(days=1), hours[0])
        return start

    # 표기가 없으면 그 날과 다음날의 오전/오후 후보 중 지금과 가장 가까운 다음 시각을 고른다.
    if hour > 12:
        hours = [hour]
    elif day > ref.date() and hour < 12:
        # "내일 8시" 처럼 날짜만 미래인 글은 저녁 방송일 가능성이 높다(방송은 대개 저녁·밤).
        hours = [hour + 12]
    else:
        hours = [hour] + ([hour + 12] if hour < 12 else [])
    days = [day] if pinned else [day, day + timedelta(days=1)]
    candidates = [at(d, h) for d in days for h in hours if 0 <= h <= 23]
    if not candidates:
        return None
    upcoming = [c for c in candidates if c >= ref - timedelta(hours=2)]
    if upcoming:
        return min(upcoming)
    return min(candidates, key=lambda c: abs(c - ref))


# ---------------------------------------------------------------- 분류
def is_cancel(text):
    """방송을 쉬거나 미루는 글인지. 굿즈·예약 취소 같은 다른 '취소'와 구분한다."""
    flat = text.replace(" ", "")
    if any(kw in flat for kw in CANCEL_KEYWORDS):
        return True
    return "방송" in flat and ("취소" in flat or "연기" in flat)


def looks_like_plan(text):
    flat = text.replace(" ", "")
    return any(kw.replace(" ", "") in flat for kw in PLAN_KEYWORDS)


NAME_CACHE = {}


def name_in_text(text, members):
    """글 안에 나오는 멤버 이름을 찾는다(없으면 스텔라이브)."""
    if not NAME_CACHE:
        for member in members:
            short = member.split()[-1]
            NAME_CACHE[member] = short
    for member, short in NAME_CACHE.items():
        if member in text:
            return member
    for member, short in NAME_CACHE.items():
        if re.search(r"(?<![가-힣])%s(?![가-힣])" % re.escape(short), text):
            return member
    return "스텔라이브"


# ---------------------------------------------------------------- 수집
def fetch_articles(menu_id):
    """게시판 최신 글 목록(1페이지, 최대 20건)."""
    data = fetch_json(LIST_API % (CAFE_ID, menu_id))
    result = (data.get("message") or {}).get("result") or {}
    return result.get("articleList") or []


def fetch_body(article_id):
    """본문 텍스트. 회원 공개 글은 401 이 오므로 (False, "") 을 돌려준다."""
    try:
        data = fetch_json(ARTICLE_API % (CAFE_ID, article_id))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            return False, ""
        raise
    article = ((data.get("result") or {}).get("article")) or {}
    return True, clean_text(article.get("contentHtml") or "")


def schedule_title(subject):
    """제목만으로는 무엇인지 알기 어려운 글("오늘은!!")에 방송 예고임을 붙여 준다."""
    if "방송" in subject or parse_time_matches(subject):
        return subject
    return "%s · 방송 예정" % subject


def cancel_title(subject):
    """휴방 글은 제목에 휴방임을 붙여 공지 목록에서 뜻이 통하게 한다."""
    flat = subject.replace(" ", "")
    if any(kw in flat for kw in ("휴방", "결방", "방송취소", "방송없")):
        return subject
    return "휴방 · %s" % subject


def article_to_record(article, menu_id, member, members, readable, body, written):
    """목록 항목(+본문)을 daily.json 레코드로. 수집 대상이 아니면 None."""
    subject = clean_title(article.get("subject") or "")
    text = subject + "\n" + body
    url = ARTICLE_URL % (CAFE_ID, int(article["articleId"]))
    # 멤버 게시판 글은 누가 쓴 글인지 게시판으로 확정된다.
    name = member or name_in_text(text, members)

    if menu_id == NOTICE_MENU:
        return {
            "kind": "notice",
            "name": name,
            "title": subject,
            "start": kst_iso(written),
            "minutes": None,
            "category": "방송 취소" if is_cancel(text) else "일반",
            "url": url,
        }

    start = resolve_start(text, written)
    if start is not None and start - written > timedelta(days=7):  # 날짜를 잘못 읽은 경우
        start = written

    # "오늘 6시 방송, 25일은 휴방" 처럼 한 글에 둘 다 있는 경우가 있어
    # 제목이 휴방을 말하거나 방송 시각을 못 찾을 때만 취소 소식으로 본다.
    cancel = is_cancel(subject) or (is_cancel(body) and start is None)
    if cancel:
        return {
            "kind": "notice",
            "name": name,
            "title": cancel_title(subject),
            "start": kst_iso(written),
            "minutes": None,
            "category": "방송 취소",
            "url": url,
        }

    if not readable:
        # 회원 공개 글은 본문을 볼 수 없다. 제목만으로 방송 예고임이 분명할 때만 남긴다.
        flat = subject.replace(" ", "")
        if start is None and not any(kw in flat for kw in TODAY_KEYWORDS):
            return None

    if start is None and not looks_like_plan(text):
        return None
    if start is None:
        start = written
    return {
        "kind": "schedule",
        "name": name,
        "title": schedule_title(subject),
        "start": kst_iso(start),
        "minutes": None,
        "url": url,
    }


def collect(members, cache, budget, verbose=False):
    """새 글을 판정해 캐시에 넣는다. (added, errors) 를 돌려준다."""
    now = datetime.now(KST)
    horizon = now - timedelta(days=MAX_AGE_DAYS)
    articles = []

    for menu_id in [NOTICE_MENU] + list(MEMBER_MENUS.values()):
        try:
            listed = fetch_articles(menu_id)
        except Exception as exc:  # noqa: BLE001
            print("warn: 게시판 %s 목록 실패 — %s" % (menu_id, exc))
            time.sleep(DELAY_SECONDS)
            continue
        for item in listed:
            stamp = item.get("writeDateTimestamp")
            if not stamp:
                continue
            written = datetime.fromtimestamp(stamp / 1000, KST)
            if written < horizon:
                continue
            articles.append((written, menu_id, item))
        time.sleep(DELAY_SECONDS)

    articles.sort(key=lambda row: row[0], reverse=True)  # 최근 글부터 판정
    added = errors = 0
    for written, menu_id, item in articles:
        key = str(item.get("articleId"))
        if not key or key in cache:
            continue
        if budget <= 0:
            break
        budget -= 1
        try:
            readable, body = fetch_body(int(key))
        except Exception as exc:  # noqa: BLE001
            print("warn: 본문 %s 실패 — %s" % (key, exc))
            errors += 1
            continue
        time.sleep(DELAY_SECONDS)
        member = next((n for n, mid in MEMBER_MENUS.items() if mid == menu_id), None)
        record = article_to_record(item, menu_id, member, members, readable, body, written)
        cache[key] = {
            "menuId": menu_id,
            "written": kst_iso(written),
            "readable": readable,
            "record": record,
        }
        added += 1
        if verbose:
            label = "제외" if record is None else "%s %s" % (record["kind"], record["start"])
            print("  %-9s %s | %s" % (key, label, clean_title(item.get("subject") or "")[:40]))
    return added, errors


def trim_cache(cache, now):
    horizon = now - timedelta(days=CACHE_MAX_AGE_DAYS)
    kept = {}
    for key, entry in cache.items():
        try:
            written = datetime.fromisoformat(entry.get("written"))
        except Exception:  # noqa: BLE001
            continue
        if written >= horizon:
            kept[key] = entry
    if len(kept) > CACHE_MAX_ITEMS:
        ordered = sorted(kept.items(), key=lambda kv: kv[1].get("written") or "", reverse=True)
        kept = dict(ordered[:CACHE_MAX_ITEMS])
    return kept


def fresh_records(cached, now):
    """캐시에 남은 판정 중 아직 싣는 것만 고른다.

    사이트의 '다가오는 방송'은 시작 시각이 지난 일정을 보여 주지 않으므로,
    자동 수집한 지난 일정은 기간이 지나면 걷어내 파일이 묵은 기록으로 차지 않게 한다.
    """
    result = []
    for record in cached:
        if not record:
            continue
        try:
            start = datetime.fromisoformat(record["start"])
        except (KeyError, ValueError):
            continue
        if record.get("kind") == "schedule":
            if start >= now - timedelta(hours=RETENTION_SCHEDULE_HOURS):
                result.append(record)
        elif start >= now - timedelta(days=RETENTION_NOTICE_DAYS):
            result.append(record)
    return result


def record_start(record):
    try:
        return datetime.fromisoformat(record.get("start") or "")
    except ValueError:
        return None


def title_tokens(title):
    return set(re.findall(r"[가-힣]{3,}", title or ""))


def is_same_event(record, other):
    """서로 다른 출처(트위터 공지·카페 글)가 같은 소식을 전한 경우."""
    start, other_start = record_start(record), record_start(other)
    if start is None or other_start is None:
        return False
    if record.get("kind") != other.get("kind"):
        return False
    if record.get("name") != other.get("name"):
        return False
    if record.get("kind") == "schedule":
        # 같은 멤버가 같은 시각에 두 방송을 하는 경우는 없다.
        return abs((start - other_start).total_seconds()) <= 1800
    if abs((start - other_start).total_seconds()) > 2 * 86400:
        return False
    shared = title_tokens(record.get("title")) & title_tokens(other.get("title"))
    return len(shared) >= 2


def merge_records(existing, from_cache):
    """기존 레코드를 남기고 중복을 덜어낸 뒤 최신순으로 자른다.

    같은 글(주소+시작 시각)은 한 번만 싣고, 자동 수집분이 이미 있는 소식과
    겹치면(다른 출처) 사람이 정리해 둔 기존 레코드를 그대로 둔다.
    """
    kept = []
    seen = set()
    for record in existing:
        url = record.get("url")
        if not url:
            continue
        key = (url, record.get("start"))
        if key in seen:
            continue
        seen.add(key)
        kept.append(record)
    for record in from_cache:
        if not record:
            continue
        url = record.get("url")
        if not url:
            continue
        key = (url, record.get("start"))
        if key in seen:
            continue
        if any(is_same_event(record, other) for other in kept):
            continue
        seen.add(key)
        kept.append(record)

    def order(record):
        return record_start(record) or datetime(1970, 1, 1, tzinfo=KST)

    records = sorted(kept, key=order, reverse=True)
    return records[:MAX_RECORDS]


def main():
    parser = argparse.ArgumentParser(description="카페 공지·일정 수집")
    parser.add_argument("--dry-run", action="store_true", help="파일을 쓰지 않고 결과만 출력")
    parser.add_argument("--verbose", action="store_true", help="글별 판정을 모두 출력")
    args = parser.parse_args()

    members = [m["name"] for m in load_json(os.path.join(ROOT, "data", "members.json"), [])]
    if not members:
        print("warn: data/members.json 을 읽지 못해 이름 추정을 건너뜁니다")

    daily = load_json(DAILY_PATH, {"records": [], "updatedAt": None})
    existing = daily.get("records") if isinstance(daily.get("records"), list) else []
    cache = load_json(CACHE_PATH, {}).get("articles") or {}
    now = datetime.now(KST)

    added, errors = collect(members, cache, MAX_BODY_PER_RUN, args.verbose)
    cache = trim_cache(cache, now)

    generated = fresh_records([entry["record"] for entry in cache.values()], now)
    records = merge_records(existing, generated)

    notices = sum(1 for r in records if r.get("kind") == "notice")
    schedules = sum(1 for r in records if r.get("kind") == "schedule")
    upcoming = sum(1 for r in records if r.get("kind") == "schedule"
                   and (r.get("start") or "") > now.isoformat(timespec="seconds"))
    print("새로 판정한 글 %d건(실패 %d) — 레코드 %d건(공지 %d·일정 %d, 예정 %d)"
          % (added, errors, len(records), notices, schedules, upcoming))
    for record in records[:3]:
        print("  - [%s] %s · %s · %s" % (record.get("kind"), record.get("start"),
                                         record.get("name"), record.get("title")[:40]))

    if args.dry_run:
        print("dry-run: 파일을 쓰지 않았습니다")
        return

    changed = records != existing
    payload = {
        "records": records,
        "updatedAt": kst_iso(now) if changed else (daily.get("updatedAt") or kst_iso(now)),
    }
    with open(DAILY_PATH, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=1)
        fp.write("\n")
    with open(CACHE_PATH, "w", encoding="utf-8") as fp:
        json.dump({"articles": cache}, fp, ensure_ascii=False, indent=1)
        fp.write("\n")
    print("daily.json 갱신 — %s" % ("변경 있음" if changed else "변경 없음"))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — 워크플로가 깨지지 않도록 조용히 경고만 남긴다
        print("warn: 공지·일정 수집을 건너뜁니다 — %s" % exc, file=sys.stderr)
    sys.exit(0)
