// 브랜드 이미지 만들기: node design/render.js  → web/img/
const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const d = __dirname, out = path.join(d, '..', 'web', 'img');
  const b = await chromium.launch();
  const p = await b.newPage({ viewport: { width: 1200, height: 630 } });
  await p.goto('file://' + path.join(d, 'og.html'));
  await p.evaluate(() => document.fonts.ready);
  await p.waitForTimeout(800);
  await p.screenshot({ path: path.join(out, 'og.png') });
  for (const [n, s] of [['apple-touch-icon.png', 180], ['icon-192.png', 192], ['icon-512.png', 512]]) {
    const q = await b.newPage({ viewport: { width: s, height: s } });
    // 아이폰은 투명 모서리를 검게 칠하므로 apple-touch-icon은 모서리 없이 꽉 채움
    const svg = require('fs').readFileSync(path.join(d, 'icon.svg'), 'utf8').replace(n.startsWith('apple') ? 'rx="14"' : '@@', 'rx="0"');
    await q.goto('data:image/svg+xml;base64,' + Buffer.from(svg.replace('<svg ', `<svg width="${s}" height="${s}" `)).toString('base64'));
    await q.screenshot({ path: path.join(out, n), omitBackground: true });
  }
  await b.close();
})();
