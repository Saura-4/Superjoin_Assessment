import sqlite3

c = sqlite3.connect("data/run_delhivery.db")
print("unlinked:", c.execute("select count(*) from facts f where not exists "
                             "(select 1 from relationships r where r.fact_a_id=f.id or r.fact_b_id=f.id)").fetchone()[0])
print("DATE facts linked:", c.execute(
    "select count(distinct f.id) from facts f join relationships r "
    "on r.fact_a_id=f.id or r.fact_b_id=f.id where f.unit_norm='DATE'").fetchone()[0])
print("DATE facts total:", c.execute("select count(*) from facts where unit_norm='DATE'").fetchone()[0])
print("rels:", [tuple(r) for r in c.execute("select type,count(*) from relationships group by type")])
