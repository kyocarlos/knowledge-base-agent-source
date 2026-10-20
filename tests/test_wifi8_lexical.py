

def test_query_expansion_adds_english_terms_for_chinese_phrasing(tmp_path, monkeypatch):
    from src.wifi8.lexical import expanded_terms, query_vector, term_index
    assert {"mandatory", "required"} <= set(expanded_terms("Security Profile 從哪一次 Plugfest 開始變成強制？"))
    assert expanded_terms("什麼是 OFDMA") == []
    indices, _ = query_vector("Security Profile 強制")
    assert term_index("mandatory") in indices


def test_query_expansion_file_is_configurable_and_failure_safe(tmp_path, monkeypatch):
    from src.wifi8.lexical import EXPANSIONS_FILE_ENV, expanded_terms
    rules = tmp_path / "rules.json"
    rules.write_text('{"expansions": [{"when": ["Foo"], "add": ["bar baz"]}]}', encoding="utf-8")
    monkeypatch.setenv(EXPANSIONS_FILE_ENV, str(rules))
    assert expanded_terms("a foo b") == ["bar", "baz"]
    assert expanded_terms("food") == []  # Latin triggers match whole words only
    rules.write_text("not json", encoding="utf-8")
    assert expanded_terms("foo") == []  # a broken file never breaks search
    monkeypatch.setenv(EXPANSIONS_FILE_ENV, str(tmp_path / "missing.json"))
    assert expanded_terms("強制") == []
