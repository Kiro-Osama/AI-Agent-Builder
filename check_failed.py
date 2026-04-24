import os
from sqlalchemy import create_engine, text

def check():
    db_url = os.getenv('ALEMBIC_DATABASE_URL')
    engine = create_engine(db_url)
    conn = engine.connect()
    res = conn.execute(text("SELECT skill_id, status, error_log FROM skills ORDER BY created_at DESC LIMIT 5")).fetchall()
    for row in res:
        print(f"Skill: {row[0]}, status: {row[1]}, log: {row[2]}")
    conn.close()

if __name__ == '__main__':
    check()
