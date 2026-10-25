"""변경 상세 페이지 — 항목마다 고정 주소의 정적 페이지 (검색 유입용) + sitemap.xml·robots.txt

  python -m lcf pages            data/lcf/pages/ 아래에 생성 (pages 워크플로가 _site/ 에 복사)

- 내용이 있는 항목만: 정비(low)가 아니고, 개정 이유·조문 비교·AI 요약 중 하나라도 있는 것
- 주소: c/<종류>-<일련번호>.html (바뀌지 않음)
- 같은 법령·자치법규의 다른 판(이번 수집 범위 안)을 '이 법령의 다른 변경'으로 연결
- 지역 페이지: r/<지자체>.html (최근 1년 그 지역 조례·규칙 변경) + r/index.html (전국 지역 목록), regions.json (첫 화면 지역 찾기)
- 모든 날짜를 읽음 (pages 워크플로에서 sync pull --all-days)
"""
import datetime as dt, html, json, os, re, shutil
from collections import defaultdict

from . import packs
from .classify import reclassify
from .core import BRAND, DAYS, DATA, config, log, read_json, today
from .digest import change_points, law_line, ordin_line

OUT = DATA / "pages"
SITE_URL = (os.environ.get("SITE_URL") or "https://flytothejy.github.io/lawradar").rstrip("/")
e = lambda x: html.escape(str(x or ""), quote=True)
LABEL = re.compile(r"^[가-하]\.\s*")
KIND = {"law": "법령", "admrul": "고시·훈령", "ordin": "조례·규칙"}

CSS = """:root{--paper:#F7F8FA;--card:#FFFFFF;--ink:#1D2433;--muted:#626B7E;--rule:#DCE0E7;--ins:#2349C2;--ins-bg:#E7ECFB;--ins-deep:#1A3794;--del:#B4372E;--del-bg:#F9E9E7;--warn-bg:#FFF6E5;--warn-line:#E8C98A;--warn-ink:#5C3D00}
@media (prefers-color-scheme:dark){:root{--paper:#12151C;--card:#1A1E27;--ink:#E6E9EF;--muted:#9AA2B3;--rule:#2A303C;--ins:#9DB2FF;--ins-bg:#1D2648;--ins-deep:#C3D0FF;--del:#FF8F84;--del-bg:#3A1F1E;--warn-bg:#2E2614;--warn-line:#6B5523;--warn-ink:#F2D9A0}}
*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:400 16px/1.7 "IBM Plex Sans KR",system-ui,sans-serif}
main{max-width:44rem;margin:0 auto;padding:2rem 16px 4rem}a{color:var(--ins);text-underline-offset:3px}
.crumb{font-size:.875rem;color:var(--muted)}.crumb a{color:inherit}
h1{font:700 clamp(1.5rem,4.5vw,2.1rem)/1.35 "Noto Serif KR",serif;margin:.5rem 0 .75rem;word-break:keep-all}
h2{font:700 1.1rem/1.4 "Noto Serif KR",serif;margin:2rem 0 .5rem}
.meta{display:flex;flex-wrap:wrap;gap:.25rem 1rem;color:var(--muted);font-size:.875rem}
.lede{font-size:1.0625rem;word-break:keep-all}
.todo{border:1.5px solid var(--ins);border-radius:12px;padding:1rem 1.1rem;margin:1.25rem 0 1.5rem;background:color-mix(in srgb,var(--ins-bg) 55%,var(--paper))}
.todo h2{margin:.35rem 0 .5rem;font-size:1.05rem}.todo ul{margin:0 0 .6rem;padding-left:1.1rem}.todo li{margin:.2rem 0}
.todo dl{display:grid;grid-template-columns:5.5rem 1fr;gap:.3rem .75rem;margin:.5rem 0;font-size:.9rem}.todo dt{color:var(--muted)}.todo dd{margin:0}
.todo-h{display:flex;flex-wrap:wrap;gap:.3rem}.actchip{font-size:.72rem;font-weight:600;color:var(--ins);border:1px solid var(--ins);border-radius:999px;padding:.05rem .5rem}
.todo .note{font-size:.8rem;color:var(--muted);margin:.4rem 0 0}
.box{border:1px solid var(--rule);border-radius:12px;padding:1rem 1.1rem;background:var(--card)}
ul{padding-left:1.2rem}li{margin:.3rem 0}
del{color:var(--del);background:var(--del-bg);padding:0 .15em;border-radius:2px}
ins{color:var(--ins);background:var(--ins-bg);text-decoration:underline;text-underline-offset:3px;padding:0 .15em;border-radius:2px}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:.5rem;list-style:none;padding:0;margin:1rem 0}
.steps li{border-top:2px solid var(--ink);padding-top:.4rem;margin:0}.steps span{display:block;font-size:.8rem;color:var(--muted)}
.cta{display:inline-block;margin-top:.5rem;padding:.6rem 1rem;border-radius:10px;background:var(--ink);color:var(--paper);text-decoration:none;font-weight:600}
details{margin-top:1rem}summary{cursor:pointer;color:var(--muted)}
.hist{list-style:none;padding:0}.hist li{border-top:1px solid var(--rule);padding:.5rem 0}
footer{margin-top:3rem;border-top:1px solid var(--rule);padding-top:1rem;font-size:.8125rem;color:var(--muted)}
:focus-visible{outline:2px solid var(--ins);outline-offset:2px}
[hidden]{display:none!important}
.chg{background:var(--card);border:1px solid var(--rule);border-radius:14px;overflow:hidden;margin:.75rem 0}
.chg .w{padding:.8rem 1rem .2rem;font-size:.8125rem;font-weight:600;color:var(--muted)}
.pair{display:grid;grid-template-columns:2.4rem minmax(0,1fr);gap:.35rem .6rem;padding:.4rem 1rem .85rem;align-items:baseline}
.pair .k{font-size:.75rem;font-weight:600}.pair .kb{color:var(--del)}.pair .ka{color:var(--ins)}
.pair .b{margin:0;color:var(--del);text-decoration:line-through;text-decoration-thickness:1px}
.pair .b.none{text-decoration:none;color:var(--muted)}
.pair .a{margin:0;font-weight:500}.pair .a span{color:var(--ins);background:var(--ins-bg);padding:1px 4px;border-radius:3px;box-decoration-break:clone;-webkit-box-decoration-break:clone}
.quote{background:color-mix(in srgb,var(--rule) 45%,var(--paper));border-top:1px solid var(--rule);padding:.7rem 1rem .8rem}
.quote .qh{display:flex;justify-content:space-between;font-size:.75rem;font-weight:600;color:var(--muted)}
.quote p{margin:.3rem 0 0;font-family:"Noto Serif KR",serif;font-size:.875rem;line-height:1.75}
.whenbox{border:1.5px solid var(--ink);border-radius:14px;overflow:hidden;margin:1.25rem 0}
.whenbox h2{margin:0;padding:.85rem 1rem .3rem}
.whenbox dl{margin:0;padding:.2rem 1rem .85rem;display:grid;grid-template-columns:4.5rem minmax(0,1fr);gap:.4rem .6rem}
.whenbox dt{font-size:.8125rem;color:var(--muted)}.whenbox dd{margin:0}
.whenbox .note{padding:.2rem 1rem .85rem;margin:0;color:var(--muted);font-size:.9rem}
.checks{list-style:none;padding:0;margin:.75rem 0;font-size:.8125rem;color:var(--muted)}.checks li::before{content:"✓ ";color:var(--ins);font-weight:600}
.warn{background:var(--warn-bg);border:1px solid var(--warn-line);color:var(--warn-ink);border-radius:12px;padding:.8rem 1rem;font-size:.9rem;margin:1rem 0}
.later{display:block;background:var(--ink);color:var(--paper);border-radius:12px;padding:.7rem 1rem;text-decoration:none;margin:.5rem 0 1rem}
.later small{display:block;opacity:.75;font-size:.75rem}
details.report{margin:1rem 0;border:1px dashed var(--rule);border-radius:12px;padding:.6rem 1rem}
details.report summary{color:var(--muted);font-size:.9rem;min-height:28px}
details.report label{display:flex;gap:.5rem;align-items:center;font-size:.9rem;min-height:36px}
details.report textarea{width:100%;font:inherit;border:1px solid var(--rule);border-radius:8px;padding:.5rem;margin:.4rem 0;background:transparent;color:var(--ink)}
details.report button{font:inherit;font-weight:600;border:0;border-radius:10px;padding:.6rem 1rem;background:var(--ink);color:var(--paper);cursor:pointer}
.back{display:inline-block;font-size:.875rem;color:var(--muted);text-decoration:none;padding:.4rem 0;margin-bottom:.75rem}
.box h2,section h2{font:600 .875rem/1.4 "IBM Plex Sans KR",sans-serif;margin:0 0 .5rem}
section{margin:1.5rem 0}.box{margin:1.25rem 0}.box .lede{margin:0 0 .5rem}
.steps li.next span{color:var(--del);font-weight:600}
.btns{display:grid;grid-template-columns:1fr 1fr;gap:.6rem;margin:2rem 0 1rem}
.btn{display:flex;align-items:center;justify-content:center;min-height:48px;border:1px solid var(--rule);background:var(--card);border-radius:12px;font-size:.875rem;font-weight:600;text-decoration:none;color:var(--ink)}
.btn.dark{background:var(--ink);color:var(--paper);border-color:var(--ink)}
#mine ul{margin:0}#mine li{color:var(--ins)}"""


def slug(it):
    return f"{it['kind']}-{it['seq']}"


def _ymd(d):
    return f"{int(d[:4])}.{int(d[5:7])}.{int(d[8:10])}" if d else ""


def item_row(it):
    """상세 페이지 안에 넣는 매칭용 정보 (web/match.js의 항목 형식과 같음)"""
    from .build import BASE
    from .packs import all_ids, load, match
    c = it["cls"]
    return {"kind": it["kind"], "name": it["name"], "base": BASE.sub("", it["name"]) if it["kind"] == "law" else "",
            "org": it["org"], "topics": "|".join(c["topics"]), "life": int(bool(c.get("life"))), "level": c["level"],
            "packs": ",".join(i for i in all_ids() if match(it, load(i), set())), "title": (it.get("ai") or {}).get("title", "")}


def open_reports():
    """신고 중 아직 확인 안 된 항목 key — Worker /report가 R2 lcf/state/reports/<key>.json에 남김"""
    out = set()
    for p in (DATA / "state" / "reports").glob("*.json"):
        doc = read_json(p) or {}
        if not doc.get("resolved"):
            out.add(doc.get("key") or p.stem.replace("-", ":", 1))
    return out


def has_content(it):
    if it["cls"]["level"] == "low":
        return False
    d = it.get("detail") or {}
    return bool((it.get("ai") or {}).get("summary") or d.get("why") or d.get("main") or d.get("diff") or d.get("marked") or d.get("purpose"))


def _arrow(s):
    """'A → B' 를 삭제/삽입 표시로"""
    if " → " not in s:
        return e(s)
    head, _, rest = s.rpartition(": ") if ": " in s.split(" → ")[0] else ("", "", s)
    b, a = rest.split(" → ", 1)
    return (e(head) + ": " if head else "") + f"<del>{e(b)}</del> → <ins>{e(a)}</ins>"


def body_changes(it):
    d = it.get("detail") or {}
    out = []
    if it["kind"] == "law":
        for p in change_points(it, limit=8):
            out.append(f"<li>{_arrow(p) if ' — ' not in p else e(p.split(' — ')[0]) + ' — ' + _arrow(p.split(' — ', 1)[1])}</li>")
        if not out and d.get("main"):
            out += ["<li>" + e(LABEL.sub("", m)) + "</li>" for m in d["main"][:6]]
    df = d.get("diff") or {}
    for c in df.get("changed", [])[:10]:
        parts = "; ".join(f"<del>{e(p['before'])}</del> → <ins>{e(p['after'])}</ins>" for p in c.get("parts", [])[:3] if p["before"] or p["after"])
        out.append(f"<li><b>{e(c['jo'])}({e(c['title'])})</b> {parts}</li>")
    if df.get("added"):
        out.append(f"<li>새로 생긴 조: {e(', '.join(df['added']))}</li>")
    if df.get("removed"):
        out.append(f"<li>없어진 조: {e(', '.join(df['removed']))}</li>")
    if not df and d.get("marked"):
        out += [f"<li><b>{e(m['jo'])}({e(m['title'])})</b> {e(m['kind'])}: {e(m['text'])}</li>" for m in d["marked"][:6]]
    if it["change"] in ("제정",) and d.get("titles"):
        out.append(f"<li>주요 조: {e(', '.join(d['titles'][:10]))}</li>")
    return out


SRC_LABEL = {"개정이유": "개정이유", "부칙": "부칙", "조문": "조문 비교"}


def _quote_box(q, src, url):
    return (f'<div class="quote"><div class="qh"><span>원문 발췌 · {e(SRC_LABEL.get(src, src))}</span>'
            f'<a href="{e(url)}" rel="noopener">원문에서 보기 ↗</a></div><p>“{e(q)}”</p></div>')


def changes_v2(ai, url):
    out = []
    marks = "①②③④"
    for i, c in enumerate(ai.get("changes") or []):
        if c.get("before"):
            before = f'<span class="k kb">전</span><p class="b">{e(c["before"])}</p>'
        elif c.get("new"):
            before = '<span class="k kb">전</span><p class="b none">없었어요 (새로 생김)</p>'
        else:
            before = ""                                         # 이전 내용을 원문으로 알 수 없으면 '전'을 지어내지 않음
        out.append(f'<div class="chg"><div class="w">{marks[i] if i < 4 else "·"} {e(c.get("what") or "")}</div>'
                   f'<div class="pair">{before}<span class="k ka">{"후" if before else "내용"}</span><p class="a"><span>{e(c["after"])}</span></p></div>'
                   + (_quote_box(c["quote"], c.get("src", ""), url) if c.get("quote") else "") + "</div>")
    return "".join(out)


def original_excerpts(it, url):
    """검증을 못 거친 경우: 원문만 (개정이유 주요내용 / 조문 비교)"""
    d = it.get("detail") or {}
    out = []
    for m in (d.get("main") or [])[:4]:
        out.append(f'<div class="chg">{_quote_box(m, "개정이유", url)}</div>')
    if not out and d.get("why"):
        out.append(f'<div class="chg">{_quote_box(d["why"][:600], "개정이유", url)}</div>')
    for c in ((d.get("diff") or {}).get("changed") or [])[:4]:
        for p in c.get("parts", [])[:2]:
            out.append(f'<div class="chg"><div class="w">{e(c["jo"])}({e(c["title"])}) · 조문 원문</div>'
                       f'<div class="pair"><span class="k kb">전</span><p class="b">{e(p["before"] or "(없음)")}</p>'
                       f'<span class="k ka">후</span><p class="a"><span>{e(p["after"] or "(삭제)")}</span></p></div></div>')
    return "".join(out)


def when_box(it, ai, url):
    d = it.get("detail") or {}
    w = ai.get("when") or {} if ai.get("status") == "ok" else {}
    rows = []
    if w.get("start"):
        rows.append(("적용 시점", f"{_ymd(w['start'])}부터"))
    if w.get("target"):
        rows.append(("적용 대상", w["target"]))
    if w.get("other"):
        rows.append(("다른 시행일", w["other"]))
    if w.get("transition"):
        rows.append(("이전 일은", w["transition"]))
    bu = d.get("buchik") or ""
    if rows:
        body = "<dl>" + "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in rows) + "</dl>"
        q = w.get("quote") or ""
        if q:
            body += _quote_box(q, "부칙", url)
        elif bu:
            body += _quote_box(bu[:400] + ("…" if len(bu) > 400 else ""), "부칙", url)
    elif bu:
        body = '<p class="note">적용 시기와 대상은 부칙 원문을 확인하세요.</p>' + _quote_box(bu[:500] + ("…" if len(bu) > 500 else ""), "부칙", url)
    else:
        return ""
    return f'<section class="whenbox"><h2>언제부터, 누구에게</h2>{body}</section>'


# ── 할 일 카드 — 행동 종류(꼬리표)·쉬운 말 전→후·부칙 시기로 "해당된다면 이렇게 확인해 보세요". AI 추가 호출 없음
ACT_LEAD = [   # (행동 종류, 첫 문장) — 위에 있을수록 먼저
    ("해야 할 것", "해야 할 일이 생겨요"),
    ("하면 안 되는 것", "앞으로 하면 안 되는 일이 생겨요"),
    ("받을 것", "받을 수 있는 것이 생기거나 달라져요"),
    ("계산이 바뀌는 것", "세금·금액·기간 계산이 달라져요"),
    ("권리가 바뀌는 것", "누릴 수 있는 권리가 달라져요"),
]
ACT_ASK = {"해야 할 것": "언제까지 무엇을 해야 하는지", "하면 안 되는 것": "지금 하는 일 중 걸리는 것이 있는지",
           "받을 것": "받을 수 있는 대상인지, 신청이 필요한지", "계산이 바뀌는 것": "내 경우 숫자가 어떻게 달라지는지",
           "권리가 바뀌는 것": "내가 쓸 수 있는 권리인지"}


def _links():
    import re as _re
    return [(_re.compile(x["match"]), x["label"], x["url"]) for x in config("action_links")["links"]]


def todo_card(it, ai):
    """행동 종류가 실제 할 일일 때만. 판정이 아니라 '해당된다면'"""
    act = (it.get("tags") or {}).get("act") or []
    lead = next(((a, s) for a, s in ACT_LEAD if a in act), None)
    if not lead or ai.get("status") != "ok":
        return ""
    w = ai.get("when") or {}
    start = w.get("start") or (it["effective"] if it["effective"] and it["effective"] != it["announced"] else "")
    rows = []
    for c in (ai.get("changes") or [])[:3]:
        if c.get("after"):
            rows.append(f'<li><b>{e(c.get("what", ""))}</b> {e(c["after"])}</li>')
    when = ""
    if start:
        dd = (dt.date.fromisoformat(start) - today()).days
        when = f'{_ymd(start)}부터' + (f' · <b>D-{dd}</b>' if dd > 0 else ' · 이미 시행 중')
        if w.get("target"):
            when += f' · {e(w["target"])}'
    asks = [ACT_ASK[a] for a, _ in ACT_LEAD if a in act][:2]
    if it["kind"] == "ordin":
        where = f'{e(it["org"])} 담당 부서 (누리집·민원 전화)'
    else:
        text = f'{it["name"]} {it["org"]}'
        lab, url = next(((l, u) for rx, l, u in _links() if rx.search(text)), ("정부24", "https://www.gov.kr"))
        where = f'<a href="{e(url)}" target="_blank" rel="noopener">{e(lab)}</a> · 소관: {e(it["org"])}'
    chips = "".join(f'<span class="actchip">{e(a)}</span>' for a, _ in ACT_LEAD if a in act)
    return (f'<section class="todo"><div class="todo-h">{chips}</div><h2>해당된다면, {e(lead[1])}</h2>'
            + (f'<ul>{"".join(rows)}</ul>' if rows else '')
            + '<dl>' + (f'<dt>언제부터</dt><dd>{when}</dd>' if when else '')
            + (f'<dt>확인할 것</dt><dd>{e(" · ".join(asks))}</dd>' if asks else '')
            + f'<dt>어디서</dt><dd>{where}</dd></dl>'
            + '<p class="note">내 경우에 해당하는지는 아래 원문과 부칙으로 확인하고, 애매하면 담당 기관이나 전문가에게 물어보세요.</p></section>')


def checks_html(ai):
    if ai.get("status") != "ok":
        return ""
    ck = ai.get("checks") or {}
    li = []
    if ck.get("quotes_ok"):
        li.append("원문 대조 · 숫자와 날짜가 원문과 같고, 발췌는 원문 문장 그대로예요")
    if ck.get("review") == "ok":
        li.append("2차 검토 · 요약이 원문과 어긋나거나 조건을 빠뜨리지 않았는지 따로 한 번 더 확인했어요")
    return f'<ul class="checks">{"".join(f"<li>{e(x)}</li>" for x in li)}</ul>' if li else ""


REPORT_PARTS = ["제목·요약", "바뀌기 전·후 내용", "적용 시기·대상", "날짜·숫자"]


def report_html(key):
    boxes = "".join(f'<label><input type="checkbox" name="part" value="{e(p)}"> {e(p)}</label>' for p in REPORT_PARTS)
    return (f'<details class="report"><summary>내용이 원문과 달라요</summary><form id="rep" data-key="{e(key)}">{boxes}'
            '<textarea name="text" rows="3" maxlength="500" placeholder="무엇이 다른지 적어 주세요 (선택)"></textarea>'
            '<button type="submit">신고하기</button><p class="meta" id="rep-msg">신고가 들어오면 확인할 때까지 쉬운 말 요약을 내리고 원문만 보여 드려요.</p>'
            '</form></details>')


def render(it, history, pack_names, reported=False):
    ai = dict(it.get("ai") or {})
    if reported and ai.get("status") == "ok":                    # 신고 확인 중: 원문만
        ai = {"status": "fallback", "problems": ["신고 확인 중"]}
    d = it.get("detail") or {}
    v2 = ai.get("v", 1) >= 2
    title = ai.get("title") or f"{it['name']} {it['change']}"
    lede = ai.get("summary") or (law_line(it) if it["kind"] == "law" else ordin_line(it))
    desc = (lede or title)[:150]
    url = f"{SITE_URL}/c/{slug(it)}.html"
    eff_future = it["effective"] and it["effective"] > today().isoformat()
    steps = [("공포·발령", it["announced"])]
    if it["effective"] and it["effective"] != it["announced"]:
        steps.append(("시행" + (" 예정" if eff_future else ""), it["effective"]))
    org = it["org"]
    changes = body_changes(it)
    if lede:                                                    # 요약과 같은 문장으로 시작하는 항목은 빼서 두 번 안 보이게
        head = e(lede.rstrip("…")[:40])
        changes = [c for c in changes if head not in c]
    reason = " ".join([d.get("why") or ""] + (d.get("main") or []))
    hist = [h for h in history if h["key"] != it["key"]]
    later = [h for h in hist if h["announced"] > it["announced"]]
    later_html = (f'<a class="later" href="{e(later[0]["href"])}"><small>이후 다시 바뀌었어요</small>{_ymd(later[0]["announced"])} · {e(later[0]["title"])} 보기 →</a>'
                  if later else "")
    if v2 and ai.get("status") == "ok" and ai.get("changes"):
        what_html = f'<h2>무엇이 바뀌나</h2>{f"<p class=lede>{e(lede)}</p>" if ai.get("summary") else ""}{changes_v2(ai, it["url"])}'
    elif ai.get("status") == "fallback":
        why_not = "신고가 들어와 확인하고 있어서" if reported else "쉬운 말 요약이 원문과 맞는지 확인되지 않아"
        what_html = (f'<div class="warn">{why_not}, <b>원문을 그대로</b> 보여 드려요.</div><h2>무엇이 바뀌나 · 원문</h2>'
                     + (original_excerpts(it, it["url"]) or "<p>원문 링크에서 확인해 주세요.</p>"))
    else:
        what_html = ('<section class="box"><h2>무엇이 바뀌나</h2>' + (f'<p class="lede">{e(lede)}</p>' if lede else '')
                     + (f'<ul>{"".join(changes)}</ul>' if changes else '')
                     + ('' if lede or changes else '<p>바뀐 내용을 정리하지 못했어요. 원문을 확인해 주세요.</p>') + '</section>')
    when_html = when_box(it, ai, it["url"])
    checks = checks_html(ai)
    nxt = ' class="next"'
    steps_html = "".join(f'<li data-d="{b}"{nxt if b > today().isoformat() else ""}><span>{e(a)}</span>{_ymd(b)}</li>' for a, b in steps)
    row_json = json.dumps(item_row(it), ensure_ascii=False).replace("</", "<\\/")
    ld = {"@context": "https://schema.org", "@type": "Article", "headline": title[:110], "datePublished": it["announced"],
          "description": desc, "inLanguage": "ko", "mainEntityOfPage": url, "publisher": {"@type": "Organization", "name": BRAND},
          "about": {"@type": "Legislation", "name": it["name"], "legislationDate": it["announced"], "legislationType": it["type"]}}
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} — {e(it['name'])} | {BRAND}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(url)}">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:type" content="article"><meta property="og:site_name" content="{BRAND}"><meta property="og:url" content="{e(url)}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;600&family=Noto+Serif+KR:wght@700&display=swap" rel="stylesheet">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False)}</script>
<style>{CSS}</style></head>
<body><main>
<a class="back" id="back" href="../">← {BRAND}</a>
<div class="meta">{e(it['name'])} · {e(it['change'])} · {e(org)}</div>
{later_html}
<h1>{e(title)}</h1>
<ol class="steps" id="steps">{steps_html}</ol>
<p class="meta"><a href="../guide.html">시행령·부칙·공포·시행이 뭔가요?</a></p>
{todo_card(it, ai)}
{what_html}
{when_html}
{checks}
<section id="mine" hidden><h2>이 변경이 내 타임라인에 보이는 이유</h2><ul id="mine-why"></ul></section>
{f'<section><h2>이런 분께 닿는 변화</h2><p>{e(ai["who"])}</p></section>' if ai.get('who') else ''}
{f'<p class="meta">분야: {e(", ".join(pack_names))}</p>' if pack_names else ''}
{f'<details><summary>개정 이유 원문</summary><p>{e(reason[:3000])}</p></details>' if reason.strip() else ''}
{report_html(it["key"])}
<div class="btns"><a class="btn" href="{e(it['url'])}" rel="noopener">원문 보기</a>{'<a class="btn dark" href="#hist">이 ' + ('조례' if it['kind'] == 'ordin' else '법령') + ' 변화 이력</a>' if hist else '<a class="btn dark" id="alert-btn" href="../#/">바뀌면 알림 받기</a>'}</div>
{('<h2 id="hist">이 ' + ('조례' if it['kind'] == 'ordin' else '법령') + '의 다른 변경</h2><ul class="hist">' + ''.join(f'<li>{_ymd(h["announced"])} · <a href="{e(h["href"])}">{e(h["title"])}</a></li>' for h in hist[:12]) + '</ul>') if hist else ''}
<footer>법레이더 공개 베타 · 자동으로 만든 요약이에요. 중요한 결정 전에는 원문을 확인하세요. 개인 상황에 맞는 판단은 전문가에게 확인하세요. 자료: 국가법령정보센터 공동활용 API.<br><span class="foot-links"><a href="../about.html">소개·자주 묻는 질문</a> · <a href="../terms.html">이용약관</a> · <a href="../privacy.html"><b>개인정보처리방침</b></a> · <a href="../about.html#contact">문의</a></span></footer>
<script type="application/json" id="lr-item">{row_json}</script>
<script src="../match.js"></script>
<script>
(function(){{
  var f = document.getElementById("rep");
  if (f) f.addEventListener("submit", function(ev){{
    ev.preventDefault();
    var parts = [].slice.call(f.querySelectorAll("input[name=part]:checked")).map(function(x){{ return x.value; }});
    var msg = document.getElementById("rep-msg"), btn = f.querySelector("button");
    btn.disabled = true;
    fetch("../config.json").then(function(r){{ return r.json(); }}).then(function(c){{
      return fetch(c.ask.slice(0, -4) + "/report", {{method: "POST", headers: {{"content-type": "application/json"}},
        body: JSON.stringify({{key: f.dataset.key, parts: parts, text: f.elements.text.value}})}});
    }}).then(function(r){{ if (!r.ok) throw 0; msg.textContent = "신고됐어요. 고마워요. 확인할 때까지 이 페이지는 원문만 보여 드릴게요 (하루 안에 반영)."; }})
      .catch(function(){{ msg.textContent = "보내지 못했어요. 잠시 후 다시 시도해 주세요."; btn.disabled = false; }});
  }});
  var p = LR.load(), r = JSON.parse(document.getElementById("lr-item").textContent), t = LR.today();
  document.querySelectorAll("#steps li.next").forEach(function(li){{ var d = LR.dday(li.dataset.d, t); if (d) li.querySelector("span").textContent += " · " + d; }});
  if (!p) return;
  var back = document.getElementById("back"); back.href = "../#/timeline"; back.textContent = "← 내 타임라인";
  var a = document.getElementById("alert-btn"); if (a) a.href = "../#/alerts";
  var m = LR.match(r, p); if (!m) return;
  document.getElementById("mine-why").innerHTML = m.why.map(function(w){{ return "<li>" + w.replace(/[&<>]/g, function(c){{ return {{"&":"&amp;","<":"&lt;",">":"&gt;"}}[c]; }}) + "</li>"; }}).join("");
  document.getElementById("mine").hidden = false;
}})();
</script>
</main></body></html>"""


REGION_DAYS = 365


def region_slug(org):
    return org.replace(" ", "-")


def sido(org):
    return org.split()[0].replace("교육청", "")


def _head(title, desc, url, depth=1):
    up = "../" * depth
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)} | {BRAND}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(url)}">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(desc)}"><meta property="og:type" content="website"><meta property="og:url" content="{e(url)}"><meta property="og:site_name" content="{BRAND}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;600&family=Noto+Serif+KR:wght@700&display=swap" rel="stylesheet">
<style>{CSS}
.rl{{list-style:none;padding:0}}.rl li{{border-top:1px solid var(--rule);padding:.75rem 0;margin:0}}.rl .t{{font-weight:600}}.rl .m{{font-size:.8125rem;color:var(--muted)}}
.rl .l{{font-size:.9rem;margin:.25rem 0 0;word-break:keep-all}}.grid{{columns:12rem;column-gap:1.5rem}}.grid li{{break-inside:avoid}}</style></head>
<body><main>
<nav class="crumb"><a href="{up}">{BRAND}</a> › <a href="{up}r/">지역</a></nav>"""


FOOT = """<h2>이 지역 조례가 바뀌면</h2>
<p class="meta">알림 받기는 준비 중이에요. 곧 이메일·텔레그램으로 받을 수 있어요.</p>
<footer>법레이더 공개 베타 · 자동으로 정리한 내용이라 빠지거나 틀릴 수 있어요. 개인 상황에 맞는 판단은 전문가에게 확인하세요. 자료: 국가법령정보센터 공동활용 API.<br><span class="foot-links"><a href="../about.html">소개·자주 묻는 질문</a> · <a href="../terms.html">이용약관</a> · <a href="../privacy.html"><b>개인정보처리방침</b></a> · <a href="../about.html#contact">문의</a></span></footer>
</main></body></html>"""


def region_pages(items, pub):
    """지역마다 최근 1년 조례·규칙 변경 목록 (정비·내부 행정은 숫자만)"""
    since = (today() - dt.timedelta(days=REGION_DAYS)).isoformat()
    by = defaultdict(list)
    for i in items:
        if i["kind"] == "ordin" and i["org"] and i["announced"] >= since:
            by[i["org"]].append(i)
    (OUT / "r").mkdir(parents=True, exist_ok=True)
    meta, urls = [], []
    for org, rows in by.items():
        show = sorted((i for i in rows if i["cls"]["level"] != "low"), key=lambda i: (i["announced"], i["seq"]), reverse=True)
        noise = len(rows) - len(show)
        url = f"{SITE_URL}/r/{region_slug(org)}.html"
        title = f"{org} 조례·규칙, 최근에 이렇게 바뀌었어요"
        desc = f"{org}에서 최근 1년 동안 바뀐 조례·규칙 {len(show)}건을 쉬운 말로 정리했어요. 지원금·감면, 새로 생긴 규칙, 시행일까지."
        li = []
        for i in show[:200]:
            ai = i.get("ai") or {}
            href = f"../c/{slug(i)}.html" if i["key"] in pub else i["url"]
            line = ai.get("summary") or ordin_line(i)
            tags = [_ymd(i["announced"]) + " 공포", i["change"]]
            if i["effective"] and i["effective"] != i["announced"]:
                tags.append(_ymd(i["effective"]) + " 시행")
            if i["cls"].get("support"):
                tags.append("지원·감면")
            li.append(f'<li><a class="t" href="{e(href)}">{e(ai.get("title") or i["name"])}</a>'
                      f'<div class="m">{e(i["name"]) + " · " if ai.get("title") else ""}{" · ".join(e(x) for x in tags)}</div>'
                      + (f'<p class="l">{e(line[:240])}</p>' if line else "") + "</li>")
        up = sido(org)
        parent = f'<p class="meta">시·도 조례는 <a href="{region_slug(up)}.html">{e(up)} 페이지</a>에서 볼 수 있어요.</p>' if up != org and up in by else ""
        body = (f'<h1>{e(org)} 조례·규칙 변화</h1><p class="lede">최근 1년 동안 바뀐 조례·규칙 {len(show)}건이에요'
                + (f". 내부 행정·문구 정리 {noise}건은 뺐어요" if noise else "") + f'.</p>{parent}'
                + f'<ol class="rl">{"".join(li) or "<li>최근 1년 동안 생활과 관련해 바뀐 것이 없어요.</li>"}</ol>'
                + (f'<p class="meta">최근 200건만 보여 줘요.</p>' if len(show) > 200 else ""))
        (OUT / "r" / f"{region_slug(org)}.html").write_text(_head(title, desc, url) + body + FOOT, encoding="utf-8")
        last = show[0]["announced"] if show else max(i["announced"] for i in rows)
        urls.append((url, last))
        meta.append({"org": org, "sido": up, "slug": region_slug(org), "n": len(show),
                     "week": sum(1 for i in show if i["announced"] >= (today() - dt.timedelta(days=7)).isoformat())})
    meta.sort(key=lambda m: (m["sido"], m["org"] != m["sido"], m["org"]))
    groups = defaultdict(list)
    for m in meta:
        groups[m["sido"]].append(m)
    idx = "".join(f'<h2>{e(s)}</h2><ul class="rl grid">' + "".join(
        f'<li><a href="{e(m["slug"])}.html">{e(m["org"] if m["org"] == s else m["org"].split(" ", 1)[-1])}</a> <span class="m">{m["n"]}건</span></li>'
        for m in ms) + "</ul>" for s, ms in groups.items())
    (OUT / "r" / "index.html").write_text(
        _head("지역별 조례·규칙 변화", "전국 시·도와 시·군·구의 조례·규칙이 최근 어떻게 바뀌었는지 지역별로 모았어요.", f"{SITE_URL}/r/")
 +
        f'<h1>지역별 조례·규칙 변화</h1><p class="lede">사는 곳을 고르면 최근 1년 동안 바뀐 조례·규칙을 볼 수 있어요. 지역 {len(meta)}곳.</p>{idx}' + FOOT,
        encoding="utf-8")
    (OUT / "regions.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    return urls + [(f"{SITE_URL}/r/", today().isoformat())]


def run():
    items = []
    for p in sorted(DAYS.glob("*.json")):
        items += [reclassify(i) for i in (read_json(p) or {}).get("items", {}).values()]
    pub = [i for i in items if has_content(i)]
    reported = open_reports()
    profs = config("profiles").get("profiles", [])
    regions = {r for pr in profs for r in pr.get("regions", [])}
    pack_list = [packs.load(pid) for pid in packs.all_ids()]
    by_id = defaultdict(list)
    for i in pub:
        ai = i.get("ai") or {}
        by_id[(i["kind"], i["id"])].append({"key": i["key"], "announced": i["announced"], "href": f"{slug(i)}.html",
                                             "title": ai.get("title") or f"{i['name']} {i['change']}"})
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "c").mkdir(parents=True)
    urls = []
    for i in pub:
        hist = sorted(by_id[(i["kind"], i["id"])], key=lambda h: h["announced"], reverse=True)
        names = [pk["name"] for pk in pack_list if packs.match(i, pk, regions)]
        (OUT / "c" / f"{slug(i)}.html").write_text(render(i, hist, names, reported=i["key"] in reported), encoding="utf-8")
        urls.append((f"{SITE_URL}/c/{slug(i)}.html", i["announced"]))
    urls += region_pages(items, {i["key"] for i in pub})
    sm = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
          f"<url><loc>{SITE_URL}/</loc><lastmod>{today().isoformat()}</lastmod></url>",
          f"<url><loc>{SITE_URL}/guide.html</loc></url>"]
    sm += [f"<url><loc>{e(u)}</loc><lastmod>{d}</lastmod></url>" for u, d in urls]
    sm.append("</urlset>")
    (OUT / "sitemap.xml").write_text("\n".join(sm), encoding="utf-8")
    (OUT / "robots.txt").write_text(f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n", encoding="utf-8")
    (OUT / "pages.json").write_text(json.dumps(sorted(i["key"] for i in pub)), encoding="utf-8")
    log(f"지역 페이지 {len(list((OUT / 'r').glob('*.html'))) - 1}개")
    log(f"상세 페이지 {len(pub)}개 (전체 {len(items)}건 중 내용 있는 것) · 날짜 파일 {len(list(DAYS.glob('*.json')))}개")
