from zipka.books.reader import (
    ARCHIVE_SUFFIXES,
    BOOK_SUFFIXES,
    CODE_SUFFIXES,
    READABLE_SUFFIXES,
    BookReader,
)

try:
    from zipka.books.rag import BookRagStore, book_id_for, rag_available
except ImportError:  # pragma: no cover
    BookRagStore = None  # type: ignore[misc, assignment]
    book_id_for = None  # type: ignore[misc, assignment]

    def rag_available() -> bool:
        return False

__all__ = [
    "BookReader",
    "BOOK_SUFFIXES",
    "CODE_SUFFIXES",
    "ARCHIVE_SUFFIXES",
    "READABLE_SUFFIXES",
    "BookRagStore",
    "book_id_for",
    "rag_available",
]
