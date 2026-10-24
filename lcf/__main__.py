"""사용법
  python -m lcf collect [--from YYYY-MM-DD] [--to YYYY-MM-DD] [--seed]
  python -m lcf daily [--no-notify]          매일: 수집 → 화면 → 일일 알림
  python -m lcf digest [프로필] [--to 날짜] [--days 7] [--no-notify]   주간 다이제스트
  python -m lcf enrich --from 날짜 [--to 날짜] [--minutes 60]   수집해 둔 날짜를 보강만 (최근부터)
  python -m lcf pack <팩id> [--from 날짜] [--to 날짜]   분야 팩에 걸린 변경 미리보기
  python -m lcf polish [--from 날짜] [--to 날짜] [--max 300] [--model 이름] [--keys 파일 --out 결과.json --no-save] [--dry]   AI로 쉬운 말 정리
  python -m lcf askindex [--put]             질문 응답 색인 (R2 lcf/ask/index.tsv)
  python -m lcf pages                        변경 상세 페이지·sitemap (data/lcf/pages/)
  python -m lcf build                        화면 데이터(site/) 다시 만들기
  python -m lcf notify [날짜]                 일일 알림만 다시 보내기
  python -m lcf backfill --from 날짜 --to 날짜 [--chunk 30] [--minutes 300] [--no-push]   과거 백필 (이어하기)
  python -m lcf sync pull|push|ls [--all-days]
  python -m lcf alert "메시지"
  python -m lcf backlog [--minutes 300] [--limit N] [--days 730] [--max-usd 0] [--count]   과거분 보강 → 배치 정리 (이어하기)
  python -m lcf bench --models a,b [--n 50] [--days 30]   모델 비교 시험 (data/lcf/bench/)
  python -m lcf probe service|search|find …   법령 API 응답 구조 보기 (lcf/probe.py)
"""
import datetime as dt
import sys

from .core import load_env


def _opt(a, name, cast=str, default=None):
    return cast(a[a.index(name) + 1]) if name in a else default


def main(a):
    load_env()
    cmd = a[0] if a else "help"
    D = dt.date.fromisoformat
    if cmd == "collect":
        from . import collect
        collect.run(_opt(a, "--from", D), _opt(a, "--to", D), seed="--seed" in a)
    elif cmd == "daily":
        from . import collect, build, notify
        from . import llm
        collect.run(); llm.run(); build.run()
        if "--no-notify" not in a:
            notify.daily()
    elif cmd == "digest":
        from . import digest
        pid = a[1] if len(a) > 1 and not a[1].startswith("--") else None
        digest.run(pid, end=_opt(a, "--to", D), days=_opt(a, "--days", int, 7), send="--no-notify" not in a)
    elif cmd == "enrich":
        from . import collect
        sys.exit(collect.enrich_range(_opt(a, "--from", D), _opt(a, "--to", D) or dt.date.today(), _opt(a, "--minutes", int, 60)))
    elif cmd == "pack":
        from . import packs
        if len(a) < 2:
            print("팩:", ", ".join(packs.all_ids())); return
        packs.preview(a[1], _opt(a, "--from", D), _opt(a, "--to", D))
    elif cmd == "polish":
        from . import llm
        ks = _opt(a, "--keys", str)
        keys = [x.strip() for x in open(ks, encoding="utf-8") if x.strip()] if ks else None
        llm.run(_opt(a, "--from", D), _opt(a, "--to", D), _opt(a, "--max", int), dry="--dry" in a,
                model=_opt(a, "--model", str), save="--no-save" not in a, keys=keys, out=_opt(a, "--out", str))
    elif cmd == "askindex":
        from . import askindex; askindex.run(put="--put" in a)
    elif cmd == "pages":
        from . import pages; pages.run()
    elif cmd == "build":
        from . import build; build.run()
    elif cmd == "notify":
        from . import notify; notify.daily(a[1] if len(a) > 1 else None)
    elif cmd == "backfill":
        from . import backfill
        sys.exit(backfill.run(_opt(a, "--from", D), _opt(a, "--to", D), _opt(a, "--chunk", int, 30),
                              _opt(a, "--minutes", int, 300), push="--no-push" not in a))
    elif cmd == "sync":
        from . import sync
        if a[1] == "pull":
            sync.pull(all_days="--all-days" in a)
        else:
            {"push": sync.push, "ls": sync.ls}[a[1]]()
    elif cmd == "backlog":
        from . import backlog
        if "--count" in a:
            backlog.count(); sys.exit(0)
        sys.exit(backlog.run(_opt(a, "--minutes", int, 300), _opt(a, "--limit", int), dry="--dry" in a,
                             days=_opt(a, "--days", int, 730), max_usd=_opt(a, "--max-usd", float, 0.0)))
    elif cmd == "bench":
        from . import bench
        bench.run(_opt(a, "--models", str, "claude-sonnet-5-5,claude-haiku-5-5").split(","), _opt(a, "--n", int, 50), _opt(a, "--days", int, 30))
    elif cmd == "probe":
        from . import probe; probe.run(a[1:])
    elif cmd == "alert":
        from . import notify; notify.send(" ".join(a[1:]))
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
