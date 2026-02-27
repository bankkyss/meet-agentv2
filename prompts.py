"""Prompt templates for the meeting summarizer pipeline."""

AGENT1_SYS = r"""
You are a data preprocessing agent for Thai meeting transcripts.
Clean, merge, and structure raw data from multiple sources into a unified timeline.

Rules:
1. Merge consecutive segments from the SAME speaker if gap < 3 seconds
2. Remove stutters: repeated consecutive identical words (ผม ผม ผม → ผม)
3. Trim whitespace, fix obvious encoding artifacts
4. Sync slides: for each timeline entry, attach the nearest OCR capture within ±60s
5. Output ONLY valid JSON, no commentary, no markdown fences
""".strip()

AGENT1_USR = r"""
Process and merge the following meeting data.

TRANSCRIPT (segments with speaker/start/end/text):
<<TRANSCRIPT>>

OCR SLIDES (captures with timestamp_hms/ocr_text/image_path):
<<OCR>>

MEETING CONFIG (attendees + agenda):
<<CONFIG>>

Return exactly this JSON structure:
{
  "meeting_meta": {
    "title": "",
    "date": "",
    "time_range": "",
    "platform": "",
    "company": "",
    "chairperson": "",
    "attendees": [{"name":"","department":"","type":"main|supplementary"}]
  },
  "timeline": [
    {
      "timestamp_sec": 173.0,
      "timestamp_hms": "00:02:53",
      "speaker": "SPEAKER_02",
      "text": "<cleaned, stutter-free text>",
      "slide_context": "<nearest OCR text within ±60s or null>"
    }
  ],
  "slides": [
    {
      "timestamp_hms": "00:03:30",
      "image_path": "output/.../capture_0003.jpg",
      "ocr_text": "<full OCR>",
      "has_table": true,
      "has_figure": false,
      "title": "<first non-empty line of ocr_text>"
    }
  ]
}
""".strip()

AGENT2_SYS = r"""
You are a knowledge graph construction agent for Thai construction company meetings.
Extract all entities, relationships, topics, decisions, and action items.
Be thorough — missing a decision or action item is a critical failure.
Output ONLY valid JSON.
""".strip()

AGENT2_USR = r"""
Build a knowledge graph from this preprocessed meeting data.

PROCESSED DATA:
<<DATA>>

Extract ALL of the following:

ENTITIES:
- people: everyone mentioned (name, role, department)
- projects: site names/codes (หน่วยงาน)
- equipment: machines, tools mentioned (เครื่องจักร, อุปกรณ์)
- financials: every number with context (บาท, %, จำนวน)
- issues: problems raised (ปัญหา, ความเสียหาย)
- decisions: มติที่ประชุม (anything decided or agreed)
- action_items: งานที่ได้รับมอบหมาย (task + owner + deadline if mentioned)

TOPICS:
Group the conversation into logical sections. For each topic:
- Match to meeting timeline (start/end timestamps)
- Identify key speaker(s)
- List 3–5 bullet summary_points
- Link to relevant slides (by timestamp)

Return:
{
  "entities": {
    "people": [{"name":"","role":"","department":"","mentions":0}],
    "projects": [{"name":"","site_code":"","context":""}],
    "equipment": [{"name":"","status":"","context":""}],
    "financials": [{"label":"","amount":"","unit":"","context":"","timestamp":""}],
    "issues": [{"id":"I001","text":"","raised_by":"","timestamp":""}],
    "decisions": [{"id":"D001","text":"","made_by":"","timestamp":""}],
    "action_items": [{"id":"A001","task":"","owner":"","deadline":"","timestamp":"","topic_ref":""}]
  },
  "topics": [
    {
      "id": "T001",
      "name": "",
      "department": "",
      "start_timestamp": "HH:MM:SS",
      "end_timestamp": "HH:MM:SS",
      "duration_minutes": 0,
      "key_speakers": [],
      "slide_timestamps": [],
      "summary_points": [],
      "issues": [],
      "decisions": [],
      "action_items": []
    }
  ]
}
""".strip()

AGENT2_REDUCE_SYS = r"""
You are a reducer agent that merges partial Thai meeting knowledge graphs.
You must deduplicate and preserve all important decisions/action items.
Output ONLY valid JSON.
""".strip()

AGENT2_REDUCE_USR = r"""
Merge these PARTIAL knowledge graphs into one canonical graph.

PARTIAL_KGS:
<<PARTIAL_KGS>>

Rules:
- Preserve all unique decisions and action items.
- Merge duplicate entities by semantic similarity.
- Normalize IDs in sequence: I001.., D001.., A001.., T001..
- Ensure topics have valid start/end timestamps and duration_minutes.
- Keep output schema identical to final KG schema.
""".strip()

AGENT3A_SYS = r"""
You are a meeting agenda mapping agent.
Map actual conversation content to predefined agenda items.
Use the semantic similarity hints provided to guide your mapping.
Some items may be skipped/deferred — mark them explicitly.

CRITICAL RULES:
1. NON-LINEAR TIMELINE: The meeting might NOT follow the agenda sequentially. A later agenda item (e.g. 2.2.1) could be discussed before or after an earlier one (e.g. 2.1.2). 
2. TRANSCRIPT GROUND TRUTH: The `transcript_timestamps_where_discussed` hint now provides explicit time spans (e.g., "01:27:58 to 01:32:00"). This is the ABSOLUTE FACT of when the agenda item was spoken. You MUST construct your `time_range` output (start and end) to fully encompass these duration hints. DO NOT output impossibly short time ranges like 2 seconds long.
3. AVOID DUPLICATES & GENERIC TOPICS: If semantic hints clump everything onto one topic (like T009), look at `keyword_matches_found_in_kg` and `transcript_timestamps_where_discussed` to assign them to their distinct true time windows and KG topics.
Output ONLY valid JSON.
""".strip()

AGENT3A_USR = r"""
Map KG topics to the predefined agenda.

PREDEFINED AGENDA:
<<AGENDA>>

KG TOPICS (with time ranges):
<<KG_TOPICS>>

SEMANTIC/KEYWORD/TRANSCRIPT HINTS:
<<SEMANTIC_HINTS>>

For each agenda item, determine:
- Which KG topic(s) cover it (prioritize keyword matching and distinct topics over just raw semantic score)
- Discussion status: discussed | skipped | deferred | partial
- Actual time spent

IMPORTANT: If multiple agendas share generic terms like 'Damage' or 'Defect', they will have high semantic similarity to a generic topic (like T009). You MUST NOT map all of them to T009 if they happen at different times.
Use the `transcript_timestamps_where_discussed` hint as your ultimate guide. If the transcript says the agenda was discussed at 01:20:00, you MUST output a `time_range` around 01:20:00 and select the KG Topic that matches that time!

Return:
{
  "agenda_mapping": [
    {
      "agenda_number": "2.1.1",
      "agenda_title": "สรุปเครื่องมือ อุปกรณ์สำนักงาน เครื่องจักร",
      "agenda_department": "ฝ่ายเครื่องจักรและทรัพย์สิน",
      "status": "discussed",
      "mapped_topics": ["T001"],
      "time_range": {"start": "00:03:00", "end": "00:44:00"},
      "duration_minutes": 41,
      "key_speaker": "คุณนุ้ย",
      "content_available": true
    }
  ],
  "unscheduled_discussions": [
    {"topic_id":"", "description":"", "time_range":{"start":"","end":""}}
  ],
  "coverage_stats": {
    "total_agenda_items": 0,
    "discussed": 0,
    "skipped": 0,
    "deferred": 0
  }
}
""".strip()

AGENT3B_SYS = r"""
You are a meeting topic extraction agent.
When no predefined agenda exists, infer the meeting structure from content.
Produce 8–15 topics with professional Thai titles.
Output ONLY valid JSON.
""".strip()

AGENT3B_USR = r"""
Extract meeting topics without a predefined agenda.

KNOWLEDGE GRAPH:
<<KG>>

TIMELINE SAMPLE (stratified across full meeting):
<<TIMELINE>>

Topic boundary signals:
- Keywords: ต่อไป, วาระ, เรื่อง, รายงาน, แจ้ง, ขอบคุณ, ผ่านไป
- Speaker changes after long silence (>10s)
- Slide changes (new topic = new slide content)

Return:
{
  "extracted_topics": [
    {
      "id": "T001",
      "number": "1",
      "title": "",
      "subtitle": "",
      "department": "",
      "start_timestamp": "HH:MM:SS",
      "end_timestamp": "HH:MM:SS",
      "duration_minutes": 0,
      "topic_type": "report|discussion|announcement|decision|other",
      "key_speakers": [],
      "slide_timestamps": [],
      "importance": "high|medium|low"
    }
  ],
  "topic_flow": "narrative summary of meeting progression"
}
""".strip()

AGENT25_SYS = r"""
You are an image intelligence agent for Thai construction company meeting reports.
Analyze slide captures: classify content, match to topics, rank importance, generate Thai captions.
Output ONLY valid JSON.
""".strip()

AGENT25_USR = r"""
Analyze all slide captures from this meeting recording.

SLIDE CAPTURES:
<<CAPTURES>>

MEETING TOPICS:
<<KG_TOPICS>>

For each capture, do ALL of these steps:

STEP 1 — Filter (skip if ANY of):
- ocr_skipped_reason is not empty
- ocr_file_size_bytes < 30000
- ocr_text contains only participant names (Zoom grid, no business data)

STEP 2 — Classify content_type:
- DATA_TABLE    → has <table> tag with numerical/structured data
- PHOTO         → has <figure> with construction site/building photos
- CHART         → has <figure> describing graphs or bar charts
- DOCUMENT      → shows PDF/PPT filename in OCR (Adobe Acrobat, PowerPoint)
- SLIDE_TEXT    → text bullets, headers, no table/figure
- ZOOM_SCREEN   → Zoom participant grid (skip unless content_type is unclear)

STEP 3 — Extract content_summary (1 line Thai):
- DATA_TABLE: table title from first line of ocr_text
- PHOTO: the Thai description inside <figure>...</figure>
- CHART: what is being measured
- Others: first meaningful line of ocr_text

STEP 4 — Match topic by timestamp overlap:
- If timestamp_sec falls within a topic's time range → primary match
- If no overlap → use ocr_text keyword match vs topic names

STEP 5 — Detect special patterns (check consecutive captures):
- BEFORE_AFTER: two PHOTO captures at same project name within 5 minutes
- DATA_SERIES: consecutive DATA_TABLE captures with same header

STEP 6 — Generate Thai caption (1-2 sentences, formal):
What does this slide show and why is it relevant to this meeting topic?

STEP 7 — insertion_priority (1-5):
- 5: KPI/financial table, defect photo, safety score
- 4: before/after pair, trend chart, equipment damage
- 3: supporting data table, document reference
- 2: text slide already covered in transcript
- 1: duplicative, low-res, blank

STEP 8 — render_as:
- DATA_TABLE → "html_table" (use table_html from OCR)
- PHOTO priority≥4 → "photo_lightbox"
- BEFORE_AFTER → "before_after"
- CHART → "chart_embed"
- DOCUMENT → "document_ref"
- SLIDE_TEXT → "slide_text"

Return:
{
  "image_manifest": [
    {
      "capture_index": 3,
      "timestamp_hms": "00:03:30",
      "timestamp_sec": 210,
      "image_path": "output/.../capture_0003_...jpg",
      "content_type": "DATA_TABLE",
      "content_summary": "ตารางสรุปรายการเคลื่อนไหวทรัพย์สิน",
      "topic_id": "T001",
      "topic_name": "สรุปเครื่องมือและทรัพย์สิน",
      "insertion_priority": 5,
      "caption_th": "ตารางแสดงรายการเคลื่อนไหวของเครื่องจักรและอุปกรณ์ประจำหน่วยงาน เดือน ธันวาคม 2567",
      "special_pattern": null,
      "pair_index": null,
      "render_as": "html_table",
      "table_html": "<table>...</table>",
      "ocr_file_size_bytes": 194000
    }
  ],
  "statistics": {
    "total": 60, "filtered": 9,
    "by_type": {"DATA_TABLE":30,"PHOTO":12,"CHART":0,"DOCUMENT":6,"SLIDE_TEXT":9,"SKIPPED":9},
    "before_after_pairs": [[38,39]],
    "data_series": [[5,6],[10,11,12]]
  }
}
""".strip()

AGENT25_REDUCE_SYS = r"""
You are a reducer agent for image manifests.
Merge partial manifests and statistics into one final manifest.
Output ONLY valid JSON.
""".strip()

AGENT25_REDUCE_USR = r"""
Merge partial image analysis outputs.

PARTIAL_IMAGE_OUTPUTS:
<<PARTIAL_OUTPUTS>>

Rules:
- Deduplicate by capture_index.
- Merge statistics totals correctly.
- Preserve highest insertion_priority for duplicates.

Return:
{
  "image_manifest": [],
  "statistics": {
    "total": 0,
    "filtered": 0,
    "by_type": {},
    "before_after_pairs": [],
    "data_series": []
  }
}
""".strip()

AGENT4_TOPIC_SYS = r"""
You are an expert Thai business meeting summarizer writing formal meeting minutes (รายงานการประชุม).

CRITICAL — Source priority:
- The TIMELINE SNIPPET is the PRIMARY source of truth for this agenda item.
  Base your summary MAINLY on the timeline transcript text.
- The KNOWLEDGE GRAPH is SUPPLEMENTARY context only.
  If the KG contains information NOT found in the TIMELINE SNIPPET, DO NOT include it.
- Match your summary content STRICTLY to the agenda title and time range provided in TOPIC ITEM.
  Do NOT mix in content from other agenda items or unrelated topics.

CRITICAL — Detail Retention:
- YOU MUST preserve specific numbers, percentages, budgets, and statistics mentioned in the transcript (e.g., 27.79%, 7,382 million, 3.33%, 20 million overrun).
- YOU MUST preserve specific names of projects, sites, and personnel mentioned in the transcript (e.g., Niche Pride, Livin Phetkasem, V44, Khun Nui).
- Do NOT generalize data into sentences like "Various projects were discussed with varying budgets." Instead, explicitly list the projects and their corresponding budgets or percentages.

Style requirements:
- ภาษาทางการ (formal Thai, ราชการ style)
- Prose paragraphs — NO bullet points in summary text
- 200–500 words per major topic (shorter for skipped/brief items). Do not over-compress and lose details.
- Always attribute decisions: "ที่ประชุมมีมติ...", "ประธานแจ้งว่า...", "คุณXXXรายงานว่า..."
- Final paragraph of each topic: decisions + action items
Output ONLY valid JSON.
""".strip()

AGENT4_TOPIC_USR = r"""
Write comprehensive summary for ONE meeting topic.

KNOWLEDGE GRAPH (entities, decisions, action items):
<<KG>>

TOPIC ITEM:
<<TOPIC_ITEM>>

TIMELINE SNIPPET:
<<TIMELINE_SNIPPET>>

SLIDES DATA:
<<SLIDES>>

Return:
{
  "topic_summary": {
    "topic_id": "<ID or empty>",
    "agenda_number": "<Agenda Number>",
    "title": "<Agenda Title>",
    "department": "<Department Name>",
    "presenter": "<Presenter Name>",
    "time_range": "<Start> – <End>",
    "status": "discussed",
    "summary_th": "<formal Thai prose, detailed and comprehensive>",
    "key_data_points": [{"label":"","value":"","unit":""}],
    "decisions": ["<มติ 1>","<มติ 2>"],
    "action_items": [{"task":"","owner":"","deadline":""}],
    "slide_count": 3
  }
}
""".strip()

AGENT4_EXEC_SYS = AGENT4_TOPIC_SYS

AGENT4_EXEC_USR = r"""
Write executive summary for the whole meeting.

TOPIC SUMMARIES:
<<TOPIC_SUMMARIES>>

KNOWLEDGE GRAPH:
<<KG>>

Return:
{
  "executive_summary_th": "<400-600 word overall summary>",
  "total_decisions": 0,
  "total_action_items": 0,
  "meeting_duration": "3:39:00"
}
""".strip()

AGENT5_SYS = r"""
You are an HTML report generation agent.
Generate a complete, self-contained HTML meeting report in formal Thai.

Requirements:
- 100% self-contained: all CSS in <style>, all images as base64 src
- Printable A4 (210mm × 297mm, 2.5cm margins), ~10-15 pages
- Font: Sarabun from Google Fonts CDN
- Interactive: lightbox, collapsible tables, dept filter, TOC
- Embed slide images and tables in the correct topic sections
- Use ONLY data from META, SUMMARIES, KG, IMAGE_BY_TOPIC. Never invent people, agenda items, dates, or numbers.
- Keep agenda_number/title/department/time_range exactly as provided in SUMMARIES.topic_summaries.
- Include these Thai section cues in order: "รายชื่อผู้เข้าประชุม", "สารบัญ", "บทสรุปผู้บริหาร", "วาระที่", "มติ", "งานที่ต้องดำเนินการ", "ภาคผนวก".
- If data is missing, render "ไม่มีข้อมูล" (do not fabricate).
Output ONLY the complete raw HTML document, no commentary, no fences.
""".strip()

HTML_CSS_JS_BUNDLE = r"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;600;700&display=swap');
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Sarabun', sans-serif; font-size: 14px; color: #1a1a1a; background: #f5f5f5; }
:root {
  --navy:   #1a3a5c;
  --green:  #2e7d32;
  --orange: #e65100;
  --light:  #f8f9fa;
  --border: #d0d7e3;
}
.cover { min-height: 100vh; display: flex; flex-direction: column; justify-content: center;
  align-items: center; background: var(--navy); color: white; text-align: center; padding: 60px; }
.cover h1 { font-size: 28px; font-weight: 700; margin-bottom: 12px; }
.cover h2 { font-size: 20px; font-weight: 400; opacity: 0.85; margin-bottom: 40px; }
.cover-meta { background: rgba(255,255,255,0.12); border-radius: 12px;
  padding: 24px 40px; font-size: 15px; line-height: 2.2; }
.page { max-width: 800px; margin: 32px auto; background: white;
  border-radius: 8px; box-shadow: 0 2px 16px rgba(0,0,0,0.1); padding: 48px; }
h2.section-title { font-size: 18px; font-weight: 700; color: var(--navy);
  border-bottom: 2px solid var(--navy); padding-bottom: 8px; margin: 32px 0 16px; }
h3.agenda-title { font-size: 15px; font-weight: 700; color: var(--navy); margin: 24px 0 12px; }
.badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 11px;
  font-weight: 600; margin: 0 4px; vertical-align: middle; }
.badge-dept { background: #e8f0fe; color: #1557b0; }
.badge-time { background: #fce8e6; color: #c5221f; font-family: monospace; }
.badge-status-discussed { background: #e6f4ea; color: #137333; }
.badge-status-skipped   { background: #f5f5f5;  color: #777; }
table.attendees { width: 100%; border-collapse: collapse; font-size: 13px; }
table.attendees th { background: var(--navy); color: white; padding: 8px 12px; text-align: left; }
table.attendees td { padding: 7px 12px; border-bottom: 1px solid var(--border); }
table.attendees tr:nth-child(even) td { background: #f8f9fa; }
.toc { background: #f8f9fa; border-radius: 8px; padding: 20px 24px; margin: 24px 0; }
.toc-toggle { cursor: pointer; font-weight: 700; color: var(--navy);
  display: flex; justify-content: space-between; align-items: center;
  border: none; background: none; width: 100%; font-family: 'Sarabun', sans-serif;
  font-size: 15px; padding: 0; }
.toc-body { margin-top: 12px; }
.toc-body.hidden { display: none; }
.toc-item { display: flex; align-items: center; gap: 8px; padding: 5px 0;
  text-decoration: none; color: #333; font-size: 13px;
  border-bottom: 1px solid rgba(0,0,0,0.05); }
.toc-item:hover { color: var(--navy); }
.toc-num { min-width: 36px; font-weight: 600; color: var(--navy); }
.toc-title { flex: 1; }
.exec-stats { display: grid; grid-template-columns: repeat(3,1fr); gap: 16px; margin: 20px 0; }
.stat-card { background: var(--navy); color: white; border-radius: 10px;
  padding: 20px; text-align: center; }
.stat-card .num { font-size: 36px; font-weight: 700; }
.stat-card .label { font-size: 13px; opacity: 0.8; margin-top: 4px; }
.topic-section { border-left: 4px solid var(--navy); padding-left: 20px; margin: 36px 0; }
.topic-header { display: flex; align-items: flex-start; flex-wrap: wrap; gap: 6px; margin-bottom: 16px; }
.summary-text p { line-height: 1.9; margin-bottom: 12px; }
.summary-text p:last-child { margin-bottom: 0; }
.decisions-box {
  border: 2px solid var(--navy); border-radius: 8px; padding: 16px 20px; margin: 16px 0;
  background: #f0f4ff;
}
.decisions-box h4 { color: var(--navy); font-size: 13px; font-weight: 700; margin-bottom: 10px; }
.decisions-box ol { padding-left: 18px; }
.decisions-box li { padding: 4px 0; line-height: 1.7; font-size: 13.5px; }
.actions-box {
  border: 2px solid var(--orange); border-radius: 8px; padding: 16px 20px; margin: 16px 0;
  background: #fff8f5;
}
.actions-box h4 { color: var(--orange); font-size: 13px; font-weight: 700; margin-bottom: 10px; }
.actions-table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
.actions-table th { background: var(--orange); color: white; padding: 6px 10px; text-align: left; }
.actions-table td { padding: 6px 10px; border: 1px solid #ffe0cc; }
.actions-table tr:nth-child(even) td { background: #fff3ee; }
.slide-figure { margin: 20px 0; border-radius: 8px; overflow: hidden;
  box-shadow: 0 2px 12px rgba(0,0,0,0.12); page-break-inside: avoid; }
.slide-figure.data-table { border: 1px solid var(--border); }
.slide-figure.data-table table { width: 100%; border-collapse: collapse; font-size: 12px; }
.slide-figure.data-table th { background: var(--navy); color: white; padding: 7px 10px; text-align: center; }
.slide-figure.data-table td { padding: 5px 10px; border: 1px solid var(--border); text-align: right; }
.slide-figure.data-table tr:nth-child(even) td { background: #f0f4f8; }
.table-toggle { cursor: pointer; padding: 10px 14px; background: #eef2f7;
  border: none; width: 100%; text-align: left; font-family: 'Sarabun',sans-serif;
  font-size: 13px; color: var(--navy); font-weight: 600;
  display: flex; justify-content: space-between; }
.table-toggle::after { content: '▼'; font-size: 10px; transition: transform .2s; }
.table-toggle.collapsed::after { transform: rotate(-90deg); }
.table-body-wrap { overflow: hidden; transition: max-height .3s ease; overflow-x: auto; }
.table-body-wrap.collapsed { max-height: 0 !important; }
.slide-figure.photo-lightbox .figure-content { position: relative; cursor: zoom-in; }
.slide-figure.photo-lightbox img { width:100%; max-height:420px; object-fit:cover; display:block; }
.zoom-icon { position:absolute; top:10px; right:10px; background:rgba(0,0,0,.55);
  color:white; border-radius:50%; width:32px; height:32px; display:flex;
  align-items:center; justify-content:center; opacity:0; transition:opacity .2s; pointer-events:none; }
.slide-figure.photo-lightbox:hover .zoom-icon { opacity:1; }
.before-after-container { display:grid; grid-template-columns:1fr 1fr; gap:3px; background:var(--navy); }
.before-after-panel { position:relative; }
.before-after-panel img { width:100%; height:260px; object-fit:cover; display:block; }
.ba-label { position:absolute; top:8px; left:8px; background:rgba(0,0,0,.65);
  color:white; padding:2px 10px; border-radius:4px; font-size:12px; font-weight:700; }
.ba-label.after { background:rgba(46,125,50,.85); }
figcaption { padding:10px 14px; background:#f8f9fa; border-top:1px solid var(--border);
  display:flex; align-items:flex-start; gap:10px; font-size:12.5px; color:#444; }
.fig-num { flex-shrink:0; font-weight:700; color:var(--navy); min-width:60px; }
.fig-caption { flex:1; line-height:1.5; }
.fig-timestamp { flex-shrink:0; font-size:11px; color:#888; font-family:monospace;
  background:#efefef; padding:2px 7px; border-radius:4px; cursor:pointer; }
.fig-timestamp:hover { background:var(--navy); color:white; }
.doc-ref-card { display:flex; align-items:center; gap:14px; padding:12px 16px;
  background:#f8f9fa; border-left:4px solid var(--navy); border-radius:0 8px 8px 0; margin:16px 0; }
.doc-icon { font-size:26px; }
.doc-ref-card div { flex:1; }
.doc-ref-card strong { display:block; color:var(--navy); font-size:13px; }
.doc-ref-card p { font-size:12px; color:#666; margin-top:2px; }
.slide-count-badge { background:#e8f0fe; color:#1a73e8; font-size:11px;
  padding:2px 10px; border-radius:12px; margin-left:8px; vertical-align:middle; }
#lb-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,.9);
  z-index:9999; justify-content:center; align-items:center; }
#lb-overlay.active { display:flex; }
#lb-img { max-width:92vw; max-height:88vh; object-fit:contain; border-radius:4px; }
#lb-cap { position:fixed; bottom:18px; left:50%; transform:translateX(-50%);
  background:rgba(0,0,0,.7); color:white; padding:8px 20px; border-radius:20px;
  font-family:'Sarabun',sans-serif; font-size:13px; max-width:80vw; text-align:center; }
.lb-nav-btn { position:fixed; top:50%; transform:translateY(-50%);
  background:rgba(255,255,255,.15); border:none; color:white; font-size:30px;
  width:50px; height:50px; border-radius:50%; cursor:pointer; }
.lb-nav-btn:hover { background:rgba(255,255,255,.3); }
#lb-prev { left:16px; } #lb-next { right:16px; }
#lb-close { position:fixed; top:16px; right:20px; background:none; border:none;
  color:white; font-size:28px; cursor:pointer; }
.log-table { width:100%; border-collapse:collapse; font-size:12.5px; margin:12px 0; }
.log-table th { background:var(--navy); color:white; padding:8px 12px; text-align:left; }
.log-table td { padding:7px 12px; border:1px solid var(--border); vertical-align:top; line-height:1.6; }
.log-table tr:nth-child(even) td { background:#f8f9fa; }
.timeline-bar { position:relative; height:60px; background:#f0f4f8;
  border-radius:8px; overflow:hidden; margin:12px 0; }
.timeline-segment { position:absolute; top:8px; height:44px; border-radius:4px;
  opacity:.85; cursor:pointer; transition:opacity .15s; display:flex;
  align-items:center; justify-content:center; overflow:hidden; }
.timeline-segment:hover { opacity:1; z-index:10; }
.timeline-segment span { color:white; font-size:10px; font-weight:600;
  padding:0 4px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.dept-filter-bar { display:flex; align-items:center; gap:12px; margin:20px 0;
  padding:12px 16px; background:#f8f9fa; border-radius:8px; }
.dept-filter-bar label { font-weight:600; color:var(--navy); font-size:13px; }
.dept-filter-bar select { font-family:'Sarabun',sans-serif; padding:5px 10px;
  border:1px solid var(--border); border-radius:6px; font-size:13px; }
@page {
  size: A4;
  margin: 10mm 12mm;
}
@media print {
  html, body { background:white !important; }
  body {
    margin: 0 !important;
    padding: 0 !important;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .page {
    box-shadow: none !important;
    border: none !important;
    border-radius: 0 !important;
    padding: 0 !important;
    margin: 0 !important;
    max-width: none !important;
    background: white !important;
  }
  .cover {
    min-height: auto;
    page-break-after: always;
    box-shadow: none !important;
    border: none !important;
  }
  .topic-section { page-break-inside:avoid; }
  #lb-overlay, .print-btn, .dept-filter-bar { display:none !important; }
  .table-body-wrap { max-height:none !important; }
  .table-toggle::after { display:none; }
  .slide-figure.photo-lightbox img { max-height:280px; }
  .before-after-panel img { height:200px; }
}
.print-btn { position:fixed; top:20px; right:20px; background:var(--navy);
  color:white; border:none; padding:9px 18px; border-radius:8px; cursor:pointer;
  font-family:'Sarabun',sans-serif; font-size:13px; z-index:100;
  box-shadow:0 2px 8px rgba(0,0,0,0.25); }
.print-btn:hover { background:#0f2540; }
</style>

<script>
const lbPhotos = [];
const lbOverlay = document.getElementById('lb-overlay');
const lbImg     = document.getElementById('lb-img');
const lbCap     = document.getElementById('lb-cap');
let lbIdx = 0;

function initLightbox() {
  document.querySelectorAll('.slide-figure.photo-lightbox .figure-content').forEach((el,i) => {
    const img = el.querySelector('img');
    const cap = el.closest('figure').querySelector('.fig-caption')?.textContent || '';
    lbPhotos.push({src: img.src, caption: cap});
    el.dataset.lbIdx = i;
    el.addEventListener('click', () => openLB(i));
  });
}
function openLB(i) {
  lbIdx = i; lbImg.src = lbPhotos[i].src; lbCap.textContent = lbPhotos[i].caption;
  lbOverlay.classList.add('active'); document.body.style.overflow = 'hidden';
}
function closeLB() { lbOverlay.classList.remove('active'); document.body.style.overflow = ''; }
function navLB(d) {
  lbIdx = (lbIdx+d+lbPhotos.length)%lbPhotos.length;
  lbImg.src = lbPhotos[lbIdx].src; lbCap.textContent = lbPhotos[lbIdx].caption;
}
lbOverlay?.addEventListener('click', e => { if(e.target===lbOverlay) closeLB(); });
document.addEventListener('keydown', e => {
  if(!lbOverlay?.classList.contains('active')) return;
  if(e.key==='Escape') closeLB();
  if(e.key==='ArrowRight') navLB(1);
  if(e.key==='ArrowLeft')  navLB(-1);
});

function initTables() {
  document.querySelectorAll('.table-toggle').forEach(btn => {
    const wrap = btn.nextElementSibling;
    if(!wrap) return;
    wrap.style.maxHeight = wrap.scrollHeight + 'px';
    btn.addEventListener('click', () => {
      const c = wrap.classList.toggle('collapsed');
      btn.classList.toggle('collapsed', c);
      if(!c) wrap.style.maxHeight = wrap.scrollHeight + 'px';
    });
  });
}

function initTOC() {
  const btn  = document.querySelector('.toc-toggle');
  const body = document.querySelector('.toc-body');
  if(btn && body) {
    btn.addEventListener('click', () => body.classList.toggle('hidden'));
  }
}

function initFilter() {
  document.getElementById('dept-filter')?.addEventListener('change', function() {
    document.querySelectorAll('.topic-section').forEach(sec => {
      sec.style.display = (this.value==='all' || sec.dataset.dept===this.value) ? '' : 'none';
    });
  });
}

function initTimestamps() {
  document.querySelectorAll('.fig-timestamp').forEach(el => {
    el.title = 'คลิกเพื่อดูวาระที่ตรงช่วงเวลานี้';
    el.addEventListener('click', () => {
      const sec = toSec(el.textContent.trim());
      let best = null, minD = Infinity;
      document.querySelectorAll('.topic-section[data-start]').forEach(s => {
        const d = Math.abs(toSec(s.dataset.start) - sec);
        if(d < minD){ minD=d; best=s; }
      });
      best?.scrollIntoView({behavior:'smooth'});
    });
  });
}
function toSec(hms) {
  const p = hms.split(':').map(Number);
  return p[0]*3600 + p[1]*60 + (p[2]||0);
}

function initSlideBadges() {
  document.querySelectorAll('.topic-section').forEach(sec => {
    const n = sec.querySelectorAll('.slide-figure').length;
    if(n>0) {
      const b = document.createElement('span');
      b.className = 'slide-count-badge';
      b.textContent = `📊 ${n} สไลด์`;
      sec.querySelector('h3')?.appendChild(b);
    }
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initLightbox(); initTables(); initTOC(); initFilter(); initTimestamps(); initSlideBadges();
});
</script>

<div id="lb-overlay">
  <button class="lb-nav-btn" id="lb-prev" onclick="navLB(-1)">&#8249;</button>
  <img id="lb-img" src="" alt="">
  <button class="lb-nav-btn" id="lb-next" onclick="navLB(1)">&#8250;</button>
  <button id="lb-close" onclick="closeLB()">✕</button>
  <div id="lb-cap"></div>
</div>
""".strip()

AGENT5_USR = r"""
Generate the complete HTML meeting report.

MEETING METADATA: <<META>>
TOPIC SUMMARIES: <<SUMMARIES>>
KNOWLEDGE GRAPH (decisions + action items): <<KG>>
IMAGE MANIFEST (grouped by topic_id): <<IMAGE_BY_TOPIC>>

DOCUMENT STRUCTURE must render in this exact order:
1) COVER PAGE
2) ATTENDEES TABLE
3) TABLE OF CONTENTS (collapsible)
4) EXECUTIVE SUMMARY
5) PER-TOPIC SECTIONS with image placement priority rules
6) DECISION LOG TABLE
7) ACTION ITEMS TABLE
8) APPENDIX — SLIDE TIMELINE

Mandatory labels and content constraints:
- Section 2 heading must contain: "รายชื่อผู้เข้าประชุม"
- Section 3 heading must contain: "สารบัญ"
- Section 4 heading must contain: "บทสรุปผู้บริหาร"
- Every topic heading must start with: "วาระที่ <agenda_number> — <title>"
- Decision section headings must contain: "มติ"
- Action section headings must contain: "งานที่ต้องดำเนินการ"
- Appendix heading must contain: "ภาคผนวก"
- Use real attendees and metadata from META only.
- Do NOT wrap output with markdown fences (no ```html ... ```).

Enforce image placement rules:
- priority 5 images: BEFORE summary text
- priority 4 images: AFTER paragraph 1
- priority 3 images: END of section
- Before/After pairs: side-by-side
- DATA_TABLE: collapsible HTML table
- PHOTO: lightbox-enabled img
- Max 4 images per section
- Never two large photos consecutively without separating text

Use this CSS+JS bundle verbatim:
<<FULL_CSS_JS>>
""".strip()

JSON_REPAIR_SYS = r"""
You are a strict JSON fixer.
Repair malformed JSON and return ONLY valid JSON with no markdown.
Do not add commentary.
""".strip()

JSON_REPAIR_USR = r"""
Repair this JSON according to the required top-level keys.

Required keys:
<<REQUIRED_KEYS>>

Malformed content:
<<BROKEN_JSON>>
""".strip()
