import asyncio
import datetime as dt
import random
import re
import typing as t
from enum import Enum

import discord
import wavelink
from discord.ext import commands

from settings import constants
from utilities import decorators
from utilities import exceptions

URL_REGEX = r"http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*(),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+"
OPTIONS = {
    constants.emotes['num1']: 0,
    constants.emotes['num2']: 1,
    constants.emotes['num3']: 2,
    constants.emotes['num4']: 3,
    constants.emotes['num5']: 4,
}
OPTIONS = {
    "1️⃣": 0,
    "2⃣": 1,
    "3⃣": 2,
    "4⃣": 3,
    "5⃣": 4,
}
class RepeatMode(Enum):
    NONE = 0
    ONE = 1
    ALL = 2


class Queue:
    def __init__(self):
        self._queue = []
        self.position = 0
        self.repeat_mode = RepeatMode.NONE

    @property
    def is_empty(self):
        return not self._queue

    @property
    def current_track(self):
        if not self._queue:
            raise exceptions.QueueIsEmpty

        if self.position <= len(self._queue) - 1:
            return self._queue[self.position]

    @property
    def upcoming(self):
        if not self._queue:
            raise exceptions.QueueIsEmpty

        return self._queue[self.position + 1:]

    @property
    def history(self):
        if not self._queue:
            raise exceptions.QueueIsEmpty

        return self._queue[:self.position]

    @property
    def length(self):
        return len(self._queue)

    def add(self, *args):
        self._queue.extend(args)

    def get_next_track(self):
        if not self._queue:
            raise exceptions.QueueIsEmpty

        self.position += 1

        if self.position < 0:
            return None
        elif self.position > len(self._queue) - 1:
            if self.repeat_mode == RepeatMode.ALL:
                self.position = 0
            else:
                return None

        return self._queue[self.position]

    def shuffle(self):
        if not self._queue:
            raise exceptions.QueueIsEmpty

        upcoming = self.upcoming
        random.shuffle(upcoming)
        self._queue = self._queue[:self.position + 1]
        self._queue.extend(upcoming)

    def set_repeat_mode(self, mode):
        if mode == "none":
            self.repeat_mode = RepeatMode.NONE
        elif mode == "1":
            self.repeat_mode = RepeatMode.ONE
        elif mode == "all":
            self.repeat_mode = RepeatMode.ALL

    def empty(self):
        self._queue.clear()
        self.position = 0


class Player(wavelink.Player):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.queue = Queue()

    async def connect(self, ctx, channel=None):
        if self.is_connected:
            raise exceptions.AlreadyConnectedToChannel

        if (channel := getattr(ctx.author.voice, "channel", channel)) is None:
            raise exceptions.NoVoiceChannel

        await super().connect(channel.id)
        return channel

    async def teardown(self):
        try:
            await self.destroy()
        except KeyError:
            pass

    async def add_tracks(self, ctx, tracks):
        if not tracks:
            raise exceptions.NoTracksFound

        if isinstance(tracks, wavelink.TrackPlaylist):
            self.queue.add(*tracks.tracks)
        elif len(tracks) == 1:
            self.queue.add(tracks[0])
            await ctx.send(f"Added {tracks[0].title} to the queue.")
        else:
            if (track := await self.choose_track(ctx, tracks)) is not None:
                self.queue.add(track)
                await ctx.send(f"Added {track.title} to the queue.")

        if not self.is_playing and not self.queue.is_empty:
            await self.start_playback()

    async def choose_track(self, ctx, tracks):
        def _check(r, u):
            return (
                r.emoji in OPTIONS.keys()
                and u == ctx.author
                and r.message.id == msg.id
            )

        embed = discord.Embed(
            title="Choose a song",
            description=(
                "\n".join(
                    f"**{i+1}.** {t.title} ({t.length//60000}:{str(t.length%60).zfill(2)})"
                    for i, t in enumerate(tracks[:5])
                )
            ),
            colour=ctx.author.colour,
            timestamp=dt.datetime.utcnow()
        )
        embed.set_author(name="Query Results")
        embed.set_footer(text=f"Invoked by {ctx.author.display_name}", icon_url=ctx.author.avatar_url)

        msg = await ctx.send(embed=embed)
        for emoji in list(OPTIONS.keys())[:min(len(tracks), len(OPTIONS))]:
            await msg.add_reaction(emoji)

        try:
            reaction, _ = await self.bot.wait_for("reaction_add", timeout=60.0, check=_check)
        except asyncio.TimeoutError:
            await msg.delete()
            await ctx.message.delete()
        else:
            await msg.delete()
            return tracks[OPTIONS[reaction.emoji]]

    async def start_playback(self):
        await self.play(self.queue.current_track)

    async def advance(self):
        try:
            if (track := self.queue.get_next_track()) is not None:
                await self.play(track)
        except exceptions.QueueIsEmpty:
            pass

    async def repeat_track(self):
        await self.play(self.queue.current_track)


class Music(commands.Cog, wavelink.WavelinkMixin):
    def __init__(self, bot):
        self.bot = bot
        self.wavelink = wavelink.Client(bot=bot)
        self.bot.loop.create_task(self.start_nodes())
        #self.options = {x for x in self.bot.get_emoji(x) for x in }

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not member.bot and after.channel is None:
            if not [m for m in before.channel.members if not m.bot]:
                await self.get_player(member.guild).teardown()

    @wavelink.WavelinkMixin.listener()
    async def on_node_ready(self, node):
        print(f" Wavelink node `{node.identifier}` ready.")

    @wavelink.WavelinkMixin.listener("on_track_stuck")
    @wavelink.WavelinkMixin.listener("on_track_end")
    @wavelink.WavelinkMixin.listener("on_track_exception")
    async def on_player_stop(self, node, payload):
        if payload.player.queue.repeat_mode == RepeatMode.ONE:
            await payload.player.repeat_track()
        else:
            await payload.player.advance()

    async def cog_check(self, ctx):
        if isinstance(ctx.channel, discord.DMChannel):
            await ctx.send("Music commands are not available in DMs.")
            return False

        return True

    async def start_nodes(self):
        await self.bot.wait_until_ready()

        nodes = {
            "MAIN": {
                "host": "127.0.0.1",
                "port": 2333,
                "rest_uri": "http://127.0.0.1:2333",
                "password": "youshallnotpass",
                "identifier": "MAIN",
                "region": "us_central",
            }
        }

        for node in nodes.values():
            await self.wavelink.initiate_node(**node)

    def get_player(self, obj):
        if isinstance(obj, commands.Context):
            return self.wavelink.get_player(obj.guild.id, cls=Player, context=obj)
        elif isinstance(obj, discord.Guild):
            return self.wavelink.get_player(obj.id, cls=Player)

    @decorators.command(name="connect", aliases=["join"])
    async def connect_command(self, ctx, *, channel: t.Optional[discord.VoiceChannel]):
        player = self.get_player(ctx)
        channel = await player.connect(ctx, channel)
        await ctx.send(f"Connected to {channel.name}.")

    @connect_command.error
    async def connect_command_error(self, ctx, exc):
        if isinstance(exc, exceptions.AlreadyConnectedToChannel):
            await ctx.send("Already connected to a voice channel.")
        elif isinstance(exc, exceptions.NoVoiceChannel):
            await ctx.send("No suitable voice channel was provided.")

    @decorators.command(name="disconnect", aliases=["leave","dc"])
    async def disconnect_command(self, ctx):
        player = self.get_player(ctx)
        await player.teardown()
        await ctx.react("Disconnected.")

    @decorators.command(name="play")
    async def play_command(self, ctx, *, query: t.Optional[str]):
        player = self.get_player(ctx)

        if not player.is_connected:
            await player.connect(ctx)

        if query is None:
            if player.queue.is_empty:
                raise exceptions.QueueIsEmpty

            await player.set_pause(False)
            await ctx.send("Playback resumed.")

        else:
            query = query.strip("<>")
            if not re.match(URL_REGEX, query):
                query = f"ytsearch:{query}"

            await player.add_tracks(ctx, await self.wavelink.get_tracks(query))

    @play_command.error
    async def play_command_error(self, ctx, exc):
        if isinstance(exc, exceptions.QueueIsEmpty):
            await ctx.send("No songs to play as the queue is empty.")
        elif isinstance(exc, exceptions.NoVoiceChannel):
            await ctx.send("No suitable voice channel was provided.")

    @decorators.command(name="pause")
    async def pause_command(self, ctx):
        player = self.get_player(ctx)

        if player.is_paused:
            raise exceptions.PlayerIsAlreadyPaused

        await player.set_pause(True)
        await ctx.send("Playback paused.")

    @pause_command.error
    async def pause_command_error(self, ctx, exc):
        if isinstance(exc, exceptions.PlayerIsAlreadyPaused):
            await ctx.send("Already paused.")

    @decorators.command(name="stop")
    async def stop_command(self, ctx):
        player = self.get_player(ctx)
        player.queue.empty()
        await player.stop()
        await ctx.send("Playback stopped.")

    @decorators.command(name="next", aliases=["skip"])
    async def next_command(self, ctx):
        player = self.get_player(ctx)

        if not player.queue.upcoming:
            raise exceptions.NoMoreTracks

        await player.stop()
        await ctx.send("Playing next track in queue.")

    @next_command.error
    async def next_command_error(self, ctx, exc):
        if isinstance(exc, exceptions.QueueIsEmpty):
            await ctx.send("This could not be executed as the queue is currently empty.")
        elif isinstance(exc, exceptions.NoMoreTracks):
            await ctx.send("There are no more tracks in the queue.")

    @decorators.command(name="previous")
    async def previous_command(self, ctx):
        player = self.get_player(ctx)

        if not player.queue.history:
            raise exceptions.NoPreviousTracks

        player.queue.position -= 2
        await player.stop()
        await ctx.send("Playing previous track in queue.")

    @previous_command.error
    async def previous_command_error(self, ctx, exc):
        if isinstance(exc, exceptions.QueueIsEmpty):
            await ctx.send("This could not be executed as the queue is currently empty.")
        elif isinstance(exc, exceptions.NoPreviousTracks):
            await ctx.send("There are no previous tracks in the queue.")

    @decorators.command(name="shuffle")
    async def shuffle_command(self, ctx):
        player = self.get_player(ctx)
        player.queue.shuffle()
        await ctx.send("Queue shuffled.")

    @shuffle_command.error
    async def shuffle_command_error(self, ctx, exc):
        if isinstance(exc, exceptions.QueueIsEmpty):
            await ctx.send("The queue is currently empty.")

    @decorators.command(name="repeat")
    async def repeat_command(self, ctx, mode: str):
        if mode not in ("none", "1", "all"):
            raise exceptions.InvalidRepeatMode

        player = self.get_player(ctx)
        player.queue.set_repeat_mode(mode)
        await ctx.send(f"The repeat mode has been set to {mode}.")

    @decorators.command(name="queue")
    async def queue_command(self, ctx, show: t.Optional[int] = 10):
        player = self.get_player(ctx)

        if player.queue.is_empty:
            raise exceptions.QueueIsEmpty

        embed = discord.Embed(
            title="Queue",
            description=f"Showing up to next {show} tracks",
            colour=ctx.author.colour,
            timestamp=dt.datetime.utcnow()
        )
        embed.set_author(name="Query Results")
        embed.set_footer(text=f"Requested by {ctx.author.display_name}", icon_url=ctx.author.avatar_url)
        embed.add_field(
            name="Currently playing",
            value=getattr(player.queue.current_track, "title", "No tracks currently playing."),
            inline=False
        )
        if upcoming := player.queue.upcoming:
            embed.add_field(
                name="Next up",
                value="\n".join(t.title for t in upcoming[:show]),
                inline=False
            )

        msg = await ctx.send(embed=embed)

    @queue_command.error
    async def queue_command_error(self, ctx, exc):
        if isinstance(exc, exceptions.QueueIsEmpty):
            await ctx.send("The queue is currently empty.")

    @decorators.command(brief="Seek to a position in the current song.")
    async def seek(self, ctx, position:str = "0"):
        player = self.get_player(ctx)
        max_dur = player.current.duration // 1000
        if not position.isdigit():
            raise commands.BadArgument(f"The `position` argument must be an integer.")
        if int(position) >= max_dur:
            raise commands.BadArgument(f"The `position` argument must be less than the duration of the song. ({max_dur} seconds)")
        position = int(position)

        await player.seek(position * 1000)
        await ctx.message.add_reaction(self.bot.emote_dict['candy'])

    @decorators.command(
        aliases=['ff','fastforward'],
        brief="Fast forward a number of seconds.",
    )
    async def fastfwd(self, ctx, seconds:str = "0"):
        player = self.get_player(ctx)
        max_dur = (player.current.duration - player.position) // 1000
        if not seconds.isdigit():
            raise commands.BadArgument(f"The `seconds` argument must be an integer.")
        if int(seconds) >= max_dur:
            raise commands.BadArgument(f"The `seconds` argument must be less than the remaining duration of the song. ({max_dur} seconds)")
        seconds = int(seconds)

        await player.seek(player.position + seconds * 1000)
        await ctx.message.add_reaction(self.bot.emote_dict['candy'])

    @decorators.command(
        aliases=['fb','rw','fastback'],
        brief="Fast forward a number of seconds.",
    )
    async def rewind(self, ctx, seconds:str = "0"):
        player = self.get_player(ctx)
        max_dur = player.position // 1000
        if not seconds.isdigit():
            raise commands.BadArgument(f"The `seconds` argument must be an integer.")
        if int(seconds) >= max_dur:
            raise commands.BadArgument(f"The `seconds` argument must be less than the duration of the song until now. ({max_dur} seconds)")
        seconds = int(seconds)

        await player.seek(player.position - seconds * 1000)
        await ctx.message.add_reaction(self.bot.emote_dict['candy'])

    

def setup(bot):
    bot.add_cog(Music(bot))