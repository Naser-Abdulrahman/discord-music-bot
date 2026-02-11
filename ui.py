import discord
from discord.ui import View, Button
import asyncio
from state import song_queue
from audio import YTDLSource, start_playing

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
        
        # Number buttons 1-5
        for i, song in enumerate(current_batch):
            self.add_item(SongButton(i, song, self))

        # Add All button
        self.add_item(AddAllButton(current_batch, self))
        
        # Next/More button if there are more results
        if end < len(self.results):
            self.add_item(MoreButton(self))
            
        # Cancel button
        self.add_item(CancelButton(self))

    async def play_song(self, interaction, song):
        url = song.get('webpage_url') or song.get('url')
        title = song.get('title')
        
        if not self.ctx.voice_client:
             if self.ctx.author.voice:
                 await self.ctx.author.voice.channel.connect()
             else:
                 await self.ctx.send("You are not connected to a voice channel.")
                 return

        voice_client = self.ctx.voice_client
        
        if voice_client.is_playing():
            song_queue.append(url)
            await interaction.followup.send(f"Added to queue: **{title}**", ephemeral=True)
        else:
             await interaction.followup.send(f"Playing **{title}**...", ephemeral=True)
             try:
                # Direct playback if queue empty and not playing
                # But wait, logic mirrors play command: append then check if playing.
                # Here we just check is_playing. If false, we play immediately.
                
                # We can reuse play_next logic by pushing to queue and calling play_next?
                # Yes, but strictly speaking SongSelectionView logic in main.py was slightly explicitly duplicated.
                # Let's standardize:
                song_queue.append(url)
                # Now trigger play_next if not playing
                # But play_next pops from queue.
                # If we just appended, play_next will pop it.
                
                await start_playing(self.ctx)
                
             except Exception as e:
                 await interaction.followup.send(f"Error starting playback: {e}", ephemeral=True)

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
        for song in self.batch:
            await self.view_ref.play_song(interaction, song)
        await interaction.followup.send(f"Added {len(self.batch)} songs to queue.", ephemeral=True)

class MoreButton(Button):
    def __init__(self, view_ref):
        super().__init__(label="More Results", style=discord.ButtonStyle.secondary)
        self.view_ref = view_ref
        
    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.view_ref.current_page += 1
        self.view_ref.update_buttons()
        start = self.view_ref.current_page * self.view_ref.per_page
        end = start + self.view_ref.per_page
        batch = self.view_ref.results[start:end]
        
        desc = ""
        for i, song in enumerate(batch):
            desc += f"**{i+1}.** {song.get('title')}\n"
            
        await interaction.message.edit(content=f"**Search Results (Page {self.view_ref.current_page + 1}):**\n{desc}", view=self.view_ref)

class CancelButton(Button):
    def __init__(self, view_ref):
        super().__init__(label="Cancel", style=discord.ButtonStyle.danger)
        self.view_ref = view_ref
        
    async def callback(self, interaction: discord.Interaction):
        await interaction.message.delete()
        self.view_ref.stop()
