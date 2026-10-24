"""과거분 쉬운 말 정리 — 보강(부칙까지) → Haiku 배치 생성 → Sonnet 배치 전수 검토 → 저장. 끊겨도 이어서 함

  python -m lcf backlog [--minutes 300] [--limit N] [--dry]

범위 (scope)
- 법령·행정규칙(고시): 최근 2년, 정비(low) 제외 전부
- 자치법규: 최근 90일, 정비 제외 전부
- 시행일이 아직 안 온 것: 종류 무관 전부 (2년 안 공포분)
이미 v2로 정리된 항목(매일 실행의 Sonnet 결과 등)은 건너뜀

단계 (state/backlog.json에 기록, R2로 이어짐)
  1. enrich   범위 안에서 보강이 필요한 항목을 최근 날짜부터 보강 (시간 한도 안에서, 날짜마다 저장)
  2. gen      Message Batches API로 생성 요청 (항목마다 요청 1개, 반값) → 끝날 때까지 기다림
  3. review   생성 결과를 코드로 검증한 뒤 통과한 것 전부를 Sonnet 배치로 2차 검토
  4. save     검토 반영해 days/에 저장 → 다음 묶음
시간 한도면 종료 코드 3 (워크플로가 다시 실행). 배치 결과는 Anthropic에 29일 보관되므로 다시 받아 씀

모델: LCF_BACKLOG_MODEL (기본 claude-haiku-5-5), 검토 LCF_REVIEW_MODEL (기본 claude-sonnet-5-5)
"""
import datetime as dt, json, os, time

import requests

from . import api, collect, llm, packs
from .classify import reclassify
from .core import DAYS, STATE, log, read_json, status, today, write_json

STATE_F = STATE / "backlog.json"
MODEL = os.environ.get("LCF_BACKLOG_MODEL") or "claude-haiku-5-5"
CHUNK = 2000                       # 배치 하나에 넣을 항목 수
B_API = "https://api.anthropic.com/v1/messages/batches"


def _h():
    return {"x-api-key": llm.key_for("claude"), "anthropic-version": "2023-06-01", "content-type": "application/json"}


def in_scope(it, now):
    if it["cls"]["level"] == "low":
        return False
    if it["kind"] == "admrul" and it["type"] != "고시":
        return False
    a = it["announced"]
    if it["effective"] and it["effective"] > now.isoformat() and a >= (now - dt.timedelta(days=730)).isoformat():
        return True
    if it["kind"] == "ordin":
        return a >= (now - dt.timedelta(days=90)).isoformat()
    return a >= (now - dt.timedelta(days=730)).isoformat()


def _days(now):
    since = (now - dt.timedelta(days=730)).isoformat()
    return sorted((p for p in DAYS.glob("*.json") if p.stem >= since), reverse=True)


# ── 1. 보강 ───────────────────────────────────────────────────────────
def enrich(now, deadline):
    collect.ORDIN_SCOPE = "all"
    regions = collect.watched_regions()
    n = left = 0
    last_push = time.time()
    for p in _days(now):
        doc = read_json(p) or {}
        todo = [it for it in doc.get("items", {}).values() if in_scope(reclassify(it), now) and collect.needs_enrich(it, regions)]
        if not todo:
            continue
        for it in todo:
            if time.time() > deadline:
                write_json(p, doc)
                left += len(todo) - todo.index(it)
                log(f"보강: 시간 한도 — {p.stem}에서 멈춤 (이번 {n}건)")
                return False, n
            collect._enrich(it); n += 1
        write_json(p, doc)
        if time.time() - last_push > 1200:                 # 20분마다 R2에 올려 둠
            from . import sync
            sync.push(); last_push = time.time()
    log(f"보강 끝: 이번 {n}건 · API {api.CALLS['n']}회")
    return True, n


# ── 2~4. 배치 ─────────────────────────────────────────────────────────
def targets(now, limit=None, enriched_only=False, fails=None):
    pl = [packs.load(i) for i in packs.all_ids()]
    out = []
    for p in _days(now):
        for it in ((read_json(p) or {}).get("items") or {}).values():
            ai = it.get("ai") or {}
            retry = ai.get("problems") == ["생성 결과 없음"] and (fails or {}).get(it["key"], 0) < 2
            if (ai.get("v") == llm.AI_V and not retry) or not it.get("detail"):
                continue
            if enriched_only and it["detail"].get("v", 1) < collect.DETAIL_V:
                continue
            it = reclassify(it)
            if in_scope(it, now) and llm.sources(it):
                out.append(it["key"])
                if limit and len(out) >= limit:
                    return out
    return out


def _cid(key):
    return key.replace(":", "-")


def submit(reqs):
    r = requests.post(B_API, headers=_h(), json={"requests": reqs}, timeout=300)
    if not r.ok:
        raise RuntimeError(f"배치 제출 실패 HTTP {r.status_code}: {r.text[:300]}")
    return r.json()["id"]


def wait(bid, deadline):
    while True:
        try:
            j = requests.get(f"{B_API}/{bid}", headers=_h(), timeout=60).json()
        except (requests.RequestException, ValueError):
            j = {}
        if j.get("processing_status") == "ended":
            return j
        if time.time() > deadline:
            return None
        c = j.get("request_counts") or {}
        log(f"  배치 {bid[-8:]} 진행 중 · 처리 {c.get('succeeded', 0) + c.get('errored', 0)}/{sum(c.values()) if c else '?'}")
        time.sleep(60)


def results(j):
    """{custom_id: (text, usage)}"""
    r = requests.get(j["results_url"], headers=_h(), timeout=300)
    out = {}
    for line in r.text.splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        res = o.get("result") or {}
        if res.get("type") == "succeeded":
            m = res["message"]
            txt = "".join(b.get("text", "") for b in m.get("content", []))
            if m.get("stop_reason") == "max_tokens":
                log(f"  응답 잘림(max_tokens) {o['custom_id']}")
            out[o["custom_id"]] = (txt, m.get("usage", {}))
        else:
            log(f"  배치 항목 실패 {o['custom_id']}: {json.dumps(res, ensure_ascii=False)[:300]}")
    return out


def load_items(keys):
    want, out = set(keys), {}
    for p in sorted(DAYS.glob("*.json")):
        doc = read_json(p) or {}
        for k, it in doc.get("items", {}).items():
            if k in want:
                out[k] = (p, reclassify(it))
    return out


def run(minutes=300, limit=None, dry=False):
    t0 = time.time()
    deadline = t0 + minutes * 60 - 15 * 60                 # 저장·올리기 시간 15분 남김
    now = today()
    st = read_json(STATE_F, {"stage": "enrich", "batches": [], "done": 0, "usd": 0.0})
    if st["stage"] == "enrich" and not limit:                # 시험(--limit)은 보강을 건너뛰고 이미 보강된 것만
        ok, _ = enrich(now, deadline)
        if not ok:
            write_json(STATE_F, st, pretty=True); return 3
        st["stage"] = "gen"; write_json(STATE_F, st, pretty=True)
    pl = [packs.load(i) for i in packs.all_ids()]
    while True:
        cur = st.get("cur")
        if not cur:                                          # 새 묶음 만들기
            keys = targets(now, limit or CHUNK, enriched_only=bool(limit), fails=st.get("fails"))
            if limit:
                keys = keys[:limit]
            if not keys:
                st["stage"] = "done"; write_json(STATE_F, st, pretty=True)
                log(f"과거분 정리 끝 · 누적 {st['done']}건 · 약 ${st['usd']:.2f}")
                return 0
            items = load_items(keys)
            reqs = [{"custom_id": _cid(k), "params": {"model": MODEL, "max_tokens": 6000, "system": llm.SYSTEM,
                                                      "messages": [{"role": "user", "content": llm.gen_prompt([items[k][1]])}]}}
                    for k in keys if k in items]
            log(f"생성 배치: {len(reqs)}건 ({MODEL})")
            if dry:
                print(json.dumps(reqs[0], ensure_ascii=False)[:3000]); return 0
            cur = st["cur"] = {"keys": keys, "gen": submit(reqs), "review": None}
            write_json(STATE_F, st, pretty=True)
        items = load_items(cur["keys"])
        j = wait(cur["gen"], deadline)
        if j is None:
            write_json(STATE_F, st, pretty=True); return 3
        gen = results(j)
        made, review_q = {}, []
        for k, (p, it) in items.items():
            g = gen.get(_cid(k))
            if not g:
                continue
            o = next((x for x in llm._parse(g[0]) if isinstance(x, dict)), None)
            if not o:
                log(f"  읽지 못한 응답 {k}: {g[0][:300]!r} … {g[0][-150:]!r}")
                continue
            srcs = llm.sources(it)
            rk = llm.risky(it, pl, "\n".join(srcs.values()) + it["name"])
            ai, problems = llm.verify(o, it, srcs, rk)
            made[k] = (ai, problems)
            if not problems and not ai["skip"] and ai.get("title"):
                review_q.append(it)                          # 과거분은 전부 2차 검토
        gen_usd = sum(llm.usd(MODEL, u) for _, u in gen.values()) / 2
        if not cur.get("review") and review_q:
            reqs = [{"custom_id": _cid(it["key"]), "params": {"model": llm.REVIEW_MODEL, "max_tokens": 1000, "system": llm.REVIEW,
                                                              "messages": [{"role": "user", "content": llm.review_prompt([it], {it["key"]: made[it["key"]][0]})}]}}
                    for it in review_q]
            cur["review"] = submit(reqs)
            log(f"검토 배치: {len(reqs)}건 ({llm.REVIEW_MODEL})")
            write_json(STATE_F, st, pretty=True)
        rv, rev_usd = {}, 0.0
        if cur.get("review"):
            j = wait(cur["review"], deadline)
            if j is None:
                write_json(STATE_F, st, pretty=True); return 3
            for cid, (txt, u) in results(j).items():
                o = next((x for x in llm._parse(txt) if isinstance(x, dict)), None)
                if o is not None:
                    rv[cid] = o
                rev_usd += llm.usd(llm.REVIEW_MODEL, u) / 2
        # 저장
        stat = {"ok": 0, "fallback": 0}
        by_file = {}
        for k, (ai, problems) in made.items():
            p, _ = items[k]
            if any(it["key"] == k for it in review_q):
                llm.apply_review(ai, problems, rv.get(_cid(k)))
            ai = llm.finalize(ai, problems, MODEL)
            ai["review_model"] = llm.REVIEW_MODEL
            by_file.setdefault(p, {})[k] = ai
            stat[ai["status"]] += 1
        for p, upd in by_file.items():
            doc = read_json(p)
            for k, ai in upd.items():
                if k in doc["items"] and (doc["items"][k].get("ai") or {}).get("v") != llm.AI_V:
                    doc["items"][k]["ai"] = ai
            write_json(p, doc)
        # 결과가 없는 항목: 다음 묶음에서 다시 (두 번 실패하면 원문만으로 표시해 빼기 — 다시 하려면 ai를 지우면 됨)
        fails = st.setdefault("fails", {})
        for k, (p, it) in items.items():
            if k in made:
                fails.pop(k, None); continue
            fails[k] = fails.get(k, 0) + 1
            if fails[k] >= 2:
                doc = read_json(p)
                if k in doc["items"] and (doc["items"][k].get("ai") or {}).get("v") != llm.AI_V:
                    doc["items"][k]["ai"] = {"v": llm.AI_V, "status": "fallback", "problems": ["생성 결과 없음"], "model": MODEL}
                    write_json(p, doc)
        st["done"] += len(made)
        st["usd"] = round(st["usd"] + gen_usd + rev_usd, 3)
        st["cur"] = None
        st["batches"].append({"at": time.strftime("%Y-%m-%d %H:%M"), "n": len(cur["keys"]), "got": len(made), **stat,
                              "usd": round(gen_usd + rev_usd, 3)})
        write_json(STATE_F, st, pretty=True)
        status("backlog", stage=st["stage"], done=st["done"], usd=st["usd"])
        log(f"묶음 저장: {len(made)}/{len(cur['keys'])}건 · 통과 {stat['ok']} · 원문만 {stat['fallback']} · 이번 ${gen_usd + rev_usd:.2f} · 누적 {st['done']}건 ${st['usd']:.2f}")
        from . import sync
        sync.push()
        if limit or time.time() > deadline:
            return 3 if not limit else 0
