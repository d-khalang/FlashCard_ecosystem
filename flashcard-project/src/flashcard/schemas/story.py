from pydantic import BaseModel, Field

class StoryParagraph(BaseModel):
    italian_text: str = Field(description="The paragraph text in Italian")
    translation: str = Field(description="The translation of the paragraph in target language")

class StoryResponse(BaseModel):
    paragraphs: list[StoryParagraph] = Field(description="List of paragraphs forming the story")
