"""The in-memory fakes structurally satisfy the assist port Protocols."""
from tests.assist.fakes import FakeDocumentIndex, FakeKbDocumentRepository, FakeTextExtractor

from fsm.assist.ports.document_index import DocumentIndex
from fsm.assist.ports.document_repository import KbDocumentRepository
from fsm.assist.ports.text_extractor import TextExtractor


def test_fakes_satisfy_the_ports():
    assert isinstance(FakeKbDocumentRepository(), KbDocumentRepository)
    assert isinstance(FakeDocumentIndex(), DocumentIndex)
    assert isinstance(FakeTextExtractor(), TextExtractor)
