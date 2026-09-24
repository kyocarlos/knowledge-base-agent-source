from src.ingest import ingest_vector


def test_ingest_vector_source_sidecar_published_state_is_not_downgraded(monkeypatch, tmp_path):
    document = tmp_path / "report.md"
    document.write_text("# report", encoding="utf-8")
    document.with_name("report.source.json").write_text(
        '{"document_id":"csit-1","document_version":"v1","publish_status":"published",'
        '"is_current":true,"run_id":"run-1","source_file_hash":"abc"}', encoding="utf-8"
    )
    captured = {}

    monkeypatch.setattr("src.chunker.chunk_document", lambda _: [{"content": "report body", "metadata": {}}])
    monkeypatch.setattr("src.knowledge_package.validate_package", lambda package: package)
    monkeypatch.setattr("src.knowledge_package.package_digest", lambda _: "digest")

    class Store:
        def add_documents(self, chunks, _doc_name):
            captured["metadata"] = chunks[0]["metadata"]
            return True

    monkeypatch.setattr("src.vector_store.get_vector_store", lambda: Store())
    assert ingest_vector(str(document), storage_category="Report") is True
    assert captured["metadata"]["publish_status"] == "published"
    assert captured["metadata"]["is_current"] is True
    assert captured["metadata"]["source_file_hash"] == "abc"
