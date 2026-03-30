-- ============================================
-- Agent Builder System V5 - Real MCP Seed Data
-- Uses OFFICIAL Docker Hub MCP images (mcp/ namespace)
-- Each MCP has a run_config explaining HOW to launch it
-- Embeddings will be auto-generated at startup
-- ============================================

-- 1. Filesystem MCP (ghcr.io - verified working)
INSERT INTO mcps (mcp_name, docker_image, description, tools_provided, category, run_config)
VALUES (
    'mcp-filesystem',
    'ghcr.io/mark3labs/mcp-filesystem-server:latest',
    'MCP server for local filesystem access. Reads, writes, moves, searches files, and manages directories. Essential for organizing files, sorting folders like Downloads based on content, and any file manipulation tasks.',
    '[
        {"name": "read_file", "description": "Read the complete contents of a file from the filesystem."},
        {"name": "write_file", "description": "Write or overwrite text content to a file."},
        {"name": "move_file", "description": "Move or rename files and directories."},
        {"name": "list_directory", "description": "List all files and folders inside a given directory."},
        {"name": "search_files", "description": "Search for files matching a specific pattern."},
        {"name": "create_directory", "description": "Create a new directory at the specified path."},
        {"name": "get_file_info", "description": "Get metadata about a file (size, modified date, type)."}
    ]'::jsonb,
    'files',
    '{
        "transport": "stdio",
        "stdin_open": true,
        "command": ["/workspace"],
        "volumes": {"/host/workspace": "/workspace"},
        "environment": {},
        "notes": "Must pass allowed directory as argument. Mount host directory to /workspace. Requires -i flag for stdio transport."
    }'::jsonb
)
ON CONFLICT (mcp_name) DO UPDATE SET
    docker_image = EXCLUDED.docker_image,
    description = EXCLUDED.description,
    tools_provided = EXCLUDED.tools_provided,
    category = EXCLUDED.category,
    run_config = EXCLUDED.run_config;

-- 2. Fetch MCP (Official Docker Hub - mcp/fetch, 54 stars)
INSERT INTO mcps (mcp_name, docker_image, description, tools_provided, category, run_config)
VALUES (
    'mcp-fetch',
    'mcp/fetch:latest',
    'Official MCP server that fetches URLs from the internet, extracts content, and converts web pages to readable text or markdown. Useful for web scraping, reading documentation, API calls, and gathering online information.',
    '[
        {"name": "fetch", "description": "Fetch a URL and return its content as text or markdown. Supports HTML pages, APIs, and raw text."}
    ]'::jsonb,
    'web',
    '{
        "transport": "stdio",
        "stdin_open": true,
        "command": [],
        "volumes": {},
        "environment": {},
        "notes": "Simple stdio MCP. No volumes needed. Just run with -i flag."
    }'::jsonb
)
ON CONFLICT (mcp_name) DO UPDATE SET
    docker_image = EXCLUDED.docker_image,
    description = EXCLUDED.description,
    tools_provided = EXCLUDED.tools_provided,
    category = EXCLUDED.category,
    run_config = EXCLUDED.run_config;

-- 3. Playwright Browser Automation MCP (Official Docker Hub - mcp/playwright, 32 stars)
INSERT INTO mcps (mcp_name, docker_image, description, tools_provided, category, run_config)
VALUES (
    'mcp-playwright',
    'mcp/playwright:latest',
    'Official Playwright MCP server for browser automation. Can navigate web pages, click buttons, fill forms, take screenshots, extract page content, and automate complex web interactions in a headless browser.',
    '[
        {"name": "browser_navigate", "description": "Navigate the browser to a specific URL."},
        {"name": "browser_click", "description": "Click an element on the page."},
        {"name": "browser_fill", "description": "Fill a form input with text."},
        {"name": "browser_screenshot", "description": "Take a screenshot of the current page."},
        {"name": "browser_get_text", "description": "Extract visible text from the current page or specific element."}
    ]'::jsonb,
    'web',
    '{
        "transport": "stdio",
        "stdin_open": true,
        "command": [],
        "volumes": {},
        "environment": {},
        "notes": "Runs headless Chromium inside the container. Needs -i for stdio. No volume mounts needed."
    }'::jsonb
)
ON CONFLICT (mcp_name) DO UPDATE SET
    docker_image = EXCLUDED.docker_image,
    description = EXCLUDED.description,
    tools_provided = EXCLUDED.tools_provided,
    category = EXCLUDED.category,
    run_config = EXCLUDED.run_config;

-- 4. Memory MCP (Official Docker Hub - mcp/memory, 27 stars)
INSERT INTO mcps (mcp_name, docker_image, description, tools_provided, category, run_config)
VALUES (
    'mcp-memory',
    'mcp/memory:latest',
    'Knowledge graph-based persistent memory system. Stores entities, relationships, and observations in a structured graph. Useful for maintaining context across conversations, building knowledge bases, and long-term memory for AI agents.',
    '[
        {"name": "create_entities", "description": "Create new entities in the knowledge graph with names and types."},
        {"name": "create_relations", "description": "Create relationships between existing entities."},
        {"name": "add_observations", "description": "Add observations or facts about existing entities."},
        {"name": "search_nodes", "description": "Search the knowledge graph for entities matching a query."},
        {"name": "read_graph", "description": "Read and return the entire knowledge graph."}
    ]'::jsonb,
    'data',
    '{
        "transport": "stdio",
        "stdin_open": true,
        "command": [],
        "volumes": {"/host/memory-data": "/app/data"},
        "environment": {},
        "notes": "Persists knowledge graph to /app/data. Mount a volume to keep data between runs. Requires -i flag."
    }'::jsonb
)
ON CONFLICT (mcp_name) DO UPDATE SET
    docker_image = EXCLUDED.docker_image,
    description = EXCLUDED.description,
    tools_provided = EXCLUDED.tools_provided,
    category = EXCLUDED.category,
    run_config = EXCLUDED.run_config;

-- 5. Notion MCP (Official Docker Hub - mcp/notion, 34 stars)
INSERT INTO mcps (mcp_name, docker_image, description, tools_provided, category, run_config)
VALUES (
    'mcp-notion',
    'mcp/notion:latest',
    'Official Notion MCP Server. Connects AI agents to Notion workspaces for reading, creating, and managing pages, databases, and blocks. Perfect for project management, documentation, and task tracking.',
    '[
        {"name": "search", "description": "Search across all Notion pages and databases."},
        {"name": "get_page", "description": "Retrieve a specific Notion page by ID."},
        {"name": "create_page", "description": "Create a new Notion page in a workspace or database."},
        {"name": "update_page", "description": "Update properties or content of an existing page."},
        {"name": "query_database", "description": "Query a Notion database with filters and sorts."}
    ]'::jsonb,
    'communication',
    '{
        "transport": "stdio",
        "stdin_open": true,
        "command": [],
        "volumes": {},
        "environment": {"NOTION_API_KEY": "REQUIRED"},
        "notes": "Requires NOTION_API_KEY environment variable. Get it from https://www.notion.so/my-integrations"
    }'::jsonb
)
ON CONFLICT (mcp_name) DO UPDATE SET
    docker_image = EXCLUDED.docker_image,
    description = EXCLUDED.description,
    tools_provided = EXCLUDED.tools_provided,
    category = EXCLUDED.category,
    run_config = EXCLUDED.run_config;

-- 6. Slack MCP (Official Docker Hub - mcp/slack, 24 stars)
INSERT INTO mcps (mcp_name, docker_image, description, tools_provided, category, run_config)
VALUES (
    'mcp-slack',
    'mcp/slack:latest',
    'Official Slack MCP Server. Enables AI agents to interact with Slack workspaces - send messages, read channels, manage threads, and automate Slack communications.',
    '[
        {"name": "send_message", "description": "Send a message to a Slack channel or user."},
        {"name": "read_channel", "description": "Read recent messages from a Slack channel."},
        {"name": "list_channels", "description": "List all channels in the Slack workspace."},
        {"name": "reply_thread", "description": "Reply to a specific message thread."}
    ]'::jsonb,
    'communication',
    '{
        "transport": "stdio",
        "stdin_open": true,
        "command": [],
        "volumes": {},
        "environment": {"SLACK_BOT_TOKEN": "REQUIRED", "SLACK_TEAM_ID": "REQUIRED"},
        "notes": "Requires SLACK_BOT_TOKEN and SLACK_TEAM_ID. Create a Slack app at https://api.slack.com/apps"
    }'::jsonb
)
ON CONFLICT (mcp_name) DO UPDATE SET
    docker_image = EXCLUDED.docker_image,
    description = EXCLUDED.description,
    tools_provided = EXCLUDED.tools_provided,
    category = EXCLUDED.category,
    run_config = EXCLUDED.run_config;

-- 7. GitLab MCP (Official Docker Hub - mcp/gitlab, 24 stars)
INSERT INTO mcps (mcp_name, docker_image, description, tools_provided, category, run_config)
VALUES (
    'mcp-gitlab',
    'mcp/gitlab:latest',
    'Official GitLab MCP Server. Enables AI agents to interact with GitLab for project management, code review, issue tracking, merge requests, and CI/CD pipeline management.',
    '[
        {"name": "list_projects", "description": "List GitLab projects accessible to the user."},
        {"name": "get_file_contents", "description": "Read file contents from a GitLab repository."},
        {"name": "create_issue", "description": "Create a new issue in a GitLab project."},
        {"name": "create_merge_request", "description": "Create a merge request between branches."},
        {"name": "list_pipelines", "description": "List CI/CD pipelines for a project."}
    ]'::jsonb,
    'development',
    '{
        "transport": "stdio",
        "stdin_open": true,
        "command": [],
        "volumes": {},
        "environment": {"GITLAB_PERSONAL_ACCESS_TOKEN": "REQUIRED", "GITLAB_API_URL": "https://gitlab.com/api/v4"},
        "notes": "Requires GITLAB_PERSONAL_ACCESS_TOKEN. Generate from GitLab > Settings > Access Tokens."
    }'::jsonb
)
ON CONFLICT (mcp_name) DO UPDATE SET
    docker_image = EXCLUDED.docker_image,
    description = EXCLUDED.description,
    tools_provided = EXCLUDED.tools_provided,
    category = EXCLUDED.category,
    run_config = EXCLUDED.run_config;
