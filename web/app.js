const $ = (selector) => document.querySelector(selector);
let statisticsRefreshPending = false;
let activeFeed = "upcoming";
let latestState = null;

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
function kickoffLabel(value) {
  if (!value) return "Time unavailable";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? esc(value) : parsed.toLocaleString([], {
    weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
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
  $("#liveCount").textContent = String(events.length);
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
      (item.watched ? '<div class="watched-mark">📌 Pinned <button class="unwatch-btn" data-unwatch="' + esc(item.event_id) + '">Remove</button></div>' : '') +
      '<button class="monitor-btn ' + (selected ? "stop" : "") + '" data-monitor="' +
      esc(item.event_id) + '">' + (selected ? "Monitoring · stop" : "Monitor this match") + "</button></article>";
  }).join("");
}
function renderUpcoming(state) {
  const matches = state.upcoming_matches || [];
  const watchlist = state.watchlist || [];
  const radar = state.upcoming_radar || {};
  $("#upcomingCount").textContent = String(matches.length);
  $("#radarStatus").textContent = radar.status === "stale"
    ? "Stale · showing last successful scan from " + ageLabel(radar.last_success_at) + (radar.last_error ? " · " + radar.last_error : "")
    : radar.status === "error" ? "Radar unavailable · " + (radar.last_error || "waiting for provider")
      : radar.last_success_at ? "Updated " + ageLabel(radar.last_success_at) + " · scan every " + Math.round((radar.refresh_seconds || 300) / 60) + " min"
        : "Waiting for first radar scan";
  $("#radarStatus").className = "radar-status " + (radar.status === "stale" || radar.status === "error" ? "stale" : "");
  $("#upcomingList").innerHTML = matches.length ? matches.map((item) => {
    const primed = item.strategy_1_may_apply;
    const volumePassed = item.volume_gate_met_at_observation;
    return '<article class="event-card upcoming-event-card ' + (item.selected ? 'selected' : '') + '">' +
      '<div class="event-card-top"><span class="event-status">UPCOMING</span><span class="event-clock">' +
      esc(kickoffLabel(item.scheduled_start_at)) + '</span></div>' +
      '<div class="event-badges">' + (primed ? '<span title="May apply only after kickoff if all live rules and gates pass">⚡ Strategy 1 may apply</span>' : '') +
      (volumePassed ? '<span title="US$1M event-volume gate met at last observation">🔥 US$1M+</span>' : '') +
      (item.watched ? '<span class="pinned-badge">📌 Pinned</span>' : '') + '</div>' +
      '<div class="event-name">' + esc(item.title) + '</div>' +
      '<div class="upcoming-event-matchup">' + esc(item.home_team || 'Home') + ' · ' + cents(item.home_price) +
      ' <i>×</i> ' + esc(item.away_team || 'Away') + ' · ' + cents(item.away_price) + '</div>' +
      '<div class="event-vol"><span>Volume Pre-Match:</span><b>' + usd(item.volume_usd) + '</b></div>' +
      '<div class="radar-action-row"><button class="monitor-btn view-upcoming-btn" data-select-upcoming="' +
      esc(item.event_id) + '">' + (item.selected ? 'Viewing details' : 'View match details') + '</button>' +
      '<button class="watch-btn" data-' + (item.watched ? 'unwatch' : 'watch') + '="' + esc(item.event_id) + '">' +
      (item.watched ? 'Unpin' : 'Pin') + '</button></div></article>';
  }).join('') : '<div class="empty-state">' + (radar.last_success_at
    ? 'No scanned upcoming Jupiter soccer matches have event volume of at least US$100,000.'
    : radar.status === 'error' ? 'Upcoming events could not be loaded. Check the radar status above.'
      : 'Loading upcoming Jupiter soccer matches…') + '</div>';
  const liveIds = new Set((state.events || []).map((row) => row.event_id));
  const upcomingIds = new Set(matches.map((row) => row.event_id));
  $("#watchlistList").innerHTML = state.watchlist_status === "unavailable"
    ? '<div class="empty-state">Watchlist storage is unavailable. Check the database connection and run current migrations.</div>'
    : watchlist.length ? watchlist.map((row) =>
    '<div class="watchlist-row"><span><b>' + esc(row.title) + '</b><small>' + esc(localTime(row.scheduled_start_at)) +
    (liveIds.has(row.event_id) ? ' · in-play' : upcomingIds.has(row.event_id) ? ' · upcoming' : ' · not in current feed') +
    '</small></span><button class="unwatch-btn" data-unwatch="' + esc(row.event_id) + '">Remove</button></div>'
  ).join('') : '<div class="empty-state">No pinned matches.</div>';
}
function renderUpcomingMatch(selected, state) {
  if (!selected) {
    $("#upcomingMatchPanel").innerHTML = '<div class="empty-match"><div class="empty-icon">⌁</div>' +
      '<h2>Choose an upcoming match</h2><p>Upcoming events load automatically. Select a match to inspect its three-way market prices. This does not start in-play monitoring.</p></div>';
    return;
  }
  if (selected.error && selected.status === "stale") {
    $("#upcomingMatchPanel").innerHTML = '<div class="notice">' + esc(selected.error) + '</div>' +
      '<div class="match-head"><div><h2 class="match-title">' + esc(selected.title) +
      '</h2><div class="match-subtitle">LAST UPCOMING OBSERVATION · ' + esc(selected.event_id) + '</div></div>' +
      '<span class="upcoming-badge">STALE</span></div>';
    return;
  }
  const watched = (state && state.watchlist || []).some((item) => item.event_id === selected.event_id);
  const markets = (selected.moneyline || []).map((market) =>
    '<article class="market-card"><div class="market-card-head"><span>' + esc(market.outcome) +
    '</span><span>' + esc(market.status || '—') + '</span></div><div class="market-side">' +
    '<div class="book-cell"><div class="book-label">BUY YES / SELL YES</div><div class="book-price">' +
    cents(market.buy_yes_usd) + ' <span style="color:#677985;font-size:11px">/</span> ' + cents(market.sell_yes_usd) +
    '</div><div class="book-depth">Jupiter event-feed quote</div></div><div class="book-cell no">' +
    '<div class="book-label">BUY NO / SELL NO</div><div class="book-price">' + cents(market.buy_no_usd) +
    ' <span style="color:#677985;font-size:11px">/</span> ' + cents(market.sell_no_usd) +
    '</div><div class="book-depth">No orderbook depth in this feed</div></div></div><div class="market-foot">' +
    '<span>Market volume ' + usd(market.market_volume_usd) + '</span><span>' + esc(market.market_id) +
    '</span></div></article>'
  ).join('');
  const issue = selected.moneyline_complete ? '' : '<div class="empty-state upcoming-mapping-note">' +
    (selected.moneyline_gate_reasons || []).map(esc).join(' ') + '</div>';
  $("#upcomingMatchPanel").innerHTML = '<div class="match-head"><div><h2 class="match-title">' + esc(selected.title) +
    '</h2><div class="match-subtitle">JUPITER EVENT · ' + esc(selected.event_id) + '</div></div>' +
    '<span class="upcoming-badge">● UPCOMING</span></div>' +
    '<div class="scoreboard upcoming-scoreboard"><div class="score-team"><span>' + esc(selected.home_team || 'Home team') +
    '</span></div><div><div class="kickoff-date">' + esc(kickoffLabel(selected.scheduled_start_at)) +
    '</div><div class="score-status">KICKOFF</div></div><div class="score-team"><span>' +
    esc(selected.away_team || 'Away team') + '</span></div></div>' +
    '<div class="metric-row"><div class="mini-metric"><span>Event volume</span><b>' + usd(selected.event_volume_usd) +
    '</b></div><div class="mini-metric"><span>Three-way moneyline</span><b>' +
    (selected.moneyline_complete ? '3 / 3' : (selected.moneyline || []).length + ' / 3') +
    '</b></div><div class="mini-metric"><span>Market data</span><b>Jupiter feed</b></div>' +
    '<div class="mini-metric"><span>Last update</span><b>' + ageLabel(selected.fetched_at) + '</b></div></div>' +
    '<div class="subheading"><h3>Three-way moneyline · market quotes</h3><span>PRE-MATCH DATA</span></div>' +
    (markets ? '<div class="market-grid">' + markets + '</div>' : issue) + issue +
    '<div class="match-actions"><span>' + esc(selected.market_source || 'Jupiter upcoming market feed') +
    '</span><button class="watch-btn" data-' + (watched ? 'unwatch' : 'watch') + '="' + esc(selected.event_id) + '">' +
    (watched ? '📌 Remove pin' : 'Pin match') + '</button></div>' +
    '<p class="match-data-note">This future-match view is separate from in-play monitoring. Quotes update with the five-minute upcoming scan; no monitoring, orders, or trading are started here.</p>';
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
    ["Candidate rules", candidates.length > 0, candidates.length ? candidates.length + " candidate(s) · execution disabled" : "No candidate passes the complete rules and shared gates"],
  ];
  $("#gateGrid").innerHTML = gates.map((gate) =>
    '<div class="gate ' + (selected ? (gate[1] ? "pass" : "fail") : "waiting") + '">' +
    '<span class="gate-symbol">' + (selected ? (gate[1] ? "✓" : "!") : "·") + "</span>" +
    "<span><b>" + esc(gate[0]) + "</b><small>" + esc(gate[2]) + "</small></span></div>"
  ).join("");
  $("#strategyNote").textContent = selected
    ? "Eligible candidates create a disabled execution-intent audit record. No wallet, order, paper fill, or transaction is created."
    : "Monitoring only. Strategy candidates are not orders or recommendations.";
  const resultsNode = $("#strategyResults");
  resultsNode.innerHTML = evaluations.length ? evaluations.map((item) =>
    '<div class="strategy-result ' + esc(item.status) + '"><span><b>' + esc(item.strategy_name.replaceAll("_", " ")) +
    ' · ' + esc(item.outcome) + '</b><small>' + esc((item.reasons || []).join(" ") || "All current gates passed.") +
    (item.execution_intent ? '<br>Intent: ' + esc(item.execution_intent.status) + ' · ' + esc(item.execution_intent.audit_status || item.execution_intent.reason || "") : "") +
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
  const drawWarning = (selected.strategy_evaluations || []).find((item) => item.hard_warning);
  const warningMarkup = drawWarning
    ? '<div class="notice hard-warning" role="alert">⚠ ' + esc((drawWarning.reasons || []).join(" ")) + '</div>'
    : "";
  const statsLoading = statisticsRefreshPending || (stats && stats.status === "loading");
  const statsButton = '<button class="stats-refresh" data-refresh-stats="' + esc(selected.event_id) + '"' +
    (statsLoading ? " disabled" : "") + ">" +
    (statsLoading ? "Fetching…" : (stats && stats.status === "healthy" ? "Refresh stats" : "Fetch match stats")) + "</button>";
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
  $("#matchPanel").innerHTML = warningMarkup + '<div class="match-head"><div><h2 class="match-title">' + esc(selected.title) +
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
  latestState = state;
  $("#serviceStatus").textContent = state.service && state.service.status || "unknown";
  $("#pollInterval").textContent = state.service && state.service.status === "running"
    ? "Browser updates via SSE" : "Waiting for monitor service";
  setProvider("#jupiterStatus", state.jupiter && state.jupiter.status);
  $("#jupiterMeta").textContent = state.jupiter && state.jupiter.last_success_at
    ? "REST · last update " + ageLabel(state.jupiter.last_success_at)
    : "REST · awaiting first update";
  const statsProvider = state.livescore_mcp || {};
  setProvider("#statsProviderStatus", statsProvider.status === "on_demand" ? "On demand" : statsProvider.status);
  $("#statsProviderMeta").textContent = statsProvider.last_error ||
    (statsProvider.last_success_at ? "Last selected-match response " + ageLabel(statsProvider.last_success_at) :
      "Fetched only when requested for the selected match");
  renderEvents(state);
  renderUpcoming(state);
  $("#eventCount").textContent = String(activeFeed === "upcoming"
    ? (state.upcoming_matches || []).length : (state.events || []).length);
  renderMatch(state.selected_event);
  renderUpcomingMatch(state.selected_upcoming_event, state);
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
async function requestUpcomingDetails(eventId) {
  const response = await fetch("/api/upcoming/" + encodeURIComponent(eventId) + "/select", { method: "POST" });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.detail || "Upcoming match details could not be loaded (" + response.status + ")");
  }
  render(await response.json());
}
const delay = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));
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
  const tab = event.target.closest("[data-feed-tab]");
  if (tab) {
    activeFeed = tab.dataset.feedTab;
    document.querySelectorAll("[data-feed-tab]").forEach((button) => {
      const active = button === tab;
      button.classList.toggle("active", active);
      button.setAttribute("aria-selected", String(active));
    });
    $("#livePane").hidden = tab.dataset.feedTab !== "live";
    $("#upcomingPane").hidden = tab.dataset.feedTab !== "upcoming";
    $(".workspace").classList.toggle("upcoming-mode", activeFeed === "upcoming");
    $("#eventCount").textContent = String(activeFeed === "upcoming"
      ? ((latestState && latestState.upcoming_matches) || []).length
      : ((latestState && latestState.events) || []).length);
    return;
  }
  const watch = event.target.closest("[data-watch]");
  const unwatch = event.target.closest("[data-unwatch]");
  const viewUpcoming = event.target.closest("[data-select-upcoming]");
  if (viewUpcoming) {
    try {
      await requestUpcomingDetails(viewUpcoming.dataset.selectUpcoming);
    } catch (error) {
      $("#topNotice").textContent = error.message;
      $("#topNotice").hidden = false;
    }
    return;
  }
  if (watch || unwatch) {
    const id = (watch || unwatch).dataset[watch ? "watch" : "unwatch"];
    try {
      const response = await fetch("/api/watchlist/" + encodeURIComponent(id), { method: watch ? "POST" : "DELETE" });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || "Watchlist update failed (" + response.status + ")");
      }
      render(await response.json());
    } catch (error) {
      $("#topNotice").textContent = error.message;
      $("#topNotice").hidden = false;
    }
    return;
  }
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
  try {
    await requestMonitor(eventId);
  } catch (error) {
    $("#topNotice").textContent = error.message;
    $("#topNotice").hidden = false;
  } finally {
    statisticsRefreshPending = false;
    fetch("/api/state").then((response) => response.json()).then(render).catch(() => {});
  }
});
function connect() {
  const source = new EventSource("/api/events");
  source.addEventListener("open", () => {
    $("#connectionDot").className = "live-dot connected";
    $("#connectionLabel").textContent = "Screen connected · streaming updates";
  });
  source.addEventListener("message", (message) => {
    try { render(JSON.parse(message.data)); } catch { /* discard malformed update */ }
  });
  source.addEventListener("error", () => {
    $("#connectionDot").className = "live-dot offline";
    $("#connectionLabel").textContent = "Reconnecting";
  });
}
connect();
