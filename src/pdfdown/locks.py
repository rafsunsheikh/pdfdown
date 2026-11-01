"""One lock for every pdfium call. pdfium is not thread-safe, even across documents.

Docling takes its own lock around pdfium; pdfdown shares that same lock, so the TUI can
render previews while Docling converts another PDF in a background thread.
"""

try:
    from docling.utils.locks import pypdfium2_lock as pdfium_lock
except ImportError:  # pragma: no cover
    import threading

    pdfium_lock = threading.Lock()
