// 법레이더 — 내 조건(프로필)과 변경 항목 맞추기. 첫 화면(index.html)과 상세 페이지(c/*.html)가 함께 씀
// 프로필: {who, region, sido, job, interests:[{label, topic, on}], laws:[], keywords:[], text}
// 항목: timeline.json 한 줄 {kind, name, base, org, topics:"a|b", life, level, packs:"x,y", title, ...}
(function () {
  const KEY = "lr-profile";
  const LR = {};

  LR.load = () => { try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch (e) { return null; } };
  LR.save = (p) => { try { localStorage.setItem(KEY, JSON.stringify(p)); } catch (e) {} };
  LR.clear = () => { try { localStorage.removeItem(KEY); } catch (e) {} };

  // 낱말 찾기 — 두 글자 낱말은 앞에 한글이 붙어 있으면 다른 말의 일부로 봄 ('부업' ≠ 대부업·정부업무)
  LR.hasWord = (text, k) => {
    if (!k) return false;
    if (k.length > 2) return text.includes(k);
    for (let i = text.indexOf(k); i >= 0; i = text.indexOf(k, i + 1)) {
      if (i === 0 || !/[가-힣]/.test(text[i - 1])) return true;
    }
    return false;
  };
  const short = (org) => (org || "").split(" ").slice(1).join(" ") || org;

  // 맞으면 {why:[이유…], strong} — strong: 지역·지켜보는 법령·낱말·분야 팩처럼 분명한 이유
  LR.match = (r, p) => {
    if (!p) return null;
    const why = [];
    let strong = false;
    const on = (p.interests || []).filter((x) => x.on);
    const topics = (r.topics || "").split("|"), packs = (r.packs || "").split(",");
    const text = `${r.name} ${r.title || ""}`;
    const kw = (p.keywords || []).find((k) => LR.hasWord(text, k));
    if (r.kind === "ordin") {
      const local = { id: "local", label: `우리 동네 · ${short(p.region || p.sido)}` };
      if (p.region && r.org === p.region) return { why: [p.region === p.sido ? `${p.sido} 조례` : `우리 동네(${short(p.region)}) 조례`], strong: true, area: local, kw: null };
      if (p.sido && r.org === p.sido) {                     // 시·도 조례는 많아서 내 분야·낱말과 겹칠 때만
        const hit = kw ? `관심 낱말: ${kw}` : (on.find((x) => topics.includes(x.topic)) || {}).label;
        return hit ? { why: [`${p.sido} 조례`, hit], strong: !!kw, area: local, kw: kw || null } : null;
      }
      return null;                                          // 다른 지역 조례는 보이지 않음
    }
    let area = null;
    for (const it of on) {
      if (packs.includes(it.topic)) { why.push(it.label); strong = true; area = area || { id: it.topic, label: it.label }; continue; }
      // 분야만 겹칠 때는 생활에 닿는 것(AI가 정리했거나 중요 표시)만
      if (topics.includes(it.topic) && (r.title || r.level === "high") && (r.kind !== "law" || +r.life || r.level === "high")) {
        why.push(it.label); area = area || { id: it.topic, label: it.label };
      }
    }
    if (r.base && (p.laws || []).includes(r.base)) { why.unshift(`지켜보는 법령: ${r.base}`); strong = true; area = area || { id: "laws", label: "지켜보는 법령" }; }
    if (kw) { why.push(`관심 낱말: ${kw}`); strong = true; area = area || { id: "kw", label: "관심 낱말" }; }
    return why.length ? { why: [...new Set(why)], strong, area, kw: kw || null } : null;
  };

  // 쉬운 종류 표시 — 누가 바꾼 것인지 (guide.html '법은 이렇게 생겼어요'와 같은 말)
  LR.kind = (r) => {
    if (r.kind === "law") return r.type === "법률" ? { t: "국회가 바꾼 법", c: "b-law" } : { t: "정부 세부 기준", c: "b-dec" };
    if (r.kind === "admrul") return { t: "부처 고시", c: "b-adm" };
    const ty = r.type === "의회규칙" ? "의회 규칙" : r.type;
    return { t: `${short(r.org)} ${ty}`, c: "b-loc" };
  };
  // 같은 법 묶음 — 법률·시행령·시행규칙은 base가 같고, 그 밖에는 이름이 같으면 한 식구
  LR.fam = (r) => r.base || r.name;

  // 관심 표시 — 이 기기에만 저장. {star:{key:시각}, hide:{key:1}, hideFam:{법령:1}, dropKw:[낱말]}
  const FB = "lr-fb";
  LR.fb = () => { try { return { star: {}, hide: {}, hideFam: {}, dropKw: [], ...JSON.parse(localStorage.getItem(FB) || "{}") }; } catch (e) { return { star: {}, hide: {}, hideFam: {}, dropKw: [] }; } };
  LR.fbSave = (f) => { try { localStorage.setItem(FB, JSON.stringify(f)); } catch (e) {} };
  LR.hidden = (r, f) => !!(f.hide[r.key] || f.hideFam[LR.fam(r)]);

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
