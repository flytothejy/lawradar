# 법레이더 (lawradar)

법령·행정규칙·자치법규 변경을 매일 모아 노이즈를 거르고, 구독 단위(지역·주제)별 브리핑으로 보내는 저장소.
출발점: public-api-monitor 아이디어 뱅크 #462(우리 동네 조례 알림), #460, #461, #288.

- **진행 상황·다음 할 일 → `docs/ROADMAP.md` 먼저**. 단계를 끝내면 체크하고 PR 번호·날짜를 적을 것
- 서비스 원칙·핵심 가치 → `docs/SCENARIO.md`
- 사업 문서(프리미엄 후보 `PREMIUM.md`, 투자자 소개 `PITCH.md`)는 **비공개 레포 flytothejy/law-change-feed의 `docs/`**에 있음. 이 레포는 공개이니 사업 문서·비밀값을 올리지 말 것
- 구조·판정 기준·실행 위치(OC IP 등록) → `README.md`
- 법령 API: law.go.kr/DRF, 인증 `LAW_OC`. 목록 `lawSearch.do`, 본문 `lawService.do`. 1건이면 dict로 오니 `api.as_list` 사용
- Actions는 **Python 3.11** — f-string 안 백슬래시 금지. 올리기 전 `for f in lcf/*.py; do python3.11 -m py_compile $f; done`
- 규칙 수정은 코드보다 `config/classify.json`·`config/profiles.json` 먼저

## 작업 규칙

- main에 직접 push하지 않음. 브랜치 → PR → (임시 브랜치가 아니면) 바로 머지. **브랜치는 항상 최신 origin/main에서** (`git fetch` 먼저)
- 비밀값은 GitHub Secrets 이름으로만: `LAW_OC`, `R2_*`, `TELEGRAM_*`, `ANTHROPIC_API_KEY`, `DATA_GO_KR_KEY`.
- 수집 결과(`data/`)는 커밋하지 않음. 상태는 R2 `lcf/` 아래.
- 기관 서버 배려: 호출 사이 `LAW_PAUSE`(기본 0.15초), 본문 보강은 실행당 `LCF_ENRICH_MAX`(기본 500)건까지.
