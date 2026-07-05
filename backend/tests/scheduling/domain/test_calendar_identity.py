"""Tests for the calendar event identity scheme (iCalUID build/parse)."""
import uuid

from fsm.scheduling.domain import build_ical_uid, parse_ical_uid


class TestBuildIcalUid:
    def test_builds_fsm_scheme(self):
        appointment_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        assert (
            build_ical_uid(appointment_id)
            == "fsm-12345678-1234-5678-1234-567812345678@fsm.local"
        )


class TestParseIcalUid:
    def test_round_trips_built_uid(self):
        appointment_id = uuid.uuid4()
        assert parse_ical_uid(build_ical_uid(appointment_id)) == appointment_id

    def test_accepts_uppercase_hex(self):
        appointment_id = uuid.UUID("12345678-1234-5678-1234-567812345678")
        uid = "fsm-12345678-1234-5678-1234-567812345678@fsm.local".upper()
        assert parse_ical_uid(uid) == appointment_id

    def test_rejects_foreign_uid(self):
        assert parse_ical_uid("some-other-meeting@gmail.com") is None

    def test_rejects_non_uuid_payload(self):
        assert parse_ical_uid("fsm-not-a-uuid@fsm.local") is None

    def test_rejects_wrong_domain(self):
        appointment_id = uuid.uuid4()
        assert parse_ical_uid(f"fsm-{appointment_id}@other.local") is None
