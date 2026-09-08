import sqlite3

c = sqlite3.connect("data/run_delhivery.db")
print("== 740-ish facts ==")
for r in c.execute(
        "select d.filename, f.subject, f.predicate, f.value_raw, f.period_raw, substr(f.claim,1,90) "
        "from facts f join documents d on d.id=f.document_id "
        "where f.value_raw like '%740%' or f.claim like '%740%antie%' or f.value_norm=740000000.0 limit 12"):
    print(tuple(r))
print("== revenue 81k-Mn / 8142-Cr facts ==")
for r in c.execute(
        "select d.filename, f.predicate, f.value_raw, f.value_norm, f.period_raw "
        "from facts f join documents d on d.id=f.document_id "
        "where (f.value_norm between 81000000000.0 and 82000000000.0) limit 12"):
    print(tuple(r))
