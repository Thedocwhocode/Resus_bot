from resusbot.cache.query_cache import hash_query, normalize_query


def test_normalize_query_lowercases():
    assert normalize_query("ROX Index Sepse") == "rox index sepse"


def test_normalize_query_strips_accents():
    assert normalize_query("Ressuscitação") == "ressuscitacao"


def test_normalize_query_collapses_spaces():
    assert normalize_query("  early  goal   directed  ") == "early goal directed"


def test_hash_query_deterministic():
    h1 = hash_query("rox index sepse")
    h2 = hash_query("rox index sepse")
    assert h1 == h2
    assert len(h1) == 64


def test_hash_query_different_inputs():
    assert hash_query("rox index") != hash_query("sofa score")
