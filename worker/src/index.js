// 법레이더 — 질문 응답 Worker
// POST /ask {q}  →  {type, answer, items[], notice}
// POST /profile {text}  →  {profile}  상황 글을 조건(지역·하는 일·분야·지켜볼 법령·낱말)으로
// POST /report {key, parts[], text}  →  '원문과 달라요' 신고 (R2 lcf/state/reports/<key>.json, 다음 화면 갱신부터 그 항목은 원문만)
// POST /subscribe {email, channel, prefs, profile}  →  알림 신청 저장 (발송 시작 전 대기 명단)
// 원칙(docs/SCENARIO.md): 판정 대신 변화로 답한다. 근거는 R2의 변경 색인(lcf/ask/index.tsv)뿐. 출처 없는 답은 내보내지 않는다.
//
// 바인딩: BUCKET(R2), LIMITS(KV) / 비밀값: ANTHROPIC_API_KEY, TEST_KEY
// 변수: ALLOW_ORIGIN, DAILY_PER_IP, DAILY_TOTAL, MODEL_CLASSIFY, MODEL_ANSWER

import { search, plainAnswer } from "./search.js";
import RANK_PROMPT from "./rank_prompt.js";

const TYPES = ["change", "current", "judgment", "out_of_scope"];
const PACKS = { real_estate_tax: "부동산 세금" };

const CLASSIFY = `너는 법령 변화 알림 서비스 '법레이더'의 질문 분류기다. 사용자의 질문을 아래 넷 중 하나로 분류하고 검색어를 뽑는다.
- change: 무엇이 언제 바뀌었는지 묻는다 ("바뀌었나요", "달라졌어", "연장됐나요", "이번 달 뭐 바뀌었어")
- current: 지금 규정·기준·금액·기간이 무엇인지 일반적으로 묻는다 (자기 상황 없이)
- judgment: 자기(또는 특정인)의 상황에 규정이 적용되는지, 얼마를 내는지, 무엇이 유리한지, 대상인지를 묻는다.
  "저/제/우리/내 경우/작년에 샀는데/이사 가면/~되나요(본인)" 처럼 개인 상황이 붙으면 바뀐 내용을 함께 물어도 judgment다.
- out_of_scope: 신고·서류 대행, 소송 전략, 전문가 추천, 계정 문제, 법령과 무관한 질문
예: "다주택자 양도소득세 알려주세요" → current, "종부세 바뀐 거 있어?" → change, "저 다주택자인데 양도세 중과돼요?" → judgment
자기 상황이 드러나지 않으면 judgment가 아니다. 개인 상황이 있는지 애매할 때만 judgment로 분류한다.
검색어(keywords): 법령 이름, 제도 이름, 핵심 낱말을 2~6개. 법령 원문에 나올 법한 말로 (다주택자→"주택 수","2주택","중과"). 예: ["일시적 2주택","양도소득세","비과세","소득세법"]
pack: 부동산 세금(양도·취득·종부·재산세, 주택)이면 "real_estate_tax", 아니면 null
JSON 하나만 출력: {"type":"...","keywords":[...],"pack":null}`;

const ANSWER = `너는 법령 변화 알림 서비스 '법레이더'의 안내자다. 아래 '근거 항목'만 사용해 질문에 답한다. 근거에 없는 사실·숫자·날짜는 쓰지 않는다.
질문 유형에 따라:
- change: 무엇이 언제(공포·시행) 어떻게 바뀌었는지 바뀌기 전→후 중심으로 2~4문장
- current: 근거 항목은 '최근 변경'뿐이다. 최근 바뀐 내용으로 답하고, 현행 전체 조문은 원문 링크에서 확인하라고 덧붙인다
- judgment: 사용자 개인에게 적용되는지, 금액, 유불리를 절대 판단하지 않는다. 관련된 변화만 사실로 알려 주고, "본인에게 해당하는지는 세무사·변호사 등 전문가 확인이 필요해요"로 끝낸다
근거 항목 중 질문과 관련 있는 것이 없으면 answer를 ""로 둔다.
해요체, 조언("~하세요") 금지 — 단 judgment의 전문가 확인 안내는 예외.
JSON 하나만 출력: {"answer":"...","cites":["근거 key", ...]}`;

const PROFILE = (v) => `너는 법령 변화 알림 서비스 '법레이더'의 상황 정리기다. 사용자가 자기 상황을 자유롭게 적으면, 매일 법령·조례 변경 중 이 사람에게 닿을 것을 고를 '조건'으로 바꾼다.
판단·조언은 하지 않는다. 적힌 내용과 그로부터 분명히 따라오는 것만 쓴다.

출력 JSON 하나만:
{"who":"짧은 호칭 (예: 펜션 사장님, 동탄 카페 사장님, 아이 키우는 화성 시민)",
 "region":"시·군·구 정식 이름 (예: 경기도 화성시). 동네·신도시 이름은 시·군·구로 (동탄→경기도 화성시, 판교→경기도 성남시). 없으면 null",
 "job":"하는 일·처지를 한 줄 (예: 숙박업 (펜션) · 소상공인). 없으면 \"\"",
 "aud":["이 사람에게 해당하는 대상 꼬리표 2~8개 — 아래 목록에서만, 가장 분명한 것부터"],
 "interests":[{"label":"사용자에게 보일 분야 이름 (구체적으로, 예: 숙박·위생 영업 기준)","topic":"아래 분야 중 하나","aud":["이 분야에 해당하는 대상 꼬리표 1~3개 (aud 안에서)"],"on":true}],
 "laws":["지켜볼 법령의 정식 이름 (법률 이름만, 시행령·시행규칙 빼고. 예: 공중위생관리법, 소상공인기본법)"],
 "keywords":["법령 이름·제목에 나올 법한 낱말 2~6개 (예: 숙박, 영업신고, 유류세)"]}

분야(topic)는 반드시 이 중에서: ${v.topics.join(", ")}${v.packs.map((p) => `, ${p.id}(${p.name}: ${p.desc})`).join("")}
interests는 3~6개. 상황에 분명히 해당하면 on:true, '그럴 수도 있는 것'(예: 직원을 두면 노무)은 on:false로 하나 정도.
지역 조례는 region으로 따로 챙기므로 interests에 넣지 않는다.
laws는 3~6개, 실제로 있는 법률만. 확실하지 않으면 넣지 않는다.
대상 꼬리표(aud)는 반드시 이 목록에서만: ${(v.aud || []).map((g) => `[${g.name}] ${g.tags.join(" / ")}`).join(" ")}
aud는 적힌 처지에서 분명한 것만 (예: '펜션 운영' → 숙박업, 소상공인. 직원 언급이 없으면 고용주는 넣지 않음. '집 두 채' → 다주택자). "국민 누구나"·"지역 주민 누구나"는 넣지 않는다.`;

const OUT_OF_SCOPE = "이 서비스는 법령·조례가 언제 어떻게 바뀌었는지를 알려 드려요. 신고 대행이나 소송, 개인 상황 판단은 도와드릴 수 없어요.";
const NOT_FOUND = "모아 둔 변경 기록(2024년 10월 이후)에서 관련 변화를 찾지 못했어요. 국가법령정보센터에서 직접 검색해 보실 수 있어요.";
const DISCLAIMER = "자동으로 정리한 안내예요. 개인 상황에 맞는 판단은 전문가에게 확인하세요.";

const cors = (env) => ({
  "Access-Control-Allow-Origin": env.ALLOW_ORIGIN || "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "content-type, x-test-key",
  "Vary": "Origin",
});
const json = (env, obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8", ...cors(env) } });

// ── Claude ─────────────────────────────────────────────────────────────
async function claude(env, model, system, user, maxTokens) {
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
    body: JSON.stringify({ model, max_tokens: maxTokens, system, messages: [{ role: "user", content: user }] }),
  });
  if (!r.ok) throw new Error(`claude ${r.status}`);
  const j = await r.json();
  const text = (j.content || []).map((b) => b.text || "").join("");
  const m = text.match(/\{[\s\S]*\}/);
  if (!m) throw new Error("no json");
  return JSON.parse(m[0]);
}

async function classify(env, q) {
  let o = null;
  for (let i = 0; i < 2 && !o; i++) {
    try { o = await claude(env, env.MODEL_CLASSIFY || "claude-haiku-5-5", CLASSIFY, q, 300); } catch (e) { if (i) o = null; }
  }
  if (!o) {                                                  // 판별 실패: 보수적으로 개별 판정, 검색어는 질문 낱말로
    return { type: "judgment", keywords: q.split(/[\s,.?!]+/).filter((t) => t.length >= 2).slice(0, 6), pack: null, fallback: true };
  }
  const type = TYPES.includes(o.type) ? o.type : "judgment";              // 모르면 보수적으로
  const keywords = (Array.isArray(o.keywords) ? o.keywords : []).map(String).filter((k) => k.trim().length >= 2).slice(0, 6);
  return { type, keywords, pack: PACKS[o.pack] ? o.pack : null };
}

// ── 색인 검색 (전체를 쪼개지 않고 indexOf로 맞는 줄만 꺼냄) ──────────────
let INDEX = null, INDEX_AT = 0;
async function loadIndex(env) {
  if (INDEX && Date.now() - INDEX_AT < 10 * 60 * 1000) return INDEX;
  const obj = await env.BUCKET.get("lcf/ask/index.tsv");
  if (!obj) throw new Error("index missing");
  const text = await obj.text();
  const nl = text.indexOf("\n");
  INDEX = { cols: text.slice(0, nl).split("\t"), body: text.slice(nl + 1) };
  INDEX_AT = Date.now();
  return INDEX;
}

// ── 검증: 답의 숫자가 인용한 근거에 모두 있어야 함 ─────────────────────
function numbersOk(answer, items) {
  // 숫자 덩어리 단위로 비교 (2026.10.1 = 2026-10-01, 1,000 = 1000). 답의 숫자가 근거에 모두 있어야 함
  const runs = (t) => (t.replace(/(\d),(\d{3})/g, "$1$2").match(/\d+/g) || []).map((n) => String(+n));
  const have = new Set(items.flatMap((i) => runs([i.name, i.title, i.summary, i.points, i.announced, i.effective].join(" "))));
  return runs(answer).every((n) => have.has(n));
}

// ── 한도 (KV) ──────────────────────────────────────────────────────────
async function overLimit(env, ip) {
  const day = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
  const kIp = `ip:${day}:${ip}`, kAll = `all:${day}`;
  const [a, b] = await Promise.all([env.LIMITS.get(kIp), env.LIMITS.get(kAll)]);
  if (+a >= +(env.DAILY_PER_IP || 20) || +b >= +(env.DAILY_TOTAL || 300)) return true;
  await Promise.all([
    env.LIMITS.put(kIp, String(+a + 1), { expirationTtl: 172800 }),
    env.LIMITS.put(kAll, String(+b + 1), { expirationTtl: 172800 }),
  ]);
  return false;
}

const card = (r) => ({ key: r.key, kind: r.kind, name: r.name, title: r.title, summary: r.summary.slice(0, 200),
  announced: r.announced, effective: r.effective, page: r.page, url: r.url });

async function ask(env, q, test) {
  const c = await classify(env, q);
  if (test === "classify") return { type: c.type, keywords: c.keywords, pack: c.pack, fallback: !!c.fallback };
  if (c.type === "out_of_scope") return { type: c.type, answer: OUT_OF_SCOPE, items: [], notice: "" };
  const idx = await loadIndex(env);
  const cand = search(idx, c.keywords, q, c.pack);
  if (test === "search") return { type: c.type, keywords: c.keywords, pack: c.pack, items: cand.map((r) => ({ key: r.key, name: r.name, announced: r.announced, title: r.title, score: +r.score.toFixed(1), matched: r.matched })) };
  if (!cand.length) return { type: c.type, answer: NOT_FOUND, items: [], notice: DISCLAIMER };
  const ctx = cand.map((r) => `[${r.key}] ${r.name} (${r.type} ${r.change}, 공포 ${r.announced}, 시행 ${r.effective})\n제목: ${r.title}\n요약: ${r.summary}\n변경 항목: ${r.points}`).join("\n\n");
  let o;
  try {
    o = await claude(env, env.MODEL_ANSWER || "claude-sonnet-5-5", ANSWER, `질문 유형: ${c.type}\n질문: ${q}\n\n근거 항목:\n${ctx}`, 700);
  } catch (e) {                                              // 답 작성 실패: 가장 가까운 항목을 그대로 소개
    return { type: c.type, answer: plainAnswer(cand), items: cand.slice(0, 3).map(card), notice: DISCLAIMER, fallback: "answer" };
  }
  const cites = (o.cites || []).filter((k) => cand.some((r) => r.key === k));
  const used = cand.filter((r) => cites.includes(r.key));
  let answer = String(o.answer || "").trim();
  if (!answer || !used.length) return { type: c.type, answer: NOT_FOUND, items: cand.slice(0, 3).map(card), notice: DISCLAIMER };
  if (!numbersOk(answer, used)) answer = plainAnswer(used);       // 숫자가 근거와 안 맞으면 쓴 답을 버리고 근거 문장으로
  if (c.type === "judgment" && !answer.includes("전문가")) answer += " 본인에게 해당하는지는 세무사·변호사 등 전문가 확인이 필요해요.";
  return { type: c.type, answer, items: used.map(card), notice: DISCLAIMER };
}

// ── 상황 → 조건 ───────────────────────────────────────────────────────
let VOCAB = null;
async function loadVocab(env) {
  if (VOCAB) return VOCAB;
  const o = await env.BUCKET.get("lcf/ask/vocab.json");
  VOCAB = o ? await o.json() : { topics: [], packs: [], regions: [] };
  return VOCAB;
}

function pickRegion(v, r) {
  if (!r) return null;
  r = String(r).trim();
  if (v.regions.includes(r)) return r;
  const tail = r.split(" ").pop();
  return v.regions.find((x) => x.endsWith(" " + tail)) || v.regions.find((x) => x.includes(tail)) || null;
}

async function profile(env, text) {
  const v = await loadVocab(env);
  let o = null, err;
  for (let i = 0; i < 3 && !o; i++) {                       // 가끔 JSON이 잘리거나 API가 실패 → 두 번 더
    try { o = await claude(env, env.MODEL_ANSWER || "claude-sonnet-5-5", PROFILE(v), text, 1500); } catch (e) { err = e; }
  }
  if (!o) throw err;
  const okTopic = new Set([...v.topics, ...v.packs.map((p) => p.id)]);
  const idx = await loadIndex(env).catch(() => null);
  const region = pickRegion(v, o.region);
  const okAud = new Set((v.aud || []).flatMap((g) => g.tags));
  const aud = [...new Set((o.aud || []).map(String).filter((x) => okAud.has(x)))].slice(0, 8);
  const interests = (o.interests || []).filter((x) => x && okTopic.has(x.topic)).slice(0, 7)
    .map((x) => ({ label: String(x.label || x.topic).slice(0, 40), topic: x.topic, on: x.on !== false,
      aud: (x.aud || []).map(String).filter((t) => okAud.has(t)).slice(0, 3) }));
  const laws = [...new Set((o.laws || []).map((x) => String(x).replace(/\s*(시행령|시행규칙)$/, "").replace(/[·・]/g, "ㆍ").trim()))]   // 법령 이름의 가운뎃점은 ㆍ
    .filter((x) => x.length >= 3 && (!idx || idx.body.includes("\t" + x)))            // 우리 기록(2년)에 있는 법령만
    .slice(0, 8);
  return {
    who: String(o.who || "").slice(0, 30), region, sido: region ? region.split(" ")[0] : null,
    job: String(o.job || "").slice(0, 60), aud, interests, laws, v: 2,
    keywords: (o.keywords || []).map(String).filter((k) => k.length >= 2).slice(0, 6), text: text.slice(0, 300),
  };
}

async function subscribe(env, b) {
  const email = String(b.email || "").trim().toLowerCase();
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || email.length > 120) return { error: "이메일 주소를 확인해 주세요" };
  const rec = { email, channel: "email", prefs: b.prefs || {}, profile: b.profile || null, at: new Date().toISOString() };
  await env.LIMITS.put(`sub:${email}`, JSON.stringify(rec).slice(0, 8000));
  return { ok: true };
}

async function report(env, b) {
  const key = String(b.key || "");
  if (!/^(law|admrul|ordin):\d{1,12}$/.test(key)) return { error: "잘못된 항목" };
  const path = `lcf/state/reports/${key.replace(":", "-")}.json`;
  const old = await env.BUCKET.get(path);
  const doc = old ? await old.json() : { key, resolved: false, reports: [] };
  doc.resolved = false;
  doc.reports = [...(doc.reports || []).slice(-19), {
    at: new Date().toISOString(),
    parts: (Array.isArray(b.parts) ? b.parts : []).map(String).slice(0, 4),
    text: String(b.text || "").slice(0, 500),
  }];
  await env.BUCKET.put(path, JSON.stringify(doc), { httpMetadata: { contentType: "application/json" } });
  return { ok: true };
}

// ── AI 재판정: 꼬리표로 모은 후보를 그 사람의 상황 글로 한 번 더 (docs/RELEVANCE.md) ──────────
// 후보 내용은 화면이 보내지 않고 색인에서 찾음 (키만 받음) → 임의 글을 모델에 넣는 통로가 되지 않게
const KIND_T = (r) => r.kind === "law" ? (r.type === "법률" ? "국회가 바꾼 법" : "정부 세부 기준") : r.kind === "admrul" ? "부처 고시" : `${r.org} ${r.type}`;
function indexRows(idx, keys) {
  const out = {};
  for (const k of keys) {
    let i = idx.body.startsWith(k + "\t") ? 0 : idx.body.indexOf("\n" + k + "\t");
    if (i < 0) continue;
    if (i > 0) i += 1;
    const line = idx.body.slice(i, idx.body.indexOf("\n", i) >>> 0 || undefined);
    const v = line.split("\t"); out[k] = Object.fromEntries(idx.cols.map((c, j) => [c, v[j] || ""]));
  }
  return out;
}
async function rankCall(env, user) {
  const model = env.MODEL_RANK || "claude-sonnet-5-5";
  const r = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
    body: JSON.stringify({ model, max_tokens: 3000, system: RANK_PROMPT, messages: [{ role: "user", content: user }],
      ...(model.startsWith("claude-sonnet-5-5") ? { thinking: { type: "between_tools" } } : model.startsWith("claude-haiku-5") ? { thinking: { type: "disabled" } } : {}) }),
  });
  if (!r.ok) throw new Error(`claude ${r.status}`);
  const text = ((await r.json()).content || []).map((b) => b.text || "").join("");
  const m = text.match(/\[[\s\S]*\]/);
  return m ? JSON.parse(m[0]) : [];
}
async function rank(env, b, ip) {
  const text = String(b.text || "").trim().slice(0, 300), region = String(b.region || "").slice(0, 40);
  const keys = [...new Set((Array.isArray(b.keys) ? b.keys : []).map(String).filter((k) => /^(law|admrul|ordin):\d{1,13}$/.test(k)))].slice(0, 90);
  if (text.length < 4 || !keys.length) return { error: "상황 글과 후보가 필요해요" };
  const day = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
  const kIp = `rk:${day}:${ip}`, kAll = `rkall:${day}`;
  const [a, z] = await Promise.all([env.LIMITS.get(kIp), env.LIMITS.get(kAll)]);
  if (+a + keys.length > +(env.RANK_PER_IP || 400) || +z + keys.length > +(env.RANK_TOTAL || 30000)) return { error: "오늘 판정 한도를 넘었어요", limited: true };
  await Promise.all([env.LIMITS.put(kIp, String(+a + keys.length), { expirationTtl: 172800 }),
    env.LIMITS.put(kAll, String(+z + keys.length), { expirationTtl: 172800 })]);
  const idx = await loadIndex(env), rows = indexRows(idx, keys);
  const have = keys.filter((k) => rows[k]), missing = keys.filter((k) => !rows[k]);
  const line = (k) => { const r = rows[k]; return `[${k}] ${KIND_T(r)} · ${r.name}` + (r.title ? ` — ${r.title}` : "") +
    (r.summary && r.summary !== r.title ? ` / ${r.summary.slice(0, 160)}` : "") + (r.effective ? ` (시행 ${r.effective})` : ""); };
  const head = `상황 (사용자가 직접 쓴 글): ${text}\n사는 곳: ${region || "모름"}\n\n후보:\n`;
  const chunks = []; for (let i = 0; i < have.length; i += 30) chunks.push(have.slice(i, i + 30));
  const res = await Promise.all(chunks.map((c) => rankCall(env, head + c.map(line).join("\n")).catch(() => [])));
  const labels = {};
  res.flat().forEach((o) => { if (o && have.includes(o.key) && [0, 1, 2].includes(o.label)) labels[o.key] = o.label; });
  return { labels, missing };
}

// 관심 표시 익명 집계 — 항목별 관심 있음·없음 횟수, 숨긴 범위, 이유. 개인 정보 없음
const FB_ACTS = ["star", "unstar", "hide", "unhide"], FB_SCOPES = ["item", "law", "keyword"];
const FB_REASONS = ["나와 상관없는 대상", "이미 알고 있음", "너무 사소함"];
async function feedback(env, b, ip) {
  const key = String(b.key || ""), act = String(b.act || "");
  if (!/^(law|admrul|ordin):\d{1,12}$/.test(key) || !FB_ACTS.includes(act)) return { error: "잘못된 표시" };
  const day = new Date().toISOString().slice(0, 10), kl = `fbl:${day}:${ip}`;
  const n = +(await env.LIMITS.get(kl)) || 0;
  if (n >= 300) return { ok: true };                      // 한도를 넘으면 조용히 버림
  await env.LIMITS.put(kl, String(n + 1), { expirationTtl: 172800 });
  const kf = `fb:${key}`;
  const doc = JSON.parse((await env.LIMITS.get(kf)) || "null") || { star: 0, hide: 0, scope: {}, reasons: {} };
  if (act === "star") doc.star++;
  if (act === "unstar") doc.star = Math.max(0, doc.star - 1);
  if (act === "hide") {
    doc.hide++;
    const s = FB_SCOPES.includes(b.scope) ? b.scope : "item";
    doc.scope[s] = (doc.scope[s] || 0) + 1;
    if (FB_REASONS.includes(b.reason)) doc.reasons[b.reason] = (doc.reasons[b.reason] || 0) + 1;
  }
  if (act === "unhide") doc.hide = Math.max(0, doc.hide - 1);
  doc.at = new Date().toISOString();
  await env.LIMITS.put(kf, JSON.stringify(doc));
  return { ok: true };
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    if (req.method === "OPTIONS") return new Response(null, { headers: cors(env) });
    if (url.pathname === "/health") return json(env, { ok: true });
    if (!["/ask", "/profile", "/subscribe", "/report", "/feedback", "/rank"].includes(url.pathname) || req.method !== "POST") return json(env, { error: "not found" }, 404);
    let body;
    try { body = await req.json(); } catch { return json(env, { error: "bad json" }, 400); }
    const ip = req.headers.get("cf-connecting-ip") || "unknown";
    if (url.pathname === "/report") {
      if (await overLimit(env, ip)) return json(env, { error: "오늘 이용 한도를 넘었어요." }, 429);
      try { const r = await report(env, body); return json(env, r, r.error ? 400 : 200); }
      catch (e) { return json(env, { error: "잠시 후 다시 시도해 주세요" }, 502); }
    }
    if (url.pathname === "/rank") {
      try { const r = await rank(env, body, ip); return json(env, r, r.error ? (r.limited ? 429 : 400) : 200); }
      catch (e) { return json(env, { error: "잠시 후 다시 시도해 주세요" }, 502); }
    }
    if (url.pathname === "/feedback") {
      try { const r = await feedback(env, body, ip); return json(env, r, r.error ? 400 : 200); }
      catch (e) { return json(env, { error: "잠시 후 다시 시도해 주세요" }, 502); }
    }
    if (url.pathname === "/subscribe") {
      try { const r = await subscribe(env, body); return json(env, r, r.error ? 400 : 200); }
      catch (e) { return json(env, { error: "잠시 후 다시 시도해 주세요" }, 502); }
    }
    if (url.pathname === "/profile") {
      const text = String(body.text || "").trim().slice(0, 300);
      if (text.length < 4) return json(env, { error: "상황을 조금 더 적어 주세요" }, 400);
      const isT = env.TEST_KEY && req.headers.get("x-test-key") === env.TEST_KEY;
      if (!isT && await overLimit(env, ip)) return json(env, { error: "오늘 이용 한도를 넘었어요. 내일 다시 이용해 주세요." }, 429);
      try { return json(env, { profile: await profile(env, text) }); }
      catch (e) { return json(env, { error: "상황을 정리하지 못했어요. 분야를 직접 골라 주세요.", detail: isT ? String(e) : undefined }, 502); }
    }
    const q = String(body.q || "").trim().slice(0, 300);
    if (q.length < 2) return json(env, { error: "질문을 입력해 주세요" }, 400);
    const isTest = env.TEST_KEY && req.headers.get("x-test-key") === env.TEST_KEY;
    if (!isTest && await overLimit(env, ip))
      return json(env, { error: "오늘 질문 한도를 넘었어요. 내일 다시 이용해 주세요." }, 429);
    try {
      return json(env, await ask(env, q, isTest ? body.test : null));
    } catch (e) {
      return json(env, { error: "잠시 후 다시 시도해 주세요", detail: isTest ? String(e) : undefined }, 502);
    }
  },
};
