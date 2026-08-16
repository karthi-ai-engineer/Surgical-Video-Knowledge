// ---------- Surgical Video RAG frontend ----------
const PHASE_COLORS = {
  "Preparation": "#64748b",
  "Calot triangle dissection": "#38bdf8",
  "Clipping and cutting": "#f472b6",
  "Gallbladder dissection": "#34d399",
  "Gallbladder retraction": "#fbbf24",
  "Cleaning and coagulation": "#a78bfa",
  "Gallbladder packaging": "#fb923c",
  "Unknown": "#334155",
};
const SUGGESTIONS = [
  "Where does clipping begin?",
  "What is the Critical View of Safety?",
  "Show where clipping begins and explain what should be verified before clipping.",
  "Show the Calot triangle dissection section.",
];

const $ = (id) => document.getElementById(id);
const player = $("player");
let OBS = [];        // sorted observations
let DURATION = 0;
let mode = "combined";
let lastNowId = -1;

function fmt(s) {
  s = Math.max(0, Math.floor(s));
  const m = Math.floor(s / 60), sec = s % 60;
  return `${m}:${String(sec).padStart(2, "0")}`;
}
function esc(t) {
  return (t || "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
function parseTs(str) {  // "4:00" -> 240
  const p = str.split(":").map(Number);
  return p.length === 2 ? p[0] * 60 + p[1] : Number(str);
}

// ---------- init ----------
async function init() {
  const meta = await (await fetch("/api/meta")).json();
  $("caseName").textContent = meta.procedure;
  DURATION = meta.duration || 0;
  if (meta.has_video) player.src = meta.video_url;

  OBS = await (await fetch("/api/observations")).json();
  buildTimeline();
  buildLegend();
  renderSuggestions();

  player.addEventListener("timeupdate", onTimeUpdate);
  player.addEventListener("loadedmetadata", () => { if (!DURATION) DURATION = player.duration; buildTimeline(); });
}

// ---------- timeline ----------
function mergedSegments() {
  const segs = [];
  for (const o of OBS) {
    if (segs.length && segs[segs.length - 1].phase === o.phase) segs[segs.length - 1].end = o.end_sec;
    else segs.push({ phase: o.phase, start: o.start_sec, end: o.end_sec });
  }
  return segs;
}
function buildTimeline() {
  const tl = $("timeline");
  const dur = DURATION || (OBS.length ? OBS[OBS.length - 1].end_sec : 1);
  [...tl.querySelectorAll(".seg")].forEach((e) => e.remove());
  for (const s of mergedSegments()) {
    const w = ((s.end - s.start) / dur) * 100;
    const d = document.createElement("div");
    d.className = "seg";
    d.style.width = w + "%";
    d.style.background = PHASE_COLORS[s.phase] || "#334155";
    d.title = `${s.phase}  (${fmt(s.start)}–${fmt(s.end)})`;
    d.onclick = () => seekTo(s.start);
    tl.insertBefore(d, $("playhead"));
  }
}
function buildLegend() {
  const seen = [...new Set(OBS.map((o) => o.phase))];
  $("legend").innerHTML = seen.map((p) =>
    `<span class="li"><span class="sw" style="background:${PHASE_COLORS[p] || "#334155"}"></span>${esc(p)}</span>`
  ).join("");
}

// ---------- now-showing ----------
function obsAt(t) {
  let cur = null;
  for (const o of OBS) {
    if (o.start_sec <= t && t <= o.end_sec) return o;
    if (o.start_sec <= t) cur = o; else break;
  }
  return cur;
}
function onTimeUpdate() {
  const t = player.currentTime;
  const dur = DURATION || player.duration || 1;
  $("playhead").style.left = (t / dur) * 100 + "%";
  $("nowTime").textContent = fmt(t);

  const o = obsAt(t);
  if (!o || o.id === lastNowId) return;
  lastNowId = o.id;
  const color = PHASE_COLORS[o.phase] || "#334155";
  $("nowPhase").innerHTML = `<span class="phase-badge" style="background:${color}">${esc(o.phase)}</span>`;
  $("nowBody").textContent = o.observation;
  $("nowInstruments").innerHTML = (o.instruments || [])
    .map((i) => `<span class="chip">${esc(i)}</span>`).join("");
}

// ---------- seek ----------
function seekTo(sec) {
  if (isNaN(sec)) return;
  player.currentTime = sec;
  player.play().catch(() => {});
  const card = $("nowCard");
  card.classList.remove("flash"); void card.offsetWidth; card.classList.add("flash");
  document.querySelector(".left").scrollIntoView({ behavior: "smooth", block: "start" });
}
window.seekTo = seekTo;

// ---------- linkify timestamps in answer text ----------
function linkify(text) {
  // matches 4:00 or 4:00-4:04 / 4:00–4:04
  return esc(text).replace(/\b(\d{1,2}:\d{2})(\s*[–-]\s*(\d{1,2}:\d{2}))?/g, (m, a) => {
    const sec = parseTs(a);
    return `<span class="ts" data-sec="${sec}">${m.trim()}</span>`;
  });
}

// ---------- chat ----------
function addUser(text) {
  $("messages").insertAdjacentHTML("beforeend",
    `<div class="msg user"><div class="bubble">${esc(text)}</div></div>`);
  scrollChat();
}
function addThinking() {
  const el = document.createElement("div");
  el.className = "msg assistant thinking";
  el.innerHTML = `<div class="bubble"><span class="d"></span><span class="d"></span><span class="d"></span></div>`;
  $("messages").appendChild(el); scrollChat();
  return el;
}
function evidenceHtml(res) {
  let html = "";
  if (res.video_evidence && res.video_evidence.length) {
    html += `<div class="ev-label">🎬 Video evidence</div>`;
    for (const v of res.video_evidence) {
      const star = v.temporal_anchor ? ` <span class="star" title="earliest/latest anchor">★</span>` : "";
      html += `<div class="ev-item" data-sec="${v.start_sec}">
        <div class="ev-top"><span class="ev-time">${fmt(v.start_sec)}–${fmt(v.end_sec)}</span>${star}
        <span class="ev-phase">${esc(v.phase)}</span></div>
        <div>${esc((v.observation || "").slice(0, 130))}</div></div>`;
    }
  }
  if (res.document_evidence && res.document_evidence.length) {
    html += `<div class="ev-label">📄 Document evidence</div>`;
    for (const d of res.document_evidence) {
      const pg = d.page ? ` · p${d.page}` : "";
      html += `<div class="ev-item doc">
        <div class="ev-top"><span class="ev-doc">${esc(d.document_name)}${pg}</span></div>
        <div class="muted">${esc((d.chunk_text || "").slice(0, 150))}…</div></div>`;
    }
  }
  if (res.graph && res.graph.nodes) {
    html += `<div class="graph-note">🕸 Knowledge graph: ${res.graph.nodes.length} related concepts connected</div>`;
  }
  return html;
}
function addAnswer(res) {
  const el = document.createElement("div");
  el.className = "msg assistant";
  el.innerHTML = `<div class="bubble">${linkify(res.answer)}
    <div class="evidence">${evidenceHtml(res)}</div></div>`;
  $("messages").appendChild(el);
  bindSeeks(el);
  scrollChat();
}
function bindSeeks(root) {
  root.querySelectorAll(".ts, .ev-item[data-sec]").forEach((n) =>
    n.addEventListener("click", () => seekTo(Number(n.dataset.sec))));
}
function scrollChat() { const m = $("messages"); m.scrollTop = m.scrollHeight; }

async function ask(q) {
  if (!q.trim()) return;
  $("input").value = "";
  addUser(q);
  const thinking = addThinking();
  $("send").disabled = true;
  try {
    const res = await (await fetch("/api/ask", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: q, mode }),
    })).json();
    thinking.remove();
    addAnswer(res);
  } catch (e) {
    thinking.remove();
    $("messages").insertAdjacentHTML("beforeend",
      `<div class="msg assistant"><div class="bubble">⚠️ Something went wrong: ${esc(String(e))}</div></div>`);
  } finally {
    $("send").disabled = false;
    $("input").focus();
  }
}

function renderSuggestions() {
  $("suggestions").innerHTML = SUGGESTIONS.map((s) => `<span class="sug">${esc(s)}</span>`).join("");
  $("suggestions").querySelectorAll(".sug").forEach((n, i) =>
    n.addEventListener("click", () => ask(SUGGESTIONS[i])));
}

// ---------- wiring ----------
$("send").addEventListener("click", () => ask($("input").value));
$("input").addEventListener("keydown", (e) => { if (e.key === "Enter") ask($("input").value); });
$("modes").addEventListener("click", (e) => {
  const b = e.target.closest(".mode"); if (!b) return;
  mode = b.dataset.mode;
  [...$("modes").children].forEach((m) => m.classList.toggle("active", m === b));
});

init();
