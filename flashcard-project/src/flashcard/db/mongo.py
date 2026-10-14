import threading
import time

from fastapi import FastAPI
from pymongo import AsyncMongoClient, monitoring

from flashcard.utils.logger import get_logger

logger = get_logger(__name__)


def _collection_name_map(settings):
    return {
        "users": settings.COLLECTION_USERS,
        "expression": settings.COLLECTION_EXPRESSION,
        "conjugation": settings.COLLECTION_CONJUGATION,
    }


class _MongoPoolStats:
    def __init__(self, log_interval_seconds: int = 300) -> None:
        self._log_interval_seconds = log_interval_seconds
        self._lock = threading.Lock()
        self._last_log = time.monotonic()
        self._counts = {
            "pool_created": 0,
            "pool_closed": 0,
            "pool_cleared": 0,
            "conn_created": 0,
            "conn_closed": 0,
            "checked_out": 0,
            "checked_in": 0,
            "checkout_failed": 0,
        }

    def bump(self, key: str) -> None:
        with self._lock:
            if key in self._counts:
                self._counts[key] += 1
            now = time.monotonic()
            if now - self._last_log < self._log_interval_seconds:
                return
            window_seconds = now - self._last_log
            snapshot = dict(self._counts)
            for name in self._counts:
                self._counts[name] = 0
            self._last_log = now

        logger.info(
            "Mongo pool stats (last %.0fs): pool_created=%d pool_closed=%d "
            "pool_cleared=%d conn_created=%d conn_closed=%d checked_out=%d "
            "checked_in=%d checkout_failed=%d",
            window_seconds,
            snapshot["pool_created"],
            snapshot["pool_closed"],
            snapshot["pool_cleared"],
            snapshot["conn_created"],
            snapshot["conn_closed"],
            snapshot["checked_out"],
            snapshot["checked_in"],
            snapshot["checkout_failed"],
        )


class _MongoPoolListener(monitoring.ConnectionPoolListener):
    def __init__(self, stats: _MongoPoolStats) -> None:
        self._stats = stats

    def pool_created(self, event) -> None:
        self._stats.bump("pool_created")

    def pool_ready(self, event) -> None:
        pass  # Ignored, but required by PyMongo

    def pool_closed(self, event) -> None:
        self._stats.bump("pool_closed")

    def pool_cleared(self, event) -> None:
        self._stats.bump("pool_cleared")
        reason = getattr(event, "reason", "unknown")
        logger.warning("Mongo pool cleared: reason=%s", reason)

    def connection_created(self, event) -> None:
        self._stats.bump("conn_created")

    def connection_ready(self, event) -> None:
        pass  # Ignored, but required by PyMongo

    def connection_closed(self, event) -> None:
        self._stats.bump("conn_closed")
    
    def connection_check_out_started(self, event) -> None:
        pass  # Ignored, but required by PyMongo

    def connection_checked_out(self, event) -> None:
        self._stats.bump("checked_out")

    def connection_checked_in(self, event) -> None:
        self._stats.bump("checked_in")

    def connection_check_out_failed(self, event) -> None:
        self._stats.bump("checkout_failed")
        reason = getattr(event, "reason", "unknown")
        logger.warning("Mongo pool checkout failed: reason=%s", reason)


def _server_type_name(description) -> str:
    name = getattr(description, "server_type_name", None)
    if name:
        return name
    return str(getattr(description, "server_type", "unknown"))


class _MongoServerListener(monitoring.ServerListener):
    def opened(self, event) -> None:
        pass  # Required by PyMongo

    def description_changed(self, event) -> None:
        prev = _server_type_name(event.previous_description)
        new = _server_type_name(event.new_description)
        address = getattr(event.new_description, "address", "unknown")
        if new.lower() == "unknown":
            logger.warning("Mongo server %s changed: %s -> %s", address, prev, new)
        else:
            logger.info("Mongo server %s changed: %s -> %s", address, prev, new)

    def closed(self, event) -> None:
        pass  # Required by PyMongo


class _MongoTopologyListener(monitoring.TopologyListener):
    def opened(self, event) -> None:
        pass  # Required by PyMongo

    def description_changed(self, event) -> None:
        prev = getattr(event.previous_description, "topology_type_name", "unknown")
        new = getattr(event.new_description, "topology_type_name", "unknown")
        if prev != new:
            logger.info("Mongo topology changed: %s -> %s", prev, new)

    def closed(self, event) -> None:
        pass  # Required by PyMongo


_MONGO_MONITORING_INSTALLED = False


def _install_mongo_monitoring() -> None:
    global _MONGO_MONITORING_INSTALLED
    if _MONGO_MONITORING_INSTALLED:
        return
    monitoring.register(_MongoPoolListener(_MongoPoolStats()))
    monitoring.register(_MongoServerListener())
    monitoring.register(_MongoTopologyListener())
    _MONGO_MONITORING_INSTALLED = True
    logger.info("Mongo monitoring enabled (pool and topology events)")


# Shared connection options for MongoDB client resilience.
# We do NOT use timeoutMS (CSOT) because it caps the entire operation
# budget (including server selection and retries) into one shared timer.
_MONGO_CLIENT_OPTIONS = dict(
    serverSelectionTimeoutMS=10_000,     # 10s to find a server (per attempt)
    connectTimeoutMS=5_000,              # 5s to establish a socket
    socketTimeoutMS=10_000,              # 10s for individual socket ops
    maxIdleTimeMS=45_000,                # Clean stale connections before Atlas does
    waitQueueTimeoutMS=5_000,            # 5s max wait for a pooled connection
    retryReads=True,                     # Explicit, critical for failover
    retryWrites=True,                    # Explicit, critical for failover
)


### Having app as source of truth ###
async def init_mongo(app: FastAPI, settings):
    _install_mongo_monitoring()
    client = AsyncMongoClient(settings.MONGO_URI, **_MONGO_CLIENT_OPTIONS)
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
    _install_mongo_monitoring()
    client = AsyncMongoClient(settings.MONGO_URI, **_MONGO_CLIENT_OPTIONS)
    db = client[settings.MONGO_DB]
    
    # One dict with all collections instead of many attributes
    # { "users": AsyncCollection, "expression": AsyncCollection, "conjugation": AsyncCollection }
    cols = {alias: db[name] for alias, name in _collection_name_map(settings).items()}

    return client, db, cols   


async def close_mongo_on_client(client: AsyncMongoClient) -> None:
    await client.close()
