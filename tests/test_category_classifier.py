from resusbot.services.category_classifier import classify_article


def test_classify_resuscitation():
    data = {
        "title": "Post-cardiac arrest targeted temperature management",
        "journal": "Resuscitation",
    }
    assert classify_article(data) == 1  # resuscitation


def test_classify_sepsis():
    data = {
        "title": "ROX index to predict failure of high-flow nasal cannula in septic patients",
        "journal": "AJRCCM",
    }
    assert classify_article(data) == 2  # sepsis


def test_classify_airway():
    data = {
        "title": "Video laryngoscopy versus direct laryngoscopy for orotracheal intubation",
        "journal": "NEJM",
    }
    assert classify_article(data) == 7  # airway


def test_classify_other():
    data = {"title": "Some unrelated topic without keywords", "journal": "General Medicine"}
    assert classify_article(data) == 9  # other


def test_classify_empty():
    assert classify_article({}) == 9
