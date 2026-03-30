# ============================================
# Agent Builder System V5 - Makefile
# ============================================

.PHONY: up down build logs migrate seed restart clean dev

# Start all services
up:
	docker-compose up -d

# Start with dev profile (includes adminer)
dev:
	docker-compose --profile dev up -d

# Stop all services
down:
	docker-compose down

# Rebuild and start
build:
	docker-compose up -d --build

# View logs (follow)
logs:
	docker-compose logs -f

# View specific service logs
logs-%:
	docker-compose logs -f $*

# Restart a specific service
restart-%:
	docker-compose restart $*

# Run database migrations manually
migrate:
	docker-compose exec db psql -U $${POSTGRES_USER:-agentbuilder} -d $${POSTGRES_DB:-agentbuilder_db} -f /docker-entrypoint-initdb.d/migrations/001_init.sql

# Run database seeds manually
seed:
	docker-compose exec db psql -U $${POSTGRES_USER:-agentbuilder} -d $${POSTGRES_DB:-agentbuilder_db} -f /docker-entrypoint-initdb.d/seeds/seed_mcps.sql

# Open psql shell
db-shell:
	docker-compose exec db psql -U $${POSTGRES_USER:-agentbuilder} -d $${POSTGRES_DB:-agentbuilder_db}

# Clean everything (volumes included)
clean:
	docker-compose down -v --rmi all --remove-orphans

# Check status
status:
	docker-compose ps

# Run tests
test:
	docker-compose exec api python -m pytest tests/ -v
