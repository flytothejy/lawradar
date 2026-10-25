"""AI로 변경 내용을 쉬운 말로 정리 (v2: 바뀌기 전→후 쌍 · 원문 발췌 · 언제부터 누구에게 · 검증)

  python -m lcf polish [--from 날짜] [--to 날짜] [--max 300] [--model 이름] [--dry]
  python -m lcf polish --keys keys.txt --model 이름 --out 결과.json --no-save     (모델 비교 시험용)

원칙
- 사용자에게 보여 줄 항목만, 항목마다 한 번만 (결과는 days/의 항목 it["ai"]에 저장)
- 모델에는 우리가 가진 원문(개정 이유·주요 내용·부칙·조문 비교)만 주고 그 안에서만 쓰게 함
- 검증 (코드)
  · 숫자: 출력의 숫자가 원문에 없으면 그 문장·변경은 버림
  · 원문 발췌: 원문과 글자 그대로 일치해야 통과 (공백·가운뎃점·따옴표 차이만 무시). 안 맞으면 발췌를 버림
  · 적용 시작일: 원문(부칙)이나 시행일로 확인되는 날짜만
- 돈과 직결되는 변경(분야 팩·지원·과태료·세금 등)은
  · 근거 발췌가 하나도 없거나, 부칙이 있는데 적용 시기·대상을 못 뽑으면 요약을 내보내지 않음
  · 다른 호출로 2차 검토(방향 오류·조건 누락·없는 사실·적용 시기) — 걸리면 요약을 내보내지 않음
  → 이때 ai.status = "fallback": 화면은 원문만 보여 줌 (초안은 ai.draft에 남겨 둠)
- 조언·판정 문장 금지

모델: LCF_LLM_MODEL (기본 claude-sonnet-5-5), 2차 검토 LCF_REVIEW_MODEL (기본 claude-sonnet-5-5)
      gemini-* 모델은 GEMINI_API_KEY로 호출
"""
import datetime as dt, json, os, re, time

import requests

from . import packs
from .collect import ORDIN_SCOPE
from .classify import reclassify
from .core import DAYS, config, log, read_json, status, today, write_json

MODEL = os.environ.get("LCF_LLM_MODEL") or "claude-sonnet-5-5"
REVIEW_MODEL = os.environ.get("LCF_REVIEW_MODEL") or "claude-sonnet-5-5"
REVIEW_ALL = os.environ.get("LCF_REVIEW_ALL") == "1"      # 모델 비교 시험: 돈 관련이 아니어도 전부 2차 검토
BATCH = 3
AI_V = 2

# 100만 토큰당 (입력, 출력) 달러 — 비용 기록용 대략값 (2026-10 기준)
PRICES = {"claude-sonnet-5-5": (2, 10), "claude-haiku-5-5": (0.1, 0.5), "claude-opus-5-5": (4, 20),
          "gemini-3.7-flash": (0.75, 3.75), "gemini-3.1-pro": (2, 12), "gemini-2.5-flash-lite": (0.1, 0.4)}

SYSTEM = """너는 한국 법령·조례 변경을 일반인에게 알려 주는 편집자다.
각 항목마다 주어진 원문(개정 이유, 주요 내용, 부칙, 조문 비교)만 근거로 쓴다. 원문에 없는 사실·숫자·날짜·대상·조건은 절대 지어내지 않는다.

항목마다 JSON 객체 하나:
- key: 입력의 key 그대로
- skip: 일반 시민·사업자의 생활과 영업에 영향이 없는 변경(공무원 조직·정원·내부 위원회 운영, 다른 법 개정에 맞춘 용어·조문 정리 등)이면 true
- title: 무엇이 바뀌는지 한 문장, 40자 이내, 해요체. 법령 이름은 쓰지 않는다. 예: "숙박 앱, 영업신고증 확인 못 하면 중개 못 해요"
- summary: 핵심을 1~2문장, 120자 이내, 해요체
- who: 이 변경이 닿는 사람·사업자를 명사구로 30자 이내. 원문으로 알 수 없으면 ""
- changes: 바뀐 것 1~4개(중요한 순서). 각각
    {"what": "무엇이 바뀌나, 15자 이내 명사구",
     "new": true/false — 이번에 처음 생긴 제도·조항이면 true (전부개정이라도 이전에 비슷한 조항이 있었으면 false),
     "before": "바뀌기 전, 해요체 짧게. 원문으로 이전 내용을 알 수 없으면 \\"\\" (모르면 지어내지 말고 비움)",
     "after": "바뀐 뒤, 해요체 짧게",
     "quote": "이 변경의 근거가 되는 원문 구절을 글자 하나 바꾸지 말고 그대로 복사 (20~150자)"}
  · 적용 조건(지역·대상·기간·금액 기준 등)이 원문에 있으면 before/after에 빠뜨리지 않는다
  · 숫자·기간·금액은 원문 값 그대로
- when: 언제부터, 누구에게
    {"start": "적용·시행 시작일 YYYY-MM-DD. 부칙이나 시행일로 확인되는 것만, 모르면 \\"\\"",
     "target": "부칙 적용례 기준으로 누구에게·어떤 경우부터 적용되는지, 60자 이내. 부칙에 없으면 \\"\\"",
     "transition": "이미 진행 중인 일에 대한 경과 규정(종전 규정 적용 등) 요약 60자 이내. 없으면 \\"\\"",
     "other": "조항마다 시행일이 다르면 그 예외를 요약 80자 이내 (예: 중증장애인 범위 확대는 2027-07-01부터). 없으면 \\"\\"",
     "quote": "적용 시기·대상의 근거가 되는 부칙 구절을 글자 그대로 복사. 없으면 \\"\\""}
  · 부칙 중 '다른 법령의 개정' 부분은 무시한다
- 원문이 너무 짧아 무엇이 바뀌었는지 알 수 없으면 title·summary는 "", changes는 []

quote는 반드시 원문에서 연속된 구절을 그대로 복사한다. 줄이거나, 고치거나, 말을 보태면 안 된다. 따옴표·말줄임표를 붙이지 않는다.
조문 끝의 '(개정 2026. 10. 7)' 같은 개정 표시는 옮기지 않는다.
금지: "~하세요", "~해야 합니다" 같은 조언, "해당됩니다" 같은 판정, 원문에 없는 효과·평가("부담이 줄어요" 등)
출력: JSON 배열만. 다른 말은 쓰지 않는다."""

REVIEW = """너는 법령 요약 검수자다. 항목마다 '원문'과 그것으로 만든 '요약 JSON'을 비교한다.
다음 중 하나라도 있으면 ok=false:
1. 방향이 원문과 반대 (완화↔강화, 확대↔축소, 생김↔없어짐)
2. 원문에 있는 적용 조건(지역·대상·기간·금액 기준 등)이 빠져서, 요약만 읽으면 더 넓게 적용되는 것처럼 보임
3. 원문에 없는 사실·숫자·날짜·대상
4. 적용 시작일·적용 대상(when)이 원문·부칙과 다름
표현이 조금 다르거나 덜 자세한 것은 문제가 아니다.
출력: JSON 배열만. [{"key": "...", "ok": true, "problems": []}, ...] — problems는 ok=false일 때 짧은 한국어 문장으로."""

RISKY = re.compile(r"과태료|벌금|과징금|이행강제금|세율|세액|비과세|감면|공제|지원금|장려금|보조금|수당|급여|부담금|사용료|수수료|이자|대출|보증")


def key_for(model):
    return (os.environ.get("GEMINI_API_KEY") if model.startswith("gemini") else os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def no_thinking(model):
    """Claude 5.x는 생각(thinking)이 기본으로 켜져 있고 max_tokens에 포함됨 → 분류처럼 단순한 일은 끔.
    Haiku 5.5는 disabled, Sonnet 5.5는 disabled를 거부해서 between_tools(도구가 없으니 사실상 끔)"""
    if model.startswith("claude-haiku-5"):
        return {"type": "disabled"}
    if model.startswith("claude-sonnet-5-5"):
        return {"type": "between_tools"}
    return None


def call(model, system, user, max_tokens=8000, tries=4, thinking=None):
    """(text, {"input_tokens", "output_tokens"})"""
    err = None
    for i in range(tries):
        try:
            if model.startswith("gemini"):
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                                  headers={"x-goog-api-key": key_for(model)}, timeout=180,
                                  json={"systemInstruction": {"parts": [{"text": system}]},
                                        "contents": [{"role": "user", "parts": [{"text": user}]}],
                                        "generationConfig": {"maxOutputTokens": max_tokens, "responseMimeType": "application/json"}})
            else:
                r = requests.post("https://api.anthropic.com/v1/messages", timeout=180, headers={
                    "x-api-key": key_for(model), "anthropic-version": "2023-06-01", "content-type": "application/json"},
                    json={"model": model, "max_tokens": max_tokens, "system": system, "messages": [{"role": "user", "content": user}],
                          **({"thinking": thinking} if thinking else {})})
            if r.status_code in (429, 500, 502, 503, 529):
                err = f"HTTP {r.status_code} {r.text[:200]}"; time.sleep(5 * (i + 1)); continue
            if not r.ok:                                        # 400·401·403·404: 다시 해도 같음 — 본문(원인)을 남기고 바로 실패
                raise RuntimeError(f"{model} HTTP {r.status_code}: {r.text[:400]}")
            j = r.json()
            if model.startswith("gemini"):
                parts = ((j.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
                m = j.get("usageMetadata") or {}
                return "".join(p.get("text", "") for p in parts), {"input_tokens": m.get("promptTokenCount", 0),
                                                                    "output_tokens": m.get("candidatesTokenCount", 0) + m.get("thoughtsTokenCount", 0)}
            txt = "".join(b.get("text", "") for b in j.get("content", []))
            if not txt.strip():                                  # 빈 답: 원인(stop_reason·블록 종류)을 남김
                log(f"  빈 응답 {model}: stop={j.get('stop_reason')} blocks={[b.get('type') for b in j.get('content', [])]} usage={j.get('usage')}")
            return txt, j.get("usage", {})
        except requests.RequestException as e:
            err = repr(e); time.sleep(3 * (i + 1))
    raise RuntimeError(f"{model} 실패: {err}")


def usd(model, u):
    pi, po = PRICES.get(model, (2, 10))
    return u.get("input_tokens", 0) / 1e6 * pi + u.get("output_tokens", 0) / 1e6 * po


# ── 원문 ──────────────────────────────────────────────────────────────
def sources(it):
    """{이름: 원문} — 모델 입력과 검증(숫자·발췌)에 같은 글을 씀"""
    d = it.get("detail") or {}
    out = {}
    why = " ".join(x for x in [d.get("why") or ""] + (d.get("main") or []) if x)
    if why:
        out["개정이유"] = why
    if d.get("buchik"):
        out["부칙"] = d["buchik"]
    jo = []
    if d.get("purpose"):
        jo.append("목적 조항: " + d["purpose"])
    if d.get("titles"):
        jo.append("조 제목: " + ", ".join(d["titles"]))
    df = d.get("diff") or {}
    for c in df.get("changed", [])[:8]:
        for p in c.get("parts", [])[:4]:
            jo.append(f"{c['jo']}({c['title']}) 개정 전: {p['ctx']} {p['before'] or '(없음)'} {p['post']} / 개정 후: {p['ctx']} {p['after'] or '(삭제)'} {p['post']}")
    if df.get("added"):
        jo.append("새로 생긴 조: " + ", ".join(df["added"]))
    if df.get("removed"):
        jo.append("없어진 조: " + ", ".join(df["removed"]))
    if not df and d.get("marked"):
        for m in d["marked"][:6]:
            jo.append(f"{m['jo']}({m['title']}) {m['kind']}: {m['text']}")
    if d.get("cause"):
        jo.append(f"다른 법 개정에 따른 정비: {d['cause']} " + " ".join(d.get("edit") or []))
    if jo:
        out["조문"] = "\n".join(jo)
    return out


def source_text(it):
    s = sources(it)
    head = [f"이름: {it['name']}", f"종류: {it['type']} {it['change']}", f"기관: {it['org']}",
            f"공포일: {it['announced']}", f"시행일: {it['effective'] or '알 수 없음'}"]
    body = [f"[{k}]\n{v[:3500 if k == '개정이유' else 2500]}" for k, v in s.items()]
    return "\n".join(head) + "\n" + "\n".join(body)


def wanted(it, regions, pack_list):
    """사용자에게 보여 줄 가능성이 있는 것만 정리"""
    c = it["cls"]
    if c["level"] == "low" or not it.get("detail"):
        return False
    if it["kind"] == "ordin":                     # 전국 조례 (지역 페이지·상세 페이지에 씀)
        return ORDIN_SCOPE == "all" or it["org"] in regions
    # 법령·고시는 타임라인에 보이는 범위(정비 제외 전부)와 같게 — 쉬운 말이 없으면 법 이름만 보여서
    if it["kind"] == "law":
        return True
    if it["kind"] == "admrul":
        return it["type"] == "고시"
    return False


def risky(it, pack_list, src):
    """돈과 직결 → 근거·적용 시기를 더 엄격히, 2차 검토"""
    return bool(it["cls"].get("support") or any(packs.match(it, p, set()) for p in pack_list) or RISKY.search(src))


# ── 검증 ──────────────────────────────────────────────────────────────
NUM = re.compile(r"\d[\d,.]*")
MARK = re.compile(r"\s*[(<]\s*(개정|신설|삭제)?\s*\d{4}\.\s?\d{1,2}\.\s?\d{1,2}\.?\s*[)>]")


def _norm(s):
    s = re.sub(r"[ㆍ·・]", "·", s or "")
    s = re.sub(r"[‘’'`]", "'", s)
    s = re.sub(r"[“”\"]", '"', s)
    return re.sub(r"\s+", "", s)


def numbers_ok(text, raw):
    norm = re.sub(r"[,\s]", "", raw)
    return all(re.sub(r"[,\s]", "", n).rstrip(".") in norm for n in NUM.findall(text or ""))


def quote_src(q, srcs):
    """발췌가 글자 그대로 들어 있는 원문 이름 (없으면 None)"""
    q = (q or "").strip().strip("…").strip(".").strip("“”\"'‘’ ").strip()
    if len(_norm(q)) < 8:
        return None, ""
    nq = _norm(q)
    for name, txt in srcs.items():
        if nq in _norm(txt):
            return name, q
    return None, ""


def _clean(v):
    return MARK.sub("", str(v or "")).strip()


def verify(o, it, srcs, is_risky):
    """모델 출력 → 화면에 쓸 ai 딕셔너리 (검증 실패 부분은 버림). 반환: (ai, 남은 문제 목록)"""
    raw = "\n".join(srcs.values()) + f"\n{it['name']} {it['announced']} {it['effective']}"
    ck = {"dropped": 0, "quotes_ok": 0, "quotes_total": 0}
    ai = {"skip": bool(o.get("skip"))}
    for f in ("title", "summary", "who"):
        v = _clean(o.get(f))
        if v and numbers_ok(v, raw):
            ai[f] = v
        elif v:
            ck["dropped"] += 1
    chs = []
    for c in (o.get("changes") or [])[:4]:
        if not isinstance(c, dict):
            continue
        c2 = {k: _clean(c.get(k)) for k in ("what", "before", "after")}
        if c.get("new") is True and not c2["before"]:
            c2["new"] = True
        if not c2["after"] or not all(numbers_ok(c2[k], raw) for k in ("what", "before", "after")):
            ck["dropped"] += 1; continue
        if c.get("quote"):
            ck["quotes_total"] += 1
            name, q = quote_src(c["quote"], srcs)
            if name:
                c2["quote"], c2["src"] = q, name; ck["quotes_ok"] += 1
        chs.append(c2)
    ai["changes"] = chs
    w = o.get("when") or {}
    when = {}
    st = str(w.get("start") or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", st):
        y, m, d = st.split("-")
        in_src = re.search(rf"{int(y)}\s*[년.]\s*{int(m)}\s*[월.]\s*{int(d)}", raw)
        if st in (it["effective"], it["announced"]) or in_src:
            when["start"] = st
    for f in ("target", "transition", "other"):
        v = _clean(w.get(f))
        if v and numbers_ok(v, raw):
            when[f] = v
    if w.get("quote"):
        ck["quotes_total"] += 1
        name, q = quote_src(w["quote"], {"부칙": srcs.get("부칙", "")})
        if name:
            when["quote"] = q; ck["quotes_ok"] += 1
    ai["when"] = when
    ai["checks"] = ck
    problems = []
    if is_risky and not ai["skip"] and ai.get("title"):
        if not any(c.get("quote") for c in chs):
            problems.append("근거 원문 발췌가 확인되지 않음")
        if srcs.get("부칙") and not (when.get("start") or when.get("target")):
            problems.append("적용 시기·대상을 부칙에서 확인하지 못함")
    return ai, problems


def _parse(txt):
    """JSON 배열 — 응답이 잘렸으면 완성된 객체만이라도 살림. 한 건짜리는 객체 하나로 오기도 함"""
    s = re.sub(r"^```(?:json)?\s*|\s*```$", "", (txt or "").strip())
    try:
        v = json.loads(s)
        if isinstance(v, dict):
            return [v]
        if isinstance(v, list):
            return v
    except ValueError:
        pass
    if s.startswith("{"):                               # 객체 하나인데 잘린 경우: 안쪽 배열(changes)을 항목으로 오인하지 않게
        return [o for o in _objects(s)]
    m = re.search(r"\[.*\]", txt, re.S)
    if m:
        try:
            v = json.loads(m.group(0))
            if isinstance(v, list):
                return v
        except ValueError:
            pass
    return _objects(txt)


def _objects(txt):
    out, depth, start = [], 0, None                     # 중첩 객체(changes·when)가 있어 괄호 짝으로 자름
    for i, ch in enumerate(txt):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                try:
                    o = json.loads(txt[start:i + 1])
                    if isinstance(o, dict) and "key" in o:
                        out.append(o)
                except ValueError:
                    pass
    return out


def gen_prompt(items):
    return "\n\n".join(f"### key: {it['key']}\n{source_text(it)}" for it in items)


def review_prompt(items, made):
    """made: {key: ai(검증 거친 초안)}"""
    return "\n\n".join(f"### key: {it['key']}\n[원문]\n{source_text(it)}\n[요약 JSON]\n" +
                       json.dumps({k: made[it["key"]].get(k) for k in ("title", "summary", "who", "changes", "when")}, ensure_ascii=False)
                       for it in items)


def apply_review(ai, problems, r):
    """2차 검토 결과를 ai·problems에 반영"""
    if r is None:
        problems.append("2차 검토를 받지 못함"); ai["checks"]["review"] = "none"
    elif r.get("ok") is False:
        problems += [f"2차 검토: {p}" for p in (r.get("problems") or ["문제 있음"])]
        ai["checks"]["review"] = "fail"
    else:
        ai["checks"]["review"] = "ok"


def finalize(ai, problems, model):
    """문제가 남으면 원문만 보여 주는 상태로 (초안은 남김)"""
    ai.update({"v": AI_V, "model": model})
    if problems:
        draft = {k: ai.pop(k) for k in ("title", "summary", "who", "changes", "when") if k in ai}
        ai.update({"status": "fallback", "problems": problems, "draft": draft})
    else:
        ai["status"] = "ok"
    return ai


def run(start=None, end=None, limit=None, dry=False, model=None, save=True, keys=None, out=None):
    model = model or MODEL
    if not key_for(model):
        log(f"{'GEMINI' if model.startswith('gemini') else 'ANTHROPIC'}_API_KEY 없음 — 정리 건너뜀 (규칙 기반 요약을 그대로 씀)")
        return 0
    end = end or today()
    start = start or (end - dt.timedelta(days=12))
    limit = limit or int(os.environ.get("LCF_LLM_MAX", "300"))
    pack_list = [packs.load(pid) for pid in packs.all_ids()]
    profs = config("profiles").get("profiles", [])
    regions = {r for p in profs for r in p.get("regions", [])}
    want_keys = set(keys) if keys else None
    todo, files = [], {}
    paths = sorted(DAYS.glob("*.json")) if want_keys else \
        [DAYS / f"{(start + dt.timedelta(days=i)).isoformat()}.json" for i in range((end - start).days + 1)]
    for p in paths:
        doc = read_json(p)
        if not doc:
            continue
        files[p] = doc
        for it in doc["items"].values():
            if want_keys is not None:
                if it["key"] in want_keys:
                    todo.append((p, reclassify(it)))
                continue
            if (it.get("ai") or {}).get("v") == AI_V:
                continue
            if wanted(reclassify(it), regions, pack_list):
                todo.append((p, it))
    todo = todo[:limit]
    log(f"정리할 항목 {len(todo)}건 (모델 {model} · 2차 검토 {REVIEW_MODEL})")
    usage = {model: {"input_tokens": 0, "output_tokens": 0}, REVIEW_MODEL: {"input_tokens": 0, "output_tokens": 0}}
    stat = {"done": 0, "ok": 0, "fallback": 0, "reviewed": 0, "review_fail": 0, "quotes_ok": 0, "quotes_total": 0, "dropped": 0}
    results = {}
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        srcs = {it["key"]: sources(it) for _, it in chunk}
        prompt = gen_prompt([it for _, it in chunk])
        if dry:
            print(prompt[:6000]); return 0
        try:
            txt, u = call(model, SYSTEM, prompt)
            got = {o.get("key"): o for o in _parse(txt) if isinstance(o, dict)}
        except (RuntimeError, ValueError) as e:
            log(f"  배치 실패: {e}"); continue
        for k in ("input_tokens", "output_tokens"):
            usage[model][k] += u.get(k, 0)
        if len(got) < len(chunk):
            log(f"  배치 {i // BATCH + 1}: {len(chunk)}건 중 {len(got)}건만 받음 (응답 {u.get('output_tokens')}토큰) — 빠진 건 한 건씩 다시")
            for _, it in chunk:                                 # 빠진 건 한 건씩 한 번 더
                if it["key"] in got:
                    continue
                try:
                    txt, u = call(model, SYSTEM, gen_prompt([it]))
                    for k in ("input_tokens", "output_tokens"):
                        usage[model][k] += u.get(k, 0)
                    o = next((x for x in _parse(txt) if isinstance(x, dict)), None)
                    if o:
                        o["key"] = it["key"]; got[it["key"]] = o
                except (RuntimeError, ValueError) as e:
                    log(f"  다시 해도 실패 {it['name']}: {e}")
        made, review_q = {}, []
        for _, it in chunk:
            o = got.get(it["key"])
            if not o:
                continue
            src_all = "\n".join(srcs[it["key"]].values())
            rk = risky(it, pack_list, src_all + it["name"])
            ai, problems = verify(o, it, srcs[it["key"]], rk)
            made[it["key"]] = (it, ai, problems)
            if (rk or REVIEW_ALL) and not problems and not ai["skip"] and ai.get("title"):
                review_q.append(it)
        if review_q:                                            # 돈과 직결되는 것만 2차 검토
            rv = {}
            for group in [review_q] + [[it] for it in review_q]:  # 한 번에, 빠진 건 한 건씩 다시
                group = [it for it in group if it["key"] not in rv]
                if not group or (len(group) == len(review_q) and rv):
                    continue
                try:
                    txt, u = call(REVIEW_MODEL, REVIEW, review_prompt(group, {k: v[1] for k, v in made.items()}), max_tokens=2000)
                    for k in ("input_tokens", "output_tokens"):
                        usage[REVIEW_MODEL][k] += u.get(k, 0)
                    got_r = [o for o in _parse(txt) if isinstance(o, dict)]
                    if len(group) == 1 and got_r:
                        got_r[0]["key"] = group[0]["key"]
                    rv.update({o.get("key"): o for o in got_r})
                except (RuntimeError, ValueError) as e:
                    log(f"  2차 검토 실패: {e}")
            for it in review_q:
                r = rv.get(it["key"])
                ai, problems = made[it["key"]][1], made[it["key"]][2]
                stat["reviewed"] += 1
                if r is None:
                    problems.append("2차 검토를 받지 못함")
                    ai["checks"]["review"] = "none"
                elif r.get("ok") is False:
                    problems += [f"2차 검토: {p}" for p in (r.get("problems") or ["문제 있음"])]
                    ai["checks"]["review"] = "fail"; stat["review_fail"] += 1
                else:
                    ai["checks"]["review"] = "ok"
        for k, (it, ai, problems) in made.items():
            ai = finalize(ai, problems, model)
            for f in ("quotes_ok", "quotes_total", "dropped"):
                stat[f] += ai["checks"][f]
            stat["done"] += 1
            stat["ok" if ai["status"] == "ok" else "fallback"] += 1
            results[k] = ai
            if save:
                it["ai"] = ai
            if stat["done"] <= 4 or ai["status"] == "fallback":
                c0 = (ai.get("changes") or [{}])[0] if ai["status"] == "ok" else {}
                log(f"  [{it['name']}] {ai['status']} | {ai.get('title', '-')} | {c0.get('before', '')} → {c0.get('after', '')}"
                    f" | 발췌 {ai['checks']['quotes_ok']}/{ai['checks']['quotes_total']}" + (f" | {ai.get('problems')}" if ai.get("problems") else ""))
    if save:
        for p, doc in files.items():
            write_json(p, doc)
    if out:
        write_json(out, {"model": model, "review_model": REVIEW_MODEL, "results": results}, pretty=True)
    cost = sum(usd(m, u) for m, u in usage.items())
    status("polish", model=model, review_model=REVIEW_MODEL, approx_usd=round(cost, 3), **stat)
    log(f"정리 {stat['done']}건 · 통과 {stat['ok']} · 원문만 {stat['fallback']} · 2차 검토 {stat['reviewed']}(걸림 {stat['review_fail']}) · "
        f"발췌 일치 {stat['quotes_ok']}/{stat['quotes_total']} · 숫자로 버린 문장 {stat['dropped']} · 약 ${cost:.3f} {usage}")
    return {**stat, "usd": round(cost, 4), "usage": usage}
