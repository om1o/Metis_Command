"""
Memory Vault — ChromaDB long-term vector memory for the swarm.
Prevents re-discovery of the same leads across sessions.
"""

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
            print(f"[MemoryBank] Init error: {e}")
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
                metadatas=[{"entity_name": entity_name, "facts": facts, "cost": cost}],
            )
        except Exception as e:
            print(f"[MemoryBank] Store error for '{entity_name}': {e}")

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
            print(f"[MemoryBank] Recall error for '{entity_name}': {e}")
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
            print(f"[MemoryBank] Search error: {e}")
            return []
