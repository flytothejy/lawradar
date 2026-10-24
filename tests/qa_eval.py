"""질문 판별 평가 — 배포된 Worker에 tests/qa_cases.json을 보내 유형 판별을 확인

  ASK_URL=https://…/ask TEST_KEY=… python tests/qa_eval.py [--answers 3]

- must_not 위반(예: 개별 판정을 변화 확인으로 봄)이 하나라도 있으면 종료 코드 1
- 정답률은 참고로 출력. --answers N: 유형별로 N건은 실제 답까지 받아 출력
"""
import json, os, sys, time
from collections import Counter
from pathlib import Path

import requests

URL, KEY = os.environ["ASK_URL"], os.environ["TEST_KEY"]
cases = json.loads((Path(__file__).parent / "qa_cases.json").read_text(encoding="utf-8"))["cases"]
n_ans = int(sys.argv[sys.argv.index("--answers") + 1]) if "--answers" in sys.argv else 0


def post(q, test=None):
    for i in range(3):
        r = requests.post(URL, json={"q": q, **({"test": test} if test else {})}, headers={"x-test-key": KEY}, timeout=90)
        if r.ok:
            return r.json()
        time.sleep(3)
    return {"error": f"HTTP {r.status_code} {r.text[:200]}"}


ok = bad = 0
viol, conf = [], Counter()
for c in cases:
    o = post(c["q"], "classify")
    got = o.get("type", "error")
    conf[(c["type"], got)] += 1
    if got == c["type"]:
        ok += 1
    else:
        bad += 1
    mark = "✓" if got == c["type"] else "✗"
    if got in c.get("must_not", []):
        viol.append(c); mark = "‼"
    print(f"{mark} [{c['type']:>12} → {got:<12}] {c['q']}  {o.get('keywords', '')}" + (" (판별 실패→보수 처리)" if o.get("fallback") else "") + (f" {o.get('error')}" if o.get("error") else ""))
print(f"\n정답 {ok}/{len(cases)} · must_not 위반 {len(viol)}")
print("혼동:", dict(conf))
if n_ans:
    shown = Counter()
    for c in cases:
        if shown[c["type"]] >= n_ans or c["type"] == "out_of_scope":
            continue
        shown[c["type"]] += 1
        o = post(c["q"])
        print(f"\nQ. {c['q']}\n[{o.get('type')}] {o.get('answer') or o.get('error')}")
        for it in o.get("items", [])[:3]:
            print(f"   · {it['announced']} {it['name']} — {it['title']}")
sys.exit(1 if viol else 0)
