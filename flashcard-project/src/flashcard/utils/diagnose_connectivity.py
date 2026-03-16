import asyncio
import socket
import time
import aiohttp
from flashcard.settings import settings

async def test_connection(name: str, family: socket.AddressFamily = socket.AF_UNSPEC):
    """Tests connection to Telegram API with specific IP family settings."""
    url = f"https://api.telegram.org/bot{settings.BOT_TOKEN}/getMe"
    
    # Configure connector to force IPv4 or IPv6 if requested
    connector = aiohttp.TCPConnector(family=family)
    
    start_time = time.perf_counter()
    try:
        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.get(url, timeout=10) as response:
                latency = (time.perf_counter() - start_time) * 1000
                if response.status == 200:
                    data = await response.json()
                    bot_name = data.get('result', {}).get('first_name', 'Unknown')
                    print(f"✅ {name:15} | SUCCESS | Latency: {latency:7.2f}ms | Bot: {bot_name}")
                    return True
                else:
                    print(f"❌ {name:15} | FAILED  | Status: {response.status} | Latency: {latency:7.2f}ms")
                    return False
    except asyncio.TimeoutError:
        latency = (time.perf_counter() - start_time) * 1000
        print(f"⏰ {name:15} | TIMEOUT | Latency: {latency:7.2f}ms")
    except Exception as e:
        latency = (time.perf_counter() - start_time) * 1000
        print(f"🔥 {name:15} | ERROR   | Latency: {latency:7.2f}ms | {type(e).__name__}: {e}")
    return False

async def main():
    print(f"\n--- Telegram Connectivity Diagnosis ---")
    print(f"Target: api.telegram.org")
    print(f"----------------------------------------")
    
    # 1. Default (usually IPv6 if available)
    await test_connection("Default (Auto)", socket.AF_UNSPEC)
    
    # 2. Force IPv4
    await test_connection("Force IPv4", socket.AF_INET)
    
    # 3. Force IPv6
    await test_connection("Force IPv6", socket.AF_INET6)
    
    print(f"----------------------------------------\n")

if __name__ == "__main__":
    asyncio.run(main())
