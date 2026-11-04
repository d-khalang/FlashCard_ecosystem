from fastapi import APIRouter

from flashcard.miniapp.routes.deps import CoreDep, GeneralUser
from flashcard.miniapp.schemas import MeOut, me_out

router = APIRouter()


@router.get("/me")
async def me(user_id: GeneralUser, core: CoreDep) -> MeOut:
    return me_out(await core.study_use_cases.overview(user_id), core.language)
