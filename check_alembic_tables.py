import sqlalchemy as sa
from sqlalchemy import create_engine, text

engine = create_engine('postgresql://cobrotherpython:Aultum12345@database-1.cno8smi8qae3.ap-south-1.rds.amazonaws.com:5432/postgres')
with engine.connect() as conn:
    result = conn.execute(text('SELECT * FROM alembic_version ORDER BY version_num'))
    rows = result.fetchall()
    print('All rows in alembic_version:')
    for row in rows:
        print(' ', row)
        
    result2 = conn.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public' AND tablename LIKE 'alembic%'"))
    tables = result2.fetchall()
    print('Alembic tables:', [t[0] for t in tables])
