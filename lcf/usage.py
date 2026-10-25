"""하루 사용 요약 — Worker 집계(live/usage/<날짜>.json) + 매일 정리·꼬리표 비용 + 신고 → 텔레그램·R2

  python -m lcf usage [날짜]     기본: 어제 (한국 날짜)

Worker는 요청 내용(상황 글·질문)을 남기지 않고 기능·결과·시간·토큰·예상 비용만 센다 (worker/src/index.js Usage)
"""
import datetime as dt

from .core import BRAND, DATA, STATE, log, read_json, today, write_json

EP = {"/profile": "상황 입력", "/rank": "AI 재판정", "/ask": "질문", "/feedback": "관심 표시", "/report": "신고", "/subscribe": "알림 신청", "/contact": "문의"}


def _batch_usd(day):
    st = read_json(STATE / "daily_batch.json", {}) or {}
    return round(sum(b.get("usd", 0) for b in st.get("batches", []) if str(b.get("at", "")).startswith(day)), 3)


def _reports(day):
    n = 0
    for p in (STATE / "reports").glob("*.json") if (STATE / "reports").exists() else []:
        n += sum(1 for r in (read_json(p) or {}).get("reports", []) if str(r.get("at", "")).startswith(day))
    return n


def summary(day=None):
    day = day or (today() - dt.timedelta(days=1)).isoformat()
    u = read_json(DATA / "live" / "usage" / f"{day}.json", {}) or {}
    ep = u.get("ep", {})
    w_usd = sum(e.get("usd", 0) for e in ep.values())
    b_usd = _batch_usd(day)
    t_usd = (read_json(STATE / "tag.json", {}) or {}).get("by_day", {}).get(day, 0)
    total = w_usd + b_usd + t_usd
    lines = [f"📊 <b>{BRAND}</b> 하루 사용 · {day}"]
    if not ep:
        lines.append("· 화면 사용 기록 없음")
    for k, name in EP.items():
        e = ep.get(k)
        if not e:
            continue
        extra = []
        if e.get("limited"):
            extra.append(f"한도 {e['limited']}")
        if e.get("err"):
            extra.append(f"오류 {e['err']}")
        if k == "/rank" and e.get("judged"):
            extra.append(f"판정 {e['judged']}건")
        if e.get("calls"):
            extra.append(f"평균 {e['ms'] / max(e['n'], 1) / 1000:.1f}초")
        lines.append(f"· {name} {e['n']}" + (f" ({' · '.join(extra)})" if extra else ""))
    fb = u.get("fb", {})
    if fb:
        stars = sorted(fb.items(), key=lambda x: -x[1].get("star", 0))[:3]
        hides = sorted(fb.items(), key=lambda x: -x[1].get("hide", 0))[:3]
        lines.append(f"· 관심 있음 {sum(v.get('star', 0) for v in fb.values())} · 관심 없음 {sum(v.get('hide', 0) for v in fb.values())}")
        if stars and stars[0][1].get("star"):
            lines.append("  ★ 많이: " + ", ".join(k for k, v in stars if v.get("star")))
        if hides and hides[0][1].get("hide"):
            lines.append("  ✕ 많이: " + ", ".join(k for k, v in hides if v.get("hide")))
    cdir = DATA / "live" / "contact" / day
    nc = len(list(cdir.glob("*.json"))) if cdir.exists() else 0
    if nc:
        lines.append(f"· 문의 {nc}건 — R2 live/contact/{day}/ 확인")
    rp = _reports(day)
    if rp:
        lines.append(f"· 신고 {rp}건 — 확인 필요")
    lines.append(f"· AI 비용 약 ${total:.2f} (화면 ${w_usd:.2f} · 매일 정리 ${b_usd:.2f} · 꼬리표 ${t_usd:.2f})")
    errs = sum(e.get("err", 0) for e in ep.values())
    warn = []
    if total > 5:
        warn.append(f"하루 비용 ${total:.2f}")
    if errs >= 10:
        warn.append(f"오류 {errs}건")
    if warn:
        lines[0] = "⚠️ " + lines[0] + " — " + ", ".join(warn)
    text = "\n".join(lines)
    write_json(STATE / "usage" / f"{day}.json", {"day": day, "worker_usd": round(w_usd, 4), "batch_usd": b_usd, "tag_usd": t_usd,
                                                   "total_usd": round(total, 4), "ep": ep, "reports": rp}, pretty=True)
    log(text.replace("<b>", "").replace("</b>", ""))
    from . import notify
    notify.send(text)
    return text
