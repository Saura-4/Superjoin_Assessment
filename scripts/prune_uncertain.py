import sqlite3

c = sqlite3.connect("data/run_delhivery.db")
n = c.execute("""
delete from relationships where type='UNCERTAIN' and exists (
  select 1 from facts fa join facts fb
   on fa.id = relationships.fact_a_id and fb.id = relationships.fact_b_id
  where fa.document_id = fb.document_id)
""").rowcount
c.commit()
print("same-doc UNCERTAIN deleted:", n)
print("rels now:", [tuple(r) for r in c.execute("select type,count(*) from relationships group by type")])
