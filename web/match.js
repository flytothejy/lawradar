// 법레이더 — 내 조건(프로필)과 변경 항목 맞추기. 첫 화면(index.html)과 상세 페이지(c/*.html)가 함께 씀
// 프로필: {who, region, sido, job, interests:[{label, topic, on}], laws:[], keywords:[], text}
// 항목: timeline.json 한 줄 {kind, name, base, org, topics:"a|b", life, level, packs:"x,y", title, ...}
(function () {
  const KEY = "lr-profile";
  const LR = {};

  LR.load = () => { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { return null; } };
  LR.save = (p) => { try { localStorage.setItem(KEY, JSON.stringify(p)); } catch (e) {} };
  LR.clear = () => { try { localStorage.removeItem(KEY); } catch (e) {} };

  const short = (org) => (org || "").split(" ").slice(1).join(" ") || org;

  // 맞으면 {why:[이유…], strong} — strong: 지역·지켜보는 법령·낱말·분야 팩처럼 분명한 이유
  LR.match = (r, p) => {
    if (!p) return null;
    const why = [];
    let strong = false;
    const on = (p.interests || []).filter((x) => x.on);
    const topics = (r.topics || "").split("|"), packs = (r.packs || "").split(",");
    const text = `${r.name} ${r.title || ""}`;
    const kw = (p.keywords || []).find((k) => text.includes(k));
    if (r.kind === "ordin") {
      if (p.region && r.org === p.region) return { why: [p.region === p.sido ? `${p.sido} 조례` : `우리 동네(${short(p.region)}) 조례`], strong: true };
      if (p.sido && r.org === p.sido) {                     // 시·도 조례는 많아서 내 분야·낱말과 겹칠 때만
        const hit = kw ? `관심 낱말: ${kw}` : (on.find((x) => topics.includes(x.topic)) || {}).label;
        return hit ? { why: [`${p.sido} 조례`, hit], strong: !!kw } : null;
      }
      return null;                                          // 다른 지역 조례는 보이지 않음
    }
    if (r.base && (p.laws || []).includes(r.base)) { why.push(`지켜보는 법령: ${r.base}`); strong = true; }
    if (kw) { why.push(`관심 낱말: ${kw}`); strong = true; }
    for (const it of on) {
      if (packs.includes(it.topic)) { why.push(it.label); strong = true; continue; }
      // 분야만 겹칠 때는 생활에 닿는 것(AI가 정리했거나 중요 표시)만
      if (topics.includes(it.topic) && (r.title || r.level === "high") && (r.kind !== "law" || +r.life || r.level === "high")) why.push(it.label);
    }
    return why.length ? { why: [...new Set(why)], strong } : null;
  };

  LR.dday = (d, today) => {
    if (!d) return null;
    const n = Math.round((Date.parse(d) - Date.parse(today)) / 864e5);
    return n > 0 ? `D-${n}` : n === 0 ? "오늘 시행" : null;
  };
  LR.today = () => new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);   // 한국 날짜
  LR.md = (d) => (d ? `${+d.slice(5, 7)}.${+d.slice(8, 10)}` : "");
  LR.ymd = (d) => (d ? `${d.slice(0, 4)}.${+d.slice(5, 7)}.${+d.slice(8, 10)}` : "");
  window.LR = LR;
})();
