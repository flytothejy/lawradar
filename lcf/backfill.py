"""과거 백필 — 오래된 기간을 구간(기본 30일)씩 수집·보강하고 구간마다 R2에 올림. 중간에 끊겨도 이어서 함

  python -m lcf backfill --from 2024-10-22 --to 2026-09-21 [--chunk 30] [--minutes 300]

- 기준선(seed) 방식: '새로 발견'·알림으로 잡지 않음
- 진행 상황: state/backfill.json {"done": [[시작, 끝], …]}
- 시간 한도(--minutes)가 되면 멈추고, 남은 구간이 있으면 종료 코드 3 (워크플로가 자기 자신을 다시 실행)
- AI 다듬기는 하지 않음 (오래된 항목은 필요해질 때 다듬음)
"""
import datetime as dt, os, sys, time

from .core import STATE, log, read_json, status, write_json

PROGRESS = STATE / "backfill.json"


def _chunks(start, end, days):
    d = start
    while d <= end:
        e = min(end, d + dt.timedelta(days=days - 1))
        yield d, e
        d = e + dt.timedelta(days=1)


def _done(prog, s, e):
    return any(a <= s.isoformat() and e.isoformat() <= b for a, b in prog.get("done", []))


def run(start, end, chunk=30, minutes=300, push=True):
    os.environ.setdefault("LCF_ENRICH_MAX", "5000")      # collect가 import 때 읽음
    from . import api, collect, sync
    t0 = time.time()
    prog = read_json(PROGRESS, {"done": []})
    todo = [(s, e) for s, e in _chunks(start, end, chunk) if not _done(prog, s, e)]
    log(f"백필 {start} ~ {end}: 남은 구간 {len(todo)}개 (구간 {chunk}일)")
    for i, (s, e) in enumerate(todo):
        if (time.time() - t0) / 60 > minutes:
            log(f"시간 한도 {minutes}분 — 남은 구간 {len(todo) - i}개는 다음 실행에서")
            status("backfill", left=len(todo) - i, calls=api.CALLS["n"])
            return 3
        collect.run(s, e, seed=True)
        prog["done"].append([s.isoformat(), e.isoformat()])
        write_json(PROGRESS, prog, pretty=True)
        log(f"구간 완료 {s} ~ {e} ({i + 1}/{len(todo)}) · 누적 API {api.CALLS['n']}회 · {(time.time() - t0) / 60:.0f}분")
        if push:
            sync.push()
    status("backfill", left=0, calls=api.CALLS["n"], range=[start.isoformat(), end.isoformat()])
    log("백필 끝")
    return 0
