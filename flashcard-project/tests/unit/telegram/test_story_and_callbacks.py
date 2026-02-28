"""
Unit tests for story UI formatting and callback data factories.

Stories: format_story_messages produces alternating Italian/spoiler message pairs.
Callbacks: GradeCallback, SettingsCallback, VerbCallback pack/unpack round-trip.
"""
from flashcard.schemas.story import StoryResponse, StoryParagraph
from flashcard.telegram.ui.story import format_story_messages
from flashcard.telegram.ui.factories.grade_callback import GradeCallback
from flashcard.telegram.ui.factories.settings_callback import SettingsCallback
from flashcard.telegram.ui.factories.verb_callback import VerbCallback


# ===================================================================
# format_story_messages
# ===================================================================
class TestFormatStoryMessages:

    def _make_story(self, n_paragraphs=2) -> StoryResponse:
        paragraphs = [
            StoryParagraph(
                italian_text=f"Paragrafo italiano {i+1}.",
                translation=f"English paragraph {i+1}.",
            )
            for i in range(n_paragraphs)
        ]
        return StoryResponse(paragraphs=paragraphs)

    def test_two_paragraphs_produce_four_messages(self):
        story = self._make_story(n_paragraphs=2)
        msgs = format_story_messages(story)

        assert len(msgs) == 4  # 2 Italian + 2 translations

    def test_italian_text_comes_first(self):
        story = self._make_story(n_paragraphs=1)
        msgs = format_story_messages(story)

        assert msgs[0] == "Paragrafo italiano 1."

    def test_translation_wrapped_in_spoiler(self):
        story = self._make_story(n_paragraphs=1)
        msgs = format_story_messages(story)

        assert "<tg-spoiler>" in msgs[1]
        assert "English paragraph 1." in msgs[1]

    def test_language_flag_in_translation(self):
        story = self._make_story(n_paragraphs=1)
        msgs = format_story_messages(story, target_lang="en")

        assert "🇬🇧" in msgs[1]

    def test_empty_story_returns_empty_list(self):
        story = StoryResponse(paragraphs=[])
        msgs = format_story_messages(story)
        assert msgs == []


# ===================================================================
# GradeCallback round-trip
# ===================================================================
class TestGradeCallback:

    def test_pack_unpack_forward(self):
        cb = GradeCallback(expression_id="abc123", grade=4, direction="fwd")
        packed = cb.pack()
        unpacked = GradeCallback.unpack(packed)

        assert unpacked.expression_id == "abc123"
        assert unpacked.grade == 4
        assert unpacked.direction == "fwd"

    def test_pack_unpack_reverse(self):
        cb = GradeCallback(expression_id="xyz", grade=0, direction="rev")
        unpacked = GradeCallback.unpack(cb.pack())

        assert unpacked.direction == "rev"
        assert unpacked.grade == 0

    def test_prefix_is_grade(self):
        cb = GradeCallback(expression_id="id", grade=3, direction="fwd")
        assert cb.pack().startswith("grade:")


# ===================================================================
# SettingsCallback round-trip
# ===================================================================
class TestSettingsCallback:

    def test_pack_unpack_with_value(self):
        cb = SettingsCallback(action="select", section="target_level", value="B1")
        unpacked = SettingsCallback.unpack(cb.pack())

        assert unpacked.action == "select"
        assert unpacked.section == "target_level"
        assert unpacked.value == "B1"

    def test_pack_unpack_without_value(self):
        cb = SettingsCallback(action="nav", section="main")
        unpacked = SettingsCallback.unpack(cb.pack())

        assert unpacked.action == "nav"
        assert unpacked.value is None

    def test_prefix_is_set(self):
        cb = SettingsCallback(action="nav", section="main")
        assert cb.pack().startswith("set:")


# ===================================================================
# VerbCallback round-trip
# ===================================================================
class TestVerbCallback:

    def test_pack_unpack(self):
        cb = VerbCallback(mood="indicativo", tense="presente", verb="parlare")
        unpacked = VerbCallback.unpack(cb.pack())

        assert unpacked.mood == "indicativo"
        assert unpacked.tense == "presente"
        assert unpacked.verb == "parlare"

    def test_prefix_and_separator(self):
        cb = VerbCallback(mood="indicativo", tense="presente", verb="parlare")
        packed = cb.pack()

        # Uses prefix "conj" and separator "|"
        assert packed.startswith("conj|")

    def test_tense_with_spaces(self):
        """Tenses like 'passato remoto' should survive pack/unpack."""
        cb = VerbCallback(mood="indicativo", tense="passato remoto", verb="essere")
        unpacked = VerbCallback.unpack(cb.pack())

        assert unpacked.tense == "passato remoto"
