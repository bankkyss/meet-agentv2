"""HTML validation and deterministic fallback renderer."""

from __future__ import annotations

from html import escape
from typing import Any

from pipeline_utils import hms_to_sec
from prompts import HTML_CSS_JS_BUNDLE


def html_has_sections_in_order(html: str) -> bool:
    lower = html.lower()
    required = ["<!doctype html", "<style>", "<script>", "id=\"lb-overlay\""]
    if not all(r in lower for r in required):
        return False

    cues = [
        "รายงานการประชุม",
        "ผู้เข้าประชุม",
        "สารบัญ",
        "บทสรุปผู้บริหาร",
        "วาระที่",
        "มติ",
        "งานที่ต้องดำเนินการ",
        "ภาคผนวก",
    ]
    pos = -1
    for cue in cues:
        i = html.find(cue)
        if i < 0:
            return False
        if i < pos:
            return False
        pos = i
    return True


def split_paragraphs(text: str) -> list[str]:
    lines = [x.strip() for x in str(text).replace("\r", "").split("\n")]
    buf: list[str] = []
    cur: list[str] = []
    for line in lines:
        if not line:
            if cur:
                buf.append(" ".join(cur).strip())
                cur = []
            continue
        cur.append(line)
    if cur:
        buf.append(" ".join(cur).strip())
    if not buf and str(text).strip():
        buf = [str(text).strip()]
    return buf


def render_figure(item: dict[str, Any], fig_num: int) -> str:
    render_as = str(item.get("render_as", "") or "")
    content_summary = escape(str(item.get("content_summary", "")))
    caption = escape(str(item.get("caption_th", "")))
    ts = escape(str(item.get("timestamp_hms", "")))

    if render_as == "html_table":
        table_html = str(item.get("table_html", "") or "")
        return (
            '<figure class="slide-figure data-table">'
            f'<button class="table-toggle">{content_summary}</button>'
            f'<div class="table-body-wrap"><div class="table-body">{table_html}</div></div>'
            '<figcaption>'
            f'<span class="fig-num">ตารางที่ {fig_num}</span>'
            f'<span class="fig-caption">{caption}</span>'
            f'<span class="fig-timestamp">{ts}</span>'
            "</figcaption>"
            "</figure>"
        )

    if render_as == "before_after" or str(item.get("special_pattern", "")) == "BEFORE_AFTER":
        before = str(item.get("before_base64", "") or item.get("image_base64", ""))
        after = str(item.get("after_base64", "") or item.get("image_base64", ""))
        return (
            '<figure class="slide-figure before-after">'
            '<div class="before-after-container">'
            '<div class="before-after-panel">'
            f'<img src="{before}" alt="before"><span class="ba-label">ก่อน</span>'
            "</div>"
            '<div class="before-after-panel">'
            f'<img src="{after}" alt="after"><span class="ba-label after">หลัง</span>'
            "</div></div>"
            '<figcaption>'
            f'<span class="fig-num">รูปที่ {fig_num}</span>'
            f'<span class="fig-caption">{caption}</span>'
            f'<span class="fig-timestamp">{ts}</span>'
            "</figcaption></figure>"
        )

    if render_as == "document_ref":
        return (
            '<div class="doc-ref-card">'
            '<span class="doc-icon">📄</span>'
            f"<div><strong>{content_summary}</strong><p>{caption}</p></div>"
            f'<span class="fig-timestamp">{ts}</span>'
            "</div>"
        )

    img = str(item.get("image_base64", "") or "")
    if not img:
        img = escape(str(item.get("image_path", "") or ""))
    return (
        '<figure class="slide-figure photo-lightbox">'
        '<div class="figure-content">'
        f'<img src="{img}" alt="{content_summary}" loading="lazy">'
        '<span class="zoom-icon">🔍</span>'
        "</div>"
        '<figcaption>'
        f'<span class="fig-num">รูปที่ {fig_num}</span>'
        f'<span class="fig-caption">{caption}</span>'
        f'<span class="fig-timestamp">{ts}</span>'
        "</figcaption></figure>"
    )


def render_images_block(images: list[dict[str, Any]], start_num: int) -> tuple[str, int]:
    html_parts: list[str] = []
    n = start_num
    for i, item in enumerate(images):
        html_parts.append(render_figure(item, n))
        n += 1
        if i < len(images) - 1:
            cur = str(item.get("render_as", ""))
            nxt = str(images[i + 1].get("render_as", ""))
            if cur in {"photo_lightbox", "before_after"} and nxt in {"photo_lightbox", "before_after"}:
                html_parts.append('<p class="summary-text">รายละเอียดประกอบเพิ่มเติมตามภาพถัดไป</p>')
    return "\n".join(html_parts), n


def fallback_render_html(
    meta: dict[str, Any],
    summaries: dict[str, Any],
    kg: dict[str, Any],
    image_by_topic: dict[str, list[dict[str, Any]]],
) -> str:
    attendees = meta.get("attendees", []) if isinstance(meta.get("attendees"), list) else []
    topic_summaries = summaries.get("topic_summaries", [])
    exec_summary = str(summaries.get("executive_summary_th", ""))

    departments = sorted(
        {
            str(t.get("department", "") or "")
            for t in topic_summaries
            if str(t.get("department", "") or "")
        }
    )

    decision_rows: list[tuple[str, str, str, str]] = []
    action_rows: list[tuple[str, str, str, str, str]] = []

    for t in topic_summaries:
        agenda_no = str(t.get("agenda_number", t.get("topic_id", "")) or "")
        decisions = t.get("decisions", []) if isinstance(t.get("decisions"), list) else []
        actions = t.get("action_items", []) if isinstance(t.get("action_items"), list) else []
        owner_default = str(t.get("presenter", "") or "")
        for d in decisions:
            decision_rows.append((agenda_no, str(d), agenda_no, owner_default))
        for a in actions:
            if isinstance(a, dict):
                action_rows.append(
                    (
                        agenda_no,
                        str(a.get("task", "") or ""),
                        str(a.get("owner", owner_default) or ""),
                        str(a.get("deadline", "") or ""),
                        agenda_no,
                    )
                )
            else:
                action_rows.append((agenda_no, str(a), owner_default, "", agenda_no))

    flat_images: list[dict[str, Any]] = []
    for topic_id, items in image_by_topic.items():
        for it in items:
            row = dict(it)
            row["_topic_id"] = topic_id
            flat_images.append(row)

    max_sec = 1
    for t in topic_summaries:
        tr = str(t.get("time_range", "") or "")
        parts = [x.strip() for x in tr.replace("–", "-").split("-")]
        if len(parts) == 2:
            max_sec = max(max_sec, hms_to_sec(parts[1]))

    toc_rows = []
    for idx, t in enumerate(topic_summaries, start=1):
        ag = str(t.get("agenda_number", idx))
        title = escape(str(t.get("title", "")))
        dept = escape(str(t.get("department", "")))
        trange = escape(str(t.get("time_range", "")))
        toc_rows.append(
            f'<a class="toc-item" href="#topic-{idx}">'
            f'<span class="toc-num">{escape(ag)}</span>'
            f'<span class="toc-title">{title}</span>'
            f'<span class="badge badge-dept">{dept}</span>'
            f'<span class="badge badge-time">{trange}</span>'
            "</a>"
        )

    topic_html: list[str] = []
    fig_counter = 1
    for idx, t in enumerate(topic_summaries, start=1):
        topic_id = str(t.get("topic_id", "") or f"T{idx:03d}")
        dept = str(t.get("department", "") or "")
        trange = str(t.get("time_range", "") or "")
        start_hms = "00:00:00"
        if trange:
            parts = [x.strip() for x in trange.replace("–", "-").split("-")]
            if parts:
                start_hms = parts[0]

        imgs = list(image_by_topic.get(topic_id, []))
        p5 = [x for x in imgs if int(x.get("insertion_priority", 0) or 0) >= 5]
        p4 = [x for x in imgs if int(x.get("insertion_priority", 0) or 0) == 4]
        p3 = [x for x in imgs if int(x.get("insertion_priority", 0) or 0) == 3]

        paras = split_paragraphs(str(t.get("summary_th", "")))
        if not paras:
            paras = ["ไม่มีข้อมูลสรุป"]

        before_text, fig_counter = render_images_block(p5, fig_counter)
        after_p1, fig_counter = render_images_block(p4, fig_counter)
        end_block, fig_counter = render_images_block(p3, fig_counter)

        summary_chunks: list[str] = []
        if before_text:
            summary_chunks.append(before_text)

        summary_chunks.append(f"<p>{escape(paras[0])}</p>")
        if after_p1:
            summary_chunks.append(after_p1)
        for p in paras[1:]:
            summary_chunks.append(f"<p>{escape(p)}</p>")
        if end_block:
            summary_chunks.append(end_block)

        decision_list = t.get("decisions", []) if isinstance(t.get("decisions"), list) else []
        decisions_html = "".join(f"<li>{escape(str(d))}</li>" for d in decision_list) or "<li>ไม่มีมติที่ต้องบันทึกเพิ่มเติม</li>"

        action_list = t.get("action_items", []) if isinstance(t.get("action_items"), list) else []
        action_trs = []
        for a in action_list:
            if isinstance(a, dict):
                action_trs.append(
                    "<tr>"
                    f"<td>{escape(str(a.get('task', '')))}</td>"
                    f"<td>{escape(str(a.get('owner', '')))}</td>"
                    f"<td>{escape(str(a.get('deadline', '')))}</td>"
                    "</tr>"
                )
            else:
                action_trs.append("<tr>" f"<td>{escape(str(a))}</td><td></td><td></td>" "</tr>")
        if not action_trs:
            action_trs.append("<tr><td>ไม่มีงานที่มอบหมายเพิ่มเติม</td><td>-</td><td>-</td></tr>")

        topic_html.append(
            f'<section id="topic-{idx}" class="topic-section" data-dept="{escape(dept)}" data-start="{escape(start_hms)}">'
            '<div class="topic-header">'
            f'<h3 class="agenda-title">วาระที่ {escape(str(t.get("agenda_number", idx)))} — {escape(str(t.get("title", "")))}</h3>'
            f'<span class="badge badge-dept">{escape(dept)}</span>'
            f'<span class="badge badge-time">{escape(trange)}</span>'
            f'<span class="badge badge-status-discussed">{escape(str(t.get("status", "")))}</span>'
            "</div>"
            f'<div class="summary-text">{"".join(summary_chunks)}</div>'
            '<div class="decisions-box"><h4>มติที่ประชุม</h4><ol>'
            f"{decisions_html}</ol></div>"
            '<div class="actions-box"><h4>งานที่ได้รับมอบหมาย</h4>'
            '<table class="actions-table"><thead><tr><th>งาน</th><th>ผู้รับผิดชอบ</th><th>กำหนดเสร็จ</th></tr></thead><tbody>'
            f"{''.join(action_trs)}</tbody></table></div>"
            "</section>"
        )

    timeline_segments = []
    colors = {
        "DATA_TABLE": "#1a3a5c",
        "PHOTO": "#2e7d32",
        "CHART": "#e65100",
        "DOCUMENT": "#5e35b1",
        "SLIDE_TEXT": "#546e7a",
    }
    for item in flat_images:
        ts = float(item.get("timestamp_sec", 0) or 0)
        left = max(min(ts / max_sec * 100, 100), 0)
        width = max(100 / max(len(flat_images), 1), 1.4)
        ctype = str(item.get("content_type", "SLIDE_TEXT"))
        color = colors.get(ctype, "#607d8b")
        label = escape(str(item.get("timestamp_hms", "")))
        title = escape(f"{item.get('topic_name', '')} | {item.get('content_summary', '')}")
        timeline_segments.append(
            f'<div class="timeline-segment" style="left:{left:.2f}%;width:{width:.2f}%;background:{color};" title="{title}">'
            f"<span>{label}</span></div>"
        )

    attendees_rows = []
    for i, a in enumerate(attendees, start=1):
        attendees_rows.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td>{escape(str(a.get('name', '')))}</td>"
            f"<td>{escape(str(a.get('department', '')))}</td>"
            f"<td>{'หลัก' if str(a.get('type', 'main')) == 'main' else 'สมทบ'}</td>"
            "</tr>"
        )

    decision_table_rows = []
    for i, row in enumerate(decision_rows, start=1):
        decision_table_rows.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td>{escape(row[1])}</td>"
            f"<td>{escape(row[2])}</td>"
            f"<td>{escape(row[3])}</td>"
            "</tr>"
        )

    action_table_rows = []
    for i, row in enumerate(action_rows, start=1):
        action_table_rows.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td>{escape(row[1])}</td>"
            f"<td>{escape(row[2])}</td>"
            f"<td>{escape(row[3])}</td>"
            f"<td>{escape(row[4])}</td>"
            "</tr>"
        )

    dept_options = ['<option value="all">ทั้งหมด</option>']
    dept_options.extend(f'<option value="{escape(d)}">{escape(d)}</option>' for d in departments)

    html = f"""<!doctype html>
<html lang="th">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(str(meta.get('title', 'รายงานการประชุม')))}</title>
{HTML_CSS_JS_BUNDLE}
</head>
<body>
<button class="print-btn" onclick="window.print()">พิมพ์รายงาน</button>
<section class="cover">
  <h1>{escape(str(meta.get('company', 'บริษัทแสงฟ้าก่อสร้าง จำกัด')))}</h1>
  <h2>{escape(str(meta.get('title', 'รายงานการประชุมประจำเดือน')))}</h2>
  <div class="cover-meta">
    <div><strong>วันที่:</strong> {escape(str(meta.get('date', '')))}</div>
    <div><strong>เวลา:</strong> {escape(str(meta.get('time_range', '')))}</div>
    <div><strong>แพลตฟอร์ม:</strong> {escape(str(meta.get('platform', 'ZOOM')))}</div>
    <div><strong>ประธาน:</strong> {escape(str(meta.get('chairperson', '')))}</div>
  </div>
</section>
<main class="page">
  <h2 class="section-title">รายชื่อผู้เข้าประชุม</h2>
  <table class="attendees">
    <thead><tr><th>ลำดับ</th><th>ชื่อ-สกุล</th><th>แผนก</th><th>ประเภท</th></tr></thead>
    <tbody>{''.join(attendees_rows)}</tbody>
  </table>

  <div class="toc">
    <button class="toc-toggle">สารบัญ <span>[+/-]</span></button>
    <div class="toc-body">{''.join(toc_rows)}</div>
  </div>

  <h2 class="section-title">บทสรุปผู้บริหาร</h2>
  <div class="exec-stats">
    <div class="stat-card"><div class="num">{int(summaries.get('total_decisions', 0) or 0)}</div><div class="label">มติ</div></div>
    <div class="stat-card"><div class="num">{int(summaries.get('total_action_items', 0) or 0)}</div><div class="label">งานที่ต้องดำเนินการ</div></div>
    <div class="stat-card"><div class="num">{len(departments)}</div><div class="label">หน่วยงาน</div></div>
  </div>
  <div class="summary-text">{''.join(f'<p>{escape(p)}</p>' for p in split_paragraphs(exec_summary))}</div>

  <div class="dept-filter-bar"><label for="dept-filter">กรองตามแผนก:</label>
    <select id="dept-filter">{''.join(dept_options)}</select>
  </div>

  {''.join(topic_html)}

  <h2 class="section-title">ตารางมติที่ประชุม</h2>
  <table class="log-table">
    <thead><tr><th>ลำดับ</th><th>มติ</th><th>วาระอ้างอิง</th><th>ผู้รับผิดชอบ</th></tr></thead>
    <tbody>{''.join(decision_table_rows) or '<tr><td colspan="4">ไม่มีข้อมูล</td></tr>'}</tbody>
  </table>

  <h2 class="section-title">ตารางงานที่ต้องดำเนินการ</h2>
  <table class="log-table">
    <thead><tr><th>ลำดับ</th><th>งานที่ต้องดำเนินการ</th><th>ผู้รับผิดชอบ</th><th>กำหนดเสร็จ</th><th>วาระ</th></tr></thead>
    <tbody>{''.join(action_table_rows) or '<tr><td colspan="5">ไม่มีข้อมูล</td></tr>'}</tbody>
  </table>

  <h2 class="section-title">ภาคผนวก — Slide Timeline</h2>
  <div class="timeline-bar">{''.join(timeline_segments)}</div>
</main>
</body>
</html>
"""
    return html
