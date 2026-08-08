"""The customer-facing chat surface — ticket 64, per ticket 55's decisions.

One self-contained HTML page at ``GET /chat``: pick a workflow, chat with it,
watch it think. No editor payload, no build step, no external assets — the
page is a string served by the same process that runs the graphs, so it can
never version-skew against the API it drives.

Identity model (ticket 64): ``user_email`` is asked for once and kept in
localStorage (the future long-term-memory namespace, per ticket 65's
research); ``session_id`` is minted per browser tab; ``thread_id`` is minted
per (workflow, conversation) and reset by "New conversation" — matching the
research's rule that thread/session scope the checkpointer, never the Store.
"""

CHAT_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dyflow Chat</title>
<style>
  :root { color-scheme: light dark; --line: #8884; --muted: #888; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 15px/1.5 system-ui, sans-serif; display: flex; flex-direction: column; height: 100vh; }
  header { display: flex; gap: 8px; align-items: center; padding: 10px 14px; border-bottom: 1px solid var(--line); flex-wrap: wrap; }
  header strong { margin-right: auto; }
  select, input, button, textarea { font: inherit; padding: 6px 10px; border: 1px solid var(--line); border-radius: 8px; background: transparent; color: inherit; }
  button { cursor: pointer; }
  main { flex: 1; overflow-y: auto; padding: 16px; max-width: 780px; width: 100%; margin: 0 auto; }
  .turn { margin-bottom: 20px; }
  .q { font-weight: 600; margin-bottom: 6px; }
  .steps { font-size: 12px; color: var(--muted); border-left: 2px solid var(--line); padding-left: 10px; margin: 6px 0; }
  .steps div.child { margin-left: 14px; opacity: .75; }
  .thinking { font-size: 13px; color: var(--muted); white-space: pre-wrap; }
  .answer { border: 1px solid var(--line); border-radius: 10px; padding: 10px 14px; margin-top: 8px; overflow-x: auto; }
  .answer table { border-collapse: collapse; } .answer td, .answer th { border: 1px solid var(--line); padding: 3px 8px; }
  .answer code, .answer pre { background: #8881; border-radius: 4px; padding: 1px 4px; }
  .error { color: #e5484d; }
  .hitl { border: 1px dashed var(--line); border-radius: 10px; padding: 10px 14px; margin-top: 8px; }
  footer { display: flex; gap: 8px; padding: 12px 14px; border-top: 1px solid var(--line); max-width: 780px; width: 100%; margin: 0 auto; }
  footer textarea { flex: 1; resize: none; height: 44px; }
</style>
</head>
<body>
<header>
  <strong>Dyflow</strong>
  <select id="wf" title="Workflow"></select>
  <button id="newconv" title="Start a fresh thread">New conversation</button>
  <input id="email" type="email" placeholder="you@example.com" title="Used to remember you across sessions" style="width:180px">
  <span id="who" style="font-size:12px;color:var(--muted)"></span>
</header>
<main id="log"></main>
<footer>
  <textarea id="msg" placeholder="Ask the selected workflow…"></textarea>
  <button id="send">Send</button>
</footer>
<script>
"use strict";
const $ = (id) => document.getElementById(id);
const state = {
  email: localStorage.getItem("dyflow.email") || "",
  sessionId: sessionStorage.getItem("dyflow.session") || crypto.randomUUID(),
  threads: JSON.parse(localStorage.getItem("dyflow.threads") || "{}"),
  workflow: null, doc: null, pending: null,
};
sessionStorage.setItem("dyflow.session", state.sessionId);
$("email").value = state.email;
$("email").onchange = () => {
  state.email = $("email").value.trim() || "anonymous";
  localStorage.setItem("dyflow.email", state.email);
  $("who").textContent = state.sessionId.slice(0, 8);
};
$("who").textContent = state.sessionId.slice(0, 8);

function threadFor(slug) {
  if (!state.threads[slug]) {
    state.threads[slug] = crypto.randomUUID();
    localStorage.setItem("dyflow.threads", JSON.stringify(state.threads));
  }
  return state.threads[slug];
}
$("newconv").onclick = () => {
  delete state.threads[state.workflow];
  localStorage.setItem("dyflow.threads", JSON.stringify(state.threads));
  $("log").innerHTML = "";
};

// Minimal markdown: headings, bold, code fences, inline code, tables, lists.
// Deliberately no raw HTML passthrough — everything is escaped first.
function md(text) {
  const esc = (s) => s.replace(/[&<>]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
  const lines = esc(text).split("\\n");
  let out = [], inCode = false, inTable = false, inList = false;
  const closeAll = () => { if (inTable) { out.push("</table>"); inTable = false; } if (inList) { out.push("</ul>"); inList = false; } };
  for (const line of lines) {
    if (line.startsWith("```")) { closeAll(); out.push(inCode ? "</pre>" : "<pre>"); inCode = !inCode; continue; }
    if (inCode) { out.push(line); continue; }
    let l = line.replace(/\\*\\*(.+?)\\*\\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
    if (/^\\s*\\|.*\\|\\s*$/.test(l)) {
      if (/^\\s*\\|[\\s:|-]+\\|\\s*$/.test(l)) continue;
      if (!inTable) { closeAll(); out.push("<table>"); inTable = true; }
      out.push("<tr>" + l.trim().slice(1, -1).split("|").map((c) => "<td>" + c.trim() + "</td>").join("") + "</tr>");
      continue;
    }
    if (/^\\s*[-*] /.test(l)) { if (!inList) { closeAll(); out.push("<ul>"); inList = true; } out.push("<li>" + l.replace(/^\\s*[-*] /, "") + "</li>"); continue; }
    closeAll();
    const h = l.match(/^(#{1,4}) (.*)$/);
    if (h) { out.push(`<h${h[1].length + 2}>${h[2]}</h${h[1].length + 2}>`); continue; }
    if (l.trim()) out.push("<p>" + l + "</p>");
  }
  closeAll();
  if (inCode) out.push("</pre>");
  return out.join("\\n");
}

async function loadWorkflows() {
  const list = await (await fetch("/api/workflows")).json();
  $("wf").innerHTML = list.map((w) => `<option value="${w.slug}">${w.name}</option>`).join("");
  state.workflow = list[0] && list[0].slug;
  $("wf").onchange = async () => { state.workflow = $("wf").value; state.doc = null; };
}

async function docFor(slug) {
  if (!state.doc || state.doc.slug !== slug) {
    const record = await (await fetch(`/api/workflows/${slug}`)).json();
    state.doc = { slug, document: record.document };
  }
  return state.doc.document;
}

function turnEl(question) {
  const el = document.createElement("div");
  el.className = "turn";
  el.innerHTML = `<div class="q"></div><div class="steps"></div><div class="thinking"></div><div class="answer" hidden></div>`;
  el.querySelector(".q").textContent = question;
  $("log").appendChild(el);
  el.scrollIntoView({ block: "end" });
  return el;
}

async function stream(path, body, el) {
  const steps = el.querySelector(".steps"), thinking = el.querySelector(".thinking"), answer = el.querySelector(".answer");
  const resp = await fetch(path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  if (!resp.ok) { answer.hidden = false; answer.innerHTML = `<span class="error">Runtime error (${resp.status}): ${esc(await resp.text())}</span>`; return; }
  const reader = resp.body.getReader(); const dec = new TextDecoder();
  let buf = "", event = null, tokens = "";
  const esc2 = (s) => s.replace(/[&<>]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\\n\\n")) >= 0) {
      const frame = buf.slice(0, idx); buf = buf.slice(idx + 2);
      for (const line of frame.split("\\n")) {
        if (line.startsWith("event: ")) event = line.slice(7);
        else if (line.startsWith("data: ")) {
          const d = JSON.parse(line.slice(6));
          if (event === "update") {
            const row = document.createElement("div");
            if (d.internal) row.className = "child";
            row.textContent = (d.internal ? "· " : "▸ ") + d.node + (d.taskId ? " (" + d.taskId + ")" : "");
            steps.appendChild(row); el.scrollIntoView({ block: "end" });
          } else if (event === "token") {
            tokens += d.content; thinking.textContent = tokens.slice(-600);
          } else if (event === "error") {
            answer.hidden = false; answer.innerHTML = `<span class="error">${esc2(d.detail || JSON.stringify(d))}</span>`;
          } else if (event === "interrupt") {
            renderInterrupt(el, d);
          } else if (event === "done") {
            thinking.textContent = "";
            answer.hidden = false;
            answer.innerHTML = md(d.answer || "_no answer_");
            if (d.warnings && d.warnings.length) answer.innerHTML += `<p class="error">${esc2(d.warnings.join("; "))}</p>`;
          }
        }
      }
    }
  }
  el.scrollIntoView({ block: "end" });
}
const esc = (s) => s.replace(/[&<>]/g, (c) => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));

function renderInterrupt(el, d) {
  const box = document.createElement("div");
  box.className = "hitl";
  box.innerHTML = `<p><b>Approval needed:</b> ${esc(d.message || "")}</p><div class="answer">${md(d.candidate || "")}</div>
    <button data-d="approve">Approve</button> <button data-d="reject">Reject</button>`;
  el.appendChild(box);
  for (const b of box.querySelectorAll("button")) {
    b.onclick = async () => {
      box.remove();
      const doc = await docFor(state.workflow);
      await stream("/api/runs/resume", {
        thread_id: d.thread_id, workflow: { document: doc }, decision: b.dataset.d,
        workflow_slug: state.workflow, session_id: state.sessionId, user_email: state.email || "anonymous",
      }, el);
    };
  }
}

$("send").onclick = send;
$("msg").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } });
async function send() {
  const q = $("msg").value.trim();
  if (!q || !state.workflow) return;
  $("msg").value = "";
  const el = turnEl(q);
  try {
    const doc = await docFor(state.workflow);
    await stream("/api/runs/stream", {
      workflow: { document: doc }, question: q, workflow_slug: state.workflow,
      thread_id: threadFor(state.workflow), session_id: state.sessionId, user_email: state.email || "anonymous",
    }, el);
  } catch (err) {
    const a = el.querySelector(".answer"); a.hidden = false;
    a.innerHTML = `<span class="error">${esc(String(err))}</span>`;
  }
}
loadWorkflows();
</script>
</body>
</html>
"""
