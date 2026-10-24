"""노이즈 필터·중요도·주제 태그 (규칙 기반, config/classify.json)

level
  high : 제정·전부개정 (새 제도 또는 통째 개편)
  mid  : 일부개정·폐지 — 내용을 봐야 하는 변경
  low  : 타법개정·일괄개정(다른 법 개정에 따른 정비), 내부 행정(정원·전결·여비…), 훈령·예규, 자구 정비
"""
import re
from functools import lru_cache

from .core import config


@lru_cache(None)
def _rules():
    c = config("classify")
    return {"internal": re.compile(c["internal"]), "support": re.compile(c["support"]),
            "topics": {k: re.compile(v) for k, v in c["topics"].items()},
            "life": set(c.get("life_topics", [])), "life_x": set(c.get("life_exclude", [])),
            "internal_kind": c.get("internal_kind", {}),
            "follow": re.compile(c["follow_up"]) if c.get("follow_up") else None}


def _is_life(tps):
    R = _rules()
    return bool(set(tps) & R["life"]) and not (set(tps) & R["life_x"])


LOW_CHANGE = {"타법개정", "일괄개정", "타법폐지", "일괄폐지"}
HIGH_CHANGE = {"제정", "전부개정", "폐지제정"}


def topics(text, top=None, min_hits=1):
    """이름에는 1번만 걸려도, 본문(개정 이유)에는 min_hits번 이상 걸린 주제만 — 많이 걸린 순으로 top개"""
    R = _rules()
    hits = {k: len(rx.findall(text or "")) for k, rx in R["topics"].items()}
    out = sorted((k for k, n in hits.items() if n >= min_hits), key=lambda k: -hits[k])
    return out[:top] if top else out


def topics_from_detail(it):
    """이름으로 주제를 못 찾은 법령: 개정 이유·주요내용 글에서 다시 찾음"""
    c = it["cls"]
    if c["topics"]:
        return it
    det = it.get("detail") or {}
    text = " ".join([det.get("why", "")] + det.get("main", []) + [det.get("purpose", "")])
    c["topics"] = topics(text, top=2, min_hits=2)
    c["life"] = _is_life(c["topics"])
    return it


def classify(it):
    """it: 정규화된 항목(collect.norm_*) → it['cls'] 채움"""
    R = _rules()
    name, ch = it["name"], it["change"]
    why = []
    tps = topics(name)
    internal = bool(R["internal"].search(name))
    if it["kind"] == "admrul" and it["type"] in R["internal_kind"].get("행정규칙", []):
        internal = True; why.append(f"{it['type']}(내부 지침)")
    if it["kind"] == "law" and it["type"] in ("대법원규칙", "국회규칙", "감사원규칙", "헌법재판소규칙", "중앙선거관리위원회규칙") and not tps:
        internal = True; why.append(it["type"])
    if internal and not why:
        why.append("내부 행정")
    if ch in LOW_CHANGE:
        level = "low"; why.append(f"{ch}(다른 법령 개정에 따른 정비)")
    elif internal:
        level = "low"
    elif ch in HIGH_CHANGE:
        level = "high"
    else:
        level = "mid"
    it["cls"] = {"level": level, "internal": internal, "support": bool(R["support"].search(name)),
                 "topics": tps, "life": _is_life(tps), "by_name": bool(tps), "why": why}
    return it


def refine_with_diff(it):
    """조례 diff를 본 뒤: 조문이 거의 안 바뀌었으면(용어·조항 번호 정리) low로 내림, 금액·숫자 변경은 표시"""
    d = (it.get("detail") or {}).get("diff")
    c = it["cls"]
    if not d:
        return it
    from .textdiff import _is_qty_change
    for x in d.get("changed", []):          # 숫자 판정 규칙이 바뀌어도 저장된 조각(parts)으로 다시 계산
        x["nums"] = [f"{p['before']} → {p['after']}" for p in x.get("parts", []) if _is_qty_change(p)]
    if c["level"] != "mid":
        return it
    nums = [n for x in d.get("changed", []) for n in x.get("nums", [])]
    small = sum(x.get("edits", 99) for x in d.get("changed", []))
    if not d.get("added") and not d.get("removed") and not nums and small <= 4:
        c["level"] = "low"; c["why"].append("자구 정비(바뀐 낱말 4개 이하)")
    if nums:
        c["nums"] = True
    return it


def follow_up(it):
    """법령 일부개정 중 '다른 법·조직 개편에 맞춘 후속 정비'(개정 이유로 판단) → low"""
    rx, c = _rules()["follow"], it["cls"]
    det = it.get("detail") or {}
    head = (det.get("why") or "") + " " + " ".join((det.get("main") or [])[:1])    # '개정이유 및 주요내용'은 main에만 들어감
    if rx and it["kind"] == "law" and c["level"] == "mid" and rx.search(head.strip()[:260]):
        c["level"] = "low"; c["why"].append("후속 정비(다른 법·조직 개편 반영)")
    return it


def reclassify(it):
    """저장된 항목을 지금 규칙으로 다시 판정 (config를 고치면 지난 자료에도 바로 반영)"""
    classify(it)
    if it.get("detail"):
        refine_with_diff(it)
        topics_from_detail(it)
        follow_up(it)
    ai = it.get("ai") or {}
    # AI가 '생활·영업 영향 없음'이라 본 것 → 정비. 단 법률·대통령령의 제정·전부개정은 큰 변화일 수 있어 그대로 둠
    big = it["cls"]["level"] == "high" and it["kind"] == "law" and it["type"] in ("법률", "대통령령")
    if ai.get("skip") and it["cls"]["level"] in ("mid", "high") and not big:
        it["cls"]["level"] = "low"; it["cls"]["why"].append("AI: 생활·영업 영향 없음")
    return it
