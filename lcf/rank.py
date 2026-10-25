"""AI 재판정 — 꼬리표로 넓게 모은 후보를, 그 사람이 직접 쓴 상황 글 기준으로 한 번 더 판정 (docs/RELEVANCE.md)

  python -m lcf rank-eval [--model M] [--cands tests/relevance/cands.json] [--out data/lcf/rank/labels.json]

- 판정: 2 꼭 관련 · 1 관련될 수도 · 0 무관 — 평가셋 판정자와 같은 기준
- 화면(Worker /rank)과 평가가 같은 프롬프트를 쓰도록 PROMPT는 config/rank_prompt.txt 한 곳에
"""
import json, os
from pathlib import Path

from . import llm
from .core import DATA, ROOT, log

PROMPT = (ROOT / "config" / "rank_prompt.txt").read_text(encoding="utf-8")
PER_CALL = 30


def cand_line(c):
    t = c.get("title") or ""
    return (f"[{c['key']}] {c['kind']} · {c['name']}" + (f" — {t}" if t else "") +
            (f" / {c['line']}" if c.get("line") and c["line"] != t else "") +
            (f" (시행 {c['effective']})" if c.get("effective") else ""))


def user_msg(text, region, cands):
    return f"상황 (사용자가 직접 쓴 글): {text}\n사는 곳: {region or '모름'}\n\n후보:\n" + "\n".join(cand_line(c) for c in cands)


def rank(text, region, cands, model):
    """{key: 0|1|2}, usage"""
    out, usage = {}, {"input_tokens": 0, "output_tokens": 0}
    mm, th, mt = (model[:-6], None, 8000) if model.endswith(":think") else (model, llm.no_thinking(model), 3000)
    for i in range(0, len(cands), PER_CALL):
        chunk = cands[i:i + PER_CALL]
        txt, u = llm.call(mm, PROMPT, user_msg(text, region, chunk), max_tokens=mt, thinking=th)
        for k in usage:
            usage[k] += u.get(k, 0)
        want = {c["key"] for c in chunk}
        for o in llm._parse(txt):
            if isinstance(o, dict) and o.get("key") in want and o.get("label") in (0, 1, 2):
                out[o["key"]] = o["label"]
    return out, usage


def evaluate(model, cands_path, out_path):
    data = json.loads(Path(cands_path).read_text(encoding="utf-8"))
    labels, usd = {}, 0.0
    for o in data:
        lab, u = rank(o["text"], o["region"], o["cands"], model)
        labels[str(o["persona"])] = lab
        usd += llm.usd(model.replace(":think", ""), u)
        log(f"  {o['persona']}: 후보 {len(o['cands'])} · 판정 {len(lab)} · 2={sum(v == 2 for v in lab.values())} 1={sum(v == 1 for v in lab.values())}")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(labels, ensure_ascii=False, indent=1), encoding="utf-8")
    log(f"재판정 끝 ({model}) · 약 ${usd:.3f} → {out_path}")
