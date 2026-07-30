"""Session-scoped SQLAlchemy adapter for triage conversation persistence."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from fsm.assist.adapters.orm import AssistConversationRow, AssistMessageRow, AssistPhotoRow
from fsm.assist.adapters.photo_repository import _to_photo
from fsm.assist.domain.conversation import (
    OPENING_LINE_CHARS,
    Conversation,
    ConversationStatus,
    ConversationSummary,
    Message,
    MessageRole,
    Photo,
)
from fsm.assist.domain.errors import ConversationAlreadyOpen, ConversationNotFound

_ONE_ACTIVE_INDEX = "uq_assist_conversation_one_active_per_customer"


def _translate_integrity_error(exc: IntegrityError, customer_id: uuid.UUID) -> None:
    """Re-raise exc as ConversationAlreadyOpen when the one-active-per-customer index fired.

    Reads the psycopg diagnostic constraint name first, falling back to a substring check on the
    stringified driver error. Any other IntegrityError propagates unchanged.
    """
    constraint = getattr(getattr(exc.orig, "diag", None), "constraint_name", None)
    if constraint is None:
        constraint = _ONE_ACTIVE_INDEX if _ONE_ACTIVE_INDEX in str(exc.orig) else None
    if constraint == _ONE_ACTIVE_INDEX:
        raise ConversationAlreadyOpen(str(customer_id)) from exc
    raise exc


class SqlAlchemyConversationRepository:
    """Caller owns the transaction; this adapter only stages rows on the session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, conversation: Conversation) -> None:
        """Insert a conversation and its messages, flushing so a lost start race surfaces here.

        The insert runs inside a savepoint: a bare failed flush leaves the surrounding transaction
        aborted, and a caller recovering from ConversationAlreadyOpen has to be able to read the
        conversation that won.
        """
        try:
            with self._session.begin_nested():
                self._session.add(
                    AssistConversationRow(
                        id=conversation.id,
                        customer_id=conversation.customer_id,
                        status=conversation.status.value,
                        service_call_id=conversation.service_call_id,
                        created_at=conversation.created_at,
                        updated_at=conversation.updated_at,
                    )
                )
                self._append_messages(conversation, from_seq=0)
                self._session.flush()
        except IntegrityError as exc:
            _translate_integrity_error(exc, conversation.customer_id)

    def get(self, conversation_id: uuid.UUID, customer_id: uuid.UUID) -> Conversation:
        row = self._session.get(AssistConversationRow, conversation_id)
        if row is None or row.customer_id != customer_id:
            raise ConversationNotFound(str(conversation_id))
        return self._to_conversation(row)

    def save(self, conversation: Conversation) -> None:
        row = self._session.get(AssistConversationRow, conversation.id)
        if row is None:
            raise ConversationNotFound(str(conversation.id))
        row.status = conversation.status.value
        row.service_call_id = conversation.service_call_id
        row.updated_at = conversation.updated_at
        self._append_messages(conversation, from_seq=self._stored_message_count(conversation.id))

    def find_active_for_customer(self, customer_id: uuid.UUID) -> Conversation | None:
        stmt = select(AssistConversationRow).where(
            AssistConversationRow.customer_id == customer_id,
            AssistConversationRow.status == ConversationStatus.ACTIVE.value,
        )
        row = self._session.execute(stmt).scalars().first()
        return None if row is None else self._to_conversation(row)

    def list_ended(self, customer_id: uuid.UUID, limit: int) -> list[ConversationSummary]:
        """A conversation nobody typed into has no opening line; those rows are dropped in SQL,
        so the limit counts rows the caller will actually show."""
        opening_line = (
            select(func.left(AssistMessageRow.text, OPENING_LINE_CHARS))
            .where(
                AssistMessageRow.conversation_id == AssistConversationRow.id,
                AssistMessageRow.role == MessageRole.CUSTOMER.value,
            )
            .order_by(AssistMessageRow.seq)
            .limit(1)
            .scalar_subquery()
        )
        ended = (
            select(
                AssistConversationRow.id.label("id"),
                AssistConversationRow.status.label("status"),
                AssistConversationRow.updated_at.label("updated_at"),
                opening_line.label("opening_line"),
            )
            .where(
                AssistConversationRow.customer_id == customer_id,
                AssistConversationRow.status != ConversationStatus.ACTIVE.value,
            )
            .subquery()
        )
        stmt = (
            select(ended)
            .where(ended.c.opening_line.is_not(None))
            .order_by(ended.c.updated_at.desc())
            .limit(limit)
        )
        return [
            ConversationSummary(
                id=row.id,
                status=ConversationStatus(row.status),
                updated_at=row.updated_at,
                opening_line=row.opening_line,
            )
            for row in self._session.execute(stmt).all()
        ]

    def _append_messages(self, conversation: Conversation, from_seq: int) -> None:
        for seq, message in enumerate(conversation.messages[from_seq:], start=from_seq):
            self._session.add(
                AssistMessageRow(
                    id=message.id,
                    conversation_id=conversation.id,
                    seq=seq,
                    role=message.role.value,
                    text=message.text,
                    created_at=message.created_at,
                )
            )

    def _stored_message_count(self, conversation_id: uuid.UUID) -> int:
        self._session.flush()
        stmt = (
            select(func.count())
            .select_from(AssistMessageRow)
            .where(AssistMessageRow.conversation_id == conversation_id)
        )
        return self._session.execute(stmt).scalar_one()

    def _to_conversation(self, row: AssistConversationRow) -> Conversation:
        stmt = (
            select(AssistMessageRow)
            .where(AssistMessageRow.conversation_id == row.id)
            .order_by(AssistMessageRow.seq)
        )
        photo_stmt = (
            select(AssistPhotoRow)
            .where(
                AssistPhotoRow.conversation_id == row.id,
                AssistPhotoRow.message_id.is_not(None),
            )
            .order_by(AssistPhotoRow.created_at, AssistPhotoRow.id)
        )
        # Key: message id. Value: that message's photos in upload order.
        photos_by_message: dict[uuid.UUID, list[Photo]] = {}
        for photo_row in self._session.execute(photo_stmt).scalars():
            # photo_stmt's WHERE clause guarantees message_id is set for every row here.
            assert photo_row.message_id is not None
            photos_by_message.setdefault(photo_row.message_id, []).append(_to_photo(photo_row))
        messages = [
            Message(
                id=m.id,
                role=MessageRole(m.role),
                text=m.text,
                created_at=m.created_at,
                photos=tuple(photos_by_message.get(m.id, ())),
            )
            for m in self._session.execute(stmt).scalars().all()
        ]
        return Conversation(
            id=row.id,
            customer_id=row.customer_id,
            status=ConversationStatus(row.status),
            created_at=row.created_at,
            updated_at=row.updated_at,
            messages=messages,
            service_call_id=row.service_call_id,
        )
