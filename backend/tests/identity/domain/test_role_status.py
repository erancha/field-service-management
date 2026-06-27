"""Tests for the RoleStatus enum."""
from fsm.identity.domain import RoleStatus


class TestRoleStatus:
    def test_has_pending_member(self):
        assert RoleStatus.PENDING is not None

    def test_has_approved_member(self):
        assert RoleStatus.APPROVED is not None

    def test_has_rejected_member(self):
        assert RoleStatus.REJECTED is not None

    def test_has_exactly_three_members(self):
        assert set(RoleStatus) == {
            RoleStatus.PENDING,
            RoleStatus.APPROVED,
            RoleStatus.REJECTED,
        }

    def test_value_round_trips_from_string(self):
        assert RoleStatus("PENDING") is RoleStatus.PENDING
