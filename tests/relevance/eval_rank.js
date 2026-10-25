// AI 재판정 평가 — 후보(cands.json) 중 판정 ≥ 기준만 본문으로 볼 때의 정밀도·재현율 (gold + gold2)
// node eval_rank.js labels.json [기준=1]
const fs = require('fs'), path = require('path');
const labels = JSON.parse(fs.readFileSync(process.argv[2])), T = +(process.argv[3] || 1);
const gold = JSON.parse(fs.readFileSync(path.join(__dirname, 'gold.json')));
const g2 = JSON.parse(fs.readFileSync(path.join(__dirname, 'gold2.json')));
for (const [i, m] of Object.entries(g2)) if (i !== 'notes') Object.assign(gold[i], m);
const cands = JSON.parse(fs.readFileSync(path.join(__dirname, 'cands.json')));
let S = 0, S1 = 0, S2 = 0, G1 = 0, G2 = 0, H1 = 0, H2 = 0, miss = [];
for (const o of cands) {
  const g = gold[o.persona], lab = labels[o.persona] || {};
  for (const [k, v] of Object.entries(g)) { if (v >= 1) G1++; if (v === 2) G2++; }
  for (const c of o.cands) {
    const shown = (lab[c.key] ?? 1) >= T, v = g[c.key] ?? 0;      // 판정이 없으면 보여 줌 (안전 쪽)
    if (shown) { S++; if (v >= 1) { S1++; H1++; } if (v === 2) { S2++; H2++; } }
    else if (v === 2) miss.push(`${o.persona} ${c.title || c.name}`);
  }
}
console.log(`기준 ${T}: 보임 ${S} · 정밀도 ${(100 * S1 / S).toFixed(0)}% (꼭 관련 ${(100 * S2 / S).toFixed(0)}%) · 꼭 관련 재현 ${H2}/${G2} · 관련 재현 ${H1}/${G1} (${(100 * H1 / G1).toFixed(0)}%)`);
if (miss.length) console.log('  놓친 꼭 관련:', miss.join(' / '));
