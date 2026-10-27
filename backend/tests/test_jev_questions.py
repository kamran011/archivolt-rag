from app.domains.retrieval.decisions.jev_questions import JevAnswers, Verdict, decide


def test_decision_table_covers_every_band():
    assert decide(JevAnswers(0.9, 0.1)) is Verdict.sufficient
    assert decide(JevAnswers(0.9, 0.9)) is Verdict.sufficient  # conflicts handled downstream
    assert decide(JevAnswers(0.1, 0.1)) is Verdict.insufficient
    assert decide(JevAnswers(0.5, 0.0)) is Verdict.unsettled
    assert decide(JevAnswers(0.7, 0.0)) is Verdict.sufficient  # boundaries are inclusive
    assert decide(JevAnswers(0.3, 0.0)) is Verdict.insufficient
