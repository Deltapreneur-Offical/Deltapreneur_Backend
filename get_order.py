from sqlalchemy import create_engine, text
engine = create_engine('postgresql://cobrotherpython:Aultum12345@database-1.cno8smi8qae3.ap-south-1.rds.amazonaws.com:5432/postgres')
with engine.connect() as conn:
    res = conn.execute(text("SELECT * FROM domain_registration_orders WHERE id='c3ea899d-5399-4b04-ac5f-17d5f4603d05'")).fetchone()
    if res:
        for k, v in res._mapping.items():
            print(f"{k}: {v}")
    else:
        print('Order not found.')
