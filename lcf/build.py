"""화면 데이터 — site/api/ 아래 JSON (GitHub Pages가 web/index.html과 함께 배포)

  recent.json          최근 30일 공포·발령분 전체 (화면에서 종류·중요도·지역·주제로 거름)
  digest/<id>.json     프로필별 최신 다이제스트 + 지난 목록
  timeline.json        내 타임라인 재료: 최근 90일 공포·발령분(정비 제외) + 앞으로 시행될 것(최근 1년 공포분)
                       화면(web/match.js)이 사용자 조건(지역·분야·법령·낱말)으로 거름
"""
import re
import datetime as dt

from . import packs
from .core import DATA, DAYS, DIGEST, SITE, config, log, read_json, today, write_json
from .classify import reclassify
from .digest import law_line, ordin_line

KEEP = 30


def run():
    end = today()
    rows = []
    for p in sorted(DAYS.glob("*.json")):
        if p.stem < (end - dt.timedelta(days=KEEP)).isoformat():
            continue
        for it in (read_json(p) or {}).get("items", {}).values():
            c = reclassify(it)["cls"]
            line = ordin_line(it) if it["kind"] == "ordin" and it.get("detail") else (law_line(it) if it["kind"] == "law" else "")
            if it["kind"] == "law" and it["change"] in ("타법개정", "타법폐지"):
                det = it.get("detail") or {}
                line = (f"「{det['cause']}」 개정에 따른 정비" if det.get("cause") else "") + (" — " + det["edit"][0] if det.get("edit") else "")
            ai = it.get("ai") or {}
            rows.append([it["kind"], it["name"], it["type"], it["change"], it["org"], it["announced"], it["effective"],
                         c["level"], "|".join(c["topics"]), int(bool(c.get("support"))), line[:200], it["url"], ai.get("title", ""), it["key"]])
    rows.sort(key=lambda r: (r[5], r[7] != "high"), reverse=True)
    cols = ["kind", "name", "type", "change", "org", "announced", "effective", "level", "topics", "support", "line", "url", "title", "key"]
    write_json(SITE / "api" / "recent.json", {"built": end.isoformat(), "cols": cols, "rows": rows})
    for prof in config("profiles").get("profiles", []):
        hist = sorted((DIGEST / prof["id"]).glob("*.json"))
        if hist:
            write_json(SITE / "api" / "digest" / f"{prof['id']}.json",
                       {"latest": read_json(hist[-1]), "history": [h.stem for h in hist][-20:]})
            for h in hist[-20:]:
                write_json(SITE / "api" / "digest" / prof["id"] / h.name, read_json(h))
    timeline(end)
    pk = [packs.load(i) for i in packs.all_ids()]                 # 조건 화면에서 고를 수 있는 분야
    write_json(SITE / "api" / "topics.json", [{"id": x["id"], "name": x["name"]} for x in pk] +
               [{"id": k, "name": k} for k in config("classify")["topics"] if k not in config("classify").get("life_exclude", [])])
    ask = (DATA / "state" / "ask_url.txt")
    write_json(SITE / "config.json", {"ask": ask.read_text().strip() if ask.exists() else ""})
    write_json(SITE / "api" / "profiles.json", [{"id": p["id"], "name": p["name"]} for p in config("profiles").get("profiles", [])])
    log(f"화면 데이터: 최근 {KEEP}일 {len(rows)}건")


TL_DAYS, TL_SOON = 90, 120
BASE = re.compile(r"\s*(시행령|시행규칙)$")


def timeline(end):
    """조건 매칭용 항목 목록. base = 시행령·시행규칙을 뗀 법령 이름 (지켜볼 법령과 비교)"""
    from .pages import has_content, slug
    recent = (end - dt.timedelta(days=TL_DAYS)).isoformat()
    soon_to = (end + dt.timedelta(days=TL_SOON)).isoformat()
    pack_list = [packs.load(i) for i in packs.all_ids()]
    rows, total = [], 0
    for p in sorted(DAYS.glob("*.json"))[-400:]:
        for it in (read_json(p) or {}).get("items", {}).values():
            if it["announced"] >= (end - dt.timedelta(days=30)).isoformat():
                total += 1
            c = reclassify(it)["cls"]
            if c["level"] == "low":
                continue
            upcoming = it["effective"] and end.isoformat() < it["effective"] <= soon_to
            if it["announced"] < recent and not upcoming:
                continue
            if it["kind"] == "admrul" and it["type"] != "고시":
                continue
            ai = it.get("ai") or {}
            line = ai.get("summary") or (ordin_line(it) if it["kind"] == "ordin" and it.get("detail") else (law_line(it) if it["kind"] == "law" else ""))
            pk = ",".join(x["id"] for x in pack_list if packs.match(it, x, set()))
            rows.append([it["key"], it["kind"], it["name"], BASE.sub("", it["name"]) if it["kind"] == "law" else "", it["type"], it["change"],
                         it["org"], it["announced"], it["effective"], c["level"], "|".join(c["topics"]), int(bool(c.get("life"))),
                         int(bool(c.get("support"))), pk, ai.get("title", ""), (line or "")[:160],
                         f"c/{slug(it)}.html" if has_content(it) else "", it["url"]])
    rows.sort(key=lambda r: r[7], reverse=True)
    cols = ["key", "kind", "name", "base", "type", "change", "org", "announced", "effective", "level", "topics", "life",
            "support", "packs", "title", "line", "page", "url"]
    write_json(SITE / "api" / "timeline.json", {"built": end.isoformat(), "total30": total, "cols": cols, "rows": rows})
    log(f"타임라인 재료 {len(rows)}건 (최근 30일 전체 {total}건)")
