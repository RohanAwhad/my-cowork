(function () {
  "use strict";

  // ---- Token management ----
  var TOKEN_KEY = "cowork_server_token";

  function getToken() {
    var t = localStorage.getItem(TOKEN_KEY);
    if (!t) {
      t = prompt("Enter your Co-work server token:");
      if (t) localStorage.setItem(TOKEN_KEY, t.trim());
    }
    return t || "";
  }

  function authHeaders() {
    return { Authorization: "Bearer " + getToken(), "Content-Type": "application/json" };
  }

  async function api(method, path, body) {
    var opts = { method: method, headers: authHeaders() };
    if (body !== undefined) opts.body = JSON.stringify(body);
    var resp = await fetch(path, opts);
    if (resp.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      showToast("Authentication failed. Refresh to re-enter token.", "error");
      throw new Error("Unauthorized");
    }
    return resp;
  }

  // ---- Navigation ----
  var navBtns = document.querySelectorAll(".nav-btn");
  navBtns.forEach(function (btn) {
    btn.addEventListener("click", function () {
      navBtns.forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      document.querySelectorAll(".section").forEach(function (s) { s.classList.remove("active"); });
      var sec = document.getElementById("section-" + btn.dataset.section);
      if (sec) sec.classList.add("active");
      if (btn.dataset.section === "tasks") loadTasks();
      if (btn.dataset.section === "connectors") loadConnectors();
      if (btn.dataset.section === "settings") loadSettings();
      if (btn.dataset.section === "memory") loadMemory();
    });
  });

  // ---- Toast notifications ----
  function showToast(msg, type) {
    var container = document.getElementById("toast-container");
    var el = document.createElement("div");
    el.className = "toast " + (type || "");
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(function () { el.remove(); }, 5000);
  }

  // ---- Sessions ----
  var selectedSessionId = null;
  var lastEventSeq = 0;

  document.getElementById("session-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    var prompt = document.getElementById("session-prompt").value.trim();
    if (!prompt) return;
    var resp = await api("POST", "/api/sessions", { prompt: prompt });
    if (resp.ok) {
      document.getElementById("session-prompt").value = "";
      var session = await resp.json();
      showToast("Session created: " + session.id.slice(0, 8));
      loadSessions();
    }
  });

  async function loadSessions() {
    var resp = await api("GET", "/api/sessions");
    if (!resp.ok) return;
    var sessions = await resp.json();
    var list = document.getElementById("session-list");
    list.innerHTML = "";
    sessions.forEach(function (s) {
      var li = document.createElement("li");
      if (selectedSessionId === s.id) li.classList.add("selected");
      li.innerHTML =
        '<span class="session-title">' + escapeHtml(s.title || s.id.slice(0, 8)) + "</span>" +
        '<span class="status-badge status-' + s.status + '">' + s.status + "</span>";
      li.addEventListener("click", function () { selectSession(s.id); });
      list.appendChild(li);
    });
  }

  async function selectSession(id) {
    selectedSessionId = id;
    lastEventSeq = 0;
    loadSessions();
    var resp = await api("GET", "/api/sessions/" + id);
    if (!resp.ok) return;
    var s = await resp.json();
    var detail = document.getElementById("session-detail");
    detail.innerHTML =
      '<div class="detail-row"><span class="detail-label">ID</span><span>' + s.id + "</span></div>" +
      '<div class="detail-row"><span class="detail-label">Status</span><span class="status-badge status-' + s.status + '">' + s.status + "</span></div>" +
      '<div class="detail-row"><span class="detail-label">Prompt</span><span>' + escapeHtml(s.prompt) + "</span></div>" +
      '<div class="detail-row"><span class="detail-label">Created</span><span>' + new Date(s.created_at).toLocaleString() + "</span></div>" +
      (s.num_turns != null ? '<div class="detail-row"><span class="detail-label">Turns</span><span>' + s.num_turns + "</span></div>" : "") +
      (s.error ? '<div class="detail-row"><span class="detail-label">Error</span><span style="color:var(--error)">' + escapeHtml(s.error) + "</span></div>" : "") +
      '<div class="detail-actions">' +
      (s.status === "pending" ? '<button onclick="startSession(\'' + s.id + "')\" >Start</button>" : "") +
      (s.status === "running" ? '<button class="danger" onclick="stopSession(\'' + s.id + "')\" >Stop</button>" : "") +
      (["done", "stopped", "failed"].includes(s.status) ? '<button class="secondary" onclick="archiveSession(\'' + s.id + "')\" >Archive</button>" : "") +
      "</div>";
    loadEvents(id);
    loadArtifacts(id);
  }

  window.startSession = async function (id) {
    await api("POST", "/api/sessions/" + id + "/start");
    selectSession(id);
  };
  window.stopSession = async function (id) {
    await api("POST", "/api/sessions/" + id + "/stop");
    selectSession(id);
  };
  window.archiveSession = async function (id) {
    await api("POST", "/api/sessions/" + id + "/archive");
    selectSession(id);
    loadSessions();
  };

  async function loadEvents(sessionId) {
    var resp = await api("GET", "/api/sessions/" + sessionId + "/events?after_seq=" + lastEventSeq);
    if (!resp.ok) return;
    var events = await resp.json();
    var log = document.getElementById("event-log");
    events.forEach(function (ev) {
      appendEventEntry(log, ev);
      if (ev.seq > lastEventSeq) lastEventSeq = ev.seq;
    });
  }

  function appendEventEntry(log, ev) {
    var div = document.createElement("div");
    div.className = "event-entry";
    var time = new Date(ev.created_at).toLocaleTimeString();
    div.innerHTML =
      '<span class="event-time">' + time + "</span>" +
      '<span class="event-type">' + ev.event_type + "</span> " +
      '<span class="event-payload">' + escapeHtml(JSON.stringify(ev.payload).slice(0, 200)) + "</span>";
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  async function loadArtifacts(sessionId) {
    var resp = await api("GET", "/api/artifacts?session_id=" + sessionId);
    if (!resp.ok) return;
    var artifacts = await resp.json();
    var grid = document.getElementById("artifact-list");
    grid.innerHTML = "";
    artifacts.forEach(function (a) {
      var card = document.createElement("div");
      card.className = "artifact-card";
      var previewUrl = "/previews/" + a.session_id + "/" + a.id + "/v" + a.current_version;
      var ext = (a.rel_path || "").split(".").pop().toLowerCase();
      var preview = "";
      if (["png", "jpg", "jpeg", "gif", "svg", "webp"].includes(ext)) {
        preview = '<img src="' + previewUrl + '" alt="' + escapeHtml(a.name) + '" style="max-width:100%;max-height:120px;margin-top:0.5rem">';
      } else if (ext === "pdf") {
        preview = '<embed src="' + previewUrl + '" type="application/pdf" style="width:100%;height:120px;margin-top:0.5rem">';
      } else if (ext === "html") {
        preview = '<iframe sandbox="" src="' + previewUrl + '" style="width:100%;height:120px;border:none;margin-top:0.5rem"></iframe>';
      }
      card.innerHTML =
        '<div class="artifact-name">' + escapeHtml(a.name) + "</div>" +
        '<div class="artifact-meta">v' + a.current_version + " &middot; " + formatBytes(a.size_bytes) + "</div>" +
        '<a href="' + previewUrl + '" target="_blank">View</a>' +
        preview;
      grid.appendChild(card);
    });
  }

  // ---- Tasks ----
  document.getElementById("task-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    var name = document.getElementById("task-name").value.trim();
    var prompt = document.getElementById("task-prompt").value.trim();
    var cadence = document.getElementById("task-cadence").value;
    var cronExpr = document.getElementById("task-cron").value.trim() || null;
    if (!name || !prompt) return;
    var body = { name: name, prompt: prompt };
    if (cronExpr) { body.cron_expr = cronExpr; } else { body.cadence = cadence; }
    var resp = await api("POST", "/api/tasks", body);
    if (resp.ok) {
      document.getElementById("task-name").value = "";
      document.getElementById("task-prompt").value = "";
      document.getElementById("task-cron").value = "";
      loadTasks();
    }
  });

  async function loadTasks() {
    var resp = await api("GET", "/api/tasks");
    if (!resp.ok) return;
    var tasks = await resp.json();
    var list = document.getElementById("task-list");
    list.innerHTML = "";
    tasks.forEach(function (t) {
      var li = document.createElement("li");
      li.innerHTML =
        "<span>" + escapeHtml(t.name) + " <small>(" + (t.cadence || t.cron_expr || "manual") + ")</small></span>" +
        '<div class="task-actions">' +
        '<span class="status-badge status-' + t.status + '">' + t.status + "</span>" +
        '<button class="secondary" onclick="runTask(\'' + t.id + "')\" >Run</button>" +
        '<button class="danger" onclick="deleteTask(\'' + t.id + "')\" >&times;</button>" +
        "</div>";
      list.appendChild(li);
    });
  }

  window.runTask = async function (id) {
    var resp = await api("POST", "/api/tasks/" + id + "/run");
    if (resp.ok) showToast("Task triggered");
  };
  window.deleteTask = async function (id) {
    await api("DELETE", "/api/tasks/" + id);
    loadTasks();
  };

  // ---- Connectors ----
  document.getElementById("connector-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    var name = document.getElementById("connector-name").value.trim();
    var command = document.getElementById("connector-command").value.trim();
    var argsRaw = document.getElementById("connector-args").value.trim();
    if (!name || !command) return;
    var args = argsRaw ? argsRaw.split(",").map(function (a) { return a.trim(); }) : [];
    var resp = await api("POST", "/api/connectors", { name: name, command: command, args: args });
    if (resp.ok) {
      document.getElementById("connector-name").value = "";
      document.getElementById("connector-command").value = "";
      document.getElementById("connector-args").value = "";
      loadConnectors();
    }
  });

  async function loadConnectors() {
    var resp = await api("GET", "/api/connectors");
    if (!resp.ok) return;
    var connectors = await resp.json();
    var list = document.getElementById("connector-list");
    list.innerHTML = "";
    connectors.forEach(function (c) {
      var li = document.createElement("li");
      li.innerHTML =
        "<span>" + escapeHtml(c.name) + " <small>" + escapeHtml(c.command) + "</small></span>" +
        '<div class="connector-actions">' +
        '<span class="status-badge status-' + c.status + '">' + c.status + "</span>" +
        '<button class="danger" onclick="deleteConnector(\'' + c.id + "')\" >&times;</button>" +
        "</div>";
      list.appendChild(li);
    });
  }

  window.deleteConnector = async function (id) {
    await api("DELETE", "/api/connectors/" + id);
    loadConnectors();
  };

  // ---- Settings ----
  var SETTING_FIELDS = [
    { key: "claude_version_pin", label: "Claude Version Pin", type: "text" },
    { key: "server_port", label: "Server Port", type: "number" },
    { key: "scheduler_tick_seconds", label: "Scheduler Tick (s)", type: "number" },
    { key: "spawn_health_timeout_seconds", label: "Spawn Health Timeout (s)", type: "number" },
    { key: "runner_no_event_timeout_minutes", label: "Runner Timeout (min)", type: "number" },
    { key: "memory_enabled", label: "Memory Enabled", type: "checkbox" },
    { key: "scheduler_max_consecutive_failures", label: "Max Consecutive Failures", type: "number" },
    { key: "log_level", label: "Log Level", type: "text" },
  ];

  async function loadSettings() {
    var resp = await api("GET", "/api/settings");
    if (!resp.ok) return;
    var settings = await resp.json();
    var container = document.getElementById("settings-fields");
    container.innerHTML = "";
    SETTING_FIELDS.forEach(function (f) {
      var div = document.createElement("div");
      div.className = "setting-field";
      var val = settings[f.key];
      if (f.type === "checkbox") {
        div.innerHTML =
          "<label>" + f.label + "</label>" +
          '<input type="checkbox" data-key="' + f.key + '" ' + (val ? "checked" : "") + " style='width:auto'>";
      } else {
        div.innerHTML =
          "<label>" + f.label + "</label>" +
          '<input type="' + f.type + '" data-key="' + f.key + '" value="' + (val != null ? val : "") + '">';
      }
      container.appendChild(div);
    });
  }

  document.getElementById("settings-form").addEventListener("submit", async function (e) {
    e.preventDefault();
    var body = {};
    SETTING_FIELDS.forEach(function (f) {
      var el = document.querySelector('[data-key="' + f.key + '"]');
      if (!el) return;
      if (f.type === "checkbox") {
        body[f.key] = el.checked;
      } else if (f.type === "number") {
        var v = el.value.trim();
        if (v) body[f.key] = parseInt(v, 10);
      } else {
        var v2 = el.value.trim();
        if (v2) body[f.key] = v2;
      }
    });
    var resp = await api("PUT", "/api/settings", body);
    if (resp.ok) showToast("Settings saved");
  });

  // ---- Memory ----
  async function loadMemory() {
    var resp = await api("GET", "/api/memory");
    if (!resp.ok) return;
    var data = await resp.json();
    document.getElementById("memory-content").value = data.content || "";
    document.getElementById("memory-info").textContent =
      "Size: " + formatBytes(data.size_bytes) + " | Modified: " + new Date(data.modified_at).toLocaleString();
  }

  document.getElementById("memory-save").addEventListener("click", async function () {
    var content = document.getElementById("memory-content").value;
    var resp = await api("PUT", "/api/memory", { content: content });
    if (resp.ok) {
      showToast("Memory saved");
      loadMemory();
    } else {
      var err = await resp.json();
      showToast(err.detail || "Save failed", "error");
    }
  });

  // ---- WebSocket ----
  var ws = null;
  var wsReconnectTimer = null;

  function connectWs() {
    var token = getToken();
    if (!token) return;
    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var url = proto + "//" + location.host + "/ws?token=" + encodeURIComponent(token);
    ws = new WebSocket(url);
    var statusEl = document.getElementById("ws-status");

    ws.onopen = function () {
      statusEl.className = "ws-indicator connected";
      statusEl.textContent = "WS";
      if (selectedSessionId) loadEvents(selectedSessionId);
    };

    ws.onmessage = function (evt) {
      var msg;
      try { msg = JSON.parse(evt.data); } catch (e) { return; }
      if (msg.type === "permission.notice") {
        showToast(msg.tool_name + ": " + msg.decision + " (" + (msg.reason || "") + ")", "permission");
      }
      if (msg.type === "session.event" && msg.session_id === selectedSessionId) {
        var log = document.getElementById("event-log");
        appendEventEntry(log, { created_at: new Date().toISOString(), event_type: msg.event_type, payload: msg.payload, seq: 0 });
      }
      if (msg.type && msg.type.startsWith("session.")) {
        loadSessions();
        if (selectedSessionId) selectSession(selectedSessionId);
      }
      if (msg.type && msg.type.startsWith("artifact.") && selectedSessionId) {
        loadArtifacts(selectedSessionId);
      }
    };

    ws.onclose = function () {
      statusEl.className = "ws-indicator disconnected";
      statusEl.textContent = "WS";
      wsReconnectTimer = setTimeout(connectWs, 3000);
    };

    ws.onerror = function () { ws.close(); };
  }

  // ---- Helpers ----
  function escapeHtml(str) {
    if (!str) return "";
    var d = document.createElement("div");
    d.appendChild(document.createTextNode(str));
    return d.innerHTML;
  }

  function formatBytes(bytes) {
    if (bytes == null) return "0 B";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / 1048576).toFixed(1) + " MB";
  }

  // ---- Init ----
  loadSessions();
  connectWs();
})();
