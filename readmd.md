# Meeting Summary Agentic Workflow (Detailed Verification Doc)

เอกสารนี้เป็นฉบับละเอียดสำหรับตรวจสอบว่า pipeline ทำงานอย่างไรจริงในโค้ดปัจจุบัน

## TL;DR

- ระบบปัจจุบันใช้ **LangChain + LangGraph**
- `orchestrator.py` เป็น thin entrypoint และรัน graph ใน `workflow_graph.py`
- แต่ละ Agent ถูกแมปเป็น LangGraph node (Agent 1,2,3A/3B,2.5,4,5)
- ใช้ **map-reduce + per-topic calls** เพื่อกัน context overflow
- มี **JSON repair/retry**, **Typhoon token-limit handling**, และ **HTML fallback renderer**

---

## 1) Current Architecture Status

### 1.1 ใช้ LangGraph หรือไม่?

**คำตอบ: ใช้ LangGraph แล้ว**

สถานะปัจจุบัน:
- graph runtime อยู่ที่ `workflow_graph.py`
- state type: `WorkflowState`
- node/edge ชัดเจนใน `MeetingWorkflow._build_graph()`
- conditional routing: Agent2 -> Agent3A/3B

---

## 2) Inputs / Outputs

## 2.1 Inputs

- `transcript_YYYY-MM-DD.json`
  - ใช้ `segments[]` เป็นหลัก
  - โครงสร้างแต่ละ segment: `speaker`, `start`, `end`, `text`
- `config_YYYY-MM-DD.json`
  - ใช้ `MEETING_INFO`, `AGENDA_TEXT`
  - รองรับกรณี `MEETING_INFO` เป็น string ยาว (ไม่ใช่ object)
- `capture_ocr_results.json`
  - ใช้ `captures[]` เป็นหลัก
  - ฟิลด์สำคัญ: `capture_index`, `timestamp_sec`, `timestamp_hms`, `image_path`, `ocr_text`, `ocr_file_size_bytes`, `ocr_skipped_reason`

## 2.2 Outputs

- ผลลัพธ์หลัก: `output/meeting_report.html`
- artifacts (เมื่อ `SAVE_INTERMEDIATE=true`):
  - `output/artifacts/run_YYYYMMDD_HHMMSS/runtime.log`
  - `output/artifacts/run_YYYYMMDD_HHMMSS/agent1_cleaned.json`
  - `output/artifacts/run_YYYYMMDD_HHMMSS/agent2_kg.json`
  - `output/artifacts/run_YYYYMMDD_HHMMSS/agent3_topic_map.json`
  - `output/artifacts/run_YYYYMMDD_HHMMSS/agent25_image_manifest.json`
  - `output/artifacts/run_YYYYMMDD_HHMMSS/agent4_summaries.json`
  - `output/artifacts/run_YYYYMMDD_HHMMSS/agent5_report.html`
  - `output/artifacts/run_YYYYMMDD_HHMMSS/run_metadata.json`

---

## 3) End-to-End Flow

```text
LangGraph Nodes:
load_inputs
  -> agent1
  -> agent2
  -> (conditional) agent3a | agent3b
  -> agent25
  -> agent4
  -> agent5
  -> END
```

---

## 4) Agent Responsibilities (Detailed)

## 4.1 Agent 1 — Data Preprocessor

เป้าหมาย:
- normalize transcript/OCR/config ให้เป็น `meeting_meta + timeline + slides`

วิธีทำ:
- map phase:
  - chunk transcript ตาม `AGENT1_CHUNK_SIZE` (default ปัจจุบัน `120`) และ overlap `AGENT1_CHUNK_OVERLAP` (default `1`)
  - ต่อ OCR subset เฉพาะช่วงเวลา chunk ±120 วินาที
  - เรียก LLM สำหรับ transcript-only (ไม่พ่วง OCR)
  - ก่อนส่งเข้า LLM จะย่อ OCR เป็น `title/flags/ocr_text snippet` (ไม่ส่ง table เต็ม)
  - จำกัดจำนวน OCR ต่อ chunk ด้วย `AGENT1_OCR_MAX_CAPTURES` และตัด snippet ตาม `AGENT1_OCR_SNIPPET_CHARS`
  - เรียก LLM แยกอีกครั้งสำหรับ OCR-only แล้ว merge ผลกับ transcript
  - ใน OCR-only path จะ chunk `ocr_text` เป็น 1000 ตัวอักษร overlap 10% ต่อ capture
- reduce phase (deterministic ใน Python):
  - รวม timeline ทุก chunk
  - sort ตามเวลา
  - merge speaker เดียวกัน gap < 3s
  - dedupe slides
  - เติม slide context ใกล้สุดภายใน ±60s
  - normalize meeting_meta และ parse attendees fallback จาก `MEETING_INFO` string

output keys:
- `meeting_meta`, `timeline`, `slides`

## 4.2 Agent 2 — Knowledge Graph Builder

เป้าหมาย:
- สกัด entities + topics + decisions + action items ให้ครบ

วิธีทำ:
- map phase:
  - chunk timeline ตาม `AGENT2_CHUNK_SIZE` (default ปัจจุบัน `160`)
  - แนบ slides เฉพาะช่วงเวลาใกล้ chunk
  - call LLM เพื่อได้ partial KG
- reduce phase:
  - รวม partial KGs ด้วย reducer prompt
- post-process:
  - สร้าง embedding ต่อ topic text (`name + summary_points`) ผ่าน Ollama
  - เก็บใน `topic["_vec"]` ใช้สำหรับ semantic matching ภายหลัง

output keys:
- `entities`, `topics`

## 4.3 Agent 3 — Topic Mapping Layer

โหมด `agenda`:
- ใช้ Agent 3A
- แตก `AGENDA_TEXT` เป็นบรรทัด
- embed agenda lines
- cosine เทียบกับ topic embeddings
- สร้าง `semantic_hints`
- call LLM เพื่อทำ agenda mapping

โหมด `auto`:
- ใช้ Agent 3B
- ให้ LLM สกัดหัวข้อประชุมเองจาก KG + timeline sample

output:
- agenda mode: `agenda_mapping`, `coverage_stats`, `unscheduled_discussions`
- auto mode: `extracted_topics`, `topic_flow`

## 4.4 Agent 2.5 — Image Intelligence

เป้าหมาย:
- วิเคราะห์ OCR captures แล้วจัดภาพเข้า section หัวข้อแบบพร้อม render

วิธีทำ:
- map phase:
  - chunk captures ตาม `AGENT25_CHUNK_SIZE` (default ปัจจุบัน `12`)
  - LLM classify + priority + render_as + caption + topic
- reduce phase:
  - รวม partial manifests
  - dedupe by `capture_index`
  - รวม statistics
- post-process deterministic:
  - re-rank topic ด้วย embedding similarity
  - resolve image path แบบหลายชั้น
  - ใส่ base64 ตาม `IMAGE_EMBED_MODE`
  - ก่อน/หลัง (`BEFORE_AFTER`) ใส่ `before_base64` / `after_base64` เมื่อหา pair ได้
  - group by topic + filter + cap:
    - priority >= 3
    - file size >= threshold
    - จำกัดจำนวนต่อหัวข้อ

## 4.5 Agent 4 — Content Summarizer

เป้าหมาย:
- เขียนสรุปรายหัวข้อแบบทางการ + executive summary

วิธีทำ:
- สร้าง `topic_items` จาก Agent 3 output
- call ต่อ 1 topic (ลด token risk)
  - แนบ KG + topic item + timeline snippet + slides snippet
- เก็บผลใน `topic_summaries[]`
- call แยกอีก 1 ครั้งเพื่อสร้าง `executive_summary_th`
- backfill fields ถ้า response ขาดฟิลด์สำคัญ

output:
- `topic_summaries`, `executive_summary_th`, `total_decisions`, `total_action_items`, `meeting_duration`

## 4.6 Agent 5 — HTML Generator

เป้าหมาย:
- สร้าง HTML รายงานประชุมฉบับสมบูรณ์

วิธีทำ:
- call LLM 1 ครั้ง พร้อม metadata + summaries + KG + image manifest + CSS/JS bundle
- validate HTML compliance:
  - ต้องมี `<!doctype html>`, `<style>`, `<script>`, `id="lb-overlay"`
  - ต้องมี section cues ตามลำดับหลัก
- ถ้าไม่ผ่าน:
  - fallback เป็น deterministic renderer (`html_renderer.py`)

---

## 5) Reliability, Retry, and Fallback

## 5.1 LLM routing

ลำดับ provider:
1. Typhoon (ถ้าคอนฟิกและใช้งานได้)
2. Ollama chat fallback (เฉพาะเมื่อ `ALLOW_OLLAMA_CHAT_FALLBACK=true`)

นโยบายที่รองรับ:
- Option A (default): `ALLOW_OLLAMA_CHAT_FALLBACK=false` → Typhoon-only สำหรับ chat
- Option B: `ALLOW_OLLAMA_CHAT_FALLBACK=true` → เปิด Ollama chat fallback พร้อม warning ใน runtime

การ handle max token ของ Typhoon:
- มี env `TYPHOON_MAX_TOKENS` สำหรับกำหนด output budget
- ถ้าเจอ token-limit error ระบบจะ:
  1) ลด `max_tokens` ลงแบบ adaptive
  2) ถ้ายังชน limit จะ shrink prompt โดยเก็บหัว/ท้ายไว้
  3) ถ้ายังไม่ผ่านจึง fallback ไป provider ถัดไป (ถ้าอนุญาต fallback)

## 5.2 JSON robustness

สำหรับ JSON-mode calls:
- parse JSON จาก raw response
- ถ้า parse ไม่ได้:
  - heuristic extract
  - ถ้ายังไม่ได้: เรียก JSON repair prompt
- validate required keys
- retry สูงสุด `LLM_MAX_RETRIES`
- กรณี Agent2 reduce ได้ `topics=[]` ระบบจะทำ deterministic fallback จาก partial KGs และถ้ายังว่างจะ synthesize topics จาก timeline แทนการ crash

## 5.3 HTML robustness

- ถ้า Agent5 output ไม่ผ่าน compliance
- ระบบยังออกไฟล์ได้ โดยใช้ deterministic fallback renderer

---

## 6) Chunking Strategy (Implemented)

- Agent 1 map: `AGENT1_CHUNK_SIZE` segments/chunk, overlap `AGENT1_CHUNK_OVERLAP`
  - ถ้า chunk fail สามารถแตก subchunk ได้ด้วย `AGENT1_SUBCHUNK_ON_FAILURE` + `AGENT1_SUBCHUNK_SIZE`
- Agent 2 map: `AGENT2_CHUNK_SIZE` timeline entries/chunk
- Agent 2.5 map: `AGENT25_CHUNK_SIZE` captures/chunk
- Agent 4: per-topic calls (หนึ่งหัวข้อต่อหนึ่ง call)

เหตุผล:
- ลดโอกาสชน context window
- ลดความเสี่ยงตกหล่นจาก long prompt เดียวขนาดใหญ่

---

## 7) File/Module Responsibilities

- `orchestrator.py`
  - CLI + load env + start LangGraph workflow
- `workflow_graph.py`
  - นิยาม LangGraph nodes + conditional edges + execution runtime
- `pipeline_utils.py`
  - config dataclass
  - helpers (`chunked`, `cosine`, time converters)
  - deterministic reduce ของ Agent 1
- `llm_client.py`
  - Typhoon-first + Ollama fallback
  - JSON parse/repair/retry + call logging
  - embeddings via Ollama
- `image_processor.py`
  - resolve image path
  - base64 conversion
  - manifest grouping + merge
- `html_renderer.py`
  - HTML compliance check
  - deterministic fallback HTML
- `prompts.py`
  - system/user prompts ทั้งหมด
  - CSS/JS bundle

---

## 8) Config Variables (Operational)

กลุ่มหลักที่ระบบใช้งานจริง:
- Provider
  - `TYPHOON_API_KEY`, `TYPHOON_BASE_URL`, `TYPHOON_MODEL`
  - `TYPHOON_MAX_TOKENS`
  - `ALLOW_OLLAMA_CHAT_FALLBACK`
  - `OLLAMA_BASE_URL`, `OLLAMA_CHAT_MODEL`, `OLLAMA_EMBED_MODEL`
- Pipeline
  - `SUMMARIZE_MODE`, `INCLUDE_OCR`, `IMAGE_INSERT_ENABLED`
  - `SAVE_INTERMEDIATE`, `LLM_MAX_RETRIES`, `LLM_TIMEOUT_SEC`
  - `AGENT1_CHUNK_SIZE`, `AGENT1_CHUNK_OVERLAP`, `AGENT1_SUBCHUNK_ON_FAILURE`, `AGENT1_SUBCHUNK_SIZE`
  - `AGENT1_OCR_MAX_CAPTURES`, `AGENT1_OCR_SNIPPET_CHARS`
  - `AGENT2_CHUNK_SIZE`, `AGENT25_CHUNK_SIZE`
  - `PIPELINE_MAX_CONCURRENCY` (parallel map/topic calls; ค่า `2` = ยิงพร้อมกันสองคำขอ)
- Image
  - `IMAGE_BASE_DIR`, `IMAGE_EMBED_MODE`, `IMAGE_MAX_PER_TOPIC`, `IMAGE_MIN_FILE_SIZE_KB`
- Paths
  - `TRANSCRIPT_PATH`, `CONFIG_PATH`, `OCR_PATH`, `OUTPUT_HTML_PATH`

---

## 9) Run Commands

```bash
python orchestrator.py
python orchestrator.py --mode agenda
python orchestrator.py --mode auto --output ./output/report_auto.html
python orchestrator.py --mode agenda --save-artifacts false
python orchestrator.py --resume-artifact-dir ./output/artifacts/run_YYYYMMDD_HHMMSS
```

---

## 10) Verification Checklist (สำหรับคอนเฟิร์ม)

- [ ] รันได้ครบโดยไม่ crash
- [ ] มี `output/meeting_report.html`
- [ ] (ถ้าเปิด artifacts) มีไฟล์ครบ 7 รายการตาม section 2.2
- [ ] มี `runtime.log` และเห็นบรรทัด log แบบ `chunk x/y` ของ Agent 1/2/2.5/4
- [ ] `run_metadata.json` มี provider call log
- [ ] HTML มี section หลักครบและเรียงลำดับถูก
- [ ] รูปในแต่ละหัวข้อถูก group ตาม priority/cap
- [ ] ไม่มี `_vec` หลุดไปใน payload ฝั่ง Agent 5

---

## 11) LangGraph Mapping (Implemented)

mapping ที่ใช้งานจริง:
- `load_inputs`
- `agent1` (map + reduce ใน node เดียว)
- `agent2` (map + reduce + embed)
- `agent3a` / `agent3b` (conditional)
- `agent25` (map + reduce + post-process)
- `agent4` (topic summaries + executive)
- `agent5` (html generation + validate/fallback + write outputs)
