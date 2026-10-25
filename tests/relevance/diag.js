global.window = {}; global.localStorage = { getItem: () => null, setItem: () => {} };
const fs = require('fs'), path = require('path');
require(path.resolve('../../web/match.js')); const LR = window.LR;
const d = JSON.parse(fs.readFileSync(process.argv[2]));
const rows = new Map(d.rows.map(r => { const o = Object.fromEntries(d.cols.map((k, i) => [k, r[i]])); return [o.key, o]; }));
const gold = JSON.parse(fs.readFileSync('gold.json'));
for (let i = 1; i <= 9; i++) {
  const p = JSON.parse(fs.readFileSync(`p${i}v2.json`)).profile;
  const miss = [], fp = [];
  for (const [k, lab] of Object.entries(gold[String(i)])) {
    const r = rows.get(k); if (!r) continue;
    const m = LR.match(r, p), s = !!(m && m.strong);
    const line = `${(r.title || r.name).slice(0, 38)} | ${r.kind} | aud=${r.aud} | act=${r.act}`;
    if (lab >= 1 && !s) miss.push(`[${lab}] ` + line);
    if (lab === 0 && s) fp.push(line);
  }
  console.log(`===== ${i} aud=${p.aud}`);
  miss.filter(x => x.startsWith('[2]')).forEach(x => console.log('  놓침', x));
  miss.filter(x => x.startsWith('[1]')).slice(0, 4).forEach(x => console.log('  놓침', x));
  fp.slice(0, 6).forEach(x => console.log('  잘못', x));
}
