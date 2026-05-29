import asyncio, json, os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy import text

engine = create_async_engine(os.environ['DATABASE_URL'])

async def q():
    async with AsyncSession(engine) as s:
        r = await s.execute(text("SELECT mcp_name, docker_image, run_config FROM mcps WHERE mcp_name LIKE '%pentest%'"))
        rows = r.fetchall()
        for row in rows:
            print(json.dumps({'name': row[0], 'img': row[1], 'cfg': row[2]}, indent=2))
        if not rows:
            print("NOT FOUND")

asyncio.run(q())
