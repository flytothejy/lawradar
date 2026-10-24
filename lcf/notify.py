"""텔레그램 — 일일 요약 (환경변수 TELEGRAM_TOKEN, TELEGRAM_CHAT_ID; 없으면 화면에 출력)"""
import html, os
from collections import Counter

import requests

from .classify import reclassify
from .core import BRAND, DAYS, FEED, log, read_json, today

LIMIT = 3800
e = lambda x: html.escape(str(x or ""), quote=False)


def send(text):
    tok, chat = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        print(text); return
    r = requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                      json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=20)
    if not r.ok:
        log(f"텔레그램 실패 {r.status_code}: {r.text[:200]}")


def send_chunks(lines):
    buf = ""
    for l in lines:
        if len(buf) + len(l) + 1 > LIMIT:
            send(buf); buf = ""
        buf += l + "\n"
    if buf.strip():
        send(buf)


def _lookup(keys):
    """feed의 key → 항목 (days/ 파일들에서 찾음)"""
    want, out = set(keys), {}
    for p in sorted(DAYS.glob("*.json"))[-20:]:
        for k, it in (read_json(p) or {}).get("items", {}).items():
            if k in want:
                out[k] = reclassify(it)
    return [out[k] for k in keys if k in out]


def daily(date=None):
    """오늘 처음 발견한 것 요약 — 구독 지역 조례와 제정·생활 주제 법령은 이름까지, 나머지는 숫자로"""
    d = date or today().isoformat()
    f = read_json(FEED / f"{d}.json")
    if f is None:
        send(f"❌ <b>{BRAND}</b> — {d} 수집 기록이 없습니다. Actions 로그를 확인하세요."); return
    items = _lookup(f["keys"])
    from .collect import watched_regions
    regions = watched_regions()
    by = Counter((i["kind"], i["cls"]["level"]) for i in items)
    n = lambda k: sum(v for (kk, _), v in by.items() if kk == k)
    L = [f"<b>📡 {BRAND} · {d}</b>",
         f"법령 {n('law')} · 행정규칙 {n('admrul')} · 자치법규 {n('ordin')} (새로 확인)",
         f"정비·내부 행정으로 거른 것 {sum(v for (_, lv), v in by.items() if lv == 'low')}건"]
    lv = {"high": 0, "mid": 1}
    hi = [i for i in items if i["kind"] == "ordin" and i["org"] in regions and i["cls"]["level"] != "low"]
    hi += sorted((i for i in items if i["kind"] == "law" and (i["cls"]["level"] == "high" or (i["cls"]["level"] == "mid" and i["cls"]["life"]))),
                 key=lambda i: (lv[i["cls"]["level"]], not i["cls"].get("by_name"), i["name"]))
    if hi:
        L.append("")
        for i in hi[:15]:
            where = i["org"].replace("경기도 ", "") if i["kind"] == "ordin" else i["type"]
            L.append(f"• <a href=\"{i['url']}\">{e(i['name'])}</a> <i>[{e(where)}·{e(i['change'])}]</i>")
    if not items:
        L.append("오늘 새로 확인된 변경이 없습니다")
    from .pages import open_reports
    rep = open_reports()
    if rep:
        L += ["", f"🚩 '원문과 달라요' 신고 확인 대기 {len(rep)}건 (그동안 원문만 보임): " + ", ".join(sorted(rep)[:10]),
              "   확인 후 R2 lcf/state/reports/<key>.json 의 resolved를 true로"]
    send_chunks(L)
