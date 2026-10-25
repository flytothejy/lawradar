// 관련도 평가 — gold.json(독립 판정) 기준으로 '강한 일치'(타임라인 본문)의 정밀도·재현율
// node eval.js <match.js 경로> <timeline.json 경로>
global.window = {}; global.localStorage = { getItem: () => null, setItem: () => {} };
const fs = require('fs'), path = require('path');
require(path.resolve(process.argv[2] || '../../web/match.js')); const LR = window.LR;
const d = JSON.parse(fs.readFileSync(process.argv[3] || 'tl.json'));
const rows = new Map(d.rows.map(r => { const o = Object.fromEntries(d.cols.map((k, i) => [k, r[i]])); return [o.key, o]; }));
const gold = JSON.parse(fs.readFileSync(path.join(__dirname, 'gold.json')));
let T = { s: 0, s2: 0, s1: 0, g2: 0, g1: 0, h2: 0, h1: 0 };
const lines = [];
for (let i = 1; i <= 9; i++) {
  const p = JSON.parse(fs.readFileSync(path.join(__dirname, `p${i}.json`))).profile;
  const g = gold[String(i)]; let s = 0, s2 = 0, s1 = 0, g2 = 0, g1 = 0, h2 = 0, h1 = 0;
  for (const [k, lab] of Object.entries(g)) {
    const r = rows.get(k); if (!r) continue;
    const m = LR.match(r, p), strong = !!(m && m.strong);
    if (lab === 2) g2++; if (lab >= 1) g1++;
    if (strong) { s++; if (lab === 2) s2++; if (lab >= 1) s1++; if (lab === 2) h2++; if (lab >= 1) h1++; }
  }
  lines.push(`${i} 보임 ${s} · 정밀도(≥1) ${s ? (100 * s1 / s).toFixed(0) : '-'}% · 꼭(2) 잡음 ${h2}/${g2} · 관련(≥1) 잡음 ${h1}/${g1}`);
  T.s += s; T.s1 += s1; T.s2 += s2; T.g2 += g2; T.g1 += g1; T.h2 += h2; T.h1 += h1;
}
console.log(lines.join('\n'));
console.log(`전체: 보임 ${T.s} · 정밀도 ${(100 * T.s1 / T.s).toFixed(0)}% (꼭 관련 ${(100 * T.s2 / T.s).toFixed(0)}%) · 꼭 관련 재현 ${T.h2}/${T.g2} · 관련 재현 ${T.h1}/${T.g1} (${(100 * T.h1 / T.g1).toFixed(0)}%)`);
