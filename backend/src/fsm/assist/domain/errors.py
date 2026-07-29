"""Domain errors for the assist context."""


class AssistError(Exception):
    """Base class for assist domain errors."""


class UnsupportedDocumentType(AssistError):
    """The uploaded file is not one of the supported document types (pdf, md, txt)."""


class EmptyDocumentText(AssistError):
    """Text extraction produced no content, so the document cannot be indexed."""


class DocumentNotFound(AssistError):
    """No knowledge-base document exists with the given id."""


class IndexModelMismatch(AssistError):
    """The index was built with a different embedding model than the configured one."""
