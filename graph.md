# Graph Schema (Neo4j)

ไฟล์นี้อธิบายโครงสร้างกราฟที่ import จาก `agent2_kg.json` โดยสคริปต์ `scripts/import_agent2_kg_to_neo4j.py`

## Node Types

1. `Person`
- Key: `name` (unique)
- Properties: `name`, `role`, `department`, `mentions`

2. `Project`
- Key: `(name, site_code)` (composite unique)
- Properties: `name`, `site_code`, `context`

3. `Equipment`
- Key: `(name, status)` (composite unique)
- Properties: `name`, `status`, `context`

4. `Financial`
- Key: `id` (unique)
- Properties: `id`, `label`, `amount`, `unit`, `context`, `timestamp`

5. `Issue`
- Key: `id` (unique)
- Properties: `id`, `text`, `raised_by`, `timestamp`

6. `Decision`
- Key: `id` (unique)
- Properties: `id`, `text`, `made_by`, `timestamp`

7. `ActionItem`
- Key: `id` (unique)
- Properties: `id`, `task`, `owner`, `deadline`, `timestamp`, `topic_ref`

8. `Topic`
- Key: `id` (unique)
- Properties: `id`, `name`, `department`, `start_timestamp`, `end_timestamp`, `duration_minutes`, `key_speakers`, `slide_timestamps`, `summary_points`

## Edge Types

1. `(:Person)-[:RAISED]->(:Issue)`
- ความหมาย: บุคคลเป็นผู้หยิบยกประเด็นปัญหา

2. `(:Person)-[:MADE]->(:Decision)`
- ความหมาย: บุคคลเป็นผู้ตัดสินใจ/มีมติ

3. `(:Person)-[:OWNS]->(:ActionItem)`
- ความหมาย: บุคคลเป็น owner ของงาน

4. `(:Person)-[:SPOKE_IN]->(:Topic)`
- ความหมาย: บุคคลเป็น key speaker ของหัวข้อนั้น

5. `(:Topic)-[:HAS_ISSUE]->(:Issue)`
- ความหมาย: หัวข้อมีประเด็นปัญหาที่เกี่ยวข้อง

6. `(:Topic)-[:HAS_DECISION]->(:Decision)`
- ความหมาย: หัวข้อมีมติที่เกี่ยวข้อง

7. `(:Topic)-[:HAS_ACTION]->(:ActionItem)`
- ความหมาย: หัวข้อมีงานที่ต้องดำเนินการ

8. `(:ActionItem)-[:REFERS_TO]->(:Topic)`
- ความหมาย: งานชิ้นนั้นอ้างอิงไปยัง topic ตาม `topic_ref`

## หมายเหตุสำคัญ

- ใน importer เวอร์ชันปัจจุบัน `Project`, `Equipment`, `Financial` ยังไม่มี edge เชื่อมไปยัง node อื่น (เป็น standalone nodes)
- ความสัมพันธ์ของ `Topic -> Issue/Decision/ActionItem` จับคู่โดย `id` ก่อน ถ้าไม่เจอจะ fallback จับด้วยข้อความ (`text` หรือ `task`)

## Quick Cypher (ดู schema)

```cypher
CALL db.labels();
```

```cypher
CALL db.relationshipTypes();
```

```cypher
MATCH (t:Topic)-[r]-(x) RETURN t,r,x LIMIT 300;
```

```cypher
MATCH (p:Person)-[r]->(x) RETURN p,r,x LIMIT 300;
```
