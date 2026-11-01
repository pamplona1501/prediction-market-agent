const $ = (selector) => document.querySelector(selector);
let reconnectDelay = 750;
let statisticsRefreshPending = false;

function esc(value) {
  return String(value == null ? "—" : value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[ch]);
}
function usd(value, digits) {
  if (value == null || value === "") return "—";
  const number = Number(value);
  return Number.isFinite(number) ? "US$" + number.toLocaleString("en-US", {
    minimumFractionDigits: 0, maximumFractionDigits: digits == null ? 0 : digits,
  }) : "—";
}
function cents(value) {
  if (value == null || value === "") return "—";
  const number = Number(value);
  return Number.isFinite(number) ? (number * 100).toFixed(1).replace(/\.0$/, "") + "¢" : "—";
}
function localTime(value) {
  if (!value) return "time unavailable";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? esc(value) : parsed.toLocaleTimeString([], {
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  });
}
function ageLabel(value) {
  if (!value) return "not received";
  const age = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
  return age < 60 ? age + "s ago" : Math.floor(age / 60) + "m " + (age % 60) + "s ago";
}
function statusClass(value) {
  value = String(value || "").toLowerCase();
  return ["healthy", "running", "saved"].includes(value) ? "healthy"
    : ["error", "degraded", "unavailable", "stale"].includes(value) ? "error" : "";
}
function setProvider(selector, value) {
  const node = $(selector);
  node.textContent = value || "—";
  node.className = "provider-state " + statusClass(value);
}
function renderEvents(state) {
  const events = state.events || [];
  $("#eventCount").textContent = String(events.length);
  $("#feedUpdated").textContent = state.jupiter && state.jupiter.last_success_at
    ? "Updated " + localTime(state.jupiter.last_success_at) + " · " + ageLabel(state.jupiter.last_success_at)
    : "No provider update yet";
  if (!events.length) {
    const message = state.jupiter && state.jupiter.status === "error"
      ? "Jupiter feed is unavailable. Last successful data remains visible when available."
      : "No live soccer events returned by Jupiter. No sample matches are shown.";
    $("#eventList").innerHTML = '<div class="empty-state">' + message + "</div>";
    return;
  }
  $("#eventList").innerHTML = events.map((item) => {
    const selected = state.selected_event_id === item.event_id;
    const eligible = selected && (state.selected_event && state.selected_event.strategy_evaluations || [])
      .some((evaluation) => evaluation.status === "candidate");
    const highVolume = Number(item.volume_usd) > 1000000;
    const teams = item.home_team && item.away_team ? item.home_team + " · " + item.away_team : item.title;
    return '<article class="event-card ' + (selected ? "selected" : "") + '">' +
      '<div class="event-card-top"><span class="event-status">' + esc(item.status || "LIVE") +
      '</span><span class="event-clock">' + (item.period ? esc(item.period) + " · " : "") +
      (item.minute == null ? "—" : esc(item.minute) + "′") + "</span></div>" +
      '<div class="event-badges">' + (eligible ? '<span title="At least one strategy passes every eligibility gate">⭐ 100% eligible</span>' : "") +
      (highVolume ? '<span title="Jupiter event volume exceeds US$1M">🔥 High volume</span>' : "") + "</div>" +
      '<div class="event-name">' + esc(item.title) + '</div><div class="event-score">' +
      esc(item.score || "—") + '</div><div class="event-teams">' + esc(teams) + '</div>' +
      '<div class="event-vol"><span>JUPITER EVENT VOLUME</span><b>' + usd(item.volume_usd) + "</b></div>" +
      '<button class="monitor-btn ' + (selected ? "stop" : "") + '" data-monitor="' +
      esc(item.event_id) + '">' + (selected ? "Monitoring · stop" : "Monitor this match") + "</button></article>";
  }).join("");
}
function renderGates(selected) {
  const evaluations = selected && selected.strategy_evaluations || [];
  const dataGates = selected && selected.data_gates || {};
  const mapping = selected && selected.fixture_mapping || {};
  const candidates = evaluations.filter((item) => item.status === "candidate");
  const gates = [
    ["Three-way moneyline", !!(selected && selected.moneyline_complete),
      selected ? (selected.moneyline_complete ? "Distinct HOME / DRAW / AWAY contracts" : (selected.moneyline_gate_reasons || []).join(" ")) : "Waiting for selected match"],
    ["Event volume ≥ $1M", !!(selected && selected.volume_gate && selected.volume_gate.passed),
      selected ? (selected.volume_gate.reason || usd(selected.event_volume_usd) + " · Jupiter event field") : "Source-verified Jupiter volume"],
    ["First-half time ≤ 45′", !!(selected && isFirstHalf(selected) && selected.minute != null && selected.minute <= 45),
      selected ? (selected.period || selected.status || "Status unavailable") + " · " + (selected.minute == null ? "minute missing" : selected.minute) : "Waiting for match clock"],
    ["In-game statistics", !!(mapping.status === "verified" && selected.statistics && selected.statistics.status === "healthy"),
      selected ? (selected.statistics && selected.statistics.status === "healthy" ? "LiveScore MCP · exact teams and score verified" : "Stats load automatically when you select the match") : "Waiting for selected match"],
    ["Fresh, consistent sources", !!(dataGates.fresh_data && dataGates.score_consistent),
      selected ? (dataGates.fresh_data && dataGates.score_consistent ? "All source timestamps within configured age" : "One or more source freshness or score checks failed") : "Waiting for current provider timestamps"],
    ["Executable order-book depth", !!(selected && (selected.moneyline || []).some((m) => Number(m.orderbook && m.orderbook.yes_ask_depth_usd || 0) > 0)),
      selected ? "Book loaded; strategy-specific minimum still applies" : "Ask-side depth required"],
    ["Candidate rules", candidates.length > 0, candidates.length ? candidates.length + " candidate(s) · no orders submitted" : "No candidate passes the complete rules and shared gates"],
  ];
  $("#gateGrid").innerHTML = gates.map((gate) =>
    '<div class="gate ' + (selected ? (gate[1] ? "pass" : "fail") : "waiting") + '">' +
    '<span class="gate-symbol">' + (selected ? (gate[1] ? "✓" : "!") : "·") + "</span>" +
    "<span><b>" + esc(gate[0]) + "</b><small>" + esc(gate[2]) + "</small></span></div>"
  ).join("");
  $("#strategyNote").textContent = selected
    ? "Candidate-only evaluation is active. A candidate is informational; it is not a paper fill, order, or recommendation. Real-money execution is disabled."
    : "Monitoring only. Strategy candidates are not orders or recommendations.";
  const resultsNode = $("#strategyResults");
  resultsNode.innerHTML = evaluations.length ? evaluations.map((item) =>
    '<div class="strategy-result ' + esc(item.status) + '"><span><b>' + esc(item.strategy_name.replaceAll("_", " ")) +
    ' · ' + esc(item.outcome) + '</b><small>' + esc((item.reasons || []).join(" ") || "All current gates passed.") +
    '</small></span><strong>' + esc(item.status) + '</strong></div>'
  ).join("") : "";
}
function isFirstHalf(item) {
  const state = ((item && item.status) || "") + " " + ((item && item.period) || "");
  return /\b(1H|FIRST_HALF|FIRST HALF|1ST HALF)\b/i.test(state) && !/HALF.?TIME/i.test(state);
}
function renderMatch(selected) {
  if (!selected) {
    $("#matchPanel").innerHTML = '<div class="empty-match"><div class="empty-icon">⌁</div><h2>Choose a live match</h2><p>Monitoring is on demand. Start one event to load its 1X2 order books and capture observations.</p></div>';
    $("#storageStatus").textContent = "Idle";
    $("#storageMeta").textContent = "Starts when a match is monitored";
    renderGates(null);
    return;
  }
  if (selected.status === "not_in_live_feed" || selected.error) {
    $("#matchPanel").innerHTML = '<div class="empty-match"><div class="empty-icon">!</div><h2>Match data is unavailable</h2><p>' +
      esc(selected.error || "Waiting for the selected event.") + "</p></div>";
    renderGates(null);
    return;
  }
  const clock = selected.period ? selected.period + (selected.minute == null ? "" : " · " + selected.minute + "′")
    : (selected.minute == null ? "—" : selected.minute + "′");
  const cards = (selected.moneyline || []).map((market) => {
    const book = market.orderbook || {};
    return '<article class="market-card"><div class="market-card-head"><span>' + esc(market.outcome) +
      '</span><span>' + esc(market.status || "—") + '</span></div><div class="market-side">' +
      '<div class="book-cell"><div class="book-label">YES · BID / ASK</div><div class="book-price">' +
      cents(book.yes_bid) + ' <span style="color:#677985;font-size:11px">/</span> ' + cents(book.yes_ask) +
      '</div><div class="book-depth">Ask depth ' + usd(book.yes_ask_depth_usd, 2) + '</div></div>' +
      '<div class="book-cell no"><div class="book-label">NO · BID / ASK</div><div class="book-price">' +
      cents(book.no_bid) + ' <span style="color:#677985;font-size:11px">/</span> ' + cents(book.no_ask) +
      '</div><div class="book-depth">Ask depth ' + usd(book.no_ask_depth_usd, 2) +
      '</div></div></div><div class="market-foot"><span>Volume ' + usd(market.market_volume_usd) +
      '</span><span>' + (market.orderbook ? "book " + ageLabel(book.fetched_at) : "book unavailable") +
      "</span></div></article>";
  }).join("");
  const stats = selected.statistics;
  const statsButton = '<button class="stats-refresh" data-refresh-stats="' + esc(selected.event_id) + '"' +
    (statisticsRefreshPending ? " disabled" : "") + ">" +
    (statisticsRefreshPending ? "Fetching…" : (stats && stats.status === "healthy" ? "Refresh stats" : "Fetch match stats")) + "</button>";
  const statsRows = [
    ["Shots", stats && stats.home_shots, stats && stats.away_shots],
    ["Shots on target", stats && stats.home_shots_on_target, stats && stats.away_shots_on_target],
    ["Possession", stats && stats.home_possession, stats && stats.away_possession, "%"],
    ["Passes", stats && stats.home_passes, stats && stats.away_passes],
    ["Pass accuracy", stats && stats.home_pass_accuracy, stats && stats.away_pass_accuracy, "%"],
    ["Fouls", stats && stats.home_fouls, stats && stats.away_fouls],
    ["Yellow cards", stats && stats.home_yellow_cards, stats && stats.away_yellow_cards],
    ["Red cards", stats && stats.home_red_cards, stats && stats.away_red_cards],
    ["Offsides", stats && stats.home_offsides, stats && stats.away_offsides],
    ["Corners", stats && stats.home_corners, stats && stats.away_corners],
  ];
  const statValue = (value, suffix) => value == null ? "—" : esc(value) + (suffix || "");
  const statsMarkup = '<section class="stats-panel"><div class="stats-panel-head"><div><b>TEAM STATS</b><span>' +
    (stats && stats.status === "healthy"
      ? 'LiveScore MCP · refreshed ' + ageLabel(stats.received_at) +
        (stats.score_consistent ? ' · score agrees' : ' · score differs; strategy gate blocked')
      : "LiveScore MCP · on-demand for the selected match") +
    '</span></div>' + statsButton + '</div>' +
    (stats && stats.status === "healthy"
      ? '<div class="stats-table-wrap"><table class="stats-table"><thead><tr><th>Statistic</th><th>' +
        esc(selected.home_team) + '</th><th>' + esc(selected.away_team) + '</th></tr></thead><tbody>' +
        statsRows.map((row) => '<tr><th>' + esc(row[0]) + '</th><td>' + statValue(row[1], row[3]) +
          '</td><td>' + statValue(row[2], row[3]) + '</td></tr>').join("") +
        '</tbody></table></div>'
      : '<div class="stats-empty">' + esc(stats && stats.error || "No match statistics loaded yet.") + '</div>') +
    '</section>';
  $("#matchPanel").innerHTML = '<div class="match-head"><div><h2 class="match-title">' + esc(selected.title) +
    '</h2><div class="match-subtitle">JUPITER EVENT · ' + esc(selected.event_id) +
    '</div></div><span class="live-badge">● AUTO-REFRESHING</span></div>' +
    '<div class="scoreboard"><div class="score-team"><span>' + esc(selected.home_team) +
    '</span></div><div><div class="score-big">' + esc(selected.score || "—") +
    '</div><div class="score-status">' + esc(clock) + '</div></div><div class="score-team"><span>' +
    esc(selected.away_team) + '</span></div></div>' +
    '<div class="metric-row"><div class="mini-metric"><span>Event volume</span><b>' + usd(selected.event_volume_usd) +
    '</b></div><div class="mini-metric"><span>Moneyline</span><b>' + (selected.moneyline_complete ? "3 / 3" : (selected.moneyline || []).length + " / 3") +
    '</b></div><div class="mini-metric"><span>Score update</span><b>' + ageLabel(selected.score_updated_at || selected.fetched_at) +
    '</b></div><div class="mini-metric"><span>Snapshots</span><b>' + (selected.persistence === "saved" ? selected.snapshots_written + " rows · saved" : "database unavailable") +
    '</b></div></div><div class="subheading"><h3>Three-way moneyline · order book</h3><span>' +
    (selected.orderbook_status === "healthy" ? "DEPTH LOADED" : "PARTIAL DEPTH") + '</span></div>' +
    (cards ? '<div class="market-grid">' + cards + '</div>' : '<div class="empty-state">' +
      (selected.moneyline_gate_reasons || []).map(esc).join(" ") + "</div>") +
    '<div class="match-actions"><span>Detail received ' + localTime(selected.fetched_at) +
    " · age " + ageLabel(selected.fetched_at) + '</span><button class="stop-monitor" data-stop="true">Stop monitoring</button></div>' +
    statsMarkup +
    '<p class="match-data-note">' +
    (selected.prematch_favorite
      ? "Pre-match favorite: " + esc(selected.prematch_favorite.outcome) + " at " + cents(selected.prematch_favorite.probability) +
        " · " + esc(selected.prematch_favorite.source) + " · captured " + ageLabel(selected.prematch_favorite.observed_at) + ". "
      : "Pre-match favorite baseline unavailable. ") +
    'Order-book ask depth is estimated from Jupiter’s binary complement-side bid levels. This is market data, not a fill guarantee. ' +
    esc((selected.orderbook_errors || []).join(" ")) + "</p>";
  $("#storageStatus").textContent = selected.persistence === "saved" ? "Healthy" : "Unavailable";
  $("#storageMeta").textContent = selected.persistence === "saved"
    ? selected.snapshots_written + " observations on last capture"
    : "Check database configuration and Alembic revision";
  $("#storageStatus").className = "provider-state " + statusClass(selected.persistence === "saved" ? "healthy" : "unavailable");
  renderGates(selected);
}
function renderLogs(logs) {
  $("#logList").innerHTML = logs && logs.length ? logs.slice(0, 20).map((entry) =>
    '<div class="log-row"><span class="log-time">' + localTime(entry.at) + '</span><span class="log-level ' +
    esc(entry.level) + '">' + esc(entry.level) + "</span><span>" + esc(entry.message) + "</span></div>"
  ).join("") : '<div class="empty-state">Monitor events will appear here.</div>';
}
function render(state) {
  $("#serviceStatus").textContent = state.service && state.service.status || "unknown";
  $("#pollInterval").textContent = state.service && state.service.poll_seconds
    ? "Refresh target " + state.service.poll_seconds + "s · REST polling" : "Waiting for first provider update";
  setProvider("#jupiterStatus", state.jupiter && state.jupiter.status);
  $("#jupiterMeta").textContent = (state.jupiter && state.jupiter.auth || "Provider access") +
    " · last success " + ageLabel(state.jupiter && state.jupiter.last_success_at);
  const statsProvider = state.livescore_mcp || {};
  setProvider("#statsProviderStatus", statsProvider.status === "on_demand" ? "On demand" : statsProvider.status);
  $("#statsProviderMeta").textContent = statsProvider.last_error ||
    (statsProvider.last_success_at ? "Last selected-match response " + ageLabel(statsProvider.last_success_at) :
      "Fetched only when requested for the selected match");
  renderEvents(state);
  renderMatch(state.selected_event);
  renderLogs(state.logs);
  const errors = [state.jupiter && state.jupiter.last_error].filter(Boolean);
  $("#topNotice").textContent = errors.join(" ");
  $("#topNotice").hidden = !errors.length;
}
async function requestMonitor(eventId) {
  const response = await fetch("/api/monitor", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_id: eventId }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || "Monitor request failed (" + response.status + ")");
  }
  render(await response.json());
}
const delay = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));
async function waitForSelectedDetails(eventId) {
  const deadline = Date.now() + 45000;
  while (Date.now() < deadline) {
    const response = await fetch("/api/state");
    const state = await response.json();
    render(state);
    if (state.selected_event_id !== eventId) {
      throw new Error("The selected match changed before its details loaded.");
    }
    if (state.selected_event && state.selected_event.event_id === eventId) {
      if (state.selected_event.status === "not_in_live_feed") {
        throw new Error("Jupiter has no current score for this match.");
      }
      return;
    }
    await delay(500);
  }
  throw new Error("The selected match details did not load in time. Try selecting it again.");
}
async function requestStatistics(eventId, retryCooldown = true) {
  const response = await fetch("/api/statistics/refresh", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event_id: eventId }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const message = error.detail || "Statistics refresh failed (" + response.status + ")";
    if (retryCooldown && response.status === 409 && message.includes("Please wait 15 seconds")) {
      $("#topNotice").textContent = "LiveScore cooldown active; the initial stats request will retry in 15 seconds.";
      $("#topNotice").hidden = false;
      await delay(15000);
      const current = await fetch("/api/state").then((result) => result.json());
      if (current.selected_event_id !== eventId) return;
      return requestStatistics(eventId, false);
    }
    throw new Error(message);
  }
  render(await response.json());
}
document.addEventListener("click", async (event) => {
  const refreshStats = event.target.closest("[data-refresh-stats]");
  const start = event.target.closest("[data-monitor]");
  const stop = event.target.closest("[data-stop]");
  if (refreshStats) {
    statisticsRefreshPending = true;
    refreshStats.disabled = true;
    refreshStats.textContent = "Fetching…";
    try {
      await requestStatistics(refreshStats.dataset.refreshStats);
    } catch (error) {
      $("#topNotice").textContent = error.message;
      $("#topNotice").hidden = false;
    } finally {
      statisticsRefreshPending = false;
      fetch("/api/state").then((response) => response.json()).then(render).catch(() => {});
    }
    return;
  }
  if (!start && !stop) return;
  const eventId = stop ? null : start.dataset.monitor;
  statisticsRefreshPending = !!eventId;
  try {
    await requestMonitor(eventId);
    if (eventId) {
      await waitForSelectedDetails(eventId);
      await requestStatistics(eventId);
    }
  } catch (error) {
    $("#topNotice").textContent = error.message;
    $("#topNotice").hidden = false;
  } finally {
    statisticsRefreshPending = false;
    fetch("/api/state").then((response) => response.json()).then(render).catch(() => {});
  }
});
function connect() {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(scheme + "//" + location.host + "/ws/events");
  socket.addEventListener("open", () => {
    reconnectDelay = 750;
    $("#connectionDot").className = "live-dot connected";
    $("#connectionLabel").textContent = "Screen connected · polling data";
  });
  socket.addEventListener("message", (message) => {
    try { render(JSON.parse(message.data)); } catch { /* discard malformed update */ }
  });
  socket.addEventListener("close", () => {
    $("#connectionDot").className = "live-dot offline";
    $("#connectionLabel").textContent = "Reconnecting";
    window.setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 2, 15000);
  });
  socket.addEventListener("error", () => socket.close());
}
fetch("/api/state").then((response) => response.json()).then(render).catch(() => {});
connect();
