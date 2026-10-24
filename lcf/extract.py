"""개정 이유 글에서 '무엇이 어떻게 바뀌나'를 규칙으로 뽑기 (LLM 없이)

법제처 제개정이유는 대개 다음 꼴을 씀:
  가. <변경 항목 제목>(안 제155조제1항 신설)
  종전에는 A 하였으나, 앞으로는 B 하도록 함.
  ‘A’에서 ‘B’로 확대
  A까지 취득하면 …하도록 하던 것을 그 기한을 1년 연장하여 B까지 …하도록 함.
→ [{title, before, after, short, kind}]  short = 전·후에서 실제로 다른 낱말만 ("3년 → 2년")
"""
import difflib, re

from .textdiff import _is_qty_change, tokens

HEAD = re.compile(r"^\s*[가-하]\.\s*(.+)$")
ARTREF = re.compile(r"\s*[\(\[]안\s*제.*$")
P_PREV = re.compile(r"종전에는\s*(.+?)(?:하였으나|했으나|였으나|이었으나|되었으나|하던\s*것을)\s*,?\s*앞으로는\s*(.+?)(?:하도록\s*함|하려는\s*것임|함|임)\.?$")
P_QUOTE = re.compile(r"[‘'“\"]([^’'”\"]{1,80})[’'”\"](?:에서|으로부터)\s*[‘'“\"]([^’'”\"]{1,80})[’'”\"](?:으로|로)")
P_INSTEAD = re.compile(r"(.{6,220}?)(?:하도록\s*하던|하던)\s*것을\s*(.+?)(?:하도록\s*함|하려는\s*것임|함)\.?$")
VERB = re.compile(r"(연장|단축|확대|축소|상향|하향|인상|인하|완화|강화|신설|폐지|삭제|변경|추가|제외|설정)")


DATE = re.compile(r"\d{4}년\s?\d{1,2}월\s?\d{1,2}일|\d[\d,.]*\s?(?:만\s?원|억\s?원|원|%|일|개월|년|명|세|배|㎡)")


def _qty_pairs(before, after):
    """전·후 문장에 나온 날짜·기간·금액 중 한쪽에만 있는 것끼리 짝지음 ('2026년 12월 31일 → 2027년 12월 31일')"""
    strip = lambda t: re.sub(r"\d+\s?(?:년|개월|일)\s?(?:간\s?)?(?:연장|단축|늘려|줄여|앞당겨)", "", t)
    qb = [m.group(0) for m in DATE.finditer(strip(before))]
    qa = [m.group(0) for m in DATE.finditer(strip(after))]
    ob = [x for x in qb if x not in qa]
    oa = [x for x in qa if x not in qb]
    return [f"{x} → {y}" for x, y in zip(ob, oa)]


def short_diff(before, after, limit=3):
    """전·후 문장에서 다른 부분만 짧게: 날짜·기간·금액 변화를 먼저, 다음은 짧은 낱말 차이"""
    q = _qty_pairs(before, after)
    a, b = tokens(before), tokens(after)
    out = [(-1, x) for x in q]
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        p = {"before": " ".join(a[i1:i2]), "after": " ".join(b[j1:j2])}
        b0, a0 = p["before"], p["after"]
        if not (b0 and a0) or max(len(b0), len(a0)) > 32:
            continue
        if (a0.startswith(b0) or b0.startswith(a0)) and abs(len(a0) - len(b0)) <= 3:     # 조사만 다름 ('경우 → 경우에는')
            continue
        out.append((0 if _is_qty_change(p) else 1, f"{b0} → {a0}"))
    out.sort(key=lambda x: x[0])
    seen, res = set(), []
    sub = lambda x, y: all(u.strip() in v for u, v in zip(x.split("→"), y.split("→")))
    for _, x in out:
        if x not in seen and not any(sub(x, y) or sub(y, x) for y in seen):
            seen.add(x); res.append(x)
    return res[:limit]


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip(" ,.")


def changes(lines):
    """lines: 제개정이유 줄 목록 (collect가 저장한 why/main 원문)"""
    out, title = [], None
    for raw in lines:
        l = _clean(raw)
        if not l or l.startswith(("[", "◇", "<")):
            continue
        m = HEAD.match(l)
        if m and len(m.group(1)) < 120 and not P_PREV.search(l):
            title = ARTREF.sub("", m.group(1)).strip()
            verb = VERB.search(title)
            out.append({"title": title, "kind": verb.group(1) if verb else "", "before": "", "after": "", "short": []})
            continue
        found = None
        if (m2 := P_PREV.search(l)):
            found = (m2.group(1), m2.group(2))
        elif (m3 := P_QUOTE.search(l)):
            found = (m3.group(1), m3.group(2))
        elif (m4 := P_INSTEAD.search(l)) and VERB.search(m4.group(2)[:40]):
            found = (m4.group(1), m4.group(2))
        if not found:
            continue
        before, after = _clean(found[0]), _clean(found[1])
        item = {"before": before[:300], "after": after[:300], "short": short_diff(before, after)}
        if out and title and not out[-1]["before"]:
            out[-1].update(item)                     # 제목 바로 아래 문장 → 그 항목의 전·후
        else:
            verb = VERB.search(after[:60])
            out.append({"title": "", "kind": verb.group(1) if verb else "", **item})
    return [c for c in out if c["title"] or c["before"]][:8]
