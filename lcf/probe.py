"""법령 API 응답 구조 보기 (등록 IP에서만 호출되므로 Actions의 probe 워크플로로 실행)

  python -m lcf probe service law MST=290841            본문 응답의 키 구조 (값은 앞부분만)
  python -m lcf probe search lsJoHstInf ID=... JO=...   목록 응답
  python -m lcf probe find 부칙 service law MST=290841   특정 키 아래를 길게
"""
import json, sys

from . import api


def shape(x, depth=0, maxd=5, w=160):
    pad = "  " * depth
    if isinstance(x, dict):
        for k, v in list(x.items())[:40]:
            if isinstance(v, (dict, list)):
                n = len(v)
                print(f"{pad}{k}: {'{…}' if isinstance(v, dict) else f'[{n}]'}")
                if depth < maxd:
                    shape(v if isinstance(v, dict) else v[:2], depth + 1, maxd, w)
            else:
                print(f"{pad}{k}: {str(v)[:w]!r}")
    elif isinstance(x, list):
        for i, v in enumerate(x[:2]):
            print(f"{pad}- [{i}]")
            shape(v, depth + 1, maxd, w)


def _params(args):
    return dict(a.split("=", 1) for a in args)


def run(a):
    if a[0] == "find":
        key, mode, target, rest = a[1], a[2], a[3], _params(a[4:])
        j = api.service(target, **rest) if mode == "service" else api.search(target, **rest)[0]
        def walk(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    if k == key:
                        print(json.dumps(v, ensure_ascii=False, indent=1)[:6000]); return True
                    if walk(v):
                        return True
            elif isinstance(x, list):
                return any(walk(v) for v in x)
            return False
        if not walk(j):
            print(f"{key} 없음")
        return
    if a[0] == "enrich":                                   # python -m lcf probe enrich admrul <일련번호> — 보강 결과 미리 보기
        from . import collect, llm
        from .classify import classify
        kind, seq = a[1], a[2]
        rows, _ = api.search(kind, query=a[3]) if len(a) > 3 else ([], 0)
        r = next((x for x in rows if str(x.get({"admrul": "행정규칙일련번호", "law": "법령일련번호", "ordin": "자치법규일련번호"}[kind])) == seq), None)
        it = classify({"admrul": collect.norm_admrul, "law": collect.norm_law, "ordin": collect.norm_ordin}[kind](r)) if r else \
            {"kind": kind, "seq": seq, "id": None, "name": "", "type": "고시", "change": "일부개정", "announced": "", "no": "", "cls": {"topics": [], "level": "mid", "life": False}}
        collect._enrich(it)
        print(json.dumps({k: v for k, v in it.items() if k != "detail"}, ensure_ascii=False)[:600])
        print(json.dumps(it.get("detail"), ensure_ascii=False, indent=1)[:5000])
        print("----- 모델 입력")
        print(llm.source_text(it)[:3000])
        return
    mode, target, rest = a[0], a[1], _params(a[2:])
    if mode == "service":
        shape(api.service(target, **rest))
    else:
        rows, total = api.search(target, **rest)
        print(f"total {total}, rows {len(rows)}")
        shape(rows[:2])


if __name__ == "__main__":
    run(sys.argv[1:])
