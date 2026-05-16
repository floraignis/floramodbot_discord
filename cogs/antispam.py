import json
import os
import time
import datetime
from collections import defaultdict

import discord
from discord import app_commands
from discord.ext import commands

from config import CREATOR_ID, SETTINGS_FILE, DEFAULT_SETTINGS


def load_settings() -> dict:
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE) as f:
            return {**DEFAULT_SETTINGS, **json.load(f)}
    return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)


class AntiSpam(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.user_history: dict[int, list[tuple[float, int]]] = defaultdict(list)
        self.muting_users: set[int] = set()

    @commands.Cog.listener()
    async def on_ready(self):
        print(f"Bot started as {self.bot.user} (ID: {self.bot.user.id})")

    @app_commands.command(name="help", description="Show bot commands and current settings")
    async def help_command(self, interaction: discord.Interaction):
        s = load_settings()
        embed = discord.Embed(title="FloraModHelper", color=discord.Color.purple())
        embed.add_field(
            name="Anti-spam settings",
            value=(
                f"`limit` — max messages before mute: **{s['limit']}**\n"
                f"`window` — time window in seconds: **{s['window']}**\n"
                f"`timeout` — mute duration in minutes: **{s['timeout_minutes']}**"
            ),
            inline=False,
        )
        embed.add_field(
            name="Commands",
            value=(
                "`/set limit <n>` — set max messages\n"
                "`/set window <s>` — set time window (seconds)\n"
                "`/set timeout <m>` — set mute duration (minutes)\n"
                "`/settings` — show current settings\n"
                "\nReply to any message with `CLEAR` to delete all messages from that user.\n"
                "Reply to any message with `BAN` to ban that user and delete their messages."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="settings", description="Show current anti-spam settings")
    async def show_settings(self, interaction: discord.Interaction):
        s = load_settings()
        embed = discord.Embed(title="Current settings", color=discord.Color.blurple())
        embed.add_field(name="Limit", value=f"{s['limit']} messages", inline=True)
        embed.add_field(name="Window", value=f"{s['window']} seconds", inline=True)
        embed.add_field(name="Timeout", value=f"{s['timeout_minutes']} minutes", inline=True)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="set", description="Change anti-spam settings (creator only)")
    @app_commands.describe(
        limit="Max messages before mute",
        window="Time window in seconds",
        timeout="Mute duration in minutes",
    )
    async def set_settings(
        self,
        interaction: discord.Interaction,
        limit: int = None,
        window: int = None,
        timeout: int = None,
    ):
        if interaction.user.id != CREATOR_ID:
            await interaction.response.send_message("Not your toy.", ephemeral=True)
            return

        s = load_settings()
        changed = []

        if limit is not None:
            s["limit"] = limit
            changed.append(f"limit → **{limit}**")
        if window is not None:
            s["window"] = window
            changed.append(f"window → **{window}s**")
        if timeout is not None:
            s["timeout_minutes"] = timeout
            changed.append(f"timeout → **{timeout}m**")

        if not changed:
            await interaction.response.send_message(
                "Nothing changed. Specify at least one parameter.", ephemeral=True
            )
            return

        save_settings(s)
        await interaction.response.send_message("Updated: " + ", ".join(changed), ephemeral=True)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if not message.guild:
            return

        now = time.time()
        user_id = message.author.id

        if user_id in self.muting_users:
            return

        print(f"[DEBUG] message from {message.author} (ID: {message.author.id})")

        cmd = message.content.strip().upper()

        if message.author.id == CREATOR_ID and cmd == "CLEAR" and message.reference:
            try:
                ref = await message.channel.fetch_message(message.reference.message_id)

                if ref.author.id != self.bot.user.id:
                    return

                target = next(
                    (u for u in ref.mentions if u.id != CREATOR_ID and u.id != self.bot.user.id),
                    None,
                )
                if target is None:
                    return

                await message.delete()
                deleted = await message.channel.purge(
                    limit=None, check=lambda m: m.author.id == target.id
                )
                print(f"Cleared {len(deleted)} messages from {target} (ID: {target.id})")
                await message.channel.send(f"{target.mention} messages cleared ({len(deleted)}).")
            except discord.Forbidden as e:
                await message.channel.send("No permission to delete messages.")
                print(f"Forbidden: {e.text} (code: {e.code})")
            except discord.HTTPException as e:
                print(f"Error clearing: {e}")
            return

        if message.author.id == CREATOR_ID and cmd == "BAN" and message.reference:
            try:
                ref = await message.channel.fetch_message(message.reference.message_id)

                if ref.author.id == self.bot.user.id:
                    target = next(
                        (u for u in ref.mentions if u.id != CREATOR_ID and u.id != self.bot.user.id),
                        None,
                    )
                    if target is None:
                        return
                else:
                    target = ref.author

                if target.id == CREATOR_ID or target.id == self.bot.user.id:
                    return

                await message.guild.ban(target, reason="Banned by creator", delete_message_seconds=604800)
                print(f"Banned {target} (ID: {target.id})")

                deleted = await message.channel.purge(
                    limit=None, check=lambda m: m.author.id == target.id
                )
                print(f"Deleted {len(deleted)} messages from {target}")
                await message.channel.send(f"{target} has been banned and their messages deleted.")
            except discord.Forbidden as e:
                await message.channel.send("No permission to ban this user.")
                print(f"Forbidden: {e.text} (code: {e.code})")
            except discord.HTTPException as e:
                print(f"Error banning: {e}")
            return

        if (
            any(u.id == self.bot.user.id for u in message.mentions)
            and message.author.id == CREATOR_ID
            and not message.reference
        ):
            await message.channel.send("Greetings, master!")
            return

        s = load_settings()
        limit = s["limit"]
        window = s["window"]
        timeout_minutes = s["timeout_minutes"]

        self.user_history[user_id] = [
            (t, mid) for t, mid in self.user_history[user_id] if now - t < window
        ]
        self.user_history[user_id].append((now, message.id))

        print(f"[DEBUG] spam counter for {message.author}: {len(self.user_history[user_id])}/{limit}")

        if len(self.user_history[user_id]) >= limit:
            member = message.guild.get_member(user_id)
            if member is None:
                await self.bot.process_commands(message)
                return

            self.muting_users.add(user_id)
            spam_ids = [mid for _, mid in self.user_history[user_id]]
            self.user_history[user_id].clear()

            try:
                to_delete = []
                async for msg in message.channel.history(limit=100):
                    if msg.id in spam_ids:
                        to_delete.append(msg)
                    if len(to_delete) == len(spam_ids):
                        break

                if to_delete:
                    if len(to_delete) == 1:
                        await to_delete[0].delete()
                    else:
                        await message.channel.delete_messages(to_delete)
            except discord.Forbidden:
                print(f"No permission to delete messages in #{message.channel.name}")
            except discord.HTTPException as e:
                print(f"Error deleting messages: {e}")

            try:
                until = discord.utils.utcnow() + datetime.timedelta(minutes=timeout_minutes)
                await member.timeout(until, reason=f"Anti-spam: {limit}+ messages in {window}s")
                await message.channel.send(
                    f"<@{CREATOR_ID}> {member.mention} has been muted for {timeout_minutes} minutes for spamming."
                )
                print(f"Muted {member} (ID: {user_id})")
            except discord.Forbidden:
                print(f"No permission to mute {member}")
            except discord.HTTPException as e:
                print(f"Error muting {member}: {e}")
            finally:
                self.muting_users.discard(user_id)

            return

        await self.bot.process_commands(message)


async def setup(bot: commands.Bot):
    await bot.add_cog(AntiSpam(bot))
