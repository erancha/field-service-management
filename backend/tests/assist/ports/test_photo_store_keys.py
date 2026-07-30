import uuid

from fsm.assist.ports.photo_store import object_prefix, original_key, photo_keys, preview_key


def test_photo_keys_cover_exactly_the_original_and_the_preview() -> None:
    prefix = object_prefix(uuid.UUID("00000000-0000-0000-0000-000000000001"))

    assert prefix == "photos/00000000-0000-0000-0000-000000000001"
    assert photo_keys(prefix) == (original_key(prefix), preview_key(prefix))
    assert original_key(prefix) == f"{prefix}/original"
    assert preview_key(prefix) == f"{prefix}/preview"
