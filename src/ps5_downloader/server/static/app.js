const $ = (sel) => document.querySelector(sel);

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error((await res.json()).error || res.statusText);
  return res.json();
}

function fmtBytes(n) {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
}

function itemHtml(item) {
  const pct = item.percent || 0;
  return `<div class="item">
    <div class="row">
      <div class="name">${item.filename || item.original_url}</div>
      <div class="meta">${item.state}</div>
    </div>
    <div class="meta">${item.host || ""} ${fmtBytes(item.downloaded_bytes)} / ${item.size ? fmtBytes(item.size) : "unknown"}</div>
    <div class="bar"><div class="fill" style="width:${pct}%"></div></div>
    <div class="meta">${pct.toFixed(1)}% ${item.speed_bps ? fmtBytes(item.speed_bps) + "/s" : ""}</div>
    ${item.error ? `<div class="error">${item.error}</div>` : ""}
    <div class="actions">
      <button onclick="act('${item.id}','start')">Start</button>
      <button onclick="act('${item.id}','pause')">Pause</button>
      <button onclick="act('${item.id}','resume')">Resume</button>
      <button onclick="act('${item.id}','cancel')">Cancel</button>
      <button onclick="delItem('${item.id}')">Delete</button>
    </div>
  </div>`;
}

async function refresh() {
  const downloads = await api("/api/downloads");
  $("#downloads").innerHTML = downloads.map(itemHtml).join("") || "<p class='meta'>No downloads yet.</p>";
  const logs = await api("/api/logs");
  $("#log-output").textContent = logs.map(l => `${new Date(l.ts * 1000).toISOString()} ${l.level} ${l.message}`).join("\n");
}

async function loadSettings() {
  const settings = await api("/api/settings");
  for (const [key, value] of Object.entries(settings)) {
    const input = document.querySelector(`[name=${key}]`);
    if (input) input.value = value;
  }
  const base = location.origin;
  $("#bookmarklet").href = `javascript:(()=>fetch('${base}/api/links',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({url:location.href})}).then(()=>alert('Sent to PS5 Downloader')))()`;
  const plugins = await api("/api/plugins");
  $("#plugins").innerHTML = `<h2>Plugins</h2>${plugins.map(p => `<div class="meta">${p.name} (${p.priority})</div>`).join("")}`;
}

window.act = async (id, action) => {
  await api(`/api/downloads/${id}/${action}`, { method: "POST" });
  refresh();
};

window.delItem = async (id) => {
  await api(`/api/downloads/${id}`, { method: "DELETE" });
  refresh();
};

$("#link-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await api("/api/links", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ text: $("#links").value })
  });
  $("#links").value = "";
  refresh();
});

$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target).entries());
  for (const key of ["max_concurrent_downloads", "per_download_connections", "speed_limit_bytes"]) {
    data[key] = Number(data[key]);
  }
  await api("/api/settings", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(data)
  });
  loadSettings();
});

document.querySelectorAll("nav button").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(tab => tab.classList.remove("active"));
    $("#" + btn.dataset.tab).classList.add("active");
  });
});

loadSettings();
refresh();
setInterval(refresh, 1500);
