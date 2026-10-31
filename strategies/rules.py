from dataclasses import dataclass
from typing import Literal

Outcome = Literal["HOME", "DRAW", "AWAY"]

@dataclass
class Match:
    minute: int
    status: str
    home_score: int
    away_score: int
    home_shots: int
    away_shots: int
    home_possession: float
    away_possession: float
    home_corners: int
    away_corners: int

@dataclass
class Quotes:
    home_ask: float
    draw_ask: float
    away_ask: float

def evaluate_candidates(match: Match, quotes: Quotes) -> list[dict]:
    """Pure rule evaluation. Candidate signals only; never submits orders."""
    if match.status != "FIRST_HALF" or not (0 <= match.minute <= 45):
        return []

    signals = []
    home_trailing = match.home_score < match.away_score
    away_trailing = match.away_score < match.home_score

    if home_trailing and quotes.home_ask <= 0.25 and (
        match.home_shots >= 4 or match.home_possession >= 50 or match.home_corners >= 3
    ):
        signals.append({"strategy": "UNDERDOG_SCOUTER", "outcome": "HOME", "ask": quotes.home_ask})

    if away_trailing and quotes.away_ask <= 0.25 and (
        match.away_shots >= 4 or match.away_possession >= 50 or match.away_corners >= 3
    ):
        signals.append({"strategy": "UNDERDOG_SCOUTER", "outcome": "AWAY", "ask": quotes.away_ask})

    if (
        25 <= match.minute <= 40 and match.home_score == 0 and match.away_score == 0
        and match.home_shots + match.away_shots <= 3 and quotes.draw_ask <= 0.15
    ):
        signals.append({"strategy": "DRAW_COMPRESSION", "outcome": "DRAW", "ask": quotes.draw_ask})

    return signals
