"""Response-header helpers shared by the routes that serve stored files."""
from __future__ import annotations

from urllib.parse import quote


def content_disposition(disposition: str, filename: str, *, fallback: str) -> str:
    """Build a Content-Disposition value from a user-supplied filename.

    Response headers are Latin-1 encoded by Starlette, so a filename with non-ASCII
    characters (Hebrew, CJK, emoji, ...) must never be interpolated as-is: doing so raises
    UnicodeEncodeError and turns the download into an unhandled 500. Per RFC 6266/5987, this
    emits both a plain-ASCII fallback filename for clients that only understand the legacy
    form, and a percent-encoded filename* for clients that render the real name.

    fallback names the file when the original has no ASCII characters to fall back on.
    """
    # Backslashes are stripped with the quotes and newlines: inside the quoted fallback a
    # backslash escapes the character after it, so a trailing one would swallow the closing quote.
    safe_name = (
        filename.replace('"', "").replace("\\", "").replace("\r", "").replace("\n", "")
    )
    # A name with no ASCII at all cannot have an ASCII extension either, so the fallback is fixed.
    ascii_name = safe_name.encode("ascii", errors="ignore").decode("ascii").strip() or fallback
    # RFC 5987's attr-char grammar admits no bare "/", which quote() would keep by default.
    encoded_name = quote(safe_name, safe="")
    return f'{disposition}; filename="{ascii_name}"; filename*=UTF-8\'\'{encoded_name}'
