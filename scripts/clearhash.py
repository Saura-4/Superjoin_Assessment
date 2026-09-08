import sqlite3

c = sqlite3.connect("data/run_delhivery.db")
c.execute("delete from fact_embeddings where model='hash'")
c.commit()
print("hash rows cleared")
