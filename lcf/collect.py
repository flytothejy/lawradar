"""매일 수집 — 공포·발령일 기준으로 법령·행정규칙·자치법규 변경을 모으고 본문으로 보강

  python -m lcf collect                 최근 10일(오늘 포함)을 다시 훑음 — 조례는 공포 며칠 뒤 등록되는 일이 많아 넉넉히
  python -m lcf collect --from 2026-09-21 --to 2026-10-20 [--seed]
        --seed : 처음 채울 때. 본 것으로만 표시하고 오늘 피드(알림)에는 넣지 않음

저장
  days/<공포일>.json  {date, items:{key: 항목}}       — 다이제스트·화면의 근거
  feed/<수집일>.json  오늘 처음 발견한 항목 key 목록   — 일일 알림의 근거
  state/seen.json     {key: 처음 본 날}
"""
import datetime as dt, os, re

from . import api, extract, textdiff
from .classify import classify, refine_with_diff, topics_from_detail
from .core import DAYS, FEED, STATE, config, log, parse_ymd, read_json, status, today, write_json, ymd

ENRICH_MAX = int(os.environ.get("LCF_ENRICH_MAX", "500"))   # 한 번에 본문까지 읽는 최대 건수 (남은 건 다음 실행에서)
ORDIN_SCOPE = os.environ.get("LCF_ORDIN_SCOPE", "all")       # 조례 조문 비교 범위: all(전국) | watched(프로필 지역만 — 과거 백필용)


def _d(s):
    d = parse_ymd(s)
    return d.isoformat() if d else ""


# ── 정규화 ────────────────────────────────────────────────────────────
def norm_law(r):
    seq = r.get("법령일련번호")
    return {"kind": "law", "key": f"law:{seq}", "seq": seq, "id": r.get("법령ID"), "name": r.get("법령명한글", ""),
            "type": r.get("법령구분명", ""), "change": r.get("제개정구분명", ""), "org": r.get("소관부처명", ""),
            "announced": _d(r.get("공포일자")), "effective": _d(r.get("시행일자")), "no": r.get("공포번호", ""),
            "url": f"https://www.law.go.kr/LSW/lsInfoP.do?lsiSeq={seq}"}


def norm_admrul(r):
    seq = r.get("행정규칙일련번호")
    return {"kind": "admrul", "key": f"admrul:{seq}", "seq": seq, "id": r.get("행정규칙ID"), "name": r.get("행정규칙명", ""),
            "type": r.get("행정규칙종류", ""), "change": r.get("제개정구분명", ""), "org": r.get("소관부처명", ""),
            "announced": _d(r.get("발령일자")), "effective": _d(r.get("시행일자")), "no": r.get("발령번호", ""),
            "url": f"https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq={seq}"}


def norm_ordin(r):
    seq = r.get("자치법규일련번호")
    return {"kind": "ordin", "key": f"ordin:{seq}", "seq": seq, "id": r.get("자치법규ID"), "name": r.get("자치법규명", ""),
            "type": r.get("자치법규종류", ""), "change": r.get("제개정구분명", ""), "org": r.get("지자체기관명", ""),
            "field": r.get("자치법규분야명", ""),
            "announced": _d(r.get("공포일자")), "effective": _d(r.get("시행일자")), "no": r.get("공포번호", ""),
            "url": f"https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq={seq}"}


def fetch_day(d):
    s = ymd(d)
    laws, _ = api.search("lsHstInf", regDt=s)
    items = [norm_law(r) for r in laws if r.get("공포일자") == s]            # 그날 '변경된 법령'의 연혁 중 그날 공포된 판만
    adm, _ = api.search("admrul", prmlYd=f"{s}~{s}", sort="ddes")
    items += [norm_admrul(r) for r in adm if r.get("발령일자") == s]
    ordn, _ = api.search("ordin", ancYd=f"{s}~{s}", sort="ddes")
    items += [norm_ordin(r) for r in ordn if r.get("공포일자") == s]
    uniq = {}
    for it in items:
        if it["seq"]:
            uniq[it["key"]] = classify(it)
    return uniq


# ── 보강: 법령 ─────────────────────────────────────────────────────────
def _lines(x):
    out = []
    def walk(v):
        if isinstance(v, list):
            for y in v: walk(y)
        elif isinstance(v, dict):
            for y in v.values(): walk(y)
        elif v:
            out.append(str(v).strip())
    walk(x)
    return [l for l in out if l]


DETAIL_V = 3      # 보강 형식 버전 — 올리면 예전 형식으로 보강된 항목을 다시 읽음 (3: 부칙, 개정이유 길게)


def _ymd8(iso):
    return iso.replace("-", "") if iso else ""


def law_buchik(b, it):
    """법령 본문의 부칙단위 중 이번 개정분 (공포일자·공포번호가 같은 것) → 줄 목록"""
    units = api.as_list((b.get("부칙") or {}).get("부칙단위"))
    day, no = _ymd8(it["announced"]), str(it.get("no") or "")
    hit = [u for u in units if u.get("부칙공포일자") == day and (not no or str(u.get("부칙공포번호")) == no)] \
        or [u for u in units if u.get("부칙공포일자") == day]
    return _lines(hit[-1].get("부칙내용")) if hit else []


BUCHIK_SPLIT = re.compile(r"(?=부칙\s*\(\s*\d{4}\.\s*\d{1,2}\.\s*\d{1,2})")


def ordin_buchik(body, it):
    """자치법규 부칙은 역대분이 한 문자열 — '부칙 (2026. 10. 7 …)'로 잘라 이번 공포일 것만"""
    raw = " ".join(_lines((body.get("부칙") or {}).get("부칙내용")))
    if not raw:
        return ""
    d = dt.date.fromisoformat(it["announced"])
    segs = BUCHIK_SPLIT.split(raw)
    mark = re.compile(rf"부칙\s*\(\s*{d.year}\.\s*{d.month}\.\s*{d.day}\b")
    hit = [s for s in segs if mark.match(s)]
    if hit:
        return hit[-1].strip()
    return segs[0].strip() if it["change"] in ("제정", "폐지제정") else ""


def enrich_law(it):
    b = api.service("law", MST=it["seq"])
    reason = _lines((b.get("제개정이유") or {}).get("제개정이유내용"))
    rev = _lines((b.get("개정문") or {}).get("개정문내용"))
    det = {"v": DETAIL_V}
    bu = law_buchik(b, it)
    if bu:
        det["buchik"] = " ".join(bu)[:3000]
    if it["change"] in ("타법개정", "타법폐지"):
        # 개정문 둘째 줄이 원인 법령: "응급의료에 관한 법률 일부개정법률" → 이 법의 어느 부분이 바뀌었는지 한두 줄
        cause = next((l for l in rev[1:4] if l.endswith(("법률", "령", "규칙")) and "생략" not in l), "")
        det["cause"] = re.sub(r"(일부|전부)개정(법률|령|규칙)$", "", cause).strip()
        hit = [i for i, l in enumerate(rev) if it["name"] in l and "개정한다" in l]
        if hit:
            det["edit"] = [l.strip() for l in rev[hit[0] + 1:hit[0] + 3] if not l.strip().startswith(("②", "③", "④"))][:2]
    else:
        main, why, sec = [], [], None
        for l in reason:
            if "주요내용" in l:
                sec = "main"; continue
            if "개정이유" in l or "제정이유" in l:
                sec = "why"; continue
            if l.startswith("<법제처"):
                break
            if sec == "main":
                main.append(l)
            elif sec == "why" and not l.startswith("["):
                why.append(l)
        det["why"] = " ".join(why)[:3000]
        det["main"] = [m[:1500] for m in main if len(m) > 4][:20]
        det["changes"] = extract.changes(why + main)
    it["detail"] = det
    return topics_from_detail(it)


# ── 보강: 자치법규 (이전 판과 조문 비교) ───────────────────────────────
def _articles(body):
    out = []
    for z in api.as_list((body.get("조문") or {}).get("조")):
        no = z.get("조문번호")
        no = no[0] if isinstance(no, list) else no
        if z.get("조문여부", "Y") == "Y":
            out.append((no, z.get("조제목", ""), z.get("조내용", "")))
    return out


def _prev_seq(it):
    rows, _ = api.search("ordin", nw=2, query=it["name"])
    cur = ymd(dt.date.fromisoformat(it["announced"]))
    cand = [r for r in rows if r.get("자치법규ID") == it["id"] and r.get("자치법규일련번호") != it["seq"]
            and (r.get("공포일자") or "") <= cur]
    cand.sort(key=lambda r: (r.get("공포일자", ""), int(r.get("자치법규일련번호") or 0)))
    return cand[-1]["자치법규일련번호"] if cand else None


def enrich_ordin(it):
    body = api.service("ordin", MST=it["seq"])
    arts = _articles(body)
    det = {"v": DETAIL_V, "n_articles": len(arts)}
    bu = ordin_buchik(body, it)
    if bu:
        det["buchik"] = bu[:3000]
    d = dt.date.fromisoformat(it["announced"])
    dot = f"{d.year}. {d.month}. {d.day}"
    marks = []
    for no, title, text in arts:
        for kind, p in textdiff.marked_paragraphs(text, dot):
            marks.append({"jo": textdiff.jo_label(no), "title": title, "kind": kind, "text": p})
    det["marked"] = marks[:10]
    if it["change"] in ("제정", "폐지제정"):
        det["titles"] = [t for _, t, _ in arts if t][:12]
        purpose = next((textdiff.clean(x) for n, t, x in arts if t in ("목적",)), "")
        det["purpose"] = purpose[:220]
    elif it["change"] in ("일부개정", "전부개정"):
        prev = _prev_seq(it)
        if prev:
            old = _articles(api.service("ordin", MST=prev))
            det["prev"] = prev
            det["diff"] = textdiff.compare(textdiff.article_map(old), textdiff.article_map(arts))
    it["detail"] = det
    return topics_from_detail(refine_with_diff(it))


# ── 보강: 행정규칙(고시) — 제개정이유 · 이번 부칙 · 이전 판과 조문 비교 ─────────
ADM_JO = re.compile(r"^\s*제\s*(\d+)\s*조(?:\s*의\s*(\d+))?\s*(?:\(([^)]*)\))?\s*(.*)$", re.S)


def _adm_articles(body):
    """조문내용은 조마다 문자열 하나 ('제2조(정의) …'). 장·절 제목은 뺌 → [(번호 'JJJJGG', 제목, 내용)]"""
    out = []
    for s in api.as_list(body.get("조문내용")):
        s = " ".join(_lines(s)) if not isinstance(s, str) else s
        m = ADM_JO.match(s or "")
        if m:
            out.append((f"{int(m.group(1)):04d}{int(m.group(2) or 0):02d}", (m.group(3) or "").strip(), s))
    return out


def admrul_buchik(body, it):
    b = body.get("부칙") or {}
    days, nos, txt = (api.as_list(b.get(k)) for k in ("부칙공포일자", "부칙공포번호", "부칙내용"))
    day, no = _ymd8(it["announced"]), str(it.get("no") or "")
    idx = [i for i, d in enumerate(days) if str(d) == day and (not no or i >= len(nos) or str(nos[i]) == no)] \
        or [i for i, d in enumerate(days) if str(d) == day]
    if idx and idx[-1] < len(txt):
        return " ".join(_lines(txt[idx[-1]]))
    return " ".join(_lines(txt[-1])) if txt and it["change"] in ("제정", "폐지제정") else ""


def _adm_prev(it):
    rows, _ = api.search("admrul", nw=2, query=it["name"])
    cur = _ymd8(it["announced"])
    cand = [r for r in rows if r.get("행정규칙ID") == it["id"] and r.get("행정규칙일련번호") != it["seq"]
            and (r.get("발령일자") or "") <= cur]
    cand.sort(key=lambda r: (r.get("발령일자", ""), int(r.get("행정규칙일련번호") or 0)))
    return cand[-1]["행정규칙일련번호"] if cand else None


def enrich_admrul(it):
    body = api.service("admrul", ID=it["seq"])
    if not isinstance(body, dict):                       # 본문이 없으면 안내 문자열만 옴 ('일치하는 행정규칙이 없습니다' 등)
        it["detail"] = {"v": DETAIL_V, "missing": str(body)[:120]}
        return it
    reason = _lines((body.get("제개정이유") or {}).get("제개정이유내용"))
    main, why, sec = [], [], None
    for l in reason:
        if "주요내용" in l:
            sec = "main"; continue
        if "개정이유" in l or "제정이유" in l:
            sec = "why"; continue
        (main if sec == "main" else why).append(l)
    det["why"] = " ".join(why)[:3000]
    det["main"] = [m[:1500] for m in main if len(m) > 4][:20]
    bu = admrul_buchik(body, it)
    if bu:
        det["buchik"] = bu[:3000]
    arts = _adm_articles(body)
    det["n_articles"] = len(arts)
    if it["change"] in ("제정", "폐지제정"):
        det["titles"] = [t for _, t, _ in arts if t][:12]
        det["purpose"] = next((textdiff.clean(x) for _, t, x in arts if t == "목적"), "")[:220]
    elif it["change"] in ("일부개정", "전부개정") and arts:
        prev = _adm_prev(it)
        if prev:
            ob = api.service("admrul", ID=prev)
            old = _adm_articles(ob) if isinstance(ob, dict) else []
            if old:
                det["prev"] = prev
                det["diff"] = textdiff.compare(textdiff.article_map(old), textdiff.article_map(arts))
    it["detail"] = det
    return topics_from_detail(refine_with_diff(it))


def watched_regions():
    return {r for p in config("profiles").get("profiles", []) for r in p.get("regions", [])}


def needs_enrich(it, regions):
    if it["kind"] == "law":
        return (it.get("detail") or {}).get("v", 1) < DETAIL_V
    if it["kind"] == "admrul":                                          # 고시만 (훈령·예규는 내부 규칙이라 뺌)
        return it["type"] == "고시" and it["cls"]["level"] != "low" and (it.get("detail") or {}).get("v", 1) < DETAIL_V
    if it["kind"] == "ordin" and it.get("detail") is not None:          # 예전 형식(부칙 없음)이면 다시 읽음
        if it["detail"].get("v", 1) >= DETAIL_V:
            return False
    elif it.get("detail") is not None:
        return False
    if it["kind"] == "ordin":
        return (ORDIN_SCOPE == "all" or it["org"] in regions) and it["cls"]["level"] != "low"
    return False


def _enrich(it):
    try:
        {"law": enrich_law, "admrul": enrich_admrul, "ordin": enrich_ordin}[it["kind"]](it)
    except (RuntimeError, KeyError, ValueError, AttributeError, TypeError, IndexError) as e:   # 한 건 실패로 실행 전체가 멈추지 않게
        log(f"  보강 실패 {it['name']}: {type(e).__name__} {e}")


def enrich_range(start, end, minutes=60):
    """이미 수집한 날짜를 다시 목록 조회 없이 보강만 (범위를 넓혔을 때 지난 기간 채우기). 시간 한도면 종료 코드 3"""
    import time
    t0, n, regions = time.time(), 0, watched_regions()
    d = end
    while d >= start:                                  # 최근 날짜부터
        p = DAYS / f"{d.isoformat()}.json"
        doc = read_json(p)
        todo = [it for it in (doc or {}).get("items", {}).values() if needs_enrich(it, regions)]
        for i, it in enumerate(todo):
            if (time.time() - t0) / 60 > minutes:
                write_json(p, doc)
                log(f"시간 한도 {minutes}분 — {d}에서 멈춤 (보강 {n}건)")
                return 3
            _enrich(it); n += 1
        if todo:
            write_json(p, doc)
            log(f"{d} 보강 {len(todo)}건 (누적 {n}건 · API {api.CALLS['n']}회)")
        d -= dt.timedelta(days=1)
    log(f"보강 끝 {start} ~ {end}: {n}건")
    return 0


def run(start=None, end=None, seed=False):
    end = end or today()
    start = start or (end - dt.timedelta(days=int(os.environ.get("LCF_LOOKBACK", "9"))))
    seen = read_json(STATE / "seen.json", {})
    regions = watched_regions()
    fresh, budget, failed = [], ENRICH_MAX, []
    d = start
    while d <= end:
        p = DAYS / f"{d.isoformat()}.json"
        old = (read_json(p) or {}).get("items", {})
        if os.environ.get("LCF_DEBUG") == "1":
            log(f"{d} 시작")
        try:
            got = fetch_day(d)
        except RuntimeError as e:
            log(f"{d} 수집 실패: {e}"); failed.append(d.isoformat()); d += dt.timedelta(days=1); continue
        for k, it in got.items():                       # 이미 보강한 항목은 보강 결과를 이어받음
            if k in old and old[k].get("detail") is not None:
                it["detail"] = old[k]["detail"]; it["cls"] = old[k]["cls"]
        merged = {**old, **got}
        for it in merged.values():
            if budget > 0 and needs_enrich(it, regions):
                _enrich(it)
                budget -= 1
        for k in merged:
            if k not in seen:
                seen[k] = today().isoformat()
                if not seed:
                    fresh.append(k)
        write_json(p, {"date": d.isoformat(), "items": merged})
        lv = {x: sum(1 for i in merged.values() if i["cls"]["level"] == x) for x in ("high", "mid", "low")}
        log(f"{d} 법령 {sum(i['kind'] == 'law' for i in merged.values())} · 행정규칙 {sum(i['kind'] == 'admrul' for i in merged.values())}"
            f" · 자치법규 {sum(i['kind'] == 'ordin' for i in merged.values())} | 중요 {lv['high']}·보통 {lv['mid']}·정비 {lv['low']} (API {api.CALLS['n']}회)")
        d += dt.timedelta(days=1)
    write_json(STATE / "seen.json", seen)
    if not seed:
        fp = FEED / f"{today().isoformat()}.json"
        prev = (read_json(fp) or {}).get("keys", [])
        write_json(fp, {"date": today().isoformat(), "keys": sorted(set(prev) | set(fresh))})
    status("collect", start=start.isoformat(), end=end.isoformat(), fresh=len(fresh), calls=api.CALLS["n"], failed=failed,
           enrich_left=budget)
    log(f"새로 발견 {len(fresh)}건 · API 호출 {api.CALLS['n']}회" + (f" · 실패한 날 {failed}" if failed else ""))
    return fresh
