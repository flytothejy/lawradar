// 색인 검색 — R2의 lcf/ask/index.tsv (머리줄 + 한 줄에 변경 하나)를 쪼개지 않고 indexOf로 맞는 줄만 꺼냄
// 점수: 맞은 '서로 다른' 낱말 수(검색어 3, 질문 낱말 1) + 이름에 들어 있음 + 분야 팩 + AI 정리 여부 + 최근일수록
// (같은 낱말이 여러 번 나오는 긴 요약이 이기지 않도록 횟수는 세지 않음)

const STOP = /^(바뀌|바뀐|달라|어요|나요|있어|있나|뭐|무엇|언제|알려|궁금|관련|해서|하는|어떻게|좀|요즘|최근|지금|현재|이번)/;
const PARTICLE = /(은|는|이|가|을|를|의|에|에서|으로|로|와|과|도|만|이요|요|자)$/;

export function terms(keywords, q) {
  const words = q.split(/[\s,.?!·()「」"']+/).filter((t) => t.length >= 2 && !STOP.test(t));
  const out = new Map();                                    // 낱말 → 가중치
  for (const k of keywords) out.set(k, 3);
  for (const w of words) {
    if (!out.has(w)) out.set(w, 1);
    const s = w.replace(PARTICLE, "");                      // '다주택자' → '다주택', '양도세를' → '양도세'
    if (s.length >= 2 && s !== w && !out.has(s)) out.set(s, out.get(w));
  }
  for (const k of keywords) {
    const s = k.replace(PARTICLE, "");
    if (s.length >= 2 && !out.has(s)) out.set(s, 3);
  }
  return [...out.entries()].slice(0, 14);
}

export function search(idx, keywords, q, pack, limit = 8, now = Date.now()) {
  const T = terms(keywords, q);
  const hits = new Map();                                   // 줄 시작 위치 → 맞은 낱말 집합
  for (const [t] of T) {
    let pos = 0, n = 0;
    while ((pos = idx.body.indexOf(t, pos)) !== -1 && n < 3000) {
      const s = idx.body.lastIndexOf("\n", pos) + 1;
      if (!hits.has(s)) hits.set(s, new Set());
      hits.get(s).add(t);
      pos += t.length; n++;
    }
  }
  const W = new Map(T);
  const rows = [];
  for (const [s, got] of hits) {
    if (![...got].some((t) => W.get(t) >= 3) && keywords.length) continue;      // 검색어가 하나도 안 맞으면 버림
    const e = idx.body.indexOf("\n", s);
    const vals = idx.body.slice(s, e === -1 ? undefined : e).split("\t");
    const r = Object.fromEntries(idx.cols.map((c, i) => [c, vals[i] || ""]));
    let sc = 0;
    for (const t of got) sc += W.get(t) + (r.name.includes(t) ? 2 : 0) + (r.title.includes(t) ? 2 : 0);
    if (pack && r.packs.split(",").includes(pack)) sc += 6;
    if (r.title) sc += 2;                                   // AI로 정리된 항목 (사용자에게 보여 줄 만한 것)
    const age = (now - Date.parse(r.announced)) / 864e5;
    sc += Math.max(0, 4 - age / 120);                       // 최근 1년 안이면 가산
    rows.push({ ...r, score: sc, matched: [...got] });
  }
  rows.sort((a, b) => b.score - a.score || b.announced.localeCompare(a.announced));
  const top = rows.length ? rows[0].score : 0;
  return rows.filter((r) => r.score >= top * 0.4).slice(0, limit);      // 1등보다 훨씬 약한 것은 버림
}

// 답 작성이 안 될 때: 가장 관련 있는 항목을 그대로 소개 (근거 문장만 써서 숫자 검증이 필요 없음)
export function plainAnswer(rows) {
  const r = rows[0];
  if (!r) return "";
  const d = r.announced ? `${+r.announced.slice(0, 4)}년 ${+r.announced.slice(5, 7)}월 ${+r.announced.slice(8, 10)}일` : "";
  const what = r.title || firstSentence(r.summary);
  return `가장 가까운 변경은 ${d} 공포된 「${r.name}」이에요.` + (what ? ` ${what}` : "") + (rows.length > 1 ? " 아래 다른 관련 변경도 함께 확인해 보세요." : "");
}

function firstSentence(t) {
  const s = String(t || "").split(/(?<=[.다함음])\s/)[0];
  return s.length > 160 ? s.slice(0, 157) + "…" : s;
}
