"""모델 비교 시험 — 같은 항목을 여러 모델로 정리해 검증 통과율·비용을 비교 (저장은 안 함)

  python -m lcf bench --models claude-sonnet-5-5,claude-haiku-5-5 [--n 50] [--days 30]

- 표본: 최근 N일 중 정리 대상에서 고루 (분야 팩 · 돈 관련 · 조례 조문 비교 · 제정 · 고시 · 그 밖의 법령)
- 2차 검토는 모든 모델 결과에 같은 검토자(LCF_REVIEW_MODEL, 기본 Sonnet)로, 돈 관련이 아니어도 전부
- 결과: data/lcf/bench/<날짜>/  keys.txt · <모델>.json · report.md (요약 표 + 항목별 나란히)
"""
import datetime as dt, json, os, random, re

from . import llm, packs
from .classify import reclassify
from .core import DATA, DAYS, log, read_json, today, write_json


def sample(n, days, seed=7):
    pl = [packs.load(i) for i in packs.all_ids()]
    since = (today() - dt.timedelta(days=days)).isoformat()
    groups = {k: [] for k in ("pack", "money", "ordin_diff", "new", "admrul", "law")}
    for p in sorted(DAYS.glob("*.json")):
        if p.stem < since:
            continue
        for it in (read_json(p) or {}).get("items", {}).values():
            it = reclassify(it)
            if not llm.wanted(it, set(), pl):
                continue
            src = "\n".join(llm.sources(it).values())
            if any(packs.match(it, x, set()) for x in pl):
                groups["pack"].append(it["key"])
            elif llm.RISKY.search(src + it["name"]):
                groups["money"].append(it["key"])
            elif it["kind"] == "ordin" and (it.get("detail") or {}).get("diff"):
                groups["ordin_diff"].append(it["key"])
            elif it["change"] in ("제정", "전부개정"):
                groups["new"].append(it["key"])
            elif it["kind"] == "admrul":
                groups["admrul"].append(it["key"])
            else:
                groups["law"].append(it["key"])
    rnd = random.Random(seed)
    quota = {"pack": 6, "money": 14, "ordin_diff": 10, "new": 8, "admrul": 4, "law": 8}
    keys, kinds = [], {}
    for g, q in quota.items():
        pick = rnd.sample(groups[g], min(q, len(groups[g])))
        keys += pick; kinds.update({k: g for k in pick})
    rest = [k for g in groups.values() for k in g if k not in kinds]
    for k in rnd.sample(rest, max(0, min(n - len(keys), len(rest)))):
        keys.append(k); kinds[k] = "extra"
    log("표본: " + ", ".join(f"{g} {sum(1 for v in kinds.values() if v == g)}" for g in list(quota) + ["extra"]))
    return keys[:n], kinds


def run(models, n=50, days=30):
    os.environ["LCF_REVIEW_ALL"] = "1"
    llm.REVIEW_ALL = True
    out = DATA / "bench" / today().isoformat()
    out.mkdir(parents=True, exist_ok=True)
    keys, kinds = sample(n, days)
    (out / "keys.txt").write_text("\n".join(keys) + "\n", encoding="utf-8")
    stats, res = {}, {}
    for m in models:
        log(f"===== {m}")
        stats[m] = llm.run(model=m, save=False, keys=keys, out=out / f"{m}.json", limit=len(keys))
        res[m] = (read_json(out / f"{m}.json") or {}).get("results", {})
    items = {}
    for p in sorted(DAYS.glob("*.json")):
        for k, it in (read_json(p) or {}).get("items", {}).items():
            if k in kinds:
                items[k] = it
    write_report(out / "report.md", models, stats, res, items, kinds, keys)
    log(f"보고서: {out / 'report.md'}")


def _pct(a, b):
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "-"


def write_report(path, models, stats, res, items, kinds, keys):
    L = [f"# 모델 비교 시험 {today().isoformat()}", "", f"표본 {len(keys)}건 · 2차 검토 {llm.REVIEW_MODEL}(모두 검토)", "",
         "| 모델 | 받은 결과 | 통과(화면에 요약) | 원문만 | 2차 검토 걸림 | 발췌 글자 일치 | 숫자로 버린 문장 | 비용 | 건당 |",
         "|---|---|---|---|---|---|---|---|---|"]
    for m in models:
        s = stats[m] or {}
        n = s.get("done", 0)
        gen = s.get("usage", {}).get(m, {})
        gen_usd = llm.usd(m, gen)
        L.append(f"| {m} | {n}/{len(keys)} | {_pct(s.get('ok', 0), n)} | {s.get('fallback', 0)} | {_pct(s.get('review_fail', 0), s.get('reviewed', 0))} | "
                 f"{_pct(s.get('quotes_ok', 0), s.get('quotes_total', 0))} | {s.get('dropped', 0)} | 생성 ${gen_usd:.3f} (+검토 포함 ${s.get('usd', 0):.3f}) | "
                 f"{(gen_usd / n * 100 if n else 0):.2f}센트 |")
    L += ["", "## 유형별 통과", "", "| 유형 | " + " | ".join(models) + " |", "|---|" + "---|" * len(models)]
    for g in ("pack", "money", "ordin_diff", "new", "admrul", "law", "extra"):
        ks = [k for k in keys if kinds.get(k) == g]
        if ks:
            L.append(f"| {g} ({len(ks)}) | " + " | ".join(_pct(sum(1 for k in ks if (res[m].get(k) or {}).get('status') == 'ok'), len(ks)) for m in models) + " |")
    L += ["", "## 항목별", ""]
    for k in keys:
        it = items.get(k)
        if not it:
            continue
        src = llm.source_text(it)
        L += [f"### {it['name']} · {it['change']} · {it['announced']} · `{k}` · {kinds.get(k)}", "",
              "<details><summary>원문</summary>", "", "```", src[:2500], "```", "</details>", ""]
        for m in models:
            a = res[m].get(k)
            if not a:
                L += [f"**{m}** — 결과 없음", ""]; continue
            body = a if a.get("status") == "ok" else (a.get("draft") or {})
            L.append(f"**{m}** — {a.get('status')}" + (f" · 문제: {'; '.join(a.get('problems') or [])}" if a.get("problems") else "")
                     + f" · 발췌 {a.get('checks', {}).get('quotes_ok', 0)}/{a.get('checks', {}).get('quotes_total', 0)}")
            L.append(f"- 제목: {body.get('title', '')}")
            L.append(f"- 요약: {body.get('summary', '')}")
            for c in body.get("changes") or []:
                L.append(f"- {c.get('what', '')}: {c.get('before') or ('(새로 생김)' if c.get('new') else '(전 모름)')} → {c.get('after', '')}"
                         + (f"  〔{c['quote']}〕" if c.get("quote") else "  〔발췌 없음〕"))
            w = body.get("when") or {}
            if w:
                L.append(f"- 언제: {w.get('start', '')} · 대상: {w.get('target', '')} · 이전: {w.get('transition', '')} · 다른 시행일: {w.get('other', '')}")
            L.append("")
    path.write_text("\n".join(L), encoding="utf-8")
