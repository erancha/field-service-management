"""Contact details an appointment depends on, resolved per party without an identity import.

The scheduling layer stays identity-free: a resolver injected at the composition root maps a
user id to this value object, so booking can enforce the presence of contact data (customer
address and phone, technician phone) without importing the identity context.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContactInfo:
    """A party's service-relevant contact fields; both optional and treated as absent when blank."""

    address: str | None = None
    phone: str | None = None

    def has_address(self) -> bool:
        return bool((self.address or "").strip())

    def has_phone(self) -> bool:
        return bool((self.phone or "").strip())
