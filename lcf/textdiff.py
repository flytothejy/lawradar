"""조문 비교 — 조(條) 단위로 맞추고, 바뀐 조는 낱말 단위로 비교해 짧은 '전 → 후' 조각과 숫자 변경을 뽑음"""
import difflib, re

MARK = re.compile(r"\s*[<(（\[]\s*(개정|신설|삭제|전문개정|본조신설|제목개정|종전)[^)）\]>]*[)）\]>]")
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
QTY = re.compile(r"\d[\d,.]*\s?(만\s?원|천\s?원|억\s?원|원|%|퍼센트|일|주|개월|년|명|세|시간|분|회|가구|㎡|제곱미터|미터|m|km|대|개소|배)")
REF = re.compile(r"제\d+(조|항|호|장|절)(의\d+)?")


def clean(s):
    return re.sub(r"\s+", " ", MARK.sub("", s or "")).strip()


def tokens(s):
    return re.findall(r"[\w.,%~ㆍ·]+|[^\w\s]", s)


def _snip(a, b, ops, width=6):
    """바뀐 구간마다 앞뒤 낱말을 조금 붙여 '…앞 [전] → [후] 뒤…' 형태로"""
    out = []
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            continue
        pre = " ".join(a[max(0, i1 - width):i1])
        post = " ".join(a[i2:i2 + 3])
        out.append({"before": " ".join(a[i1:i2]), "after": " ".join(b[j1:j2]), "ctx": pre, "post": post})
    return out


def article_map(articles):
    """[(번호, 제목, 내용)] → {번호: (제목, 정리된 내용)}  (조문여부 N = 장·절 제목은 뺌)"""
    return {no: (title, clean(text)) for no, title, text in articles if text}


def compare(old, new, limit=12):
    """old/new: article_map 결과. 반환 {added, removed, changed:[{jo,title,edits,nums,parts}]}"""
    lab = lambda k, m: jo_label(k) + (f"({m[k][0]})" if m[k][0] else "")
    added = [lab(k, new) for k in new if k not in old]
    removed = [lab(k, old) for k in old if k not in new]
    changed = []
    for k in new:
        if k in old and old[k][1] != new[k][1]:
            a, b = tokens(old[k][1]), tokens(new[k][1])
            ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
            parts = _snip(a, b, ops)
            edits = sum(max(i2 - i1, j2 - j1) for t, i1, i2, j1, j2 in ops if t != "equal")
            nums = [f"{p['before']} → {p['after']}" for p in parts if _is_qty_change(p)]
            changed.append({"jo": jo_label(k), "title": new[k][0], "edits": edits, "nums": nums[:4], "parts": parts[:4]})
    changed.sort(key=lambda x: (-len(x["nums"]), -x["edits"]))
    return {"added": added[:limit], "removed": removed[:limit], "changed": changed[:limit],
            "n_changed": len(changed), "n_added": len(added), "n_removed": len(removed)}


def _is_qty_change(p):
    """금액·기간·인원 같은 '양'이 바뀐 조각만 (조항 번호 이동 '제17조 → 제18조'는 제외)"""
    b, a = p["before"], p["after"]
    if not (b and a) or len(b + a) > 60:
        return False
    qb = {m.group(0).replace(" ", "") for m in QTY.finditer(REF.sub("", b))}
    qa = {m.group(0).replace(" ", "") for m in QTY.finditer(REF.sub("", a))}
    return bool(qb and qa) and qb != qa


def jo_label(no):
    """'000202' → '제2조의2'"""
    s = str(no)
    if len(s) == 6 and s.isdigit():
        j, g = int(s[:4]), int(s[4:])
        return f"제{j}조" + (f"의{g}" if g else "")
    return s


def marked_paragraphs(text, date_dot):
    """조문 안에서 '(개정 2026. 10. 7)'처럼 이번 공포일 표시가 붙은 항을 찾아 줌 — 이전 버전이 없을 때 대신 사용"""
    if not text or date_dot not in text:
        return []
    paras = re.split(f"(?=[{CIRCLED}])", text)
    hits = []
    for p in paras:
        m = re.search(r"[<(（\[]\s*(개정|신설|전문개정|본조신설)([^)）\]>]*)", p)
        if m and date_dot in m.group(2):
            hits.append((m.group(1), clean(p)[:200]))
    if not hits:
        m = re.search(r"[<(（\[]\s*(개정|신설|전문개정|본조신설)([^)）\]>]*)", text)
        if m and date_dot in m.group(2):
            hits.append((m.group(1), clean(text)[:200]))
    return hits
