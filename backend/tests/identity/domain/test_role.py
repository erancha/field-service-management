"""Tests for the Role enum."""
from fsm.identity.domain import Role


class TestRole:
    def test_has_customer_member(self):
        assert Role.CUSTOMER is not None

    def test_has_technician_member(self):
        assert Role.TECHNICIAN is not None

    def test_has_admin_member(self):
        assert Role.ADMIN is not None

    def test_has_exactly_three_members(self):
        assert set(Role) == {Role.CUSTOMER, Role.TECHNICIAN, Role.ADMIN}
