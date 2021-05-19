import asyncio
import discord
import logging
import json
from discord.ext import commands, tasks
from utilities import decorators

command_logger = logging.getLogger("Candybot")

def setup(bot):
    bot.add_cog(Moniter(bot))

class Moniter(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.batch_lock = asyncio.Lock(loop=bot.loop)
        self.command_batch = list()
        self.bulk_inserter.start()

    def cog_unload(self):
        self.bulk_inserter.cancel()

    
    @tasks.loop(seconds=1.0)
    async def bulk_inserter(self):
        # Insert all the commands executed.
        if self.command_batch:
            query = """
                    INSERT INTO commands (
                        server_id, channel_id,
                        author_id, timestamp,
                        prefix, command, failed
                    )
                    SELECT x.server, x.channel,
                           x.author, x.timestamp,
                           x.prefix, x.command, x.failed
                    FROM jsonb_to_recordset($1::jsonb)
                    AS x(
                        server BIGINT, channel BIGINT,
                        author BIGINT, timestamp TIMESTAMP,
                        prefix TEXT, command TEXT, failed BOOLEAN
                    )
                    """
            async with self.batch_lock:
                data = json.dumps(self.command_batch)
                await self.bot.cxn.execute(query, str(data))

                # Command logger to ./data/logs/commands.log
                destination = None
                for x in self.command_batch:
                    if x["server"] is None:
                        destination = "Private Message"
                    else:
                        destination = f"#{self.bot.get_channel(x['channel'])} [{x['channel']}] ({self.bot.get_guild(x['server'])}) [{x['server']}]"
                    command_logger.info(
                        f"{self.bot.get_user(x['author'])} in {destination}: {x['content']}"
                    )
                self.command_batch.clear()

    @commands.Cog.listener()
    @decorators.wait_until_ready()
    async def on_command(self, ctx):
        command = ctx.command.qualified_name
        self.bot.command_stats[command] += 1
        if ctx.guild:
            server_id = ctx.guild.id
        else:
            server_id = None
        async with self.batch_lock:
            self.command_batch.append(
                {
                    "server": server_id,
                    "channel": ctx.channel.id,
                    "author": ctx.author.id,
                    "timestamp": str(ctx.message.created_at.utcnow()),
                    "prefix": ctx.prefix,
                    "command": ctx.command.qualified_name,
                    "failed": ctx.command_failed,
                    "content": ctx.message.clean_content,
                }
            )