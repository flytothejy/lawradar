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

  // ── 관련도 v2: 꼬리표 맞추기 (docs/RELEVANCE.md) ─────────────────────
  // 변경(r.aud·r.act)과 조건(p.aud, 분야별 aud)이 같은 꼬리표 목록을 씀. 둘 다 있을 때만 쓰고, 없으면 예전 방식(LR.match1)
  const BROAD = new Set(["직장인", "소상공인", "중소기업", "고용주", "법인", "학생·청소년", "청년", "노인", "1인 가구", "학부모"]);
  const ACTION = ["받을 것", "해야 할 것", "하면 안 되는 것", "계산이 바뀌는 것", "권리가 바뀌는 것"];
  LR.effAud = (p) => {                                       // 사람 꼬리표에서, 끈 분야에만 있던 것은 뺌
    const on = (p.interests || []).filter((x) => x.on), off = (p.interests || []).filter((x) => !x.on);
    const offOnly = new Set(off.flatMap((x) => x.aud || []));
    on.forEach((x) => (x.aud || []).forEach((t) => offOnly.delete(t)));
    return new Set((p.aud || []).filter((t) => !offOnly.has(t)));   // 분야별 aud는 칸 나누기에만 (사람 꼬리표 밖은 더하지 않음)
  };
  LR.v2 = (r, p) => !!(+r.tagged && p && p.aud && p.aud.length);
  LR.match2 = (r, p) => {
    const aud = (r.aud || "").split("|").filter(Boolean), act = (r.act || "").split("|").filter(Boolean);
    const internal = !aud.length && (act.includes("행정 내부") || !act.length);
    if (!aud.length && !internal) {                           // 꼬리표를 못 붙였지만 할 일이 있는 변경 — 예전 규칙으로, 낱말만 맞으면 약하게
      const m1 = match1(r, p);
      if (m1 && m1.strong && !m1.why.some((w) => !w.startsWith("관심 낱말"))) m1.strong = false;
      return m1;
    }
    const pa = LR.effAud(p), hit = aud.filter((t) => pa.has(t));
    const doing = act.some((a) => ACTION.includes(a));
    const text = `${r.name} ${r.title || ""}`;
    const kw = (p.keywords || []).find((k) => LR.hasWord(text, k));
    const law = r.base && (p.laws || []).includes(r.base);
    const on = (p.interests || []).filter((x) => x.on);
    const areaOf = () => {
      const it = on.find((x) => (x.aud || []).some((t) => hit.includes(t)));
      return it ? { id: it.topic + ":" + it.label, label: it.label } : { id: "aud:" + hit[0], label: hit[0] };
    };
    const whyAud = hit.length ? [`${hit.slice(0, 2).join("·")}에게 닿는 변화`] : [];
    if (r.kind === "ordin") {
      const local = { id: "local", label: `우리 동네 · ${short(p.region || p.sido)}` };
      if (internal) return null;                              // 의회·위원회·기관 운영 같은 조례는 보이지 않음
      if (p.region && r.org === p.region) {
        if (hit.length)
          return { why: [p.region === p.sido ? `${p.sido} 조례` : `우리 동네(${short(p.region)}) 조례`, ...whyAud], strong: true, area: local, kw: kw || null };
        return { why: [`우리 동네(${short(p.region)}) 조례`], strong: false, area: local, kw: kw || null };   // '지역 주민 누구나'도 접힌 칸
      }
      if (p.sido && r.org === p.sido && hit.length) return { why: [`${p.sido} 조례`, ...whyAud], strong: true, area: local, kw: kw || null };
      return null;
    }
    if (internal) return null;
    // 넓은 꼬리표(직장인·소상공인 등)만 겹치면 접힌 칸 — 2차 판정(실제로 보이는 것 전부)에서 '콕 집으면 허용'은 정밀도 30%, 이 규칙은 39%
    const specific = hit.some((t) => !BROAD.has(t));
    const focused = aud.length <= 2 && act.some((a) => a !== "절차가 바뀌는 것" && a !== "행정 내부");
    if (hit.length && (!act.length || !specific)) return { why: whyAud, strong: false, area: null, kw: kw || null };
    if (hit.length) {
      const why = [...whyAud]; if (law) why.unshift(`지켜보는 법령: ${r.base}`); if (kw) why.push(`관심 낱말: ${kw}`);
      return { why, strong: true, area: areaOf(), kw: kw || null };
    }
    // 대상은 안 겹치지만 내가 고른 법령·낱말 — 아래 '그 밖에' 접힌 칸으로
    if (law || kw || (aud.includes("국민 누구나") && doing))
      return { why: [law ? `지켜보는 법령: ${r.base}` : kw ? `관심 낱말: ${kw}` : "모두에게 닿는 변화"], strong: false, area: null, kw: kw || null };
    return null;
  };
  const match1 = LR.match;
  LR.match1 = match1;
  LR.match = (r, p) => (LR.v2(r, p) ? LR.match2(r, p) : match1(r, p));

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
