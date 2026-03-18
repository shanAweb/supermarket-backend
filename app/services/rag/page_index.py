"""PageIndex — lightweight JSON-file-based document store indexed by session ID.

Stores session documents as structured text on disk. Retrieval is done by
direct session_id/store_id lookup rather than vector similarity search.
"""

import json
import logging
import os
import uuid
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

# Directory where page index files are stored
INDEX_DIR = os.path.join(settings.CHROMA_PERSIST_DIR, "page_index")


class PageIndex:
    """Simple file-based document index keyed by session ID."""

    def __init__(self, index_dir: str = INDEX_DIR):
        self.index_dir = index_dir
        os.makedirs(self.index_dir, exist_ok=True)

    def _session_path(self, session_id: uuid.UUID) -> str:
        return os.path.join(self.index_dir, f"{session_id}.json")

    def store(self, session_id: uuid.UUID, document: dict[str, Any]) -> None:
        """Store a session document to disk."""
        path = self._session_path(session_id)
        with open(path, "w") as f:
            json.dump(document, f, indent=2, default=str)
        logger.info("PageIndex: stored document for session %s", session_id)

    def load(self, session_id: uuid.UUID) -> dict[str, Any] | None:
        """Load a session document from disk. Returns None if not found."""
        path = self._session_path(session_id)
        if not os.path.exists(path):
            return None
        with open(path) as f:
            return json.load(f)

    def delete(self, session_id: uuid.UUID) -> None:
        """Remove a session document from the index."""
        path = self._session_path(session_id)
        if os.path.exists(path):
            os.remove(path)
            logger.info("PageIndex: deleted document for session %s", session_id)

    def load_many(
        self,
        session_ids: list[uuid.UUID] | None = None,
        store_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Load multiple session documents, optionally filtered by session_ids or store_id."""
        docs: list[dict[str, Any]] = []

        if session_ids:
            # Direct lookup by known IDs
            for sid in session_ids:
                doc = self.load(sid)
                if doc:
                    if store_id and doc.get("metadata", {}).get("store_id") != store_id:
                        continue
                    docs.append(doc)
        else:
            # Scan all indexed documents
            for filename in os.listdir(self.index_dir):
                if not filename.endswith(".json"):
                    continue
                filepath = os.path.join(self.index_dir, filename)
                with open(filepath) as f:
                    doc = json.load(f)
                if store_id and doc.get("metadata", {}).get("store_id") != store_id:
                    continue
                docs.append(doc)

        return docs

    def build_context(
        self,
        session_ids: list[uuid.UUID] | None = None,
        store_id: str | None = None,
        max_docs: int | None = None,
    ) -> str:
        """Build a combined text context from matching documents for LLM input."""
        docs = self.load_many(session_ids=session_ids, store_id=store_id)

        if max_docs:
            docs = docs[:max_docs]

        if not docs:
            return "No session data available for the given filters."

        sections: list[str] = []
        for doc in docs:
            sections.append(doc.get("text", ""))

        return "\n\n---\n\n".join(sections)


# Module-level singleton
page_index = PageIndex()
