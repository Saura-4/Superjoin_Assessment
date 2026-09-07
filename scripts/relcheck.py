import sqlite3

c = sqlite3.connect("data/run_delhivery.db")
print("== contradict pairs: same subject? ==")
print(c.execute("""
select case when fa.subject = fb.subject then 'same-subj' else 'DIFF-SUBJ' end, count(*)
from relationships r
join facts fa on fa.id = r.fact_a_id join facts fb on fb.id = r.fact_b_id
where r.type='CONTRADICTS' group by 1""").fetchall())
print("== top predicates in CONTRADICTS ==")
for r in c.execute("""
select fa.predicate, count(*) n from relationships r
join facts fa on fa.id = r.fact_a_id
where r.type='CONTRADICTS' group by 1 order by n desc limit 12"""):
    print(tuple(r))
print("== sample: same predicate, diff subjects ==")
for r in c.execute("""
select fa.subject, fa.predicate, fa.value_raw, fa.period_raw, fb.subject, fb.value_raw, r.reason
from relationships r join facts fa on fa.id=r.fact_a_id join facts fb on fb.id=r.fact_b_id
where r.type='CONTRADICTS' and fa.subject != fb.subject limit 6"""):
    print(tuple(r))
print("== sample: same subject+predicate ==")
for r in c.execute("""
select fa.subject, fa.predicate, fa.value_raw, fa.claim, fb.value_raw, fb.claim
from relationships r join facts fa on fa.id=r.fact_a_id join facts fb on fb.id=r.fact_b_id
where r.type='CONTRADICTS' and fa.subject = fb.subject limit 5"""):
    print(tuple(r))
