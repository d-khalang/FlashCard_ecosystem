from pydantic import BaseModel
from typing import List, Optional

class ImportResponse(BaseModel):
    success: bool
    import_list: List[str]
    log: Optional[str] = None
