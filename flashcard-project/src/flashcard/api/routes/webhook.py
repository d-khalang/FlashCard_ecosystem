from fastapi import APIRouter, Header, HTTPException, Request
from aiogram.types import Update
from flashcard.settings import settings

router = APIRouter()

#TODO: activate
@router.post(settings.WEBHOOK_PATH)
async def webhook_handler(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None)
):
    return {"ok": True, "message": "Webhook not implemented right now"}
    
    if x_telegram_bot_api_secret_token != settings.WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret token")

    try:
        data = await request.json()
        update = Update(**data)
        
        # Get bot and dispatcher from app state (set during init_telegram_bot)
        bot = request.app.state.bot
        dp = request.app.state.dispatcher
        
        # Feed update to dispatcher
        await dp.feed_update(bot, update)
        return {"ok": True}
    except Exception as e:
        # Log error in real app
        print(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
