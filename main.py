import asyncio
import discord
from discord.ext import commands
from config import DISCORD_TOKEN


def create_bot() -> commands.Bot:
    intents = discord.Intents.default()
    intents.messages = True
    intents.message_content = True
    intents.members = True
    return commands.Bot(command_prefix="!", intents=intents)


async def main():
    bot = create_bot()
    async with bot:
        await bot.load_extension("cogs.antispam")
        await bot.load_extension("cogs.verification")
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
