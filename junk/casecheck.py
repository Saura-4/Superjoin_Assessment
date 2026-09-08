import sqlite3

c = sqlite3.connect("data/run_delhivery.db")


def show(title, where):
    print(f"== {title} ==")
    q = (
        "select r.type, substr(d1.filename,4,20), f1.predicate, f1.value_raw, f1.period_raw,"
        " substr(d2.filename,4,20), f2.predicate, f2.value_raw, f2.period_raw, substr(r.reason,1,110)"
        " from relationships r"
        " join facts f1 on f1.id=r.fact_a_id join documents d1 on d1.id=f1.document_id"
        " join facts f2 on f2.id=r.fact_b_id join documents d2 on d2.id=f2.document_id"
        f" where d1.id != d2.id and ({where}) limit 8")
    for r in c.execute(q):
        print(str(tuple(r)).encode("ascii", "replace").decode())


show("CASE 1: 740 parcels cross-doc",
     "f1.value_norm=740000000.0 or f2.value_norm=740000000.0")
show("revenue cross-doc (81.4e9-ish)",
     "(f1.value_norm between 80000000000.0 and 83000000000.0"
     " or f2.value_norm between 80000000000.0 and 83000000000.0)")
show("director-ish cross-doc",
     "(f1.predicate like '%director%' or f2.predicate like '%director%'"
     " or f1.predicate like '%resign%' or f1.predicate like '%appoint%')")
show("PAT cross-doc",
     "(f1.predicate like '%pat%' or f1.predicate like '%profit%'"
     " or f2.predicate like '%pat%' or f2.predicate like '%profit%')")
