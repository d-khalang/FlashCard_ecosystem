from fastapi import FastAPI
from pymongo import AsyncMongoClient


def _collection_name_map(settings):
    return {
        "users": settings.COLLECTION_USERS,
        "expression": settings.COLLECTION_EXPRESSION,
        "conjugation": settings.COLLECTION_CONJUGATION,
    }

### Having app as source of truth ###
async def init_mongo(app: FastAPI, settings):
    client = AsyncMongoClient(settings.MONGO_URI, timeoutMS=10_000)
    db = client[settings.MONGO_DB]
    
    # One dict with all collections instead of many attributes
    cols = {alias: db[name] for alias, name in _collection_name_map(settings).items()}

    app.state.mongo_client = client
    app.state.db = db
    app.state.cols = cols   # { "users": AsyncCollection, "expression": AsyncCollection, "conjugation": AsyncCollection }


async def close_mongo(app: FastAPI) -> None:
    client: AsyncMongoClient = app.state.mongo_client
    await client.close()


### Having output version to be called and stored on dp ###
async def init_and_get_mongo(settings):
    client = AsyncMongoClient(settings.MONGO_URI, timeoutMS=10_000)
    db = client[settings.MONGO_DB]
    
    # One dict with all collections instead of many attributes
    # { "users": AsyncCollection, "expression": AsyncCollection, "conjugation": AsyncCollection }
    cols = {alias: db[name] for alias, name in _collection_name_map(settings).items()}

    return client, db, cols   


async def close_mongo_on_client(client: AsyncMongoClient) -> None:
    await client.close()