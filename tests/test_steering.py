"""Tests for SteeringState."""
from yay.steering import SteeringState


class TestSteeringState:
    def test_init_empty(self):
        s = SteeringState()
        assert s.instructions == []

    def test_instructions_append(self):
        s = SteeringState()
        s.instructions.append("do this")
        assert s.instructions == ["do this"]
