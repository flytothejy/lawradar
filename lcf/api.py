"""국가법령정보 공동활용 OPEN API (law.go.kr/DRF) 클라이언트

인증값 OC: open.law.go.kr에서 OPEN API 신청 후 받은 아이디 (환경변수 LAW_OC).
목록: lawSearch.do?target=... / 본문: lawService.do?target=...
응답은 type=JSON. 결과가 1건이면 리스트 대신 dict로 오므로 as_list로 맞춥니다.
"""
import os, sys, time

import requests

from .core import log

BASE = "https://www.law.go.kr/DRF"
_s = requests.Session()
_s.headers["User-Agent"] = "lawradar/0.1 (+https://github.com/flytothejy/lawradar)"
CALLS = {"n": 0}
PAUSE = float(os.environ.get("LAW_PAUSE", "0.15"))   # 호출 사이 쉬는 시간(초) — 기관 서버 배려
DEBUG = os.environ.get("LCF_DEBUG") == "1"           # 호출마다 걸린 시간 기록
SLOW = {"n": 0, "sec": 0.0}


def oc():
    v = os.environ.get("LAW_OC", "").strip()
    if not v:
        sys.exit("LAW_OC가 없습니다 — open.law.go.kr에서 OPEN API를 신청하고 받은 아이디(OC)를 Secret LAW_OC로 등록하세요")
    return v


def as_list(x):
    return [] if x in (None, "") else (x if isinstance(x, list) else [x])


def _get(path, params, tries=5):
    p = {"OC": oc(), "type": "JSON", **params}
    err = None
    for i in range(tries):
        t0 = time.time()
        try:
            r = _s.get(f"{BASE}/{path}", params=p, timeout=(10, 30))
            CALLS["n"] += 1
            dt_ = time.time() - t0
            SLOW["sec"] += dt_
            if DEBUG or dt_ > 10:
                log(f"  api {params.get('target')} {params.get('MST') or params.get('regDt') or params.get('ancYd') or params.get('prmlYd') or params.get('query', '')} p{params.get('page', '')} {dt_:.1f}s HTTP {r.status_code} {len(r.content)}B")
            time.sleep(PAUSE)
            t = r.text.lstrip()
            if r.ok and t.startswith("{"):
                j = r.json()
                if isinstance(j, dict) and "result" in j and "msg" in j:      # 인증 실패 응답: {"result": "사용자 정보 검증에 실패…", "msg": "…IP주소 및 도메인주소를 등록…"}
                    sys.exit(f"법령 API 인증 실패 — {j['result']} {j['msg']}\n"
                             "  · LAW_OC 값, open.law.go.kr OPEN API 신청(법령·행정규칙·자치법규 체크) 상태를 확인하세요\n"
                             "  · 서버 IP/도메인 등록이 필요합니다. GitHub Actions처럼 IP가 바뀌는 곳에서 막히면 README '실행 위치'를 보세요")
                return j
            err = f"HTTP {r.status_code}: {t[:160]!r}"
        except requests.RequestException as e:
            err = repr(e)
            log(f"  api 실패 {params.get('target')} {time.time() - t0:.1f}s {err[:120]}")
        time.sleep(2 * (i + 1))
    raise RuntimeError(f"법령 API 실패 {path} {params}: {err}")


def search(target, **params):
    """목록 조회 — 모든 페이지를 모아 (행 리스트, totalCnt) 반환"""
    rows, page, total = [], 1, 0
    while True:
        j = _get("lawSearch.do", {"target": target, "display": 100, "page": page, **params})
        root = j[next(iter(j))] if j else {}
        total = int(root.get("totalCnt") or 0)
        key = next((k for k in ("law", "admrul", "ordin", "prec") if k in root), None)
        got = as_list(root.get(key)) if key else []
        rows += got
        if not got or page * 100 >= total or page >= 60:
            return rows, total
        page += 1


def service(target, **params):
    j = _get("lawService.do", {"target": target, **params})
    return j[next(iter(j))] if j else {}
