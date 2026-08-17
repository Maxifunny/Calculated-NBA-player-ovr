from nba_ovr.names import best_name_match, normalize_name


def test_normalize_strips_accents_and_suffixes():
    assert normalize_name("Nikola Jokić") == "nikola jokic"
    assert normalize_name("Luka Dončić Jr.") == "luka doncic"
    assert normalize_name("P.J. Washington") == "pj washington"
    assert normalize_name("Karl-Anthony Towns") == "karl anthony towns"


def test_fuzzy_match_handles_spelling_variants():
    candidates = ["nikola jokic", "nikola vucevic", "bogdan bogdanovic"]
    match = best_name_match("nikola jokic", candidates)
    assert match is not None
    assert match[0] == "nikola jokic"


def test_fuzzy_match_rejects_unrelated_names():
    assert best_name_match("lebron james", ["stephen curry", "kevin durant"], score_cutoff=90) is None
