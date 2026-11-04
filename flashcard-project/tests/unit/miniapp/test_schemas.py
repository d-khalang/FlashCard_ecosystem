import pytest

from flashcard.miniapp.schemas import SettingsPatch, content_out, country_from_flag
from tests.integration.study_helpers import make_card


@pytest.mark.parametrize("label, country", [
    ("🇮🇷 FA", "ir"), ("🇬🇧 EN", "gb"), ("🇮🇹", "it"), ("EN 🇬🇧", "gb"), ("🇮🇷🇬🇧", "ir"),
    ("EN", None), ("🌍", None), ("", None), ("⚪ none", None),
])
def test_country_comes_from_the_labels_flag_emoji(label, country):
    assert country_from_flag(label) == country


def test_a_single_regional_indicator_is_not_a_flag():
    assert country_from_flag("\U0001F1EE alone") is None


def test_content_has_exactly_the_contract_fields_and_empty_text_is_null():
    card = make_card(learning_definition="", learning_example="  ", note="")

    content = content_out(card).model_dump()

    assert set(content) == {"definition", "translations", "example", "note"}
    assert content["definition"] is None and content["note"] is None and content["example"] == "  "
    assert content["translations"][1] == {"label": "🇮🇷 FA", "country": "ir", "text": "رفتن"}


def test_patch_collects_only_what_was_sent_and_allows_null_for_secondary_only():
    assert SettingsPatch.model_validate({"target_level": "B1"}).changes() == {"target_level": "B1"}
    assert SettingsPatch.model_validate({"secondary_language": None}).changes() == {"secondary_language": None}
    assert SettingsPatch.model_validate({}).changes() == {}
    with pytest.raises(ValueError):
        SettingsPatch.model_validate({"target_level": None}).changes()


def test_patch_refuses_unknown_fields_and_wrong_types():
    for body in ({"tier": "admin"}, {"review_interval_minutes": "30"}, {"is_active": 1}):
        with pytest.raises(ValueError):
            SettingsPatch.model_validate(body)
