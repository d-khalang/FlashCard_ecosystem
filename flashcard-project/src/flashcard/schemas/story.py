from pydantic import AliasChoices, BaseModel, Field

class StoryParagraph(BaseModel):
    learning_text: str = Field(
        description="The paragraph text in the learning language",
        validation_alias=AliasChoices("learning_text", "italian_text"),
    )
    translation: str = Field(description="The translation of the paragraph in target language")

class StoryResponse(BaseModel):
    paragraphs: list[StoryParagraph] = Field(description="List of paragraphs forming the story")
