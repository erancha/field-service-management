"""Tests for the User entity."""
import uuid
import pytest

from fsm.identity.domain import User, Role, InvalidUser


def _new_user(**kwargs) -> User:
    defaults = dict(
        id=uuid.uuid4(),
        google_sub="google-sub-1234567890",
        email="alice@example.com",
        name="Alice",
        role=Role.CUSTOMER,
    )
    defaults.update(kwargs)
    return User(**defaults)


class TestUserCreation:
    def test_creates_valid_user(self):
        user = _new_user()
        assert user.email == "alice@example.com"
        assert user.role == Role.CUSTOMER

    def test_fields_accessible(self):
        uid = uuid.uuid4()
        user = _new_user(id=uid, name="Bob")
        assert user.id == uid
        assert user.name == "Bob"

    def test_empty_google_sub_raises(self):
        with pytest.raises(InvalidUser):
            _new_user(google_sub="")

    def test_empty_email_raises(self):
        with pytest.raises(InvalidUser):
            _new_user(email="")


class TestUserAssignRole:
    def test_customer_promoted_to_technician(self):
        user = _new_user(role=Role.CUSTOMER)
        user.assign_role(Role.TECHNICIAN)
        assert user.role == Role.TECHNICIAN

    def test_assign_same_role_is_idempotent(self):
        user = _new_user(role=Role.CUSTOMER)
        user.assign_role(Role.CUSTOMER)
        assert user.role == Role.CUSTOMER

    def test_technician_can_be_set_back_to_customer(self):
        user = _new_user(role=Role.TECHNICIAN)
        user.assign_role(Role.CUSTOMER)
        assert user.role == Role.CUSTOMER
