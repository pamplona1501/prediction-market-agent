"""Alternative, engine-style live soccer view using sourced Jupiter data only."""

import os
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP

import streamlit as st
from dotenv import load_dotenv

from integrations.market_data.jupiter import (
    JupiterDataError,
    JupiterEvent,
    JupiterEventPage,
    JupiterLiveScore,
    JupiterMarket,
    JupiterPredictionClient,
)

load_dotenv()


st.set_page_config(
    page_title="Soccer Engine View",
    page_icon="⚡",
    layout="wide",
)

st.markdown(
    """
    <style>
    .engine-card {
        background: #101923;
        border: 1px solid #293847;
        border-radius: 12px;
        padding: 14px 16px;
        min-height: 72px;
    }
    .engine-label { color: #94a3b8; font-size: .78rem; text-transform: uppercase; letter-spacing: .06em; }
    .engine-value { color: #e2e8f0; font-size: 1.12rem; font-weight: 700; margin-top: 5px; }
    .gate-ready { color: #34d399; font-weight: 700; }
    .gate-missing { color: #fbbf24; font-weight: 700; }
    .gate-disabled { color: #94a3b8; font-weight: 700; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(ttl=20, show_spinner=False)
def fetch_live_soccer() -> tuple[JupiterEventPage, tuple[JupiterLiveScore, ...]]:
    client = JupiterPredictionClient.from_environment()
    events = client.list_sports_events(filter_name="live", limit=50, tag="soccer")
    scores = client.get_live_scores(tuple(item.event_id for item in events.events)) if events.events else ()
    return events, scores


@st.cache_data(ttl=30, show_spinner=False)
def fetch_event_markets(event_id: str) -> JupiterEvent:
    return JupiterPredictionClient.from_environment().get_sports_event_details(event_id)


def cents(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{format((value * Decimal('100')).normalize(), 'f')}¢"


def payout(value: Decimal | None) -> str:
    if value is None or value <= 0:
        return "—"
    amount = (Decimal("1") / value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"${amount:.2f}"


def usd(value: Decimal | None) -> str:
    return f"${value:,.0f}" if value is not None else "—"


def market_table(event: JupiterEvent, score: JupiterLiveScore | None) -> list[dict[str, str | None]]:
    moneyline = [m for m in event.markets if m.sports_market_type == "moneyline"]
    first_score = [m for m in event.markets if m.sports_market_type == "soccer_first_to_score"]
    both_score = [m for m in event.markets if m.sports_market_type == "both_teams_to_score"]
    prices = [m.buy_yes_usd for m in moneyline if m.buy_yes_usd is not None]
    favorite = max(prices) if prices else None
    long_shot = min(prices) if prices else None
    home = score.home_team.casefold() if score else ""
    away = score.away_team.casefold() if score else ""

    rows: list[tuple[str, JupiterMarket, str, str]] = []
    for market in moneyline:
        badge = ""
        if market.buy_yes_usd is not None and market.buy_yes_usd == favorite:
            badge = "FAVORITE · price-derived"
        elif market.buy_yes_usd is not None and market.buy_yes_usd == long_shot:
            badge = "LONG SHOT · price-derived"
        rows.append(("Moneyline", market, market.team_name or market.title, badge))

    def first_score_label(market: JupiterMarket) -> str:
        if market.title.casefold() == "neither":
            return "NEITHER"
        abbreviation = f"{market.team_abbreviation.upper()} · " if market.team_abbreviation else ""
        return f"{abbreviation}{market.team_name or market.title}"

    rows.extend(("First Team to Score", m, first_score_label(m), "") for m in first_score)
    rows.extend(("Both Teams to Score", m, "Yes / No", "") for m in both_score)

    groups = {"Moneyline": 0, "First Team to Score": 1, "Both Teams to Score": 2}

    def sort_key(row: tuple[str, JupiterMarket, str, str]) -> tuple[int, int]:
        group, market, _, _ = row
        name = (market.team_name or market.title).casefold()
        if group == "Moneyline":
            if name == home:
                return groups[group], 0
            if name == away:
                return groups[group], 1
            if market.title.casefold() == "draw":
                return groups[group], 2
        if group == "First Team to Score":
            if name == home:
                return groups[group], 0
            if market.title.casefold() == "neither":
                return groups[group], 1
            if name == away:
                return groups[group], 2
        return groups[group], 3

    rows.sort(key=sort_key)
    return [
        {
            "market": group,
            "team badge": market.team_image_url,
            "period": market.period_type or "Not supplied by API",
            "outcome": outcome,
            "tag": badge,
            "price": cents(market.buy_yes_usd),
            "YES": cents(market.buy_yes_usd),
            "YES pays per $1": payout(market.buy_yes_usd),
            "NO": cents(market.buy_no_usd),
            "NO pays per $1": payout(market.buy_no_usd),
            "volume": usd(market.volume_usd),
            "status": market.status or "—",
        }
        for group, market, outcome, badge in rows
    ]


def _now_utc() -> datetime:
    return datetime.now(UTC)


st.title("⚡ Live Soccer · Engine View")
st.caption("Alternative dashboard layout · Jupiter Prediction API · research mode · all trading disabled")

with st.sidebar:
    st.header("⚡ Data Controls")
    st.markdown("**Feed:** Jupiter Prediction API")
    st.markdown("**Sport:** Soccer · live")
    st.markdown(
        f"**API key:** {'Loaded locally' if (os.getenv('JUPITER_API_KEY') or '').strip() else 'Not loaded'}"
    )
    refresh = st.button("Refresh live feed", type="primary", width="stretch")
    st.divider()
    st.markdown("**Wallet:** Not connected")
    st.markdown("**Order execution:** Disabled")
    st.caption("This page sends read-only API requests. It has no RPC pool or wallet controls.")

event_count = len(st.session_state.engine_soccer_data[0].events) if st.session_state.get("engine_soccer_data") else "—"
score_count = len(st.session_state.engine_soccer_data[1]) if st.session_state.get("engine_soccer_data") else "—"
top1, top2, top3, top4, top5 = st.columns(5)
top1.metric("Feed state", "Configured" if (os.getenv("JUPITER_API_KEY") or "").strip() else "Key missing")
top2.metric("Live events", event_count)
top3.metric("Score rows", score_count)
top4.metric("Execution", "Disabled")
top5.metric("Paper strategy", "Not implemented")
st.caption("Scores are fetched from Jupiter on demand. No database write or background polling is performed.")
st.markdown("---")

if refresh:
    fetch_live_soccer.clear()
    try:
        with st.spinner("Refreshing live soccer events and scores…"):
            st.session_state.engine_soccer_data = fetch_live_soccer()
        event_page, score_rows = st.session_state.engine_soccer_data
        log = st.session_state.setdefault("engine_event_log", [])
        log.insert(0, f"{_now_utc():%H:%M:%S UTC} · Loaded {len(event_page.events)} events and {len(score_rows)} score rows from Jupiter.")
    except JupiterDataError as exc:
        st.session_state.engine_soccer_data = None
        log = st.session_state.setdefault("engine_event_log", [])
        log.insert(0, f"{_now_utc():%H:%M:%S UTC} · Jupiter read failed: {exc}")

data: tuple[JupiterEventPage, tuple[JupiterLiveScore, ...]] | None = st.session_state.get("engine_soccer_data")
main, side = st.columns([2.1, 1], gap="large")

with main:
    st.subheader("🏟️ In-Play Match Tracker")
    if not data:
        st.info("Use **Refresh live feed** to load current soccer events. No example fixtures are substituted.")
    else:
        event_page, scores = data
        score_by_id = {item.event_id: item for item in scores}
        if not event_page.events:
            st.info("Jupiter returned no live soccer events.")
        else:
            selected = st.selectbox(
                "Live match",
                event_page.events,
                format_func=lambda item: item.title,
                key="engine_selected_event",
            )
            score = score_by_id.get(selected.event_id)
            event_volume = usd(selected.reported_volume_usd)
            card1, card2, card3, card4 = st.columns(4)
            card1.metric("Match Time", f"{score.period or '—'} · {score.elapsed or '—'}'" if score else "Unavailable")
            card2.metric("Scoreline", score.score or "—" if score else "Unavailable")
            card3.metric("Status", score.status or "—" if score else "No score row")
            card4.metric("Event Volume", event_volume)
            st.caption(
                f"Source: Jupiter · event fetched {event_page.fetched_at:%Y-%m-%d %H:%M:%S UTC} · "
                f"score updated {score.updated_at if score and score.updated_at else 'timestamp unavailable'}"
            )

            if st.button("Load selected match markets"):
                fetch_event_markets.clear()
                try:
                    with st.spinner("Loading the selected event’s market details…"):
                        st.session_state.engine_market_detail = fetch_event_markets(selected.event_id)
                    log = st.session_state.setdefault("engine_event_log", [])
                    log.insert(0, f"{_now_utc():%H:%M:%S UTC} · Loaded {len(st.session_state.engine_market_detail.markets)} market records for selected event.")
                except JupiterDataError as exc:
                    st.session_state.engine_market_detail = None
                    log = st.session_state.setdefault("engine_event_log", [])
                    log.insert(0, f"{_now_utc():%H:%M:%S UTC} · Market detail request failed: {exc}")

            detail: JupiterEvent | None = st.session_state.get("engine_market_detail")
            if detail and detail.event_id == selected.event_id:
                st.markdown("#### Live Contract Pricing")
                table = market_table(detail, score)
                if table:
                    st.dataframe(
                        table,
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "team badge": st.column_config.ImageColumn("team badge", width="small"),
                        },
                    )
                    st.caption(
                        "$1 payout multiples are derived from current buy prices before fees. "
                        "Favorite/long-shot tags are price-derived; depth and the REG TIME label are not in this response."
                    )
                else:
                    st.info("No moneyline, first-team-to-score, or both-teams-to-score markets were returned.")

            st.markdown("#### Data Availability Checks")
            g1, g2, g3 = st.columns(3)
            g1.markdown(
                '<div class="engine-card"><span class="engine-label">Soccer event filter</span><br>'
                '<span class="gate-ready">PASS · tags=soccer</span></div>',
                unsafe_allow_html=True,
            )
            g2.markdown(
                '<div class="engine-card"><span class="engine-label">Live score</span><br>'
                f'<span class="{"gate-ready" if score else "gate-missing"}">'
                f'{"AVAILABLE" if score else "NO SCORE ROW"}</span></div>',
                unsafe_allow_html=True,
            )
            g3.markdown(
                '<div class="engine-card"><span class="engine-label">Bet/order execution</span><br>'
                '<span class="gate-disabled">DISABLED</span></div>',
                unsafe_allow_html=True,
            )

            st.subheader("Strategy Diagnostics")
            st.info(
                "Strategies and paper-order execution are not implemented in the current milestone. "
                "This page does not report PASS/FAIL trade gates or create signals."
            )

with side:
    st.subheader("📜 Live Data Log")
    logs: list[str] = st.session_state.get("engine_event_log", [])
    log_text = "\n".join(logs) if logs else "Waiting for a manual data refresh."
    st.text_area("Provider requests", value=log_text, height=300, disabled=True)
    st.subheader("System Boundaries")
    st.markdown(
        '<div class="engine-card"><span class="engine-label">Shots / possession / corners</span><br>'
        '<span class="gate-missing">NOT PROVIDED BY JUPITER SCORES</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="engine-card"><span class="engine-label">Order book depth</span><br>'
        '<span class="gate-missing">NOT LOADED</span></div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="engine-card"><span class="engine-label">Real-money execution</span><br>'
        '<span class="gate-disabled">DISABLED</span></div>',
        unsafe_allow_html=True,
    )
