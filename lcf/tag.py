"""관련도 꼬리표 — 변경마다 '누구에게 닿나'(대상)와 '무엇을 하게 되나'(행동 종류)를 붙임. docs/RELEVANCE.md

  python -m lcf tag [--days 730] [--limit N] [--model M] [--keys a,b] [--realtime] [--dry] [--minutes 120]

- 꼬리표 목록은 config/audience.json. 사용자 조건(/profile)도 같은 목록을 씀 → 화면(match.js)이 둘을 맞춤
- 저장: 항목의 it["tags"] = {"v": tag_v, "aud": [...], "act": [...], "m": 모델}. 쉬운 말(ai)과 따로라 다시 붙여도 요약은 그대로
- 입력: 쉬운 말 요약이 있으면 그것(짧고 정확), 없으면 원문(개정 이유·조문 제목) 앞부분
- 기본은 Message Batches API(반값). --realtime은 적은 수(매일 실행·시험)용
"""
import datetime as dt, json, os, time

import requests

from . import llm
from .classify import reclassify
from .core import DAYS, STATE, config, log, read_json, status, today, write_json

AUD = config("audience")
TAG_V = AUD["tag_v"]
TAGS = [t for g in AUD["groups"] for t, _ in g["tags"]]
ACTS = [a for a, _ in AUD["acts"]]
MODEL = os.environ.get("LCF_TAG_MODEL") or "claude-haiku-5-5"
PER_REQ = 10                                   # 요청 하나에 넣을 항목 수 (꼬리표 목록 설명을 덜 반복)
STATE_F = STATE / "tag.json"
B_API = "https://api.anthropic.com/v1/messages/batches"


def _taglist():
    out = []
    for g in AUD["groups"]:
        out.append(f"[{g['name']}] " + " / ".join(f"{t}" + (f"({d})" if d else "") for t, d in g["tags"]))
    return "\n".join(out)


SYSTEM = f"""너는 한국 법령·조례 변경을 '누구에게 닿는지'로 분류하는 편집자다.
항목마다 아래 목록에서만 고른다. 목록에 없는 말은 쓰지 않는다.

대상 꼬리표 (aud) — 이 변경 때문에 돈·의무·권리·혜택·일상이 실제로 달라지는 사람. 0~4개, 가장 직접적인 것부터
{_taglist()}

행동 종류 (act) — 그 사람에게 생기는 일. 1~3개
{" / ".join(f"{a}({d})" for a, d in AUD["acts"])}

규칙
- 제도를 '집행하는 쪽'(공무원·지자체·위원회·공공기관)은 대상이 아니다. 일반인이 할 일이 없으면 aud는 []이고 act는 ["행정 내부"]
- 건설·공사업처럼 '그 일을 하는 사업자'와 '그 결과물을 쓰는 사람'을 구분한다. 예: 정보통신공사업 규정 → 건설업 (앱·IT 서비스 아님)
- 넓게 걸칠 수 있다고 다 붙이지 않는다. 이 변경을 알려 주면 "나한테 해당되네" 할 사람만
- "국민 누구나"는 거의 모든 사람에게 직접 닿을 때만. "지역 주민 누구나"는 조례에서 주민이 쓰거나 내는 것(시설 이용·사용료·주차·생활 지원)일 때만
- 다른 법 개정에 맞춘 용어·조문 정리, 위원회 구성, 의원 국외출장, 기관 설치·운영 같은 것은 ["행정 내부"]

출력: JSON 배열만. [{{"key": "...", "aud": [...], "act": [...]}}, ...] 다른 말은 쓰지 않는다."""


def item_text(it):
    """모델에 줄 한 항목 — 쉬운 말이 있으면 그것, 없으면 원문 앞부분"""
    ai = it.get("ai") or {}
    head = f"key: {it['key']}\n이름: {it['name']}\n종류: {it['type']} {it['change']} · {it['org']}"
    if ai.get("title") and not ai.get("skip"):
        ch = "; ".join(f"{c.get('what', '')}: {c.get('after', '')}" for c in (ai.get("changes") or [])[:4])
        return f"{head}\n요약: {ai['title']} — {ai.get('summary', '')}\n닿는 사람(요약자 판단): {ai.get('who', '')}\n바뀐 것: {ch}"
    d = it.get("detail") or {}
    body = " ".join(x for x in [d.get("why") or ""] + (d.get("main") or [])[:3] if x)[:700]
    if d.get("purpose"):
        body += " / 목적: " + d["purpose"][:200]
    if d.get("titles"):
        body += " / 조 제목: " + ", ".join(d["titles"][:10])
    df = d.get("diff") or {}
    if df.get("changed"):
        body += " / 바뀐 조: " + ", ".join(f"{c['jo']}({c['title']})" for c in df["changed"][:6])
    if df.get("added"):
        body += " / 새 조: " + ", ".join(df["added"][:6])
    if ai.get("skip"):
        body = "(요약자가 일반인 영향 없음으로 판단) " + body
    return f"{head}\n원문: {body or '(본문 없음 — 이름으로만 판단)'}"


def clean(o):
    aud = [t for t in (o.get("aud") or []) if t in TAGS][:4]
    act = [a for a in (o.get("act") or []) if a in ACTS][:3]
    if not act:
        act = ["행정 내부"] if not aud else []
    if "행정 내부" in act and aud:                         # 대상이 있으면 내부가 아님
        act = [a for a in act if a != "행정 내부"]
    return {"v": TAG_V, "aud": aud, "act": act}


def in_scope(it, now, days):
    """꼬리표가 필요한 항목 — 화면·검색에 나오는 범위 (정비 제외)"""
    if it["cls"]["level"] == "low":
        return False
    if it["kind"] == "admrul" and it["type"] != "고시":
        return False
    a = it["announced"]
    if it["kind"] == "ordin":                               # 조례는 최근 120일 + 시행 전
        return a >= (now - dt.timedelta(days=120)).isoformat() or (it["effective"] or "") > now.isoformat()
    return a >= (now - dt.timedelta(days=days)).isoformat()


def todo(now, days, limit=None, keys=None):
    want = set(keys) if keys else None
    out = []
    for p in sorted(DAYS.glob("*.json"), reverse=True):
        if not want and p.stem < (now - dt.timedelta(days=days)).isoformat():
            break
        for it in ((read_json(p) or {}).get("items") or {}).values():
            if want is not None:
                if it["key"] in want:
                    out.append(it["key"])
                continue
            if (it.get("tags") or {}).get("v") == TAG_V:
                continue
            if in_scope(reclassify(it), now, days):
                out.append(it["key"])
        if limit and len(out) >= limit:
            break
    return out[:limit] if limit else out


def _load(keys):
    want, out = set(keys), {}
    for p in sorted(DAYS.glob("*.json"), reverse=True):
        doc = read_json(p) or {}
        for k, it in doc.get("items", {}).items():
            if k in want:
                out[k] = (p, it)
        if len(out) == len(want):
            break
    return out


def _save(results):
    """{key: tags} → days/에 기록"""
    by_file = {}
    items = _load(list(results))
    for k, t in results.items():
        if k in items:
            by_file.setdefault(items[k][0], {})[k] = t
    for p, upd in by_file.items():
        doc = read_json(p)
        for k, t in upd.items():
            if k in doc["items"]:
                doc["items"][k]["tags"] = t
        write_json(p, doc)
    return sum(len(u) for u in by_file.values())


def _user(chunk):
    return "\n\n".join(item_text(it) for it in chunk)


_SHOWN = [0]


def _collect(txt, chunk, model):
    got = {}
    want = {it["key"] for it in chunk}
    for o in llm._parse(txt):
        if isinstance(o, dict) and str(o.get("key", "")).strip() in want:
            got[str(o["key"]).strip()] = {**clean(o), "m": model}
    if len(got) < len(want) and _SHOWN[0] < 3:              # 무엇이 어긋나는지 몇 개만 남김
        _SHOWN[0] += 1
        log(f"  꼬리표 응답 {len(got)}/{len(want)} 읽음 · 앞부분: {txt[:400]!r}")
    return got


def realtime(keys, model=MODEL, dry=False):
    items = [it for _, it in _load(keys).values()]
    res, usage = {}, {"input_tokens": 0, "output_tokens": 0}
    for i in range(0, len(items), PER_REQ):
        chunk = items[i:i + PER_REQ]
        if dry:
            print(SYSTEM[:1500]); print("-----"); print(_user(chunk)[:3000]); return {}
        txt, u = llm.call(model, SYSTEM, _user(chunk), max_tokens=2000, thinking=llm.no_thinking(model))
        for k in usage:
            usage[k] += u.get(k, 0)
        res.update(_collect(txt, chunk, model))
    n = _save(res)
    log(f"꼬리표 {n}/{len(items)}건 ({model}) · 약 ${llm.usd(model, usage):.3f}")
    return res


def _h():
    return {"x-api-key": llm.key_for("claude"), "anthropic-version": "2023-06-01", "content-type": "application/json"}


def batch(keys, model=MODEL, minutes=120):
    """Batches API로 한 번에 — 제출한 배치 id는 state에 남겨 끊겨도 다음 실행에서 결과를 받음"""
    deadline = time.time() + minutes * 60 - 10 * 60
    st = read_json(STATE_F, {"cur": None, "done": 0, "usd": 0.0})
    if not st.get("cur"):
        items = [it for _, it in _load(keys).values()]
        chunks = [items[i:i + PER_REQ] for i in range(0, len(items), PER_REQ)]
        th = llm.no_thinking(model)
        reqs = [{"custom_id": f"c{i}", "params": {"model": model, "max_tokens": 2000, "system": SYSTEM,
                                                  "messages": [{"role": "user", "content": _user(c)}],
                                                  **({"thinking": th} if th else {})}} for i, c in enumerate(chunks)]
        if not reqs:
            log("꼬리표 붙일 항목 없음"); return 0
        r = requests.post(B_API, headers=_h(), json={"requests": reqs}, timeout=300)
        if not r.ok:
            raise RuntimeError(f"배치 제출 실패 HTTP {r.status_code}: {r.text[:300]}")
        st["cur"] = {"id": r.json()["id"], "chunks": [[it["key"] for it in c] for c in chunks], "model": model}
        write_json(STATE_F, st, pretty=True)
        log(f"꼬리표 배치 제출: {len(items)}건 / 요청 {len(reqs)}개 ({model})")
    cur = st["cur"]
    while True:
        j = requests.get(f"{B_API}/{cur['id']}", headers=_h(), timeout=60).json()
        if j.get("processing_status") == "ended":
            break
        if time.time() > deadline:
            log("꼬리표 배치 아직 진행 중 — 다음 실행에서 받음"); return 3
        c = j.get("request_counts") or {}
        log(f"  배치 진행 중 · 처리 {c.get('succeeded', 0) + c.get('errored', 0)}/{sum(c.values()) if c else '?'}")
        time.sleep(60)
    r = requests.get(j["results_url"], headers=_h(), timeout=300)
    res, usd = {}, 0.0
    by_cid = {f"c{i}": ks for i, ks in enumerate(cur["chunks"])}
    for line in r.text.splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        rr = o.get("result") or {}
        if rr.get("type") != "succeeded":
            continue
        m = rr["message"]
        usd += llm.usd(cur["model"], m.get("usage", {})) / 2
        txt = "".join(b.get("text", "") for b in m.get("content", []))
        chunk = [{"key": k} for k in by_cid.get(o["custom_id"], [])]
        res.update(_collect(txt, chunk, cur["model"]))
    n = _save(res)
    total = sum(len(c) for c in cur["chunks"])
    st["done"] += n; st["usd"] = round(st["usd"] + usd, 3); st["cur"] = None
    write_json(STATE_F, st, pretty=True)
    status("tag", done=st["done"], usd=st["usd"])
    log(f"꼬리표 저장 {n}/{total}건 · 이번 ${usd:.2f} · 누적 {st['done']}건 ${st['usd']:.2f}")
    return 0


def run(days=730, limit=None, model=MODEL, keys=None, rt=False, dry=False, minutes=120):
    now = today()
    if read_json(STATE_F, {}).get("cur") and not keys and not rt:
        return batch([], model, minutes)                     # 받다 만 배치부터
    ks = todo(now, days, limit, keys)
    log(f"꼬리표 대상 {len(ks)}건")
    if not ks:
        return 0
    if rt or dry or len(ks) <= 40:
        realtime(ks, model, dry)
        return 0
    return batch(ks, model, minutes)
