from fastapi import APIRouter, Header, HTTPException, Request
from aiogram.types import Update
from flashcard.settings import settings

router = APIRouter()

@router.post(settings.WEBHOOK_PATH)
async def webhook_handler(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(None)
):
    if x_telegram_bot_api_secret_token != settings.WEBHOOK_SECRET:
        raise HTTPException(status_code=403, detail="Invalid secret token")

    try:
        data = await request.json()
        update = Update(**data)
        
        # Get bot and dispatcher from app state (set during init_telegram_bot)
        bot = request.app.state.bot
        dp = request.app.state.dispatcher
        dispatcher_data = getattr(request.app.state, "dispatcher_data", {})
        
        # Feed update to dispatcher
        await dp.feed_update(bot, update, **dispatcher_data)
        return {"ok": True}
    except Exception as e:
        # Log error in real app
        print(f"Webhook error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
