"""주간 다이제스트 — 구독 단위(config/profiles.json)별로 지난 7일 변경을 골라 쉬운 요약으로

  python -m lcf digest [프로필id] [--to 2026-10-20] [--days 7] [--no-notify]

구성
  🏘 우리 동네 조례·규칙   지역(regions) 자치법규 중 정비·내부 행정을 뺀 것. 바뀐 조문·숫자를 한 줄로
  🏛 생활에 영향 있는 법령  법률·시행령·시행규칙 중 생활 주제(또는 프로필 topics)에 걸리는 제정·개정
  ⏰ 곧 시행               앞으로 14일 안에 시행되는 것 (전에 공포된 것 포함)
결과: digest/<프로필>/<마지막날>.json (화면용) + 텔레그램
"""
import datetime as dt, html, re

from . import notify, packs
from .classify import reclassify
from .core import BRAND, DAYS, DIGEST, config, log, read_json, today, write_json

LV = {"high": 0, "mid": 1, "low": 2}
LAW_RANK = {"법률": 0, "대통령령": 1, "총리령": 2}
e = lambda x: html.escape(str(x or ""), quote=False)


def load_days(start, end):
    out = []
    d = start
    while d <= end:
        out += [reclassify(i) for i in (read_json(DAYS / f"{d.isoformat()}.json") or {}).get("items", {}).values()]
        d += dt.timedelta(days=1)
    return out


def _short(s, n):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[:n - 1].rstrip() + "…"


def _strip_label(s):
    return re.sub(r"^\s*([가-하]\.|\d+\)|[○◦·•-])\s*", "", s or "")


def ordin_line(it):
    ai = it.get("ai") or {}
    if ai.get("summary"):
        return ai["summary"]
    """조례 한 건이 무엇을 바꿨는지 한 줄"""
    det = it.get("detail") or {}
    d = det.get("diff") or {}
    if it["change"] in ("제정", "폐지제정"):
        p = re.sub(r"^제1조\(목적\)\s*", "", det.get("purpose", ""))
        return "새로 만듦 — " + _short(p, 110) if p else "새로 만듦"
    if it["change"] == "폐지":
        return "폐지"
    bits = []
    nums = [(x["jo"], x["title"], n) for x in d.get("changed", []) for n in x.get("nums", [])]
    for jo, title, n in nums[:2]:
        bits.append(f"{jo}({title}): {n}" if title else f"{jo}: {n}")
    if d.get("added"):
        bits.append("신설 " + ", ".join(d["added"][:3]))
    if not bits and d.get("changed"):
        tt = [f"{x['jo']}({x['title']})" if x["title"] else x["jo"] for x in d["changed"][:3]]
        bits.append(", ".join(tt) + (f" 등 {d['n_changed']}개 조 개정" if d["n_changed"] > 3 else " 개정"))
    if not bits and det.get("marked"):
        m = det["marked"][0]
        bits.append(f"{m['jo']}({m['title']}) {m['kind']}: " + _short(m["text"], 90))
    if d.get("removed"):
        bits.append("삭제 " + ", ".join(d["removed"][:2]))
    return " · ".join(bits) or it["change"]


DEFN = re.compile(r"정의(함|하고|하며|를)|목적(을|으로 함)|약칭|용어의 뜻")


def law_line(it):
    ai = it.get("ai") or {}
    if ai.get("summary"):
        return ai["summary"]
    """제정: 정의·목적 조항을 건너뛴 첫 주요내용 / 개정: 개정이유 한 문단(…하려는 것임)"""
    det = it.get("detail") or {}
    main = [_strip_label(m) for m in det.get("main") or []]
    if it["change"] in ("제정", "전부개정"):
        t = next((m for m in main if not DEFN.search(m) and len(m) > 15), main[0] if main else det.get("why", ""))
    else:
        t = det.get("why") or (main[0] if main else "")
    t = re.sub(r"\(안 제[^)]*\)|\(법률 제\d+호[^)]*\)", "", t)
    return _short(t, 130)


def _other_region(it, prof):
    """이름에 다른 지역이 박힌 법령(강원특별자치도 … 특별법 시행령 등)은 그 지역 구독자에게만"""
    rx = config("classify").get("region_only")
    m = re.search(rx, it["name"]) if rx and it["kind"] != "ordin" else None
    return bool(m) and not any(m.group(0) in r for r in prof.get("regions", []))


def _wanted_topic(it, prof):
    if _other_region(it, prof):
        return False
    want = set(prof.get("topics") or [])
    c = it["cls"]
    return bool(set(c["topics"]) & want) if want else c["life"]


def build(prof, end, days=7):
    start = end - dt.timedelta(days=days - 1)
    items = load_days(start, end)
    regions = prof.get("regions", [])
    ordin_all = [i for i in items if i["kind"] == "ordin" and i["org"] in regions]
    ordin = [i for i in ordin_all if i["cls"]["level"] != "low"]
    ordin.sort(key=lambda i: (not i["cls"].get("support"), LV[i["cls"]["level"]], not i["cls"].get("nums"),
                              not i["cls"]["life"], regions.index(i["org"]), i["name"]))
    laws_all = [i for i in items if i["kind"] == "law"]
    laws = [i for i in laws_all if i["cls"]["level"] != "low" and _wanted_topic(i, prof)]
    laws.sort(key=lambda i: (LV[i["cls"]["level"]], not i["cls"].get("by_name"), LAW_RANK.get(i["type"], 3), i["name"]))
    adm = [i for i in items if i["kind"] == "admrul" and i["type"] == "고시" and i["cls"]["level"] != "low" and _wanted_topic(i, prof)]
    # 곧 시행: 앞으로 14일 — 최근 1년 공포분까지 훑음
    soon_from, soon_to = end + dt.timedelta(days=1), end + dt.timedelta(days=14)
    pool = load_days(end - dt.timedelta(days=370), end)
    soon = [i for i in pool if i["effective"] and soon_from.isoformat() <= i["effective"] <= soon_to.isoformat()
            and i["effective"] != i["announced"] and i["cls"]["level"] != "low"
            and ((i["kind"] == "ordin" and i["org"] in regions) or (i["kind"] == "law" and _wanted_topic(i, prof)))]
    soon.sort(key=lambda i: (i["effective"], LV[i["cls"]["level"]]))
    other = sum(1 for i in items if i["kind"] == "ordin" and i["org"] not in regions)
    pk = []
    for pid in prof.get("packs", []):
        pack = packs.load(pid)
        rows = []
        for i in items:
            m = packs.match(i, pack, regions)
            if m:
                ai = i.get("ai") or {}
                pts = change_points(i)
                if ai.get("summary"):
                    pts = [ai["summary"]] + [x for x in pts if " → " in x][:2]
                rows.append(dict(_card(i), tags=m["tags"], why=m["why"], points=pts, line=law_line(i) if i["kind"] == "law" else ""))
        rows.sort(key=lambda r: (r["kind"] != "law", LV[r["level"]], r["name"]))
        pk.append({"id": pid, "name": pack["name"], "items": rows})
    in_pack = {r["key"] for p_ in pk for r in p_["items"]}
    laws = [i for i in laws if i["key"] not in in_pack]
    return {"profile": prof["id"], "name": prof["name"], "regions": regions, "start": start.isoformat(), "end": end.isoformat(), "packs": pk,
            "ordin": [dict(_card(i), line=ordin_line(i)) for i in ordin[:prof.get("ordin_max", 25)]],
            "laws": [dict(_card(i), line=law_line(i)) for i in laws[:prof.get("law_max", 12)]],
            "admrul": [_card(i) for i in adm[:5]],
            "soon": [_card(i) for i in soon[:10]],
            "counts": {"ordin_region": len(ordin_all), "ordin_shown": len(ordin), "ordin_noise": len(ordin_all) - len(ordin),
                       "ordin_more": max(0, len(ordin) - prof.get("ordin_max", 25)), "ordin_elsewhere": other,
                       "ordin_regions": len({i["org"] for i in items if i["kind"] == "ordin" and i["cls"]["level"] != "low"}),
                       "law": len(laws_all), "law_shown": len(laws), "law_noise": sum(1 for i in laws_all if i["cls"]["level"] == "low"),
                       "law_more": max(0, len(laws) - prof.get("law_max", 12)), "admrul": sum(1 for i in items if i["kind"] == "admrul")}}


def change_points(i, limit=4):
    """개정 이유에서 뽑은 변경 항목: '조정대상지역 일시적 2주택 비과세 요건 강화 — 3년 → 2년'"""
    out = []
    for c in ((i.get("detail") or {}).get("changes") or [])[:limit]:
        t = re.sub(r"\s*(에 대한|의)\s*", " ", c["title"]).strip() if c["title"] else ""
        if not t and c.get("after"):                  # 제목 없는 변경: '앞으로는 …' 문장 앞부분으로 무엇이 바뀌는지 보여 줌
            t = _short(re.sub(r"^(조정대상지역 여부를 불문하고\s*)", "", c["after"]), 70)
        sh = c["short"][0] if c["short"] else ""
        if t or sh:
            out.append(" — ".join(x for x in (t, sh) if x))
    return out


def _card(i):
    ai = i.get("ai") or {}
    return {k: i.get(k) for k in ("kind", "key", "name", "type", "change", "org", "announced", "effective", "url")} | \
           {"level": i["cls"]["level"], "topics": i["cls"]["topics"], "support": i["cls"].get("support", False),
            "title": ai.get("title", ""), "who": ai.get("who", "")}


def _md(d, ref=None):
    if not d:
        return ""
    ref = ref or today().isoformat()
    far = abs((dt.date.fromisoformat(d) - dt.date.fromisoformat(ref)).days) > 150
    return (f"{d[2:4]}.{int(d[5:7])}.{int(d[8:10])}" if far else f"{int(d[5:7])}/{int(d[8:10])}")


def _ordin_tg(g):
    c, L = g["counts"], []
    L.append(f"🏘 <b>우리 동네 조례·규칙 {c['ordin_shown']}건</b>"
             + (f" (내부 행정·자구 정비 {c['ordin_noise']}건은 뺐어요)" if c["ordin_noise"] else ""))
    if not g["ordin"]:
        L.append("  이번 주 바뀐 것이 없어요")
    for x in g["ordin"]:
        org = _short_org(x["org"], g["regions"])
        tag = "💰 " if x["support"] else ("🆕 " if x["change"] == "제정" else "")
        eff = f" · 시행 {_md(x['effective'], g['end'])}" if x["effective"] and x["effective"] != x["announced"] else ""
        if x.get("title"):
            L.append(f"• {tag}<b>{e(x['title'])}</b>")
            L.append(f"  <a href=\"{x['url']}\">{e(x['name'])}</a> <i>[{e(org)}·{e(x['change'])}{eff}]</i>")
        else:
            L.append(f"• {tag}<a href=\"{x['url']}\">{e(x['name'])}</a> <i>[{e(org)}·{e(x['change'])}{eff}]</i>")
        L.append(f"  {e(x['line'])}")
    if c["ordin_more"]:
        L.append(f"  … 외 {c['ordin_more']}건")
    return L


def _short_org(org, regions):
    """프로필 지역이 한 시·도 안이면 시·도 이름은 떼고 보여 줌"""
    top = {r.split()[0] for r in regions}
    return org.split(" ", 1)[1] if len(top) == 1 and " " in org and org.split()[0] in top else org


def to_telegram(g):
    c = g["counts"]
    L = [f"<b>📡 {BRAND} 주간 브리핑 · {e(g['name'])}</b>",
         f"{_md(g['start'])} ~ {_md(g['end'])} 공포·발령분", ""]
    for p_ in g.get("packs", []):
        L.append(f"📦 <b>{e(p_['name'])} {len(p_['items'])}건</b>")
        if not p_["items"]:
            L.append("  이번 주 바뀐 것이 없어요")
        for x in p_["items"]:
            eff = f" · 시행 {_md(x['effective'], g['end'])}" if x["effective"] else ""
            if x.get("title"):
                L.append(f"• <b>{e(x['title'])}</b>")
                L.append(f"  <a href=\"{x['url']}\">{e(x['name'])}</a> <i>[{e(x['change'])}{eff}]</i>")
            else:
                L.append(f"• <a href=\"{x['url']}\">{e(x['name'])}</a> <i>[{e(x['change'])}{eff}]</i>")
            for pt in x["points"] or ([x["line"]] if x["line"] else []):
                L.append(f"  · {e(pt)}")
            if x["tags"]:
                L.append(f"  <i>이런 분께 해당: {e(', '.join(x['tags']))}</i>")
        L.append("")
    if g.get("regions"):
        L += _ordin_tg(g)
    else:
        L.append(f"🏘 이번 주 조례가 바뀐 지역 {c.get('ordin_regions', 0)}곳 — 지역 페이지에서 볼 수 있어요")
    L += ["", f"🏛 <b>생활에 영향 있는 법령 {c['law_shown']}건</b> (이번 주 공포 {c['law']}건 중 · 후속 정비·내부 행정 {c['law_noise']}건 제외)"]
    for x in g["laws"]:
        eff = f" · 시행 {_md(x['effective'], g['end'])}" if x["effective"] else ""
        if x.get("title"):
            L.append(f"• <b>{e(x['title'])}</b>")
            L.append(f"  <a href=\"{x['url']}\">{e(x['name'])}</a> <i>[{e(x['change'])}{eff}]</i>")
        else:
            L.append(f"• <a href=\"{x['url']}\">{e(x['name'])}</a> <i>[{e(x['change'])}{eff}]</i>")
        if x["line"]:
            L.append(f"  {e(x['line'])}")
    if c["law_more"]:
        L.append(f"  … 외 {c['law_more']}건")
    if g["soon"]:
        L += ["", "⏰ <b>곧 시행 (14일 안)</b>"]
        for x in g["soon"]:
            L.append(f"• {_md(x['effective'])} " + (f"{e(x['title'])} — " if x.get("title") else "") + f"<a href=\"{x['url']}\">{e(x['name'])}</a>")
    if g["admrul"]:
        L += ["", f"📋 <b>고시·지침</b> " + ", ".join(f"<a href=\"{x['url']}\">{e(x['name'])}</a>" for x in g["admrul"][:6])]
    return L


def run(pid=None, end=None, days=7, send=True):
    end = end or (today() - dt.timedelta(days=1))
    profs = [p for p in config("profiles").get("profiles", []) if not pid or p["id"] == pid]
    for prof in profs:
        g = build(prof, end, days)
        write_json(DIGEST / prof["id"] / f"{end.isoformat()}.json", g)
        lines = to_telegram(g)
        if send:
            notify.send_chunks(lines)
        else:
            print("\n".join(lines))
        log(f"다이제스트 {prof['id']}: 조례 {len(g['ordin'])} · 법령 {len(g['laws'])} · 곧 시행 {len(g['soon'])}")
