"""Read-only health dashboard for the research and paper-trading prototype."""

import streamlit as st

from database.connection import check_database, database_configuration


st.set_page_config(page_title="Prediction Market Agent", page_icon="📊", layout="wide")
st.title("Prediction Market Agent")
st.caption("Research and paper trading only. Live trading is disabled.")

configured, database_kind = database_configuration()
connected, detail = check_database()

left, middle, right = st.columns(3)
left.metric("Mode", "Paper only")
middle.metric("Database configuration", database_kind)
right.metric("Database health", "Connected" if connected else "Unavailable")

if connected:
    st.success(detail)
else:
    st.warning(detail)

st.subheader("Application status")
st.write("Market and sports data integrations are not configured. No live observations are shown.")
st.write("The initial schema stores market/event reference data and timestamped snapshots. It does not place orders.")
st.info("No wallet, signing key, transaction submission, or real-money execution is present.")

with st.expander("Local setup status"):
    st.write("Set DATABASE_URL in a local .env file to enable the Neon health check.")
    st.write("Apply the schema with `alembic upgrade head` after configuring the database.")
