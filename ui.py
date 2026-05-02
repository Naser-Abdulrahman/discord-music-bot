import asyncio
import logging

import discord
from discord.ui import Button, View

from audio import YTDLSource, start_playing
from state import song_queue

logger = logging.getLogger(__name__)


class SongSelectionView(View):
    def __init__(self, ctx, results, per_page=5):
        super().__init__(timeout=60)
        self.ctx = ctx
        self.results = results
        self.per_page = per_page
        self.current_page = 0
        self.message = None
        self.update_buttons()

    def update_buttons(self):
        self.clear_items()
        start = self.current_page * self.per_page
        end = start + self.per_page
        current_batch = self.results[start:end]

        for i, song in enumerate(current_batch):
            self.add_item(SongButton(i, song, self))

        self.add_item(AddAllButton(current_batch, self))

        if end < len(self.results):
            self.add_item(MoreButton(self))

        self.add_item(CancelButton(self))

    async def play_song(self, interaction, song):
        url = song.get('webpage_url') or song.get('url')
        title = song.get('title')

        try:
            if not self.ctx.voice_client:
                if self.ctx.author.voice:
                    await self.ctx.author.voice.channel.connect()
                else:
                    await self.ctx.send("You are not connected to a voice channel.")
                    return

            voice_client = self.ctx.voice_client

            if not url:
                await interaction.followup.send(f"Could not resolve **{title}** to a playable URL.", ephemeral=True)
                return

            if voice_client.is_playing():
                song_queue.append({"url": url, "user_id": interaction.user.id})
                await interaction.followup.send(f"Added to queue: **{title}**", ephemeral=True)
            else:
                await interaction.followup.send(f"Playing **{title}**...", ephemeral=True)
                song_queue.append({"url": url, "user_id": interaction.user.id})
                await start_playing(self.ctx)
        except Exception:
            logger.exception("Failed to play selected song %r", title)
            await interaction.followup.send("Could not start playback for that selection.", ephemeral=True)


class SongButton(Button):
    def __init__(self, index, song, view_ref):
        super().__init__(label=str(index + 1), style=discord.ButtonStyle.primary)
        self.song = song
        self.view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.view_ref.play_song(interaction, self.song)


class AddAllButton(Button):
    def __init__(self, batch, view_ref):
        super().__init__(label="Add All", style=discord.ButtonStyle.success)
        self.batch = batch
        self.view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            added = 0
            for song in self.batch:
                await self.view_ref.play_song(interaction, song)
                added += 1
            await interaction.followup.send(f"Added {added} songs to queue.", ephemeral=True)
        except Exception:
            logger.exception("Add All failed")
            await interaction.followup.send("Could not add all tracks.", ephemeral=True)


class MoreButton(Button):
    def __init__(self, view_ref):
        super().__init__(label="More Results", style=discord.ButtonStyle.secondary)
        self.view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        try:
            self.view_ref.current_page += 1
            self.view_ref.update_buttons()
            start = self.view_ref.current_page * self.view_ref.per_page
            end = start + self.view_ref.per_page
            batch = self.view_ref.results[start:end]

            desc = ""
            for i, song in enumerate(batch):
                desc += f"**{i+1}.** {song.get('title')}\n"

            await interaction.message.edit(content=f"**Search Results (Page {self.view_ref.current_page + 1}):**\n{desc}", view=self.view_ref)
        except Exception:
            logger.exception("Failed to advance search results page")
            await interaction.followup.send("Could not load the next page.", ephemeral=True)


class CancelButton(Button):
    def __init__(self, view_ref):
        super().__init__(label="Cancel", style=discord.ButtonStyle.danger)
        self.view_ref = view_ref

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.message.delete()
            self.view_ref.stop()
        except Exception:
            logger.exception("Failed to cancel search view")
            await interaction.response.send_message("Could not cancel the view cleanly.", ephemeral=True)
