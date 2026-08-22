/* Shared OKF graph viewer — one file for every trees/*.html */
(function () {
  const el = document.getElementById("okf");
  if (!el) return;
  const G = JSON.parse(el.textContent);
  window.G = G;
  const title = document.getElementById("title");
  if (title) title.textContent = G.repo || title.textContent;
  const head = document.getElementById("head");
  if (head) head.textContent = G.git_head || "";
  const sum = document.getElementById("sum");
  if (sum) sum.textContent = G.summary || "No README summary yet.";
  let mode = "both";
  let POS = {};
  let flowTimer = 0;
  let focusCommit = null;

  function extractedNeighbors(id) {
    const ids = new Set();
    (G.edges || []).forEach((e) => {
      if (e.tag !== "EXTRACTED") return;
      if (e.from === id) ids.add(e.to);
      if (e.to === id) ids.add(e.from);
    });
    return ids;
  }

  function pickSet() {
    const files = G.nodes.filter((n) => n.type === "file").sort((a, b) => (b.churn_30d || 0) - (a.churn_30d || 0)).slice(0, 48);
    const commits = G.nodes.filter((n) => n.type === "commit").slice(0, 20);
    const byId = {};
    G.nodes.forEach((n) => { byId[n.id] = n; });
    if (mode === "file") return files;
    if (mode === "commit") {
      if (focusCommit && byId[focusCommit]) {
        const keep = new Set([focusCommit]);
        extractedNeighbors(focusCommit).forEach((id) => keep.add(id));
        Array.from(keep).forEach((id) => {
          extractedNeighbors(id).forEach((oid) => {
            const n = byId[oid];
            if (n && n.type !== "project") keep.add(oid);
          });
        });
        return G.nodes.filter((n) => keep.has(n.id));
      }
      const cids = new Set(commits.map((c) => c.id));
      const extra = new Set();
      (G.edges || []).forEach((e) => {
        if (e.tag !== "EXTRACTED") return;
        if (cids.has(e.from)) extra.add(e.to);
        if (cids.has(e.to)) extra.add(e.from);
      });
      const linked = G.nodes.filter((n) => extra.has(n.id) && n.type !== "commit").slice(0, 60);
      return commits.concat(linked);
    }
    return files.concat(commits);
  }
  function nodeSummary(n) {
    if (n.type === "commit") return n.summary || n.subject || "Commit with no message.";
    if (n.purpose) return n.purpose;
    const why = (n.history && n.history[0] && n.history[0].why) || "";
    if (why) return "Last change: " + why;
    return (n.type === "file" ? "Source file" : n.type) + " — no docstring yet.";
  }
  function showPanel(n) {
    const ed = G.edges.filter((e) => (e.from === n.id || e.to === n.id) && e.tag === "EXTRACTED");
    const flows = ed.map((e) => {
      const other = e.from === n.id ? e.to : e.from;
      const on = G.nodes.find((x) => x.id === other);
      const lab = on ? (on.label || on.id).split("/").pop() : other;
      const dir = e.from === n.id ? "out" : "in";
      return (dir === "out" ? "→ " : "← ") + e.type + " " + lab;
    });
    const last = (n.history && n.history[0]) || {};
    const t = (n.label || n.id).split("/").pop();
    document.getElementById("out").innerHTML =
      "<h2>" + (n.icon_emoji || "") + " " + t + "</h2>" +
      '<div><span class="chip">' + n.type + "</span>" +
      (n.role ? '<span class="chip">' + n.role + "</span>" : "") + "</div>" +
      "<h3>Summary</h3><p>" + nodeSummary(n).replace(/</g, "&lt;") + "</p>" +
      "<h3>Metadata</h3><p>" +
      "repo: " + (G.repo || "") + "<br>" +
      (G.git_head ? "HEAD: " + G.git_head + "<br>" : "") +
      (n.label && n.type === "file" ? "path: " + n.label + "<br>" : "") +
      (n.churn_30d != null ? "churn 30d: " + n.churn_30d + "<br>" : "") +
      (last.why ? "last commit: " + (last.commit || "") + " " + last.why + "<br>" : "") +
      (n.date ? "date: " + n.date + "<br>" : "") +
      (n.sha ? "sha: " + n.sha + "<br>" : "") +
      (n.files ? "files: " + n.files.slice(0, 10).join(", ") : "") +
      "</p><h3>How it connects</h3><pre>" + (flows.slice(0, 16).join("\n") || "no EXTRACTED edges on canvas") + "</pre>";
  }
  function animateFlow(startId) {
    if (flowTimer) {
      clearTimeout(flowTimer);
      flowTimer = 0;
    }
    function runOnce(thenLoop) {
      document.querySelectorAll("line.flow").forEach((l) => l.classList.remove("flow"));
      document.querySelectorAll("circle.pulse").forEach((c) => c.classList.remove("pulse"));
      const adj = {};
      G.edges.forEach((e) => {
        if (e.tag !== "EXTRACTED") return;
        (adj[e.from] = adj[e.from] || []).push(e);
      });
      const seen = new Set([startId]);
      let q = [startId], hop = 0;
      function step() {
        const next = [];
        q.forEach((id) => {
          (adj[id] || []).forEach((e) => {
            if (seen.has(e.to)) return;
            seen.add(e.to);
            next.push(e.to);
            const line = document.querySelector('line[data-eid="' + e.from + "__" + e.to + '"]');
            if (line) line.classList.add("flow");
            const c = document.querySelector('circle[data-nid="' + e.to + '"]');
            if (c) c.classList.add("pulse");
          });
        });
        q = next;
        hop++;
        if (q.length && hop < 8) flowTimer = setTimeout(step, 280);
        else if (thenLoop) flowTimer = setTimeout(function () { runOnce(true); }, 900);
      }
      const c0 = document.querySelector('circle[data-nid="' + startId + '"]');
      if (c0) c0.classList.add("pulse");
      flowTimer = setTimeout(step, 80);
    }
    runOnce(true);
  }
  window.setGraphMode = function (m) {
    mode = m;
    if (m !== "commit") focusCommit = null;
    draw();
  };
  function draw() {
    ["bboth", "bfile", "bcommit"].forEach((id) => {
      const b = document.getElementById(id);
      if (b) b.className = id === "b" + mode || (id === "bboth" && mode === "both") ? "on" : "";
    });
    const svg = document.getElementById("canvas");
    if (!svg) return;
    const W = svg.clientWidth || 800, H = svg.clientHeight || 560;
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    const nodes = pickSet();
    const ids = new Set(nodes.map((n) => n.id));
    POS = {};
    const files = nodes.filter((n) => n.type !== "commit");
    const commits = nodes.filter((n) => n.type === "commit");
    if (mode === "commit" && focusCommit && commits.length === 1) {
      POS[commits[0].id] = { x: W * 0.16, y: H * 0.5 };
      files.forEach((n, i) => {
        const a = (i / Math.max(files.length, 1)) * Math.PI * 2 - Math.PI / 2;
        POS[n.id] = { x: W * 0.58 + Math.cos(a) * W * 0.28, y: H * 0.5 + Math.sin(a) * H * 0.38 };
      });
    } else {
      files.forEach((n, i) => {
        const a = (i / Math.max(files.length, 1)) * Math.PI * 2 - Math.PI / 2;
        POS[n.id] = { x: W * 0.52 + Math.cos(a) * W * 0.32, y: H * 0.5 + Math.sin(a) * H * 0.38 };
      });
      commits.forEach((n, i) => {
        POS[n.id] = { x: 70 + (i % 2) * 40, y: 40 + i * Math.min(28, (H - 80) / Math.max(commits.length, 1)) };
      });
    }
    const edges = G.edges.filter((e) => ids.has(e.from) && ids.has(e.to) && e.tag === "EXTRACTED");
    let html = "";
    edges.forEach((e) => {
      const a = POS[e.from], b = POS[e.to];
      if (!a || !b) return;
      const eid = e.from + "__" + e.to;
      html += '<line data-eid="' + eid + '" x1="' + a.x + '" y1="' + a.y + '" x2="' + b.x + '" y2="' + b.y + '" stroke="#334155" stroke-width="1"/>';
    });
    nodes.forEach((n) => {
      const p = POS[n.id];
      if (!p) return;
      const r = n.type === "commit" ? 8 : 11;
      const lab = (n.label || n.id).split("/").pop().slice(0, 22);
      const img = n.icon_uri
        ? '<image href="' + n.icon_uri + '" x="' + (p.x - 8) + '" y="' + (p.y - 8) + '" width="16" height="16"/>'
        : "";
      html +=
        '<g data-id="' + n.id.replace(/"/g, "") + '" style="cursor:pointer">' +
        '<circle data-nid="' + n.id.replace(/"/g, "") + '" cx="' + p.x + '" cy="' + p.y + '" r="' + r +
        '" fill="#1e293b" stroke="' + (n.type === "commit" ? "#a78bfa" : "#38bdf8") + '"/>' +
        img +
        '<text x="' + (p.x + 14) + '" y="' + (p.y + 4) + '" fill="#94a3b8" font-size="10">' +
        (n.icon_emoji || "") + " " + lab + "</text></g>";
    });
    svg.innerHTML = html;
    svg.querySelectorAll("g[data-id]").forEach((g) =>
      g.addEventListener("click", () => {
        const n = G.nodes.find((x) => x.id === g.getAttribute("data-id"));
        if (!n) return;
        if (mode === "commit" && n.type === "commit") {
          focusCommit = n.id;
          draw();
        }
        showPanel(n);
        animateFlow(n.id);
      })
    );
  }
  window.draw = draw;
  draw();
  window.addEventListener("resize", draw);
})();
