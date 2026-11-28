# 스텔라 온에어 (Stellive On Air)

스텔라이브 14명 멤버의 치지직 방송 현황·다시보기·공식 일정을 한 화면에 모은 **비공식 팬 사이트**입니다.
원본 사이트(`stellive-onair-desk.cosmicsmile19.chatgpt.site`)의 디자인과 기능을 그대로 옮겨 GitHub Pages에서 돌아가도록 다시 구성했습니다.

- 사이트: https://2019kkq.github.io/stellive-onair/
- 원본: https://stellive-onair-desk.cosmicsmile19.chatgpt.site

## 구성

| 경로 | 내용 |
| --- | --- |
| `index.html` | 사이트 전체(HTML/CSS/JS 한 파일). 모든 경로는 상대 경로(`./art`, `./data`)입니다. |
| `art/` | 아바타 14종, 멤버별 배너 14종, `orbit`·`stellamode`·`ensemble`·`gallery` 이미지 32개 |
| `data/members.json` | 멤버 14명의 이름·치지직 채널 ID·슬러그·기수 |
| `data/live.json` | 방송 상태 스냅샷(상태·방송 제목·시작 시각) + `updatedAt` |
| `data/videos.json` | 멤버별 최근 다시보기 기록(썸네일·길이·링크) |
| `data/daily.json` | 공식 공지·방송 일정 기록 + `updatedAt` (카페에서 자동 수집) |
| `data/daily-cache.json` | 자동 수집이 확인한 카페 글의 판정 캐시(같은 글을 다시 읽지 않도록) |
| `scripts/update_live.py` | 치지직에서 방송 상태를 받아 `data/live.json` 갱신 |
| `scripts/update_videos.py` | 새 다시보기만 `data/videos.json`에 추가 |
| `scripts/update_daily.py` | 네이버 카페(공지사항·멤버 게시판)에서 공지와 방송 일정을 모아 `data/daily.json` 갱신 |
| `scripts/actions/update-data.yml` | 위 스크립트를 10분마다 실행하는 워크플로. **아래 설명대로 한 번 옮겨 붙여야 동작합니다.** |

## 데이터가 갱신되는 방식

GitHub Pages는 정적 호스팅이라 브라우저가 치지직 API를 직접 부를 수 없습니다.
치지직은 `Origin` 헤더가 붙은 교차 출처 요청을 403으로 막고 `Access-Control-Allow-Origin`도 주지 않습니다.
그래서 수집은 **GitHub Actions(서버 측)** 가 맡습니다.

### 한 번만 해두면 되는 설정

1. 저장소 → **Settings → Pages → Build and deployment**
   - Source: **Deploy from a branch** / Branch: **main** / 폴더: **/ (root)** → Save
2. 자동 갱신을 켜려면 `.github/workflows/update-data.yml` 파일을 사이트에서 만들어야 합니다.
   `scripts/actions/update-data.yml` 내용을 복사해 같은 경로로 저장하면 10분마다 아래 작업이 돕니다.
   (Pickle의 GitHub 연결에는 `workflows` 권한이 없어 이 파일만은 직접 올릴 수 없습니다.)

### 워크플로가 하는 일

- 10분마다 `scripts/update_live.py` — 치지직 방송 상태를 받아 `data/live.json` 갱신
- 매시 정각대에 `scripts/update_videos.py` — 새 다시보기를 `data/videos.json`에 추가
- 매 실행마다 `scripts/update_daily.py` — 네이버 카페 `공지사항`과 멤버 게시판에서 공지·방송 일정을 모아 `data/daily.json` 갱신
- 내용이 바뀔 때만 커밋하므로 커밋 기록이 과도하게 쌓이지 않습니다.

사이트는 열려 있는 동안 `data/live.json`을 1분마다 다시 읽고, 화면에 `치지직 상태 M/D HH:MM 기준`이라고 스냅샷 시각을 표시합니다.
워크플로가 멈추면 이 시각이 그대로 남아 있어 데이터가 얼마나 오래된 것인지 바로 알 수 있습니다.

워크플로를 켜지 않아도 사이트는 마지막으로 커밋된 스냅샷으로 정상 동작합니다.
이때 최신 상태가 필요하면 같은 스크립트를 로컬에서 한 번 돌리고 커밋하면 됩니다:

```bash
python3 scripts/update_live.py && git commit -am "방송 상태 갱신" && git push
```

## 로컬에서 보기

```bash
python3 -m http.server 8000   # 이 폴더에서 실행 후 http://localhost:8000
```

## 고친 것 (원본 대비)

- `/art/...`, `/api/...` 루트 절대 경로 → 프로젝트 하위 경로에서도 동작하는 상대 경로
- `/favicon.ico` 404 → 인라인 SVG 파비콘
- 배경 일러스트 위에 얹히던 안내문·푸터 글자 대비 개선(반투명 판)
- 다시보기 썸네일이 없을 때만 안내 문구 표시(원본은 항상 표시)
- 방송 기록 280여 건을 한 번에 그리던 것을 최신 40건만 표시하고, 목록 아래에 치지직에서 더 보기 링크를 둠(검색·멤버 필터는 전체 기록 대상)
- 치지직·원본 사이트 API 의존 제거 — 모든 데이터가 저장소 안에 있음

## 저작권

멤버 일러스트·배너 이미지의 권리는 각 작가와 스텔라이브에 있습니다. 이 저장소는 팬 사이트 운영 목적의 사본이며, 원본 작가 표기는 사이트의 ‘원본 작품’ 링크로 연결됩니다.
