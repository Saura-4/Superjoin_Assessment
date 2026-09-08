import sqlite3

c = sqlite3.connect("data/run_delhivery.db")
print("facts per doc:", [tuple(r) for r in c.execute(
    "select d.filename, count(*) from facts f join documents d on d.id=f.document_id group by d.id")])
print("pages with facts:", c.execute(
    "select count(distinct f.document_id || ev.page) from facts f join evidence ev on ev.fact_id=f.id"
).fetchone()[0])
print("processed pages:", c.execute(
    "select count(*) from page_processing where status='processed'").fetchone()[0])
print("status mix:", [tuple(r) for r in c.execute(
    "select status, count(*) from page_processing group by status")])
for r in c.execute("select subject,predicate,value_raw,period_raw from facts limit 6"):
    print("fact:", tuple(r))
