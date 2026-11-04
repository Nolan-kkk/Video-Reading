import pytest
from pydantic import ValidationError

from videomind.models.schemas import Evidence


def test_evidence_preserves_provenance_and_uncertainty():
    evidence = Evidence(
        start_seconds=3.5,
        end_seconds=4.0,
        source="vision",
        text="partial code",
        uncertainty="last line is unreadable",
    )
    record = evidence.model_dump(mode="json")
    assert record["start_seconds"] == 3.5
    assert record["source"] == "vision"
    assert record["uncertainty"] == "last line is unreadable"


@pytest.mark.parametrize("start,end", [(-1, 1), (2, 1), (0, float("inf"))])
def test_invalid_timestamps_rejected(start, end):
    with pytest.raises(ValidationError):
        Evidence(start_seconds=start, end_seconds=end, source="subtitle", text="sample")
