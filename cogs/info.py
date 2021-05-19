import io
import os
import sys
import time
import codecs
import psutil
import struct
import asyncio
import discord
import inspect
import pathlib
import datetime
import platform
import statistics
import subprocess
import collections

from discord import __version__ as dv
from discord.ext import commands, menus

from utilities import utils
from utilities import checks
from utilities import decorators
from utilities import pagination


def setup(bot):
    bot.add_cog(Info(bot))


class Info(commands.Cog):
    """
    Module for bot information.
    """

    def __init__(self, bot):
        self.bot = bot
        self.socket_event_total = 0
        self.process = psutil.Process(os.getpid())
        self.socket_since = datetime.datetime.utcnow()
        self.message_latencies = collections.deque(maxlen=500)

    @commands.Cog.listener()
    @decorators.wait_until_ready()
    async def on_message(self, message):
        now = datetime.datetime.utcnow()
        self.message_latencies.append((now, now - message.created_at))

    @commands.Cog.listener()  # Update our socket counters
    async def on_socket_response(self, msg: dict):
        """When a websocket event is received, increase our counters."""
        if event_type := msg.get("t"):
            self.socket_event_total += 1
            self.bot.socket_events[event_type] += 1

    async def total_global_commands(self):
        query = """SELECT COUNT(*) FROM commands"""
        value = await self.bot.cxn.fetchval(query)
        return value

    async def total_global_messages(self):
        query = """
                SELECT COUNT(*)
                FROM commands
                WHERE command = 'play';
                """
        value = await self.bot.cxn.fetchval(query)
        return value

    @decorators.command(
        aliases=["info", "bot", "botstats", "botinfo"],
        brief="Display information about the bot.",
        implemented="2021-03-15 22:27:29.973811",
        updated="2021-05-06 00:06:19.096095",
    )
    @checks.bot_has_perms(embed_links=True)
    async def about(self, ctx):
        """
        Usage: {0}about
        Aliases: {0}info, {0}bot, {0}botstats, {0}botinfo
        Output: Version info and bot stats
        """
        msg = await ctx.send_or_reply(
            content=f"**{self.bot.emote_dict['loading']} Collecting Bot Info...**"
        )
        version_query = """
                        SELECT version
                        FROM config
                        WHERE client_id = $1;
                        """
        bot_version = await self.bot.cxn.fetchval(version_query, self.bot.user.id)
        total_members = sum(1 for x in self.bot.get_all_members())
        voice_channels = []
        text_channels = []
        for guild in self.bot.guilds:
            voice_channels.extend(guild.voice_channels)
            text_channels.extend(guild.text_channels)

        text = len(text_channels)
        voice = len(voice_channels)

        ram_usage = self.process.memory_full_info().rss / 1024 ** 2
        proc = psutil.Process()
        with proc.oneshot():
            mem_total = psutil.virtual_memory().total / (1024 ** 2)
            mem_of_total = proc.memory_percent()

        embed = discord.Embed(colour=self.bot.constants.embed)
        embed.set_thumbnail(url=self.bot.user.avatar_url)
        embed.add_field(
            name="Last boot",
            value=str(
                utils.timeago(datetime.datetime.utcnow() - self.bot.uptime)
            ).capitalize(),
            inline=True,
        )
        embed.add_field(
            name=f"Developer{'' if len(self.bot.constants.owners) == 1 else 's'}",
            value=",\n ".join(
                [str(self.bot.get_user(x)) for x in self.bot.constants.owners]
            ),
            inline=True,
        )
        embed.add_field(
            name="Python Version", value=f"{platform.python_version()}", inline=True
        )
        embed.add_field(name="Library", value="Discord.py", inline=True)
        embed.add_field(name="API Version", value=f"{dv}", inline=True)
        embed.add_field(
            name="Command Count",
            value=len([x.name for x in self.bot.commands if not x.hidden]),
            inline=True,
        )
        embed.add_field(
            name="Server Count", value=f"{len(ctx.bot.guilds):,}", inline=True
        )
        embed.add_field(
            name="Channel Count",
            value=f"""{self.bot.emote_dict['textchannel']} {text:,}        {self.bot.emote_dict['voicechannel']} {voice:,}""",
            inline=True,
        )
        embed.add_field(name="Member Count", value=f"{total_members:,}", inline=True)
        embed.add_field(
            name="Commands Run",
            value=f"{await self.total_global_commands():,}",
            inline=True,
        )
        embed.add_field(
            name="Songs Played",
            value=f"{await self.total_global_messages():,}",
            inline=True,
        )
        embed.add_field(name="RAM", value=f"{ram_usage:.2f} MB", inline=True)

        await msg.edit(
            content=f"{self.bot.emote_dict['candy']} About **{ctx.bot.user}** | **{round(bot_version, 1)}**",
            embed=embed,
        )

    @decorators.command(
        aliases=["socketstats"],
        brief="Show global bot socket stats.",
        implemented="2021-03-18 17:55:01.726405",
        updated="2021-05-07 18:00:54.076428",
        examples="""
                {0}socket
                {0}socketstats
                """,
    )
    @checks.bot_has_perms(add_reactions=True, external_emojis=True)
    async def socket(self, ctx):
        """
        Usage: {0}socket
        Alias: {0}socketstats
        Output:
            Fetch information on the socket
            events received from Discord.
        """
        running_s = (datetime.datetime.utcnow() - self.socket_since).total_seconds()

        per_s = self.socket_event_total / running_s

        width = len(max(self.bot.socket_events, key=lambda x: len(str(x))))

        line = "\n".join(
            "{0:<{1}} : {2:>{3}}".format(
                str(event_type), width, count, len(max(str(count)))
            )
            for event_type, count in self.bot.socket_events.most_common()
        )

        header = (
            "**Receiving {0:0.2f} socket events per second** | **Total: {1}**\n".format(
                per_s, self.socket_event_total
            )
        )

        m = pagination.MainMenu(
            pagination.TextPageSource(line, prefix="```yaml", max_size=500)
        )
        await ctx.send_or_reply(header)
        try:

            await m.start(ctx)
        except menus.MenuError as e:
            await ctx.send_or_reply(e)

    @decorators.command(
        aliases=["averageping", "averagelatency", "averagelat"],
        brief="View the average message latency.",
        implemented="2021-05-10 22:39:37.374649",
        updated="2021-05-10 22:39:37.374649",
    )
    async def avgping(self, ctx):
        """
        Usage: {0}avgping
        Aliases:
            {0}averageping
            {0}avglat
            {0}avglatency
        Output:
            Shows the average message latency
            over the past 500 messages send.
        """
        await ctx.send(
            "{:.2f}ms".format(
                1000
                * statistics.mean(
                    lat.total_seconds() for ts, lat in self.message_latencies
                )
            )
        )

    @decorators.command(
        brief="Show reply latencies.",
        implemented="2021-05-10 23:53:06.937010",
        updated="2021-05-10 23:53:06.937010",
    )
    async def replytime(self, ctx):
        """
        Usage: {0}replytime
        Output:
            Shows 3 times showing the
            discrepancy between timestamps.
        """
        recv_time = ctx.message.created_at
        msg_content = "."

        task = asyncio.ensure_future(
            self.bot.wait_for(
                "message",
                timeout=15,
                check=lambda m: (m.author == ctx.bot.user and m.content == msg_content),
            )
        )
        now = datetime.datetime.utcnow()
        sent_message = await ctx.send(msg_content)
        await task
        rtt_time = datetime.datetime.utcnow()
        content = "```prolog\n"
        content += "Client Timestamp - Discord  Timestamp: {:.2f}ms\n"
        content += "Posted Timestamp - Response Timestamp: {:.2f}ms\n"
        content += "Sent   Timestamp - Received Timestamp: {:.2f}ms\n"
        content += "```"
        await sent_message.edit(
            content=content.format(
                (now - recv_time).total_seconds() * 1000,
                (sent_message.created_at - recv_time).total_seconds() * 1000,
                (rtt_time - now).total_seconds() * 1000,
            )
        )

    @decorators.command(
        aliases=["reportbug", "reportissue", "issuereport"],
        brief="Send a bugreport to the developer.",
        implemented="2021-03-26 19:10:10.345853",
    )
    @commands.cooldown(2, 60, commands.BucketType.user)
    async def bugreport(self, ctx, *, bug):
        """
        Usage:    {0}bugreport <report>
        Aliases:  {0}issuereport, {0}reportbug, {0}reportissue
        Examples: {0}bugreport Hello! I found a bug with Snowbot
        Output:   Confirmation that your bug report has been sent.
        Notes:
            Do not hesitate to use this command,
            but please be very specific when describing the bug so
            that the developer may easily see the issue and
            correct it as soon as possible.
        """
        author = ctx.message.author
        if ctx.guild:
            server = ctx.message.guild
            source = "server **{}** ({})".format(server.name, server.id)
        else:
            source = "a direct message"
        sender = "**{0}** ({0.id}) sent you a bug report from {1}:\n\n".format(
            author, source
        )
        message = sender + bug
        try:
            await self.bot.hecate.send(message)
        except discord.errors.InvalidArgument:
            await ctx.send_or_reply(
                "I cannot send your bug report, I'm unable to find my owner."
            )
        except discord.errors.HTTPException:
            await ctx.fail("Your bug report is too long.")
        except Exception:
            await ctx.fail("I'm currently unable to deliver your bug report.")
        else:
            if ctx.guild:
                if ctx.channel.permissions_for(ctx.guild.me):
                    await ctx.react(self.bot.emote_dict["letter"])
            else:
                await ctx.react(self.bot.emote_dict["letter"])
            await ctx.success(
                content="Your bug report has been sent.",
            )

    @decorators.command(
        brief="Send a suggestion to the developer.", aliases=["suggestion"]
    )
    @commands.cooldown(2, 60, commands.BucketType.user)
    async def suggest(self, ctx, *, suggestion: str = None):
        """
        Usage:    {0}suggest <report>
        Alias:  {0}suggestion
        Examples: {0}suggest Hello! You should add this feature...
        Output:   Confirmation that your suggestion has been sent.
        Notes:
            Do not hesitate to use this command,
            your feedback is valued immensly.
            However, please be detailed and concise.
        """
        if suggestion is None:
            return await ctx.send_or_reply(
                content=f"Usage `{ctx.prefix}suggest <suggestion>`",
            )
        author = ctx.author
        if ctx.guild:
            server = ctx.guild
            source = "server **{}** ({})".format(server.name, server.id)
        else:
            source = "a direct message"
        sender = "**{}** ({}) sent you a suggestion from {}:\n\n".format(
            author, author.id, source
        )
        message = sender + suggestion
        try:
            await self.bot.hecate.send(message)
        except discord.errors.InvalidArgument:
            await ctx.send_or_reply(content="I cannot send your message")
        except discord.errors.HTTPException:
            await ctx.fail("Your message is too long.")
        except Exception:
            await ctx.fail("I'm currently unable to deliver your message.")
        else:
            if ctx.guild:
                if ctx.channel.permissions_for(ctx.guild.me):
                    await ctx.react(self.bot.emote_dict["letter"])
            else:
                await ctx.react(self.bot.emote_dict["letter"])
            await ctx.success(
                content="Your message has been sent.",
            )

    @decorators.command(brief="Show the bot's uptime.", aliases=["runtime"])
    async def uptime(self, ctx):
        """
        Usage: {0}uptime
        Alias: {0}runtime
        Output: Time since last boot.
        """
        uptime = utils.time_between(self.bot.starttime, int(time.time()))
        await ctx.send_or_reply(
            f"{self.bot.emote_dict['stopwatch']} I've been running for `{uptime}`"
        )

    @decorators.command(
        brief="Test the bot's response latency.",
        aliases=["latency", "response"],
    )
    async def ping(self, ctx):
        """
        Usage: {0}ping
        Aliases: {0}latency, {0}response
        Output: Bot latency statistics.
        Notes:
            Use {0}speed and the bot will attempt
            to run an internet speedtest. May fail.
        """
        async with ctx.channel.typing():
            start = time.time()
            message = await ctx.send_or_reply(
                content=f'{self.bot.emote_dict["loading"]} **Calculating Latency...**',
            )
            end = time.time()

            db_start = time.time()
            await self.bot.cxn.fetch("SELECT 1;")
            elapsed = time.time() - db_start

            p = str(round((end - start) * 1000, 2))
            q = str(round(self.bot.latency * 1000, 2))

            v = str(round((elapsed) * 1000, 2))

            formatter = []
            formatter.append(p)
            formatter.append(q)
            formatter.append(v)
            width = max(len(a) for a in formatter)

            msg = "**Results:**\n"
            msg += "```yaml\n"
            msg += "Latency : {} ms\n".format(q.ljust(width, " "))
            msg += "Response: {} ms\n".format(p.ljust(width, " "))
            msg += "Database: {} ms\n".format(v.ljust(width, " "))
            msg += "```"
        await message.edit(content=msg)

    @decorators.command(brief="Show the bot's host environment.")
    async def hostinfo(self, ctx):
        """
        Usage: {0}hostinfo
        Output: Detailed information on the bot's host environment
        """
        message = await ctx.channel.send(
            f'{self.bot.emote_dict["loading"]} **Collecting Information...**'
        )

        with self.process.oneshot():
            process = self.process.name
        swap = psutil.swap_memory()

        processName = self.process.name()
        pid = self.process.ppid()
        swapUsage = "{0:.1f}".format(((swap[1] / 1024) / 1024) / 1024)
        swapTotal = "{0:.1f}".format(((swap[0] / 1024) / 1024) / 1024)
        swapPerc = swap[3]
        cpuCores = psutil.cpu_count(logical=False)
        cpuThread = psutil.cpu_count()
        cpuUsage = psutil.cpu_percent(interval=1)
        memStats = psutil.virtual_memory()
        memPerc = memStats.percent
        memUsed = memStats.used
        memTotal = memStats.total
        memUsedGB = "{0:.1f}".format(((memUsed / 1024) / 1024) / 1024)
        memTotalGB = "{0:.1f}".format(((memTotal / 1024) / 1024) / 1024)
        currentOS = platform.platform()
        system = platform.system()
        release = platform.release()
        version = platform.version()
        processor = platform.processor()
        botOwner = self.bot.get_user(self.bot.constants.owners[0])
        botName = self.bot.user
        currentTime = int(time.time())
        timeString = utils.time_between(self.bot.starttime, currentTime)
        pythonMajor = sys.version_info.major
        pythonMinor = sys.version_info.minor
        pythonMicro = sys.version_info.micro
        pythonRelease = sys.version_info.releaselevel
        pyBit = struct.calcsize("P") * 8
        process = subprocess.Popen(
            ["git", "rev-parse", "--short", "HEAD"], shell=False, stdout=subprocess.PIPE
        )
        git_head_hash = process.communicate()[0].strip()

        threadString = "thread"
        if not cpuThread == 1:
            threadString += "s"

        msg = "***{}'s*** ***Home:***\n".format(botName)
        msg += "```fix\n"
        msg += "OS       : {}\n".format(currentOS)
        msg += "Owner    : {}\n".format(botOwner)
        msg += "Client   : {}\n".format(botName)
        msg += "Commit   : {}\n".format(git_head_hash.decode("utf-8"))
        msg += "Uptime   : {}\n".format(timeString)
        msg += "Process  : {}\n".format(processName)
        msg += "PID      : {}\n".format(pid)
        msg += "Hostname : {}\n".format(platform.node())
        msg += "Language : Python {}.{}.{} {} ({} bit)\n".format(
            pythonMajor, pythonMinor, pythonMicro, pythonRelease, pyBit
        )
        msg += "Processor: {}\n".format(processor)
        msg += "System   : {}\n".format(system)
        msg += "Release  : {}\n".format(release)
        msg += "CPU Core : {} Threads\n\n".format(cpuCores)
        msg += (
            utils.center(
                "{}% of {} {}".format(cpuUsage, cpuThread, threadString), "CPU"
            )
            + "\n"
        )
        msg += utils.makeBar(int(round(cpuUsage))) + "\n\n"
        msg += (
            utils.center(
                "{} ({}%) of {}GB used".format(memUsedGB, memPerc, memTotalGB), "RAM"
            )
            + "\n"
        )
        msg += utils.makeBar(int(round(memPerc))) + "\n\n"
        msg += (
            utils.center(
                "{} ({}%) of {}GB used".format(swapUsage, swapPerc, swapTotal), "Swap"
            )
            + "\n"
        )
        msg += utils.makeBar(int(round(swapPerc))) + "\n"
        # msg += 'Processor Version: {}\n\n'.format(version)
        msg += "```"

        await message.edit(content=msg)

    @decorators.command(
        aliases=["purpose"],
        brief="Show some info on the bot's purpose.",
        botperms=["embed_links"],
        implemented="2021-03-15 19:38:03.463155",
        updated="2021-05-06 01:12:57.626085",
    )
    @checks.bot_has_perms(embed_links=True)
    async def overview(self, ctx):
        """
        Usage:  {0}overview
        Alias:  {0}purpose
        Output: Me and my purpose
        """

        owner, command_list, category_list = self.bot.public_stats()
        with open("./data/txts/overview.txt", "r", encoding="utf-8") as fp:
            overview = fp.read()
        embed = discord.Embed(
            description=overview.format(
                self.bot.user.name, len(command_list), len(category_list)
            ),
            color=self.bot.constants.embed,
        )
        embed.set_author(name=owner, icon_url=owner.avatar_url)
        await ctx.send_or_reply(embed=embed)

    @decorators.command(brief="Show my changelog.", aliases=["updates"])
    async def changelog(self, ctx):
        """
        Usage: -changelog
        Alias: -updates
        Output: My changelog
        """
        with open("./data/txts/changelog.txt", "r", encoding="utf-8") as fp:
            changelog = fp.read()
        await ctx.send_or_reply(
            content=f"**{self.bot.user.name}'s Changelog**",
        )
        p = pagination.MainMenu(
            pagination.TextPageSource(changelog, prefix="```prolog")
        )
        try:
            await p.start(ctx)
        except menus.MenuError as e:
            await ctx.send_or_reply(e)

    @decorators.command(brief="Display the source code.", aliases=["sourcecode","src"])
    async def source(self, ctx, *, command: str = None):
        """
        Usage: {0}source [command]
        Alias: {0}sourcecode, {0}src
        Notes:
            If no command is specified, shows full repository
        """
        source_url = "https://github.com/Hecate946/Snowbot"
        branch = "main"
        if command is None:
            return await ctx.send_or_reply("<"+source_url+">")

        else:
            obj = self.bot.get_command(command.replace(".", " "))
            if obj is None:
                return await ctx.send_or_reply(
                    f'{self.bot.emote_dict["failed"]} Command `{command}` does not exist.'
                )
            # Show source for all commands so comment this out.
            # elif obj.hidden:
            #     return await ctx.send_or_reply(
            #         f'{self.bot.emote_dict["failed"]} Command `{command}` does not exist.'
            #     )

            src = obj.callback.__code__
            module = obj.callback.__module__
            filename = src.co_filename

        lines, firstlineno = inspect.getsourcelines(src)
        if not module.startswith("discord"):
            # not a built-in command
            location = os.path.relpath(filename).replace("\\", "/")
        else:
            location = module.replace(".", "/") + ".py"
            source_url = "https://github.com/Hecate946/Snowbot"
            branch = "main"

        final_url = f"<{source_url}/blob/{branch}/{location}#L{firstlineno}-L{firstlineno + len(lines) - 1}>"
        msg = f"**__My source {'' if command is None else f'for {command}'} is located at:__**\n\n{final_url}"
        await ctx.send_or_reply(msg)


    @decorators.command(
        brief="Invite me to your server!",
        aliases=["botinvite", "bi"],
        implemented="2021-05-05 18:05:30.156694",
        updated="2021-05-05 18:05:30.156694",
    )
    async def invite(self, ctx):
        """
        Usage: -invite
        Aliases:
            -bi, botinvite
        Output:
            An invite link to invite me to your server
        """
        await self.bot.get_command("oauth").__call__(ctx)

    @decorators.command(
        aliases=["sup", "assistance", "assist"],
        brief="Join my support server!",
        implemented="2021-04-12 23:31:35.165019",
        updated="2021-05-06 01:24:02.569676",
    )
    async def support(self, ctx):
        """
        Usage: {0}support
        Aliases: {0}sup, {0}assist, {0}assistance
        Output: An invite link to my support server
        """
        await ctx.reply(self.bot.constants.support)

    @decorators.command(
        aliases=["userstats", "usercount"],
        brief="Show users I'm connected to.",
        botperms=["embed_links"],
        implemented="2021-03-23 04:20:58.938991",
        updated="2021-05-06 01:30:32.347076",
    )
    @checks.bot_has_perms(embed_links=True)
    async def users(self, ctx):
        """
        Usage: {0}users
        Aliases: {0}userstats, {0}usercount
        Output:
            Shows users and bots I'm connected to and
            percentages of unique and online members.
        """
        async with ctx.channel.typing():
            msg = await ctx.send_or_reply(
                content=f"{self.bot.emote_dict['loading']} **Collecting User Stats...**",
            )
            users = [x for x in self.bot.get_all_members() if not x.bot]
            users_online = [x for x in users if x.status != discord.Status.offline]
            unique_users = set([x.id for x in users])
            bots = [x for x in self.bot.get_all_members() if x.bot]
            bots_online = [x for x in bots if x.status != discord.Status.offline]
            unique_bots = set([x.id for x in bots])
            e = discord.Embed(title="User Stats", color=self.bot.constants.embed)
            e.add_field(
                name="Humans",
                value="{:,}/{:,} online ({:,g}%) - {:,} unique ({:,g}%)".format(
                    len(users_online),
                    len(users),
                    round((len(users_online) / len(users)) * 100, 2),
                    len(unique_users),
                    round((len(unique_users) / len(users)) * 100, 2),
                ),
                inline=False,
            )
            e.add_field(
                name="Bots",
                value="{:,}/{:,} online ({:,g}%) - {:,} unique ({:,g}%)".format(
                    len(bots_online),
                    len(bots),
                    round((len(bots_online) / len(bots)) * 100, 2),
                    len(unique_bots),
                    round(len(unique_bots) / len(bots) * 100, 2),
                ),
                inline=False,
            )
            e.add_field(
                name="Total",
                value="{:,}/{:,} online ({:,g}%)".format(
                    len(users_online) + len(bots_online),
                    len(users) + len(bots),
                    round(
                        (
                            (len(users_online) + len(bots_online))
                            / (len(users) + len(bots))
                        )
                        * 100,
                        2,
                    ),
                ),
                inline=False,
            )
            await msg.edit(content=None, embed=e)

    @decorators.command(
        aliases=["code", "cloc", "codeinfo"],
        brief="Show sourcecode statistics.",
        botperms=["embed_links"],
        implemented="2021-03-22 08:19:35.838365",
        updated="2021-05-06 01:21:46.580294",
    )
    @checks.bot_has_perms(embed_links=True)
    async def lines(self, ctx):
        """
        Usage: {0}lines
        Aliases: {0}cloc, {0}code, {0}codeinfo
        Output:
            Gives the linecount, characters, imports, functions,
            classes, comments, and files within the source code.
        """
        async with ctx.channel.typing():
            msg = "```fix\n"
            lines = 0
            file_amount = 0
            comments = 0
            funcs = 0
            classes = 0
            chars = 0
            imports = 0
            exclude = set([".testervenv", ".git", "__pycache__", ".vscode"])
            for path, subdirs, files in os.walk("."):
                [subdirs.remove(d) for d in list(subdirs) if d in exclude]
                for name in files:
                    if name.endswith(".py"):
                        file_amount += 1
                        with codecs.open(
                            "./" + str(pathlib.PurePath(path, name)), "r", "utf-8"
                        ) as f:
                            for l in f:
                                chars += len(l.strip())
                                if l.strip().startswith("#"):
                                    comments += 1
                                elif len(l.strip()) == 0:
                                    pass
                                else:
                                    lines += 1
                                    if l.strip().startswith(
                                        "def"
                                    ) or l.strip().startswith("async"):
                                        funcs += 1
                                    elif l.strip().startswith("class"):
                                        classes += 1
                                    elif l.strip().startswith(
                                        "import"
                                    ) or l.strip().startswith("from"):
                                        imports += 1
            width = max(
                len(f"{lines:,}"),
                len(f"{file_amount:,}"),
                len(f"{chars:,}"),
                len(f"{imports:,}"),
                len(f"{classes:,}"),
                len(f"{funcs:,}"),
                len(f"{comments:,}"),
            )
            files = "{:,}".format(file_amount)
            lines = "{:,}".format(lines)
            chars = "{:,}".format(chars)
            imports = "{:,}".format(imports)
            classes = "{:,}".format(classes)
            funcs = "{:,}".format(funcs)
            comments = "{:,}".format(comments)
            msg += f"{files.ljust(width)} Files\n"
            msg += f"{lines.ljust(width)} Lines\n"
            msg += f"{chars.ljust(width)} Characters\n"
            msg += f"{imports.ljust(width)} Imports\n"
            msg += f"{classes.ljust(width)} Classes\n"
            msg += f"{funcs.ljust(width)} Functions\n"
            msg += f"{comments.ljust(width)} Comments"
            msg += "```"
            em = discord.Embed(color=self.bot.constants.embed)
            em.title = f"{self.bot.emote_dict['info']}  Source information"
            em.description = msg
            await ctx.send_or_reply(embed=em)

    @decorators.command(
        aliases=["badmins"],
        brief="Show the bot's admins.",
        botperms=["embed_links", "external_emojis", "add_reactions"],
        implemented="2021-04-02 21:37:49.068681",
        updated="2021-05-05 19:08:47.761913",
    )
    @checks.bot_has_perms(
        embed_links=True,
        add_reactions=True,
        external_emojis=True,
    )
    async def botadmins(self, ctx):
        """
        Usage: {0}botadmins
        Alias: {0}badmins
        Output:
            An embed of all the current bot admins
        """
        our_list = []
        for user_id in self.bot.constants.admins:
            user = self.bot.get_user(user_id)
            our_list.append({"name": f"**{str(user)}**", "value": f"ID: `{user.id}`"})
        p = pagination.MainMenu(
            pagination.FieldPageSource(
                entries=[
                    ("{}. {}".format(y + 1, x["name"]), x["value"])
                    for y, x in enumerate(our_list)
                ],
                title="My Admins ({:,} total)".format(len(self.bot.constants.admins)),
                per_page=15,
            )
        )

        try:
            await p.start(ctx)
        except menus.MenuError as e:
            await ctx.send_or_reply(e)

    @decorators.command(
        aliases=["owners"],
        brief="Show the bot's owners.",
        botperms=["embed_links", "external_emojis", "add_reactions"],
        implemented="2021-04-12 06:23:15.545363",
        updated="2021-05-05 19:08:47.761913",
    )
    @checks.bot_has_perms(
        embed_links=True,
        add_reactions=True,
        external_emojis=True,
    )
    async def botowners(self, ctx):
        """
        Usage: {0}botowners
        Alias: {0}owners
        Output:
            An embed of the bot's owners
        """
        our_list = []
        for user_id in self.bot.constants.owners:
            user = self.bot.get_user(user_id)
            our_list.append({"name": f"**{str(user)}**", "value": f"ID: `{user.id}`"})
        p = pagination.MainMenu(
            pagination.FieldPageSource(
                entries=[
                    ("{}. {}".format(y + 1, x["name"]), x["value"])
                    for y, x in enumerate(our_list)
                ],
                title="My Owners ({:,} total)".format(len(self.bot.constants.owners)),
                per_page=15,
            )
        )
        try:
            await p.start(ctx)
        except menus.MenuError as e:
            await ctx.send_or_reply(e)

