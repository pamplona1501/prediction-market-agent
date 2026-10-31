from strategies.rules import Match, Quotes, evaluate_candidates

def test_draw_candidate():
    match = Match(30, "FIRST_HALF", 0, 0, 1, 1, 48, 52, 0, 1)
    quotes = Quotes(0.70, 0.14, 0.20)
    signals = evaluate_candidates(match, quotes)
    assert any(s["strategy"] == "DRAW_COMPRESSION" for s in signals)

def test_no_new_entry_after_halftime():
    match = Match(46, "SECOND_HALF", 0, 0, 1, 1, 48, 52, 0, 1)
    quotes = Quotes(0.70, 0.14, 0.20)
    assert evaluate_candidates(match, quotes) == []
