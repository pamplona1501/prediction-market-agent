"""Read-only live soccer dashboard backed by Jupiter's documented data API."""

import os
from decimal import Decimal, ROUND_HALF_UP

import streamlit as st

from database.connection import check_database
from integrations.market_data.capture import capture_selected_event
from integrations.market_data.jupiter import (
    JupiterDataError,
    JupiterEvent,
    JupiterEventPage,
    JupiterLiveScore,
    JupiterMarket,
    JupiterPredictionClient,
)


st.set_page_config(page_title="Live Soccer Scores", page_icon="⚽", layout="wide")
st.title("Live soccer scores")
st.caption("Jupiter Prediction API · soccer scores and selected-match markets · read-only")


@st.cache_data(ttl=20, show_spinner=False)
def fetch_live_soccer() -> tuple[JupiterEventPage, tuple[JupiterLiveScore, ...]]:
    client = JupiterPredictionClient.from_environment()
    events = client.list_sports_events(filter_name="live", limit=50, tag="soccer")
    if not events.events:
        return events, ()
    scores = client.get_live_scores(tuple(event.event_id for event in events.events))
    return events, scores


def _capture_market_selection() -> None:
    event_id = st.session_state.get("soccer_market_event_id")
    data = st.session_state.get("soccer_data")
    if not event_id or not data:
        return
    event_page, scores = data
    score = next((item for item in scores if item.event_id == event_id), None)
    try:
        result = capture_selected_event(event_id, score=score)
        st.session_state.soccer_market_detail = result.event
        st.session_state.soccer_capture_status = (
            f"Recorded {result.snapshots_written} YES/NO market observations." if result.persisted
            else "Markets loaded, but snapshots were not saved. Check database configuration/schema."
        )
    except JupiterDataError as exc:
        st.session_state.soccer_market_detail = None
        st.session_state.soccer_capture_status = f"Market detail request failed: {exc}"


def _price_cents(value: Decimal | None) -> str:
    if value is None:
        return "—"
    cents = (value * Decimal("100")).normalize()
    return f"{format(cents, 'f')}¢"


def _payout(value: Decimal | None) -> str:
    if value is None or value <= 0:
        return "—"
    amount = (Decimal("1") / value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return f"${amount:.2f}"


def _volume(value: Decimal | None) -> str:
    return f"${value:,.0f}" if value is not None else "—"


connected, database_detail = check_database()
left, middle, right = st.columns(3)
left.metric("Sport filter", "Soccer")
middle.metric("Database", "Connected" if connected else "Unavailable")
right.metric("Trading", "Disabled")
st.caption(database_detail if connected else "Database status unavailable; check local configuration.")

st.subheader("Matches in progress")
st.caption("Uses Jupiter’s documented `tags=soccer` and `filter=live` event filters, then fetches score rows for those events.")

if not (os.getenv("JUPITER_API_KEY") or "").strip():
    st.info("JUPITER_API_KEY is not loaded from the local .env file. Restart Streamlit after adding the key.")

if st.button("Refresh live soccer scores", type="primary"):
    fetch_live_soccer.clear()
    try:
        with st.spinner("Fetching live soccer events and scores…"):
            st.session_state.soccer_data = fetch_live_soccer()
    except JupiterDataError as exc:
        st.session_state.soccer_data = None
        st.error(str(exc))

data: tuple[JupiterEventPage, tuple[JupiterLiveScore, ...]] | None = st.session_state.get("soccer_data")
if data:
    event_page, score_rows = data
    st.caption(f"Events fetched {event_page.fetched_at:%Y-%m-%d %H:%M:%S UTC} · displayed scores are from Jupiter.")
    if not event_page.events:
        st.info("Jupiter returned no live soccer events at this time. No sample fixtures are shown.")
    else:
        score_by_event = {score.event_id: score for score in score_rows}
        rows = []
        for event in event_page.events:
            score = score_by_event.get(event.event_id)
            rows.append(
                {
                    "match": f"{score.home_team} vs {score.away_team}" if score else event.title,
                    "score": score.score if score and score.score else "—",
                    "status": score.status if score and score.status else "No score row",
                    "period": score.period if score and score.period else "—",
                    "minute": score.elapsed if score and score.elapsed else "—",
                "league": (score.league_abbreviation if score else None) or event.subcategory or "—",
                "score updated": score.updated_at if score and score.updated_at else "—",
                }
            )
        st.dataframe(rows, width="stretch", hide_index=True)
        st.caption(f"{len(event_page.events)} live-tagged soccer events · {len(score_rows)} score rows")

        selected_event_id = st.selectbox(
            "Match market details",
            [event.event_id for event in event_page.events],
            format_func=lambda event_id: next(
                (event.title for event in event_page.events if event.event_id == event_id), str(event_id)
            ),
            on_change=_capture_market_selection,
            key="soccer_market_event_id",
        )
        selected_event = next(event for event in event_page.events if event.event_id == selected_event_id)
        if st.button("Refresh markets & record snapshot"):
            with st.spinner("Loading selected match markets and recording observations…"):
                _capture_market_selection()
        if st.session_state.get("soccer_capture_status"):
            st.caption(st.session_state.soccer_capture_status)

        market_event: JupiterEvent | None = st.session_state.get("soccer_market_detail")
        if market_event and market_event.event_id == selected_event.event_id:
            moneyline = [m for m in market_event.markets if m.sports_market_type == "moneyline"]
            first_score = [m for m in market_event.markets if m.sports_market_type == "soccer_first_to_score"]
            both_score = [m for m in market_event.markets if m.sports_market_type == "both_teams_to_score"]
            yes_prices = [m.buy_yes_usd for m in moneyline if m.buy_yes_usd is not None]
            favorite = max(yes_prices) if yes_prices else None
            long_shot = min(yes_prices) if yes_prices else None
            score = score_by_event.get(selected_event.event_id)
            home_team = score.home_team.casefold() if score else ""
            away_team = score.away_team.casefold() if score else ""

            market_rows: list[tuple[str, JupiterMarket, str, str]] = []
            for market in moneyline:
                tag = ""
                if market.buy_yes_usd is not None and favorite is not None and market.buy_yes_usd == favorite:
                    tag = "FAVORITE (price-derived)"
                elif market.buy_yes_usd is not None and long_shot is not None and market.buy_yes_usd == long_shot:
                    tag = "LONG SHOT (price-derived)"
                market_rows.append(("Moneyline", market, market.team_name or market.title, tag))

            def goal_outcome(market: JupiterMarket) -> str:
                if market.title.casefold() == "neither":
                    return "NEITHER"
                prefix = f"{market.team_abbreviation.upper()} — " if market.team_abbreviation else ""
                return f"{prefix}{market.team_name or market.title}"

            market_rows.extend(
                ("First Team to Score", market, goal_outcome(market), "")
                for market in first_score
            )
            market_rows.extend(
                ("Both Teams to Score", market, "Yes / No", "")
                for market in both_score
            )
            group_order = {"Moneyline": 0, "First Team to Score": 1, "Both Teams to Score": 2}

            def outcome_order(row: tuple[str, JupiterMarket, str, str]) -> tuple[int, int]:
                group, market, _, _ = row
                team_name = (market.team_name or market.title).casefold()
                if group == "Moneyline":
                    if team_name == home_team:
                        return group_order[group], 0
                    if team_name == away_team:
                        return group_order[group], 1
                    if market.title.casefold() == "draw":
                        return group_order[group], 2
                if group == "First Team to Score":
                    if team_name == home_team:
                        return group_order[group], 0
                    if market.title.casefold() == "neither":
                        return group_order[group], 1
                    if team_name == away_team:
                        return group_order[group], 2
                return group_order[group], 3

            market_rows.sort(
                key=outcome_order
            )
            if market_rows:
                table_rows = [
                    {
                        "market": group,
                        "team badge": market.team_image_url,
                        "period": market.period_type or "Not supplied by API",
                        "outcome": outcome,
                        "label": tag,
                        "price": _price_cents(market.buy_yes_usd),
                        "YES": _price_cents(market.buy_yes_usd),
                        "$1 YES pays": _payout(market.buy_yes_usd),
                        "NO": _price_cents(market.buy_no_usd),
                        "$1 NO pays": _payout(market.buy_no_usd),
                        "volume": _volume(market.volume_usd),
                        "status": market.status or "—",
                    }
                    for group, market, outcome, tag in market_rows
                ]
                st.subheader(f"{selected_event.title} — markets")
                st.dataframe(
                    table_rows,
                    width="stretch",
                    hide_index=True,
                    column_config={
                        "team badge": st.column_config.ImageColumn("team badge", width="small"),
                    },
                )
                st.caption(
                    "Payout multiples are calculated as $1 divided by the current buy price, before fees. "
                    "Favorite/long-shot labels are derived from listed moneyline YES prices. "
                    "Jupiter does not supply the REG TIME label shown in the example."
                )
            else:
                st.info("No moneyline, first-to-score, or both-teams-to-score markets were returned for this event.")

st.divider()
st.subheader("Match statistics")
st.info(
    "Jupiter’s documented score feed provides teams, score, period, elapsed time, status, and update time. "
    "It does not provide shots, possession, or corners. Those fields need a separate licensed sports-data provider such as API-Football."
)
st.caption(
    "This dashboard reads data only. It does not infer missing statistics, create signals, place bets, "
    "or submit transactions."
)
