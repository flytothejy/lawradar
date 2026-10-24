"""분야 팩 — 사람이 한 번 손본 '이 분야에 해당하는 법령·고시·조례와 조건' 묶음 (config/packs/*.json)

  match(it, pack) → None | {"tags": [조건 라벨], "why": "이름" | "개정 이유: 양도소득·1세대"}
  python -m lcf pack <id> [--from 2026-09-21] [--to 2026-10-21]   팩에 걸린 변경을 날짜순으로 출력 (검증용)
"""
import datetime as dt, json, re
from functools import lru_cache

from .core import CONFIG, DAYS, read_json, today

PACKS = CONFIG / "packs"


@lru_cache(None)
def load(pid):
    p = read_json(PACKS / f"{pid}.json")
    if not p:
        raise SystemExit(f"분야 팩이 없습니다: {pid} (config/packs/{pid}.json)")
    rx = lambda k: re.compile(p[k]) if p.get(k) else None
    p["_rx"] = {"always": rx_or(p["laws"].get("always")), "mention": rx_or(p["laws"].get("mention")),
                "kw": rx("keywords"), "admrul": rx("admrul"), "ordin": rx("ordin")}
    for c in p.get("conditions", []):
        c["_rx"] = re.compile(c["rx"])
    return p


def rx_or(s):
    return re.compile(s) if s else None


def all_ids():
    return sorted(x.stem for x in PACKS.glob("*.json"))


def text_of(it):
    d = it.get("detail") or {}
    return " ".join([d.get("why") or ""] + (d.get("main") or []) + [d.get("purpose") or ""]
                    + [c.get("title", "") + " " + c.get("before", "") + " " + c.get("after", "") for c in d.get("changes") or []])


def match(it, pack, regions=()):
    R = pack["_rx"]
    name, body = it["name"], text_of(it)
    why = None
    if it["kind"] == "law":
        if it["cls"]["level"] == "low":                       # 타법개정·후속 정비는 팩에서도 뺌
            return None
        if R["always"] and R["always"].search(name):
            why = "이름"
        elif R["mention"] and R["mention"].search(name):
            hits = sorted(set(R["kw"].findall(body))) if R["kw"] else []
            if not hits:
                return None
            why = "개정 이유: " + "·".join(hits[:4])
    elif it["kind"] == "admrul":
        if R["admrul"] and R["admrul"].search(name) and it["type"] in pack.get("admrul_kind", [it["type"]]):
            why = "이름"
    elif it["kind"] == "ordin":
        if R["ordin"] and R["ordin"].search(name) and (not regions or it["org"] in regions):
            why = "이름"
    if not why:
        return None
    tags = [c["label"] for c in pack.get("conditions", []) if c["_rx"].search(name + " " + body)]
    return {"tags": tags, "why": why}


def items(pid, start, end, regions=()):
    from .classify import reclassify
    pack, out = load(pid), []
    d = start
    while d <= end:
        for it in (read_json(DAYS / f"{d.isoformat()}.json") or {}).get("items", {}).values():
            m = match(reclassify(it), pack, regions)
            if m:
                out.append({**it, "pack": m})
        d += dt.timedelta(days=1)
    return out


def preview(pid, start=None, end=None):
    end = end or today()
    start = start or (end - dt.timedelta(days=30))
    rows = items(pid, start, end)
    print(f"[{load(pid)['name']}] {start} ~ {end}: {len(rows)}건")
    for it in rows:
        print(f"\n{it['announced']} {it['name']} ({it['change']}, 시행 {it['effective']}) — {it['pack']['why']}")
        if it["pack"]["tags"]:
            print("  해당: " + ", ".join(it["pack"]["tags"]))
        for c in (it.get("detail") or {}).get("changes") or []:
            print(f"  · {c['title'] or '(본문)'}" + (f"  [{' / '.join(c['short'])}]" if c["short"] else ""))
