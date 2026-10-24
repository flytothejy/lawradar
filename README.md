# 법레이더 (lawradar)

> 진행 상황: [`docs/ROADMAP.md`](docs/ROADMAP.md)

법령·행정규칙·자치법규(조례·규칙)가 바뀌면 **매일 모으고, 생활과 상관없는 변경은 걸러 내고, 무엇이 바뀌었는지 한 줄로** 알려 주는 저장소입니다.
[public-api-monitor 아이디어 뱅크](https://flytothejy.github.io/public-api-monitor/ideas.html)의 법령 아이템(#460~463, #288, #461)에서 출발했고, 공통 엔진 위에 앞단을 하나씩 얹는 구조입니다.

- 사용 시나리오·목업: [`docs/SCENARIO.md`](docs/SCENARIO.md)
- 1차 앞단: **화성시 주민용 주간 브리핑** (#462 우리 동네 조례 알림) — 텔레그램 + GitHub Pages
- 다음 후보: 업종별 규제 알림(#460), 규제 영향 사업장 레이더(#461 — 대기 배출시설부터)

## 구성

```
GitHub Actions daily (매일 07:40)                 Cloudflare R2 (버킷의 lcf/)             GitHub Pages
 ① 최근 10일 공포·발령분 목록 (법령·행정규칙·자치법규) ─▶ days/<공포일>.json  항목+보강 결과  ┌ index.html
 ② 분류: 정비·내부 행정 거르기, 주제 태그                  feed/<수집일>.json 새로 발견한 것   │  주간 브리핑
 ③ 보강: 법령 = 제개정이유·주요내용, 타법개정 원인           state/seen.json                   │  최근 30일 전체
        조례(구독 지역만) = 이전 판과 조문 비교             digest/<프로필>/<날짜>.json  ──▶ └ api/*.json
 ④ 텔레그램 일일 요약
GitHub Actions digest (월 07:55) ─ 프로필별 주간 브리핑 → 텔레그램
```

| 폴더 | 내용 |
|---|---|
| `lcf/` | 수집·분류·비교·다이제스트·화면·알림·R2 코드 (`python -m lcf …`) |
| `config/classify.json` | 노이즈 필터·주제 규칙 (정규식). 고치면 다음 수집부터 반영 |
| `config/profiles.json` | 브리핑 구독 단위 (지역·주제·건수) |
| `web/index.html` | 화면 (브리핑 + 최근 30일 필터 목록) |

## 판정 기준

| 중요도 | 기준 |
|---|---|
| 중요 `high` | 제정·전부개정 |
| 보통 `mid` | 일부개정·폐지 |
| 정비 `low` (기본 숨김) | 타법개정·일괄개정(다른 법 개정에 따른 문구 정리), 내부 행정(정원·전결·여비·복무·위원회 구성…), 행정규칙 중 훈령·예규, 조례 diff에서 바뀐 낱말 4개 이하이고 숫자 변화가 없는 것 |

- **법령**: `lsHstInf`(그날 변경된 법령)에서 그날 공포된 판만. 본문의 `제개정이유 → 주요내용` 첫 항목이 요약. 타법개정은 `개정문`에서 원인 법령과 바뀐 문장을 뽑음
- **자치법규**: `ordin` 공포일 검색. 구독 지역은 `nw=2`(연혁)에서 같은 자치법규ID의 직전 판을 찾아 조 단위로 비교 → 바뀐 숫자(`200만원 → 300만원`), 신설·삭제 조. 직전 판을 못 찾으면 본문의 `(개정 2026. 10. 7)` 표시로 바뀐 항을 찾음
- **행정규칙**: 발령일 검색. v1은 목록·분류만 (본문 보강 없음)
- 지원금 표시(💰): 이름에 지원·장려금·감면·수당 등이 들어간 것
- 같은 날 다시 돌려도 겹치지 않음 (key = 종류:일련번호). 이미 보강한 항목은 다시 읽지 않음

## 설정 (Secrets)

| 이름 | 용도 |
|---|---|
| `LAW_OC` | **국가법령정보 공동활용 OPEN API 인증값** — [open.law.go.kr](https://open.law.go.kr) 회원가입 → OPEN API 신청(법령·행정규칙·자치법규 체크, 서버 IP 등록) 후 받은 아이디 |
| `R2_ACCOUNT_ID` `R2_ACCESS_KEY_ID` `R2_SECRET_ACCESS_KEY` `R2_BUCKET` | 상태 저장 (public-api-monitor와 같은 버킷 OK — 폴더 `lcf/`) |
| `TELEGRAM_TOKEN` `TELEGRAM_CHAT_ID` | 알림 (없으면 로그에만 출력) |
| `DATA_GO_KR_KEY` | 지금은 안 씀 — 입법예고(국민참여입법센터) 연결 때 사용 예정 |

공공데이터포털의 법제처 API들은 대부분 'LINK형'이라 실제 호출은 law.go.kr/DRF로 가고 **OC가 필요**합니다.

## 실행 위치 (중요)

법령 API는 OC마다 **등록한 서버 IP·도메인에서 온 호출만** 받습니다 (등록 안 된 곳: `사용자 정보 검증에 실패하였습니다 … IP주소 및 도메인주소를 등록해 주세요`).
GitHub Actions는 IP가 매번 바뀌므로 막히면:

1. **self-hosted runner** — 집 PC(고정에 가까운 IP)에 GitHub runner를 설치하고 그 IP를 open.law.go.kr에 등록 → 저장소 변수 `LCF_RUNNER=self-hosted`. `daily`만 그쪽에서 돌고, `digest`·`pages`는 법령 API를 부르지 않아 그대로 GitHub에서 돕니다
2. 또는 고정 IP 서버(작은 VPS 등)에서 `python -m lcf sync pull && python -m lcf daily && python -m lcf sync push`를 cron으로

## 처음 실행

1. PR을 main에 머지 (워크플로는 기본 브랜치에 있어야 수동 실행 가능)
2. Actions → **daily** → Run workflow → `seed_from`에 30일 전 날짜(예: `2026-09-22`) → 실행
   - 한 달 치를 기준선으로 저장하고 본문까지 보강 (20~30분). 그다음 오늘 분을 평소처럼 수집
3. Actions → **digest** → Run workflow → 지난주 브리핑 생성 (텔레그램 없으면 로그에 출력)
4. Settings → Pages → Source: GitHub Actions → **pages** 실행 → 화면 확인

## 로컬 실행

```bash
pip install -r requirements.txt
echo "LAW_OC=내아이디" > .env
python -m lcf collect --from 2026-09-21 --to 2026-10-21 --seed   # 처음 채우기 (알림 없이)
python -m lcf digest hwaseong --to 2026-10-19 --no-notify         # 브리핑 미리보기
python -m lcf build && python -m http.server -d data/lcf/site      # web/index.html은 site/에 복사해 확인
```

## 다음 할 일

- 입법예고(의견 마감일)를 붙여 `예고 → 공포 → 시행 D-7` 타임라인 알림
- 행정규칙(고시) 본문·신구법 비교 보강 — 업종 알림(#460)의 핵심
- 조례 diff를 쉬운 문장 한 줄로 (주간 Claude 세션 또는 `ANTHROPIC_API_KEY`)
- 지방의회 의안(#288)으로 공포 전 단계까지
