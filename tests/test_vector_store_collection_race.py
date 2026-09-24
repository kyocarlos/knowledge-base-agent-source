from types import SimpleNamespace

from src.vector_store import VectorStore


def test_collection_create_race_keeps_vector_store_available_when_collection_now_exists():
    store = object.__new__(VectorStore)

    class Client:
        def get_collections(self):
            return SimpleNamespace(collections=[])

        def create_collection(self, **_kwargs):
            raise RuntimeError("already exists")

        def collection_exists(self, name):
            return name == "knowledge_base"

    store.client = Client()
    store._ensure_collection()
