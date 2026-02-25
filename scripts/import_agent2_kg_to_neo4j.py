#!/usr/bin/env python3
"""Import Agent2 KG JSON into Neo4j for visualization."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable

from neo4j import GraphDatabase


def norm(value: Any) -> str:
    return str(value or "").strip()


def to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def stable_id(prefix: str, *parts: Any) -> str:
    joined = "|".join(norm(p) for p in parts)
    digest = hashlib.sha1(joined.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def chunks(rows: list[dict[str, Any]], size: int) -> Iterable[list[dict[str, Any]]]:
    step = max(size, 1)
    for i in range(0, len(rows), step):
        yield rows[i : i + step]


def dedupe(rows: list[dict[str, Any]], key_fn) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = key_fn(row)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def sanitize_list(items: Any) -> list[str]:
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        val = norm(item)
        if val:
            out.append(val)
    return out


CONSTRAINT_QUERIES = [
    "CREATE CONSTRAINT person_name IF NOT EXISTS FOR (p:Person) REQUIRE p.name IS UNIQUE",
    "CREATE CONSTRAINT project_key IF NOT EXISTS FOR (p:Project) REQUIRE (p.name, p.site_code) IS UNIQUE",
    "CREATE CONSTRAINT equipment_key IF NOT EXISTS FOR (e:Equipment) REQUIRE (e.name, e.status) IS UNIQUE",
    "CREATE CONSTRAINT financial_id IF NOT EXISTS FOR (f:Financial) REQUIRE f.id IS UNIQUE",
    "CREATE CONSTRAINT issue_id IF NOT EXISTS FOR (i:Issue) REQUIRE i.id IS UNIQUE",
    "CREATE CONSTRAINT decision_id IF NOT EXISTS FOR (d:Decision) REQUIRE d.id IS UNIQUE",
    "CREATE CONSTRAINT action_id IF NOT EXISTS FOR (a:ActionItem) REQUIRE a.id IS UNIQUE",
    "CREATE CONSTRAINT topic_id IF NOT EXISTS FOR (t:Topic) REQUIRE t.id IS UNIQUE",
    "CREATE INDEX issue_text IF NOT EXISTS FOR (i:Issue) ON (i.text)",
    "CREATE INDEX decision_text IF NOT EXISTS FOR (d:Decision) ON (d.text)",
    "CREATE INDEX action_task IF NOT EXISTS FOR (a:ActionItem) ON (a.task)",
]


QUERY_PEOPLE = """
UNWIND $rows AS row
WITH row WHERE row.name <> ''
MERGE (p:Person {name: row.name})
SET p.role = row.role,
    p.department = row.department,
    p.mentions = toInteger(row.mentions)
"""


QUERY_PROJECTS = """
UNWIND $rows AS row
WITH row WHERE row.name <> ''
MERGE (p:Project {name: row.name, site_code: row.site_code})
SET p.context = row.context
"""


QUERY_EQUIPMENT = """
UNWIND $rows AS row
WITH row WHERE row.name <> ''
MERGE (e:Equipment {name: row.name, status: row.status})
SET e.context = row.context
"""


QUERY_FINANCIALS = """
UNWIND $rows AS row
MERGE (f:Financial {id: row.id})
SET f.label = row.label,
    f.amount = row.amount,
    f.unit = row.unit,
    f.context = row.context,
    f.timestamp = row.timestamp
"""


QUERY_ISSUES = """
UNWIND $rows AS row
MERGE (i:Issue {id: row.id})
SET i.text = row.text,
    i.raised_by = row.raised_by,
    i.timestamp = row.timestamp
WITH i, row WHERE row.raised_by <> ''
MERGE (p:Person {name: row.raised_by})
MERGE (p)-[:RAISED]->(i)
"""


QUERY_DECISIONS = """
UNWIND $rows AS row
MERGE (d:Decision {id: row.id})
SET d.text = row.text,
    d.made_by = row.made_by,
    d.timestamp = row.timestamp
WITH d, row WHERE row.made_by <> ''
MERGE (p:Person {name: row.made_by})
MERGE (p)-[:MADE]->(d)
"""


QUERY_ACTIONS = """
UNWIND $rows AS row
MERGE (a:ActionItem {id: row.id})
SET a.task = row.task,
    a.owner = row.owner,
    a.deadline = row.deadline,
    a.timestamp = row.timestamp,
    a.topic_ref = row.topic_ref
WITH a, row WHERE row.owner <> ''
MERGE (p:Person {name: row.owner})
MERGE (p)-[:OWNS]->(a)
"""


QUERY_TOPICS = """
UNWIND $rows AS row
MERGE (t:Topic {id: row.id})
SET t.name = row.name,
    t.department = row.department,
    t.start_timestamp = row.start_timestamp,
    t.end_timestamp = row.end_timestamp,
    t.duration_minutes = toInteger(row.duration_minutes),
    t.key_speakers = row.key_speakers,
    t.slide_timestamps = row.slide_timestamps,
    t.summary_points = row.summary_points
"""


QUERY_TOPIC_SPEAKERS = """
UNWIND $rows AS row
MATCH (t:Topic {id: row.topic_id})
MERGE (p:Person {name: row.speaker})
MERGE (p)-[:SPOKE_IN]->(t)
"""


QUERY_TOPIC_ISSUES = """
UNWIND $rows AS row
MATCH (t:Topic {id: row.topic_id})
OPTIONAL MATCH (i1:Issue {id: row.ref})
OPTIONAL MATCH (i2:Issue {text: row.ref})
WITH t, coalesce(i1, i2) AS i
FOREACH (_ IN CASE WHEN i IS NULL THEN [] ELSE [1] END |
  MERGE (t)-[:HAS_ISSUE]->(i)
)
"""


QUERY_TOPIC_DECISIONS = """
UNWIND $rows AS row
MATCH (t:Topic {id: row.topic_id})
OPTIONAL MATCH (d1:Decision {id: row.ref})
OPTIONAL MATCH (d2:Decision {text: row.ref})
WITH t, coalesce(d1, d2) AS d
FOREACH (_ IN CASE WHEN d IS NULL THEN [] ELSE [1] END |
  MERGE (t)-[:HAS_DECISION]->(d)
)
"""


QUERY_TOPIC_ACTIONS = """
UNWIND $rows AS row
MATCH (t:Topic {id: row.topic_id})
OPTIONAL MATCH (a1:ActionItem {id: row.ref})
OPTIONAL MATCH (a2:ActionItem {task: row.ref})
WITH t, coalesce(a1, a2) AS a
FOREACH (_ IN CASE WHEN a IS NULL THEN [] ELSE [1] END |
  MERGE (t)-[:HAS_ACTION]->(a)
)
"""


QUERY_ACTION_TOPIC_REF = """
UNWIND $rows AS row
MATCH (a:ActionItem {id: row.action_id})
MATCH (t:Topic {id: row.topic_id})
MERGE (a)-[:REFERS_TO]->(t)
"""


def run_batched(session, query: str, rows: list[dict[str, Any]], batch_size: int) -> None:
    if not rows:
        return
    for batch in chunks(rows, batch_size):
        session.run(query, rows=batch).consume()


def load_kg(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"KG file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("KG JSON root must be object")
    return data


def build_rows(kg: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    entities = kg.get("entities", {}) if isinstance(kg.get("entities"), dict) else {}
    topics = kg.get("topics", []) if isinstance(kg.get("topics"), list) else []

    people_rows: list[dict[str, Any]] = []
    for raw in entities.get("people", []) if isinstance(entities.get("people"), list) else []:
        if not isinstance(raw, dict):
            continue
        row = {
            "name": norm(raw.get("name")),
            "role": norm(raw.get("role")),
            "department": norm(raw.get("department")),
            "mentions": to_int(raw.get("mentions"), 0),
        }
        if row["name"]:
            people_rows.append(row)
    people_rows = dedupe(people_rows, lambda r: r["name"])

    project_rows: list[dict[str, Any]] = []
    for raw in entities.get("projects", []) if isinstance(entities.get("projects"), list) else []:
        if not isinstance(raw, dict):
            continue
        row = {
            "name": norm(raw.get("name")),
            "site_code": norm(raw.get("site_code")),
            "context": norm(raw.get("context")),
        }
        if row["name"]:
            project_rows.append(row)
    project_rows = dedupe(project_rows, lambda r: f"{r['name']}|{r['site_code']}")

    equipment_rows: list[dict[str, Any]] = []
    for raw in entities.get("equipment", []) if isinstance(entities.get("equipment"), list) else []:
        if not isinstance(raw, dict):
            continue
        row = {
            "name": norm(raw.get("name")),
            "status": norm(raw.get("status")),
            "context": norm(raw.get("context")),
        }
        if row["name"]:
            equipment_rows.append(row)
    equipment_rows = dedupe(equipment_rows, lambda r: f"{r['name']}|{r['status']}")

    financial_rows: list[dict[str, Any]] = []
    for raw in entities.get("financials", []) if isinstance(entities.get("financials"), list) else []:
        if not isinstance(raw, dict):
            continue
        label = norm(raw.get("label"))
        amount = norm(raw.get("amount"))
        unit = norm(raw.get("unit"))
        context = norm(raw.get("context"))
        timestamp = norm(raw.get("timestamp"))
        if not any([label, amount, unit, context, timestamp]):
            continue
        financial_rows.append(
            {
                "id": stable_id("F", label, amount, unit, context, timestamp),
                "label": label,
                "amount": amount,
                "unit": unit,
                "context": context,
                "timestamp": timestamp,
            }
        )
    financial_rows = dedupe(financial_rows, lambda r: r["id"])

    issue_rows: list[dict[str, Any]] = []
    for raw in entities.get("issues", []) if isinstance(entities.get("issues"), list) else []:
        if not isinstance(raw, dict):
            continue
        text = norm(raw.get("text"))
        raised_by = norm(raw.get("raised_by"))
        timestamp = norm(raw.get("timestamp"))
        issue_id = norm(raw.get("id")) or stable_id("I", text, raised_by, timestamp)
        if not text and not issue_id:
            continue
        issue_rows.append(
            {
                "id": issue_id,
                "text": text,
                "raised_by": raised_by,
                "timestamp": timestamp,
            }
        )
    issue_rows = dedupe(issue_rows, lambda r: r["id"])

    decision_rows: list[dict[str, Any]] = []
    for raw in entities.get("decisions", []) if isinstance(entities.get("decisions"), list) else []:
        if not isinstance(raw, dict):
            continue
        text = norm(raw.get("text"))
        made_by = norm(raw.get("made_by"))
        timestamp = norm(raw.get("timestamp"))
        decision_id = norm(raw.get("id")) or stable_id("D", text, made_by, timestamp)
        if not text and not decision_id:
            continue
        decision_rows.append(
            {
                "id": decision_id,
                "text": text,
                "made_by": made_by,
                "timestamp": timestamp,
            }
        )
    decision_rows = dedupe(decision_rows, lambda r: r["id"])

    action_rows: list[dict[str, Any]] = []
    action_topic_ref_rows: list[dict[str, Any]] = []
    for raw in entities.get("action_items", []) if isinstance(entities.get("action_items"), list) else []:
        if not isinstance(raw, dict):
            continue
        task = norm(raw.get("task"))
        owner = norm(raw.get("owner"))
        deadline = norm(raw.get("deadline"))
        timestamp = norm(raw.get("timestamp"))
        topic_ref = norm(raw.get("topic_ref"))
        action_id = norm(raw.get("id")) or stable_id("A", task, owner, deadline, timestamp, topic_ref)
        if not task and not action_id:
            continue
        action_rows.append(
            {
                "id": action_id,
                "task": task,
                "owner": owner,
                "deadline": deadline,
                "timestamp": timestamp,
                "topic_ref": topic_ref,
            }
        )
        if topic_ref:
            action_topic_ref_rows.append({"action_id": action_id, "topic_id": topic_ref})
    action_rows = dedupe(action_rows, lambda r: r["id"])
    action_topic_ref_rows = dedupe(action_topic_ref_rows, lambda r: f"{r['action_id']}|{r['topic_id']}")

    topic_rows: list[dict[str, Any]] = []
    topic_speaker_rows: list[dict[str, Any]] = []
    topic_issue_rows: list[dict[str, Any]] = []
    topic_decision_rows: list[dict[str, Any]] = []
    topic_action_rows: list[dict[str, Any]] = []

    for idx, raw in enumerate(topics, start=1):
        if not isinstance(raw, dict):
            continue
        topic_id = norm(raw.get("id")) or f"T{idx:03d}"
        key_speakers = sanitize_list(raw.get("key_speakers"))
        issue_refs = sanitize_list(raw.get("issues"))
        decision_refs = sanitize_list(raw.get("decisions"))
        action_refs = sanitize_list(raw.get("action_items"))
        row = {
            "id": topic_id,
            "name": norm(raw.get("name")),
            "department": norm(raw.get("department")),
            "start_timestamp": norm(raw.get("start_timestamp")),
            "end_timestamp": norm(raw.get("end_timestamp")),
            "duration_minutes": to_int(raw.get("duration_minutes"), 0),
            "key_speakers": key_speakers,
            "slide_timestamps": sanitize_list(raw.get("slide_timestamps")),
            "summary_points": sanitize_list(raw.get("summary_points")),
        }
        topic_rows.append(row)

        for speaker in key_speakers:
            topic_speaker_rows.append({"topic_id": topic_id, "speaker": speaker})
        for ref in issue_refs:
            topic_issue_rows.append({"topic_id": topic_id, "ref": ref})
        for ref in decision_refs:
            topic_decision_rows.append({"topic_id": topic_id, "ref": ref})
        for ref in action_refs:
            topic_action_rows.append({"topic_id": topic_id, "ref": ref})

    topic_rows = dedupe(topic_rows, lambda r: r["id"])
    topic_speaker_rows = dedupe(topic_speaker_rows, lambda r: f"{r['topic_id']}|{r['speaker']}")
    topic_issue_rows = dedupe(topic_issue_rows, lambda r: f"{r['topic_id']}|{r['ref']}")
    topic_decision_rows = dedupe(topic_decision_rows, lambda r: f"{r['topic_id']}|{r['ref']}")
    topic_action_rows = dedupe(topic_action_rows, lambda r: f"{r['topic_id']}|{r['ref']}")

    return {
        "people": people_rows,
        "projects": project_rows,
        "equipment": equipment_rows,
        "financials": financial_rows,
        "issues": issue_rows,
        "decisions": decision_rows,
        "actions": action_rows,
        "topics": topic_rows,
        "topic_speakers": topic_speaker_rows,
        "topic_issues": topic_issue_rows,
        "topic_decisions": topic_decision_rows,
        "topic_actions": topic_action_rows,
        "action_topic_refs": action_topic_ref_rows,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import agent2_kg.json into Neo4j")
    parser.add_argument("--kg-path", default="./output/artifacts/agent2_kg.json")
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "bolt://localhost:7687"))
    parser.add_argument("--user", default=os.getenv("NEO4J_USER", "neo4j"))
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD", ""))
    parser.add_argument("--database", default=os.getenv("NEO4J_DATABASE", "neo4j"))
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument(
        "--clear",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Clear existing graph before import (default: true)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.password:
        raise SystemExit("Missing Neo4j password. Set --password or NEO4J_PASSWORD")

    kg_path = Path(args.kg_path).expanduser()
    kg = load_kg(kg_path)
    rows = build_rows(kg)

    driver = GraphDatabase.driver(args.uri, auth=(args.user, args.password))
    with driver.session(database=args.database) as session:
        if args.clear:
            session.run("MATCH (n) DETACH DELETE n").consume()

        for query in CONSTRAINT_QUERIES:
            session.run(query).consume()

        run_batched(session, QUERY_PEOPLE, rows["people"], args.batch_size)
        run_batched(session, QUERY_PROJECTS, rows["projects"], args.batch_size)
        run_batched(session, QUERY_EQUIPMENT, rows["equipment"], args.batch_size)
        run_batched(session, QUERY_FINANCIALS, rows["financials"], args.batch_size)
        run_batched(session, QUERY_ISSUES, rows["issues"], args.batch_size)
        run_batched(session, QUERY_DECISIONS, rows["decisions"], args.batch_size)
        run_batched(session, QUERY_ACTIONS, rows["actions"], args.batch_size)
        run_batched(session, QUERY_TOPICS, rows["topics"], args.batch_size)
        run_batched(session, QUERY_TOPIC_SPEAKERS, rows["topic_speakers"], args.batch_size)
        run_batched(session, QUERY_TOPIC_ISSUES, rows["topic_issues"], args.batch_size)
        run_batched(session, QUERY_TOPIC_DECISIONS, rows["topic_decisions"], args.batch_size)
        run_batched(session, QUERY_TOPIC_ACTIONS, rows["topic_actions"], args.batch_size)
        run_batched(session, QUERY_ACTION_TOPIC_REF, rows["action_topic_refs"], args.batch_size)

        result = session.run(
            """
            CALL () { MATCH (p:Person) RETURN count(p) AS c_person }
            CALL () { MATCH (p:Project) RETURN count(p) AS c_project }
            CALL () { MATCH (e:Equipment) RETURN count(e) AS c_equipment }
            CALL () { MATCH (f:Financial) RETURN count(f) AS c_financial }
            CALL () { MATCH (i:Issue) RETURN count(i) AS c_issue }
            CALL () { MATCH (d:Decision) RETURN count(d) AS c_decision }
            CALL () { MATCH (a:ActionItem) RETURN count(a) AS c_action }
            CALL () { MATCH (t:Topic) RETURN count(t) AS c_topic }
            RETURN {
              Person: c_person,
              Project: c_project,
              Equipment: c_equipment,
              Financial: c_financial,
              Issue: c_issue,
              Decision: c_decision,
              ActionItem: c_action,
              Topic: c_topic
            } AS counts
            """
        ).single()

    driver.close()
    counts = dict(result["counts"]) if result and result.get("counts") else {}
    print("Imported KG to Neo4j")
    print(f"Source: {kg_path.resolve()}")
    print(f"Neo4j: {args.uri} db={args.database}")
    print(f"Counts: {counts}")


if __name__ == "__main__":
    main()
