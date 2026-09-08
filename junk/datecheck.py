import sqlite3

c = sqlite3.connect("data/run_delhivery.db")
for r in c.execute(
        "select value_raw, unit_raw, value_norm, unit_norm from facts "
        "where predicate='appointment_date' limit 4"):
    print(tuple(r))
print("DATE units:", c.execute("select count(*) from facts where unit_norm='DATE'").fetchone()[0])
