"""Add MCP config columns and seed 20+ new MCPs

Revision ID: 004
Revises: 003
Create Date: 2026-04-10

New columns: requires_user_config, config_schema, shared_container_id, shared_container_status
Seeds ~20 new real MCP servers from Docker Hub / GHCR.
Also back-fills requires_user_config + config_schema on existing 7 MCPs.
"""
from typing import Sequence, Union
from alembic import op
from sqlalchemy import text

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- 1. Add new columns ---
    op.execute("ALTER TABLE mcps ADD COLUMN IF NOT EXISTS requires_user_config BOOLEAN DEFAULT false")
    op.execute("ALTER TABLE mcps ADD COLUMN IF NOT EXISTS config_schema JSONB DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE mcps ADD COLUMN IF NOT EXISTS shared_container_id VARCHAR(100)")
    op.execute("ALTER TABLE mcps ADD COLUMN IF NOT EXISTS shared_container_status VARCHAR(20)")

    # --- 2. Back-fill existing MCPs ---
    conn = op.get_bind()
    conn.execute(text(
        "UPDATE mcps SET requires_user_config = true, config_schema = CAST(:cs AS jsonb) WHERE mcp_name = :name"
    ), {"cs": '[{"key":"NOTION_API_KEY","label":"Notion Integration Token","description":"Get from notion.so/my-integrations","required":true,"secret":true}]', "name": "mcp-notion"})
    conn.execute(text(
        "UPDATE mcps SET requires_user_config = true, config_schema = CAST(:cs AS jsonb) WHERE mcp_name = :name"
    ), {"cs": '[{"key":"SLACK_BOT_TOKEN","label":"Slack Bot Token","description":"Create app at api.slack.com/apps","required":true,"secret":true},{"key":"SLACK_TEAM_ID","label":"Slack Team ID","description":"Your workspace team ID","required":true,"secret":false}]', "name": "mcp-slack"})
    conn.execute(text(
        "UPDATE mcps SET requires_user_config = true, config_schema = CAST(:cs AS jsonb) WHERE mcp_name = :name"
    ), {"cs": '[{"key":"GITLAB_PERSONAL_ACCESS_TOKEN","label":"GitLab Token","description":"Settings > Access Tokens","required":true,"secret":true}]', "name": "mcp-gitlab"})
    conn.execute(text("UPDATE mcps SET requires_user_config = false WHERE mcp_name IN ('mcp-filesystem','mcp-fetch','mcp-playwright','mcp-memory')"))

    # --- 3. Seed new shared MCPs (no user config) ---
    _seed(
        "mcp-git", "mcp/git", "development",
        "Git version control MCP. Clone repos, check status, diff, log, commit, branch, and manage Git repositories mounted into the workspace.",
        '[{"name":"git_status","description":"Show working tree status"},{"name":"git_log","description":"Show commit log"},{"name":"git_diff","description":"Show changes between commits or working tree"},{"name":"git_commit","description":"Create a new commit"},{"name":"git_branch","description":"List, create, or delete branches"},{"name":"git_checkout","description":"Switch branches or restore files"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{"/host/workspace":"/workspace"},"environment":{}}',
        False, "[]",
    )
    _seed(
        "mcp-sequentialthinking", "mcp/sequentialthinking", "reasoning",
        "Chain-of-thought scaffolding MCP. Helps the agent break complex problems into sequential thinking steps with revision and branching support.",
        '[{"name":"sequentialthinking","description":"Create a structured chain-of-thought reasoning sequence with revision and branching"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{}}',
        False, "[]",
    )
    _seed(
        "mcp-puppeteer", "mcp/puppeteer", "web",
        "Headless Chrome browser automation via Puppeteer. Navigate pages, click, fill forms, take screenshots, evaluate JavaScript in the browser.",
        '[{"name":"puppeteer_navigate","description":"Navigate browser to a URL"},{"name":"puppeteer_click","description":"Click an element on the page"},{"name":"puppeteer_fill","description":"Fill a form input"},{"name":"puppeteer_screenshot","description":"Take a screenshot"},{"name":"puppeteer_evaluate","description":"Execute JavaScript in the browser"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{"DOCKER_CONTAINER":"true"}}',
        False, "[]",
    )
    _seed(
        "mcp-context7", "mcp/context7", "development",
        "Provides up-to-date library and framework documentation for LLMs. Resolves library names and fetches current docs so agents always reference the latest API.",
        '[{"name":"resolve-library-id","description":"Resolve a library name to a Context7 library ID"},{"name":"get-library-docs","description":"Fetch up-to-date documentation for a specific library"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{}}',
        False, "[]",
    )
    _seed(
        "mcp-dockerhub", "mcp/dockerhub", "devops",
        "Docker Hub API MCP. Search repositories, list tags, get image metadata, and manage Docker Hub namespaces. Read-only by default.",
        '[{"name":"search_repos","description":"Search Docker Hub repositories"},{"name":"get_repo","description":"Get details of a specific repository"},{"name":"list_tags","description":"List tags for a repository"},{"name":"get_tag","description":"Get details of a specific tag"},{"name":"list_namespaces","description":"List Docker Hub namespaces"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{}}',
        False, "[]",
    )
    _seed(
        "mcp-redis", "mcp/redis", "data",
        "Redis MCP server with full Redis operations including vector search, JSON, streams, pub/sub, and all standard Redis commands.",
        '[{"name":"set","description":"Set a key-value pair"},{"name":"get","description":"Get value by key"},{"name":"del","description":"Delete a key"},{"name":"keys","description":"List keys matching pattern"},{"name":"hset","description":"Set hash field"},{"name":"hget","description":"Get hash field"},{"name":"lpush","description":"Push to list"},{"name":"ft.search","description":"Full-text and vector search"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{"REDIS_URL":"redis://redis:6379"}}',
        False, "[]",
    )

    # --- 4. Seed configurable MCPs (need user API keys) ---
    _seed(
        "mcp-github", "ghcr.io/github/github-mcp-server", "development",
        "Official GitHub MCP server. Full GitHub API access: repositories, issues, pull requests, code search, file operations, branches, and CI/CD workflows.",
        '[{"name":"search_repositories","description":"Search GitHub repositories"},{"name":"get_file_contents","description":"Get file contents from a repo"},{"name":"create_issue","description":"Create an issue"},{"name":"create_pull_request","description":"Create a pull request"},{"name":"list_commits","description":"List commits on a branch"},{"name":"search_code","description":"Search code across GitHub"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{"GITHUB_PERSONAL_ACCESS_TOKEN":"REQUIRED"}}',
        True,
        '[{"key":"GITHUB_PERSONAL_ACCESS_TOKEN","label":"GitHub Personal Access Token","description":"Generate at github.com/settings/tokens","required":true,"secret":true}]',
    )
    _seed(
        "mcp-brave-search", "mcp/brave-search", "web",
        "Brave Search API MCP. Web search, news search, image search, video search, local search, and AI-powered summarization via the Brave Search API.",
        '[{"name":"brave_web_search","description":"Search the web via Brave Search"},{"name":"brave_local_search","description":"Search for local businesses and places"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{"BRAVE_API_KEY":"REQUIRED"}}',
        True,
        '[{"key":"BRAVE_API_KEY","label":"Brave Search API Key","description":"Get from brave.com/search/api","required":true,"secret":true}]',
    )
    _seed(
        "mcp-stripe", "mcp/stripe", "business",
        "Stripe MCP server for payment processing. Manage customers, products, prices, subscriptions, invoices, and payment intents via the Stripe API.",
        '[{"name":"list_customers","description":"List Stripe customers"},{"name":"create_customer","description":"Create a customer"},{"name":"list_products","description":"List products"},{"name":"create_product","description":"Create a product"},{"name":"create_payment_intent","description":"Create a payment intent"},{"name":"list_subscriptions","description":"List subscriptions"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{"STRIPE_SECRET_KEY":"REQUIRED"}}',
        True,
        '[{"key":"STRIPE_SECRET_KEY","label":"Stripe Secret Key","description":"From Stripe Dashboard > API keys","required":true,"secret":true}]',
    )
    _seed(
        "mcp-sentry", "mcp/sentry", "devops",
        "Sentry error tracking MCP. Fetch issues, events, and stack traces from Sentry. Debug production errors by querying real error data.",
        '[{"name":"get_sentry_issue","description":"Get details of a Sentry issue by ID"},{"name":"list_sentry_issues","description":"List recent issues for a project"},{"name":"get_sentry_event","description":"Get a specific error event with stack trace"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{"SENTRY_AUTH_TOKEN":"REQUIRED","SENTRY_ORG":"REQUIRED"}}',
        True,
        '[{"key":"SENTRY_AUTH_TOKEN","label":"Sentry Auth Token","description":"From Sentry > Settings > Auth Tokens","required":true,"secret":true},{"key":"SENTRY_ORG","label":"Sentry Organization Slug","description":"Your Sentry organization slug","required":true,"secret":false}]',
    )
    _seed(
        "mcp-grafana", "mcp/grafana", "devops",
        "Grafana observability MCP. Query dashboards, alerts, incidents, datasources. Supports Prometheus, Loki, and Pyroscope queries. 50+ tools for full Grafana stack management.",
        '[{"name":"search_dashboards","description":"Search Grafana dashboards"},{"name":"get_dashboard_by_uid","description":"Get dashboard by UID"},{"name":"list_datasources","description":"List configured datasources"},{"name":"query_prometheus","description":"Execute a PromQL query"},{"name":"query_loki","description":"Execute a LogQL query"},{"name":"list_alerts","description":"List alert rules"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{"GRAFANA_URL":"REQUIRED","GRAFANA_API_KEY":"REQUIRED"}}',
        True,
        '[{"key":"GRAFANA_URL","label":"Grafana URL","description":"e.g. https://your-grafana.com","required":true,"secret":false},{"key":"GRAFANA_API_KEY","label":"Grafana API Token","description":"From Grafana > Administration > Service Accounts","required":true,"secret":true}]',
    )
    _seed(
        "mcp-kubernetes", "mcp/kubernetes", "devops",
        "Kubernetes cluster management MCP. Run kubectl commands, manage deployments, pods, services, Helm charts, and monitor cluster resources.",
        '[{"name":"kubectl_get","description":"Get Kubernetes resources"},{"name":"kubectl_describe","description":"Describe a resource in detail"},{"name":"kubectl_apply","description":"Apply a manifest"},{"name":"kubectl_delete","description":"Delete resources"},{"name":"kubectl_logs","description":"Get pod logs"},{"name":"helm_install","description":"Install a Helm chart"},{"name":"helm_list","description":"List Helm releases"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{"/host/workspace/.kube":"/root/.kube"},"environment":{}}',
        True,
        '[{"key":"KUBECONFIG_CONTENT","label":"Kubeconfig Content","description":"Paste your kubeconfig YAML or mount ~/.kube","required":true,"secret":true}]',
    )
    _seed(
        "mcp-neon", "mcp/neon", "data",
        "Neon serverless Postgres MCP. Manage Neon projects, branches, databases. Run SQL queries, create migrations, and get query performance advice.",
        '[{"name":"run_sql","description":"Execute a SQL query on a Neon database"},{"name":"list_projects","description":"List Neon projects"},{"name":"create_branch","description":"Create a database branch"},{"name":"get_connection_string","description":"Get the connection string"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{"NEON_API_KEY":"REQUIRED"}}',
        True,
        '[{"key":"NEON_API_KEY","label":"Neon API Key","description":"From console.neon.tech > Account > API Keys","required":true,"secret":true}]',
    )
    _seed(
        "mcp-mongodb", "mcp/mongodb", "data",
        "MongoDB MCP server. Connect to MongoDB or Atlas, run CRUD operations, aggregation pipelines, index management, and Atlas search.",
        '[{"name":"find","description":"Query documents in a collection"},{"name":"insertOne","description":"Insert a document"},{"name":"updateOne","description":"Update a document"},{"name":"deleteOne","description":"Delete a document"},{"name":"aggregate","description":"Run an aggregation pipeline"},{"name":"createIndex","description":"Create an index"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{"MDB_MCP_CONNECTION_STRING":"REQUIRED"}}',
        True,
        '[{"key":"MDB_MCP_CONNECTION_STRING","label":"MongoDB Connection String","description":"mongodb+srv://user:pass@cluster.mongodb.net/db","required":true,"secret":true}]',
    )
    _seed(
        "mcp-elasticsearch", "mcp/elasticsearch", "data",
        "Elasticsearch MCP server. Manage indices, run ES|QL and DSL queries, index documents, and perform full-text search operations.",
        '[{"name":"search","description":"Search documents using ES DSL or ES|QL"},{"name":"index_document","description":"Index a new document"},{"name":"get_document","description":"Get a document by ID"},{"name":"list_indices","description":"List all indices"},{"name":"create_index","description":"Create a new index"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{"ES_URL":"REQUIRED","ES_API_KEY":"REQUIRED"}}',
        True,
        '[{"key":"ES_URL","label":"Elasticsearch URL","description":"e.g. https://your-cluster.es.io:9243","required":true,"secret":false},{"key":"ES_API_KEY","label":"Elasticsearch API Key","description":"From Kibana > Stack Management > API Keys","required":true,"secret":true}]',
    )
    _seed(
        "mcp-aws", "mcp/aws-api-mcp-server", "cloud",
        "AWS API MCP server. Call any AWS service API. Suggest AWS CLI commands and execute AWS operations across EC2, S3, Lambda, and all other services.",
        '[{"name":"call_aws","description":"Call any AWS API action"},{"name":"suggest_aws_commands","description":"Suggest AWS CLI commands for a task"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{"AWS_ACCESS_KEY_ID":"REQUIRED","AWS_SECRET_ACCESS_KEY":"REQUIRED","AWS_REGION":"us-east-1"}}',
        True,
        '[{"key":"AWS_ACCESS_KEY_ID","label":"AWS Access Key ID","description":"From AWS IAM console","required":true,"secret":true},{"key":"AWS_SECRET_ACCESS_KEY","label":"AWS Secret Access Key","description":"From AWS IAM console","required":true,"secret":true},{"key":"AWS_REGION","label":"AWS Region","description":"e.g. us-east-1","required":false,"secret":false}]',
    )
    _seed(
        "mcp-google-maps", "mcp/google-maps", "web",
        "Google Maps Platform MCP. Geocode addresses, get directions, find places, calculate distance matrices, and get elevation data.",
        '[{"name":"geocode","description":"Convert address to coordinates"},{"name":"directions","description":"Get directions between locations"},{"name":"places_search","description":"Search for places nearby"},{"name":"distance_matrix","description":"Calculate travel time and distance"},{"name":"elevation","description":"Get elevation for coordinates"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{},"environment":{"GOOGLE_MAPS_API_KEY":"REQUIRED"}}',
        True,
        '[{"key":"GOOGLE_MAPS_API_KEY","label":"Google Maps API Key","description":"From Google Cloud Console > APIs & Services","required":true,"secret":true}]',
    )
    _seed(
        "mcp-blender", "ghcr.io/patrykiti/blender-ai-mcp", "3d",
        "Blender 3D MCP server. Control Blender for 3D modeling, rendering, animation, and scene manipulation. Create and modify 3D objects, materials, cameras, and lights programmatically.",
        '[{"name":"create_object","description":"Create a 3D object (cube, sphere, etc.)"},{"name":"modify_object","description":"Modify object properties (position, scale, rotation)"},{"name":"set_material","description":"Apply materials and textures"},{"name":"render_scene","description":"Render the current scene"},{"name":"execute_blender_code","description":"Execute arbitrary Blender Python code"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{"/host/workspace":"/workspace"},"environment":{}}',
        True,
        '[{"key":"BLENDER_HOST","label":"Blender Host","description":"Host where Blender addon is running (e.g. host.docker.internal:9876)","required":true,"secret":false}]',
    )
    _seed(
        "mcp-docker", "acuvity/mcp-server-docker", "devops",
        "Docker Engine MCP server. Manage local Docker containers, images, volumes, and networks. List running containers, start/stop containers, pull images, and inspect Docker resources.",
        '[{"name":"list_containers","description":"List Docker containers"},{"name":"start_container","description":"Start a container"},{"name":"stop_container","description":"Stop a container"},{"name":"pull_image","description":"Pull a Docker image"},{"name":"list_images","description":"List local Docker images"},{"name":"inspect_container","description":"Get detailed container info"},{"name":"container_logs","description":"Get container logs"}]',
        '{"transport":"stdio","stdin_open":true,"command":[],"volumes":{"/var/run/docker.sock":"/var/run/docker.sock"},"environment":{}}',
        False, "[]",
    )


def _seed(name, image, category, desc, tools_json, config_json, requires_config, config_schema_json):
    conn = op.get_bind()
    conn.execute(
        text(
            "INSERT INTO mcps (mcp_name, docker_image, description, tools_provided, category, "
            "run_config, requires_user_config, config_schema) "
            "VALUES (:name, :image, :desc, CAST(:tools AS jsonb), :cat, CAST(:cfg AS jsonb), :req, CAST(:cs AS jsonb)) "
            "ON CONFLICT (mcp_name) DO UPDATE SET "
            "docker_image = EXCLUDED.docker_image, "
            "description = EXCLUDED.description, "
            "tools_provided = EXCLUDED.tools_provided, "
            "category = EXCLUDED.category, "
            "run_config = EXCLUDED.run_config, "
            "requires_user_config = EXCLUDED.requires_user_config, "
            "config_schema = EXCLUDED.config_schema"
        ),
        {
            "name": name,
            "image": image,
            "desc": desc,
            "tools": tools_json,
            "cat": category,
            "cfg": config_json,
            "req": requires_config,
            "cs": config_schema_json,
        },
    )


def downgrade() -> None:
    op.execute(text(
        "DELETE FROM mcps WHERE mcp_name IN ("
        "'mcp-git','mcp-sequentialthinking','mcp-puppeteer','mcp-context7',"
        "'mcp-dockerhub','mcp-redis','mcp-github','mcp-brave-search',"
        "'mcp-stripe','mcp-sentry','mcp-grafana','mcp-kubernetes',"
        "'mcp-neon','mcp-mongodb','mcp-elasticsearch','mcp-aws',"
        "'mcp-google-maps','mcp-blender','mcp-docker')"
    ))
    op.execute(text("ALTER TABLE mcps DROP COLUMN IF EXISTS requires_user_config"))
    op.execute(text("ALTER TABLE mcps DROP COLUMN IF EXISTS config_schema"))
    op.execute(text("ALTER TABLE mcps DROP COLUMN IF EXISTS shared_container_id"))
    op.execute(text("ALTER TABLE mcps DROP COLUMN IF EXISTS shared_container_status"))
