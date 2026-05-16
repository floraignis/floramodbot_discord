import datetime

import discord
from discord.ext import commands

from config import CREATOR_ID, MOD_ROLE_NAME, VERIFIED_ROLE_NAME, TICKET_CATEGORY_NAME, REQUIRED_PHOTOS


_STATUSES = ("new-", "ready-", "in-progress-", "approved-", "rejected-")


def _strip_status(name: str) -> str:
    for status in _STATUSES:
        if name.startswith(status):
            return name[len(status):]
    return name


def _log_missing_perms(location: str, perms: discord.Permissions, required: list[str]):
    missing = [p for p in required if not getattr(perms, p, False)]
    if missing:
        print(f"[perms] {location} — missing: {', '.join(missing)}")
    return missing


class OpenTicketView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Get Verified", style=discord.ButtonStyle.primary, custom_id="open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        user = interaction.user

        safe_name = "".join(c if c.isalnum() else "-" for c in user.name.lower())[:20].strip("-")
        date_str = datetime.date.today().strftime("%d-%m-%Y")
        channel_name = f"new-verify-{safe_name}-{date_str}"

        final_statuses = ("approved-", "rejected-")
        category = discord.utils.get(guild.categories, name=TICKET_CATEGORY_NAME)
        search_channels = category.channels if category else guild.text_channels
        existing = next(
            (
                ch for ch in search_channels
                if isinstance(ch, discord.TextChannel)
                and f"verify-{safe_name}-" in ch.name
                and not ch.name.startswith(final_statuses)
            ),
            None,
        )
        if existing:
            await interaction.response.send_message(
                f"You already have an open verification: {existing.mention}", ephemeral=True
            )
            return

        mod_role = discord.utils.get(guild.roles, name=MOD_ROLE_NAME)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(read_messages=False),
            user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True),
            guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True),
        }
        if mod_role:
            overwrites[mod_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

        _log_missing_perms(
            f"open_ticket / guild-level for {user} (ID: {user.id})",
            guild.me.guild_permissions,
            ["manage_channels", "manage_roles"],
        )
        if category:
            _log_missing_perms(
                f"open_ticket / category '{category.name}' for {user} (ID: {user.id})",
                category.permissions_for(guild.me),
                ["manage_channels", "send_messages", "read_messages", "manage_roles"],
            )

        try:
            channel = await guild.create_text_channel(
                name=channel_name,
                overwrites=overwrites,
                category=category,
                reason=f"Verification opened by {user}",
            )
        except discord.Forbidden as e:
            print(f"[open_ticket] Forbidden creating channel for {user} (ID: {user.id}): {e}")
            await interaction.response.send_message("Bot has no permission to create channels.", ephemeral=True)
            return
        except discord.HTTPException as e:
            print(f"[open_ticket] HTTPException creating channel for {user} (ID: {user.id}): {e}")
            await interaction.response.send_message("Failed to create verification channel.", ephemeral=True)
            return

        instructions = discord.Embed(
            title="Verification Instructions",
            description=(
                "To get verified, prepare **3 photos** following these steps:\n\n"
                "**1) Take 3 Photos**\n"
                "Capture 3 photos from different angles. Make sure your body is clearly visible.\n\n"
                "**2) The Crumpled Paper**\n"
                "In each photo, hold a crumpled piece of paper with the following written on it:\n"
                f"- Your username: `{user.name}`\n"
                f"- Server name: `{guild.name}`\n"
                "- Today's date\n\n"
                "**3) When Ready**\n"
                "Attach all 3 photos in **one message** in this channel, then click **Submit for Review**."
            ),
            color=discord.Color.blue(),
        )
        instructions.set_footer(text=f"User ID: {user.id}")

        await channel.send(content=user.mention, embed=instructions, view=SubmitReviewView())
        await interaction.response.send_message(
            f"Your verification request has been created: {channel.mention}", ephemeral=True
        )
        print(f"Verification opened by {user} (ID: {user.id}) → #{channel.name}")

        try:
            thread = await channel.create_thread(
                name="new-mod-controls",
                type=discord.ChannelType.private_thread,
                reason="Mod controls for verification",
            )

            mod_embed = discord.Embed(
                title="Verification Controls",
                description=f"Verification request from {user.mention}",
                color=discord.Color.orange(),
            )
            mod_embed.set_footer(text=f"User ID: {user.id}")
            await thread.send(embed=mod_embed, view=TicketControlView())

            if mod_role:
                for member in mod_role.members:
                    try:
                        await thread.add_user(member)
                    except discord.HTTPException as e:
                        print(f"[open_ticket] Failed to add {member} to mod thread: {e}")

            print(f"Mod thread created: {thread.name} (ID: {thread.id})")
        except discord.Forbidden as e:
            print(f"[open_ticket] Forbidden creating mod thread: {e}")
        except discord.HTTPException as e:
            print(f"[open_ticket] HTTPException creating mod thread: {e}")


class SubmitReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Submit for Review", style=discord.ButtonStyle.primary, custom_id="submit_review")
    async def submit_review(self, interaction: discord.Interaction, button: discord.ui.Button):
        channel = interaction.channel
        user = interaction.user

        photos = []
        async for msg in channel.history(limit=50):
            if msg.author.id == user.id:
                for att in msg.attachments:
                    if att.content_type and att.content_type.startswith("image/"):
                        photos.append(att)
            if len(photos) >= REQUIRED_PHOTOS:
                break

        if len(photos) < REQUIRED_PHOTOS:
            await interaction.response.send_message(
                f"Please attach exactly {REQUIRED_PHOTOS} photos in this channel first "
                f"(found {len(photos)}).",
                ephemeral=True,
            )
            return

        button.disabled = True
        button.label = "Submitted"
        await interaction.response.edit_message(view=self)

        try:
            base = _strip_status(channel.name)
            await channel.edit(name=f"ready-{base}")
        except discord.HTTPException as e:
            print(f"[submit_review] Failed to rename channel: {e}")

        for thread in channel.threads:
            if "mod-controls" in thread.name:
                try:
                    base = _strip_status(thread.name)
                    await thread.edit(name=f"ready-{base}")
                    await thread.send(f"{user.display_name} (ID: {user.id}) submitted photos for review.")
                except discord.HTTPException as e:
                    print(f"[submit_review] Failed to update thread: {e}")
                break

        print(f"[submit_review] {user} submitted {len(photos)} photos in #{channel.name}")


class RejectModal(discord.ui.Modal, title="Reject Verification"):
    reason = discord.ui.TextInput(
        label="Reason",
        placeholder="Why is this verification rejected?",
        style=discord.TextStyle.paragraph,
        max_length=500,
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            f"{interaction.user.mention} rejected this verification.\n**Reason:** {self.reason.value}",
        )
        if interaction.channel.parent:
            await interaction.channel.parent.send(
                f"Verification rejected.\n**Reason:** {self.reason.value}",
            )
            try:
                base = _strip_status(interaction.channel.parent.name)
                await interaction.channel.parent.edit(name=f"rejected-{base}")
            except discord.HTTPException as e:
                print(f"[reject] Failed to rename channel: {e}")
        try:
            base = _strip_status(interaction.channel.name)
            await interaction.channel.edit(name=f"rejected-{base}")
        except discord.HTTPException as e:
            print(f"[reject] Failed to rename thread: {e}")
        print(f"[reject] {interaction.channel.name} rejected by {interaction.user} — {self.reason.value}")


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def _is_mod(self, interaction: discord.Interaction) -> bool:
        mod_role = discord.utils.get(interaction.guild.roles, name=MOD_ROLE_NAME)
        return mod_role is not None and mod_role in interaction.user.roles

    @discord.ui.button(label="Claim", style=discord.ButtonStyle.primary, custom_id="ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_mod(interaction):
            await interaction.response.send_message("Moderators only.", ephemeral=True)
            return

        button.disabled = True
        button.label = f"Claimed by {interaction.user.display_name}"
        await interaction.response.edit_message(view=self)
        await interaction.channel.send(f"{interaction.user.mention} took it in work.")

        try:
            await interaction.channel.edit(name="in-progress-mod-controls")
        except discord.HTTPException as e:
            print(f"[claim] Failed to rename thread: {e}")

        if interaction.channel.parent:
            try:
                base = _strip_status(interaction.channel.parent.name)
                await interaction.channel.parent.edit(name=f"in-progress-{base}")
            except discord.HTTPException as e:
                print(f"[claim] Failed to rename channel: {e}")

        print(f"Verification {interaction.channel.name} claimed by {interaction.user} (ID: {interaction.user.id})")

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.success, custom_id="ticket_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_mod(interaction):
            await interaction.response.send_message("Moderators only.", ephemeral=True)
            return

        user_id = None
        async for msg in interaction.channel.history(limit=10, oldest_first=True):
            for embed in msg.embeds:
                if embed.footer and embed.footer.text and embed.footer.text.startswith("User ID:"):
                    try:
                        user_id = int(embed.footer.text.split("User ID:")[1].strip())
                    except ValueError:
                        pass
            if user_id:
                break

        if not user_id:
            await interaction.response.send_message("Could not find user ID.", ephemeral=True)
            return

        member = interaction.guild.get_member(user_id)
        if not member:
            await interaction.response.send_message("User is no longer in the server.", ephemeral=True)
            return

        verified_role = discord.utils.get(interaction.guild.roles, name=VERIFIED_ROLE_NAME)
        if not verified_role:
            await interaction.response.send_message(
                f"Role '{VERIFIED_ROLE_NAME}' not found on this server.", ephemeral=True
            )
            return

        try:
            await member.add_roles(verified_role, reason=f"Verified by {interaction.user}")
        except discord.Forbidden:
            await interaction.response.send_message("No permission to assign roles.", ephemeral=True)
            return
        except discord.HTTPException as e:
            print(f"[approve] Failed to assign role: {e}")
            await interaction.response.send_message("Failed to assign role.", ephemeral=True)
            return

        button.disabled = True
        button.label = f"Approved by {interaction.user.display_name}"
        await interaction.response.edit_message(view=self)
        await interaction.channel.send(f"{member.display_name} (ID: {member.id}) has been approved.")

        if interaction.channel.parent:
            await interaction.channel.parent.send(
                f"Congratulations {member.mention}, your verification has been approved!"
            )
            try:
                base = _strip_status(interaction.channel.parent.name)
                await interaction.channel.parent.edit(name=f"approved-{base}")
            except discord.HTTPException as e:
                print(f"[approve] Failed to rename channel: {e}")

        try:
            base = _strip_status(interaction.channel.name)
            await interaction.channel.edit(name=f"approved-{base}")
        except discord.HTTPException as e:
            print(f"[approve] Failed to rename thread: {e}")

        print(f"[approve] {member} (ID: {member.id}) verified by {interaction.user}")

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.danger, custom_id="ticket_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._is_mod(interaction):
            await interaction.response.send_message("Moderators only.", ephemeral=True)
            return
        await interaction.response.send_modal(RejectModal())


class Verification(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(OpenTicketView())
        self.bot.add_view(SubmitReviewView())
        self.bot.add_view(TicketControlView())
        await self.bot.tree.sync()

    @discord.app_commands.command(name="verify-panel", description="Post a verification panel (creator only)")
    async def verify_panel(self, interaction: discord.Interaction):
        if interaction.user.id != CREATOR_ID:
            await interaction.response.send_message("Not your toy.", ephemeral=True)
            return

        embed = discord.Embed(
            title="Verification",
            description="Click the button below to submit a verification request.",
            color=discord.Color.blue(),
        )
        _log_missing_perms(
            f"verify-panel / #{interaction.channel.name}",
            interaction.channel.permissions_for(interaction.guild.me),
            ["send_messages", "embed_links", "view_channel"],
        )
        try:
            await interaction.channel.send(embed=embed, view=OpenTicketView())
            await interaction.response.send_message("Panel posted.", ephemeral=True)
        except discord.Forbidden as e:
            print(f"[verify-panel] Forbidden in #{interaction.channel.name}: {e}")
            await interaction.response.send_message(
                "Bot has no permission to send messages in this channel.", ephemeral=True
            )
        except discord.HTTPException as e:
            print(f"[verify-panel] HTTPException: {e}")
            await interaction.response.send_message("Failed to post panel.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Verification(bot))
