from prometheus_observatory.analyzer import DeterministicAnalyzer


def test_negative_agreement_is_only_disagreement() -> None:
    analyzer = object.__new__(DeterministicAnalyzer)
    assert analyzer._dialogue_acts("Не согласен: нужен другой подход.") == ["DISAGREE"]


def test_positive_agreement_remains_detected() -> None:
    analyzer = object.__new__(DeterministicAnalyzer)
    assert analyzer._dialogue_acts("Согласна, это надёжнее.") == ["AGREE"]
