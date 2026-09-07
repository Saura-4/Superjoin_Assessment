import sqlite3

c = sqlite3.connect("data/run_delhivery.db")
print("predicates:", c.execute("select count(distinct predicate) from facts").fetchone()[0])
print("top units:", c.execute(
    "select unit_norm,count(*) from facts group by 1 order by 2 desc limit 8").fetchall())
print("empty period:", c.execute(
    "select count(*) from facts where period_norm=''").fetchone()[0])
print("empty value_norm:", c.execute(
    "select count(*) from facts where value_norm is null").fetchone()[0])
print("scope empty:", c.execute(
    "select count(*) from facts where scope=''").fetchone()[0])
print("sample semantic:", c.execute(
    "select subject,predicate,value_raw,confidence from facts where value_norm is null limit 6").fetchall())
