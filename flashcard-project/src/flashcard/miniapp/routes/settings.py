from fastapi import APIRouter

from flashcard.miniapp.errors import invalid_request
from flashcard.miniapp.routes.deps import CoreDep, GeneralUser
from flashcard.miniapp.schemas import SettingsOut, SettingsPatch, settings_out

router = APIRouter()


@router.patch("/settings")
async def patch_settings(body: SettingsPatch, user_id: GeneralUser, core: CoreDep) -> SettingsOut:
    try:
        user = await core.settings_use_cases.update(user_id, body.changes())
    except ValueError:
        raise invalid_request("Invalid settings value.") from None
    return settings_out(user)
