# ============================================
# PostgreSQL + pgvector Database
# ============================================
FROM pgvector/pgvector:pg16

# Copy initialization scripts DIRECTLY into docker-entrypoint-initdb.d
# PostgreSQL only auto-runs files at the TOP LEVEL of this directory
# Files run in alphabetical order: 001_ first, then 002_
COPY migrations/001_init.sql /docker-entrypoint-initdb.d/001_init.sql
COPY seeds/seed_mcps.sql /docker-entrypoint-initdb.d/002_seed_mcps.sql

EXPOSE 5432
