"""질문 응답용 색인 — Worker(/ask)가 R2에서 읽는 한 줄 한 항목 TSV

  python -m lcf askindex [--put]     data/lcf/ask/index.tsv 생성 (--put: R2에 바로 올림)

열: key kind name type change org announced effective title summary points packs page url
- 내용 있는 항목만 (상세 페이지와 같은 기준). 최신순
- 탭·줄바꿈은 공백으로
"""
from . import packs
from .classify import reclassify
from .core import DATA, DAYS, config, log, read_json
from .digest import change_points, law_line, ordin_line
from .pages import has_content, slug

OUT = DATA / "ask" / "index.tsv"
COLS = ["key", "kind", "name", "type", "change", "org", "announced", "effective", "title", "summary", "points", "packs", "page", "url"]


def _c(s):
    return " ".join(str(s or "").split())


def run(put=False):
    profs = config("profiles").get("profiles", [])
    regions = {r for p in profs for r in p.get("regions", [])}
    pack_list = [packs.load(pid) for pid in packs.all_ids()]
    rows = []
    for p in sorted(DAYS.glob("*.json")):
        for it in (read_json(p) or {}).get("items", {}).values():
            reclassify(it)
            if not has_content(it):
                continue
            ai = it.get("ai") or {}
            summ = ai.get("summary") or (law_line(it) if it["kind"] == "law" else ordin_line(it))
            pts = " / ".join(f"{c.get('what', '')}: {c.get('before') or '없음'} → {c['after']}" for c in ai.get("changes") or []) \
                if ai.get("status") == "ok" else ""
            pk = [x["id"] for x in pack_list if packs.match(it, x, regions)]
            rows.append([it["key"], it["kind"], it["name"], it["type"], it["change"], it["org"], it["announced"], it["effective"],
                         ai.get("title", ""), summ, pts or " / ".join(change_points(it, limit=5)), ",".join(pk),
                         f"c/{slug(it)}.html", it["url"]])
    rows.sort(key=lambda r: r[6], reverse=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\t".join(COLS) + "\n" + "\n".join("\t".join(_c(x) for x in r) for r in rows) + "\n", encoding="utf-8")
    log(f"질문 색인 {len(rows)}건 · {OUT.stat().st_size / 1e6:.2f}MB")
    vocab()
    if put:
        from . import sync
        sync.put(["ask/index.tsv", "ask/vocab.json"])


def vocab():
    """상황 → 조건 변환(Worker /profile)이 쓰는 낱말 목록: 분야(주제·팩), 지역(자치법규 기관명)"""
    import json
    cls = config("classify")
    orgs = set()
    for p in sorted(DAYS.glob("*.json"))[-400:]:
        orgs |= {it["org"] for it in (read_json(p) or {}).get("items", {}).values() if it["kind"] == "ordin" and it["org"]}
    v = {"topics": list(cls["topics"].keys()),
         "packs": [{"id": x["id"], "name": x["name"], "desc": x.get("desc", "")} for x in (packs.load(i) for i in packs.all_ids())],
         "regions": sorted(orgs),
         "aud": [{"name": g["name"], "tags": [x for x, _ in g["tags"]]} for g in config("audience")["groups"]]}
    (OUT.parent / "vocab.json").write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
    log(f"조건 낱말: 분야 {len(v['topics'])} · 팩 {len(v['packs'])} · 지역 {len(v['regions'])}")
