#!/usr/bin/env python3
import asyncio
import aiohttp
import random
import string
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.enums import ParseMode

BOT_TOKEN = "8647879379:AAEA17ZXW3cOBwwjdxkWM90s1Tlv9yrs5R8"

logging.basicConfig(level=logging.INFO)

CONSONANTS = "bcdfghjklmnprstvwxyz"
VOWELS = "aeiou"

def _syllable() -> str:
    return random.choice(CONSONANTS) + random.choice(VOWELS)

def generate_candidate(length: int) -> str:
    result = ""
    while len(result) < length:
        result += _syllable()
    return result[:length]

def generate_random(length: int) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))

FRAGMENT_URL = "https://fragment.com/username/{}"
TG_URL = "https://t.me/{}"
TIMEOUT = 8

YOUR_PROXIES = [
    "socks5://206.123.156.211:4332",
    "socks5://206.123.156.211:4362",
    "socks5://206.123.156.218:5738",
    "socks5://206.123.156.211:46185",
    "socks5://206.123.156.219:7960",
    "socks5://206.123.156.234:4662",
    "socks5://5.189.163.212:1080",
    "socks5://206.123.156.218:6254",
    "socks5://206.123.156.232:16640",
    "socks4://98.170.57.249:4145",
    "socks5://206.123.156.232:6039",
    "socks5://206.123.156.218:8182",
    "socks5://51.79.177.162:1010",
    "socks5://206.123.156.219:5251",
    "socks5://206.123.156.209:4560",
    "socks5://206.123.156.233:7583",
    "socks5://206.123.156.211:4779",
    "socks5://206.123.156.218:5683",
    "socks5://185.13.134.202:1080",
    "socks5://206.123.156.211:6318",
    "socks5://8.212.168.170:8443",
    "socks4://174.138.64.121:9052",
    "socks5://206.123.156.236:7436",
    "socks5://206.123.156.230:9416",
    "socks5://206.123.156.211:5333",
    "socks5://206.123.156.233:7153",
    "socks5://206.123.156.211:5672",
    "socks5://206.123.156.221:9537",
    "socks5://47.108.159.113:8080",
    "socks5://23.133.196.12:9000",
    "socks5://206.123.156.230:4204",
    "socks5://206.123.156.236:4418",
    "socks4://86.107.168.166:22",
    "socks5://206.123.156.232:5415",
    "socks5://206.123.156.218:4581",
    "socks5://206.123.156.238:4049",
    "socks5://206.123.156.211:6053",
    "socks5://91.189.238.202:1080",
    "socks5://206.123.156.229:5410",
    "socks5://206.123.156.223:6369",
    "socks5://206.123.156.223:4783",
    "socks5://68.183.52.128:9103",
    "socks5://206.123.156.238:6064",
    "socks5://206.123.156.211:6083",
    "socks5://206.123.156.222:5068",
    "socks5://206.123.156.233:7321",
    "socks5://206.123.156.233:7501",
]

async def check_proxy(session, proxy):
    try:
        async with session.get("https://httpbin.org/ip",
                              timeout=aiohttp.ClientTimeout(total=3),
                              proxy=proxy) as resp:
            if resp.status == 200:
                return proxy
    except:
        pass
    return None

async def get_working_proxy():
    connector = aiohttp.TCPConnector(limit=20)
    async with aiohttp.ClientSession(connector=connector) as session:
        tasks = [check_proxy(session, proxy) for proxy in YOUR_PROXIES]
        results = await asyncio.gather(*tasks)
        for result in results:
            if result:
                return result
    return None

async def check_telegram(session, username):
    url = TG_URL.format(username)
    try:
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                return True
            html = await resp.text()
            if 'tgme_action_button_new' in html or 'Send Message' in html:
                return False
            return True
    except:
        return True

async def check_fragment(session, username):
    url = FRAGMENT_URL.format(username)
    try:
        async with session.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=TIMEOUT) as resp:
            if resp.status != 200:
                return False
            html = await resp.text()
            return 'Unavailable' in html
    except:
        return False

async def find_free_username(length, proxy=None):
    if proxy:
        from aiohttp_socks import ProxyConnector
        connector = ProxyConnector.from_url(proxy)
    else:
        connector = aiohttp.TCPConnector(limit=10, ssl=False)
    
    async with aiohttp.ClientSession(connector=connector) as session:
        for attempt in range(1, 201):
            candidate = generate_candidate(length) if attempt % 2 == 0 else generate_random(length)
            
            tg_free = await check_telegram(session, candidate)
            if not tg_free:
                continue
            
            frag_free = await check_fragment(session, candidate)
            
            if tg_free and frag_free:
                return candidate
    return None

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(Command("start"))
async def start_command(message: Message):
    await message.answer(
        "🤖 Бот для поиска свободных Telegram-ников\n\n"
        "Отправь длину ника (5, 6 или 7)"
    )

@dp.message()
async def search_handler(message: Message):
    if message.text not in ["5", "6", "7"]:
        await message.answer("❌ Введи 5, 6 или 7!")
        return
    
    length = int(message.text)
    await message.answer(f"🔍 Ищу свободный ник длиной {length}...\n⏱ Около 2-3 минут")
    
    proxy = await get_working_proxy()
    result = await find_free_username(length, proxy)
    
    if result:
        await message.answer(
            f"🎉 НАЙДЕН СВОБОДНЫЙ НИК!\n\n"
            f"@{result}\n\n"
            f"💰 Купить: https://fragment.com/username/{result}"
        )
    else:
        await message.answer(f"❌ Не удалось найти свободный ник длиной {length}")

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())