from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

class UserDB(BaseModel):
    user_id: str = Field(..., description="User ID as string")
    last_push_at: Optional[str] = Field(None, description="ISO timestamp of last push")
    has_pending: bool = Field(False, description="If user has pending reviews")
