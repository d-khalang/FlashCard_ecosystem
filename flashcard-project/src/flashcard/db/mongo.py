from fastapi import FastAPI
from pymongo import AsyncMongoClient


def _collection_name_map(settings):
    return {
        "users": settings.COLLECTION_USERS,
        "expression": settings.COLLECTION_EXPRESSION,
        "conjugation": settings.COLLECTION_CONJUGATION,
    }


async def init_mongo(app: FastAPI, settings):
    client = AsyncMongoClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB]
    
    # One dict with all collections instead of many attributes
    cols = {alias: db[name] for alias, name in _collection_name_map(settings).items()}

    app.state.mongo_client = client
    app.state.db = db
    app.state.cols = cols   # { "users": AsyncCollection, "expression": AsyncCollection, "conjugation": AsyncCollection }


async def close_mongo(app: FastAPI) -> None:
    client: AsyncMongoClient = app.state.mongo_client
    await client.close()