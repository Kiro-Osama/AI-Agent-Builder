import asyncio
import os
from core.mcp_adapter import load_mcp_tools_for_agent
from langchain_core.messages import HumanMessage

mcp_configs = [{'mcp_name': 'mcp-filesystem', 'docker_image': 'ghcr.io/mark3labs/mcp-filesystem-server:latest', 'run_config': {'command': ['/workspace'], 'volumes': {'/host/workspace': '/workspace'}}}]
user_configs = {'mcp-filesystem': {'allowed_directory': 'C:/Users/amrda/Downloads'}}

async def run():
    tools = await load_mcp_tools_for_agent(mcp_configs, user_configs)
    # Find the list_allowed_directories tool
    tool = next((t for t in tools if t.name == "list_allowed_directories"), None)
    if tool:
        res = await tool.ainvoke({})
        print(f"Tool response: {res}")
    else:
        print("Tool not found")

asyncio.run(run())
