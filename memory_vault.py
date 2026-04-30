"""
Memory Vault — ChromaDB long-term vector memory for the swarm.
Prevents re-discovery of the same leads across sessions.
"""

import time
import chromadb


class MemoryBank:
    def __init__(self, path: str | None = None):
        # Default to PATHS.metis_db so the sandbox fixture can redirect this
        # per-test; callers can still pass an explicit path if they want.
        if path is None:
            try:
                from safety import PATHS
                path = str(PATHS.metis_db)
            except Exception:
                path = "./metis_db"
        try:
            self.client = chromadb.PersistentClient(path=path)
            self.collection = self.client.get_or_create_collection("metis_memory")
        except Exception as e:
            try:
                from safety import log as _safety_log
                _safety_log("memvault_init_failed", error=str(e))
            except Exception:
                pass
            self.client = None
            self.collection = None

    def store_interaction(self, entity_name: str, facts: str, cost: float = 0.0) -> None:
        """Upsert a single entity/lead into the memory collection."""
        if not self.collection:
            return
        try:
            self.collection.upsert(
                ids=[entity_name],
                documents=[f"Facts: {facts}\nCost: {cost}"],
                metadatas=[{
                    "entity_name": entity_name,
                    "facts": facts,
                    "cost": cost,
                    "stored_at_ms": int(time.time() * 1000),
                }],
            )
        except Exception as e:
            try:
                from safety import log as _safety_log
                _safety_log("memvault_store_failed", entity=entity_name, error=str(e))
            except Exception:
                pass

    def recall_entity(self, entity_name: str) -> dict | None:
        """Return a stored entity by name, or None if not found."""
        if not self.collection:
            return None
        try:
            results = self.collection.get(ids=[entity_name])
            if results and entity_name in (results.get("ids") or []):
                idx = results["ids"].index(entity_name)
                return {
                    "entity_name": results["ids"][idx],
                    "facts": results["metadatas"][idx].get("facts"),
                    "cost": results["metadatas"][idx].get("cost"),
                    "document": results["documents"][idx],
                }
            return None
        except Exception as e:
            try:
                from safety import log as _safety_log
                _safety_log("memvault_recall_failed", entity=entity_name, error=str(e))
            except Exception:
                pass
            return None

    def search(self, query: str, n_results: int = 5) -> list[dict]:
        """Semantic search over stored memory."""
        if not self.collection:
            return []
        try:
            response = self.collection.query(query_texts=[query], n_results=n_results)
            hits = []
            for i, doc in enumerate(response.get("documents", [[]])[0]):
                hits.append({
                    "document": doc,
                    "metadata": response["metadatas"][0][i] if response.get("metadatas") else {},
                })
            return hits
        except Exception as e:
            try:
                from safety import log as _safety_log
                _safety_log("memvault_search_failed", error=str(e))
            except Exception:
                pass
            return []

    def compact_older_than(self, days: int) -> dict:
        """
        Drop vectors older than `days` from the collection.

        Returns a dict with `before`, `after`, `dropped` counts. We rely on
        the `stored_at_ms` metadata stamped by store_interaction; entries
        without that field are kept (legacy data, no way to know their age).
        """
        if not self.collection or days <= 0:
            return {"before": 0, "after": 0, "dropped": 0}
        try:
            # Pull the whole collection. Chroma keeps this cheap for typical sizes.
            res = self.collection.get(include=["metadatas"])
            ids = list(res.get("ids") or [])
            metas = list(res.get("metadatas") or [])
            cutoff_ms = int((time.time() - days * 86400) * 1000)
            doomed: list[str] = []
            for i, m in zip(ids, metas):
                ts = (m or {}).get("stored_at_ms") if isinstance(m, dict) else None
                if isinstance(ts, (int, float)) and ts < cutoff_ms:
                    doomed.append(i)
            if doomed:
                self.collection.delete(ids=doomed)
            return {
                "before": len(ids),
                "after": len(ids) - len(doomed),
                "dropped": len(doomed),
            }
        except Exception as e:
            try:
                from safety import log as _safety_log
                _safety_log("memvault_compact_failed", error=str(e))
            except Exception:
                pass
            return {"before": 0, "after": 0, "dropped": 0, "error": str(e)}
