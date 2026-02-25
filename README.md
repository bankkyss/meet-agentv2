# Meeting Summarizer (LangChain + LangGraph)

Pipeline สร้างรายงานประชุม HTML จาก 3 input:
- `transcript_YYYY-MM-DD.json`
- `config_YYYY-MM-DD.json`
- `capture_ocr_results.json`

## Project Structure

```text
.
├── orchestrator.py        # thin entrypoint (CLI + load .env + run graph)
├── workflow_graph.py      # LangGraph StateGraph (Agent 1..5 nodes + routing)
├── pipeline_utils.py      # config/dataclass + shared helpers + Agent1 reduce
├── llm_client.py          # LangChain chat routing + JSON repair/retry + token handling
├── html_renderer.py       # HTML compliance check + deterministic fallback renderer
├── image_processor.py     # image path resolve/base64/grouping helpers
├── prompts.py             # all agent prompts + CSS/JS bundle
└── data/...               # inputs
```

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

แก้ `.env` ให้ครบก่อนรัน โดยรองรับ 2 นโยบาย:
- `Option A (default)`: `ALLOW_OLLAMA_CHAT_FALLBACK=false` → Typhoon-only สำหรับ chat
- `Option B`: `ALLOW_OLLAMA_CHAT_FALLBACK=true` → ถ้า Typhoon ใช้ไม่ได้จะ fallback ไป `OLLAMA_CHAT_MODEL` พร้อม warning
- token handling: ถ้า Typhoon ชน token limit ระบบจะลด `TYPHOON_MAX_TOKENS` อัตโนมัติและ shrink prompt ก่อนตัดสินใจ fallback

## Run

```bash
python orchestrator.py
python orchestrator.py --mode agenda
python orchestrator.py --report-layout react_official --output ./output/meeting_report_official.html
python orchestrator.py --mode auto --output ./output/report_auto.html --save-artifacts false
python orchestrator.py --resume-artifact-dir ./output/artifacts/run_20260224_104605
```

`--resume-artifact-dir` จะโหลด `agent1_cleaned.json` จาก run เดิมและข้าม Agent1 เพื่อรันต่อที่ Agent2
และถ้าโฟลเดอร์เดียวกันมี `agent2_kg.json` ด้วย ระบบจะข้าม Agent2 ต่ออัตโนมัติ

ปรับ chunk size ได้จาก `.env`:
- `AGENT1_CHUNK_SIZE` (default `120`)
- `AGENT1_CHUNK_OVERLAP` (default `1`)
- `AGENT1_SUBCHUNK_ON_FAILURE` (default `true`)
- `AGENT1_SUBCHUNK_SIZE` (default `40`)
- `AGENT1_OCR_MAX_CAPTURES` (default `3`, จำกัดจำนวน OCR ต่อ Agent1 chunk)
- `AGENT1_OCR_SNIPPET_CHARS` (default `220`, ตัดข้อความ OCR ต่อรูป)
- `AGENT2_CHUNK_SIZE` (default `160`)
- `AGENT25_CHUNK_SIZE` (default `12`)
- `PIPELINE_MAX_CONCURRENCY` (default `1`, ตั้ง `2` เพื่อยิง LLM พร้อมกัน 2 งาน)
- `REPORT_LAYOUT_MODE` (`current` | `react_official`, default `current`)

## Output

- ไฟล์หลัก: `output/meeting_report.html`
- ไฟล์ตรวจสอบย้อนหลัง: `output/artifacts/run_YYYYMMDD_HHMMSS/`
  - `runtime.log` (log ละเอียดระดับ chunk)
  - `agent1_cleaned.json`
  - `agent2_kg.json`
  - `agent3_topic_map.json`
  - `agent25_image_manifest.json`
  - `agent4_summaries.json`
  - `agent5_report.html`
  - `run_metadata.json`

## Neo4j Visualization

รัน Neo4j (ตั้งรหัสผ่านให้ชัดเจนก่อน):

```bash
docker run -d --name meetsum-neo4j \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/neo4j12345 \
  neo4j:5
```

import `agent2_kg.json` เข้า Neo4j:

```bash
pip install -r requirements.txt
python3 scripts/import_agent2_kg_to_neo4j.py \
  --kg-path ./output/artifacts/agent2_kg.json \
  --uri bolt://localhost:7687 \
  --user neo4j \
  --password neo4j12345
```

เปิด Browser ที่ `http://localhost:7474` แล้วลอง query:

```cypher
MATCH (n) RETURN n LIMIT 200;
```

```cypher
MATCH (t:Topic)-[r]-(x) RETURN t, r, x LIMIT 300;
```

## Notes

- ใช้ map-reduce chunking สำหรับ transcript/OCR ขนาดใหญ่
- Agent1 ส่ง OCR เข้า LLM แบบย่อ (`title/flags/ocr_text snippet`) เพื่อลด JSON fail จากตาราง OCR ขนาดใหญ่
- Agent1 จะคัด OCR เฉพาะรูปที่ใกล้ช่วงเวลา chunk ที่สุดตาม `AGENT1_OCR_MAX_CAPTURES`
- Agent1 แยกทางทำงาน: transcript ใช้ LLM แบบ transcript-only และ OCR ใช้ LLM แบบ ocr-only (แยก call แล้ว merge)
- ฝั่ง OCR-only จะตัดข้อความ OCR เป็นชิ้นละ 1000 ตัวอักษร overlap 10% ก่อนส่ง LLM
- มี JSON repair + retry (สูงสุด 3 ครั้ง)
- ถ้า HTML จาก Agent 5 ไม่ครบโครงสร้าง จะ fallback เป็น deterministic renderer
- กรณี OCR image path ไม่ตรง filesystem มี resolver fallback หลายชั้น
