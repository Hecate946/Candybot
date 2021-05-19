import os
import time
import asyncio
import asyncpg

from settings import constants

prefixes = dict()
scripts = [x[:-4] for x in sorted(os.listdir("./data/scripts")) if x.endswith(".sql")]
postgres = asyncio.get_event_loop().run_until_complete(
    asyncpg.create_pool(constants.postgres)
)

async def initialize(bot):
    await scriptexec()
    await set_config_id(bot)
    await load_prefixes()

async def set_config_id(bot):
    # Initialize the config table
    # with the bot's client ID.
    query = """
            INSERT INTO config
            VALUES ($1)
            ON CONFLICT (client_id)
            DO NOTHING;
            """
    await postgres.execute(query, bot.user.id)


async def scriptexec():
    # We execute the SQL script to make sure we have all our tables.
    st = time.time()
    for script in scripts:
        with open(f"./data/scripts/{script}.sql", "r", encoding="utf-8") as script:
            try:
                await postgres.execute(script.read())
            except Exception as e:
                print(e)
    print(f"Script execution: {str(time.time() - st)[:10]}s")


async def load_prefixes():
    query = """
            SELECT server_id, ARRAY_REMOVE(ARRAY_AGG(prefix), NULL) as prefix_list
            FROM prefixes GROUP BY server_id;
            """
    records = await postgres.fetch(query)
    for server_id, prefix_list in records:
        prefixes[server_id] = prefix_list
