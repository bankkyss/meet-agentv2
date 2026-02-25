"""HTML validation and deterministic fallback renderer."""

from __future__ import annotations

from html import escape
from typing import Any

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


def _collect_unmapped_images(
    image_by_topic: dict[str, list[dict[str, Any]]],
    mapped_topic_ids: set[str],
) -> list[dict[str, Any]]:
    extra: list[dict[str, Any]] = []
    seen: set[int] = set()
    for topic_id, items in image_by_topic.items():
        if topic_id in mapped_topic_ids:
            continue
        for item in items:
            cap_idx = int(item.get("capture_index", 0) or 0)
            if cap_idx > 0 and cap_idx in seen:
                continue
            if cap_idx > 0:
                seen.add(cap_idx)
            extra.append(item)
    extra.sort(key=lambda x: float(x.get("timestamp_sec", 0) or 0))
    return extra


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
    mapped_topic_ids: set[str] = set()
    for idx, t in enumerate(topic_summaries, start=1):
        topic_id = str(t.get("topic_id", "") or f"T{idx:03d}")
        mapped_topic_ids.add(topic_id)
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

    unmatched_images = _collect_unmapped_images(image_by_topic, mapped_topic_ids)
    unmatched_html = ""
    if unmatched_images:
        unmapped_blocks, fig_counter = render_images_block(unmatched_images, fig_counter)
        unmatched_html = (
            '<h2 class="section-title">ภาคผนวก — ภาพประกอบที่ยังไม่จับคู่หัวข้อ</h2>'
            '<div class="summary-text"><p>'
            f"ตรวจพบภาพจาก OCR เพิ่มเติม {len(unmatched_images)} รายการ "
            "แต่ไม่พบหัวข้อสรุปที่แมปตรงกันในรอบนี้ จึงแสดงรวมในภาคผนวก"
            "</p></div>"
            f'<div class="summary-text">{unmapped_blocks}</div>'
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

  {unmatched_html}

</main>
</body>
    </html>
    """
    return html


def _pick_image_src(item: dict[str, Any], preferred: str = "image_base64") -> str:
    candidates = []
    if preferred:
        candidates.append(str(item.get(preferred, "") or ""))
    candidates.extend(
        [
            str(item.get("image_base64", "") or ""),
            str(item.get("before_base64", "") or ""),
            str(item.get("after_base64", "") or ""),
            str(item.get("resolved_image_path", "") or ""),
            str(item.get("image_path", "") or ""),
        ]
    )
    for src in candidates:
        if src:
            return src
    return ""


def _render_official_media(item: dict[str, Any], fig_num: int) -> str:
    render_as = str(item.get("render_as", "") or "")
    summary = escape(str(item.get("content_summary", "") or "ภาพประกอบ"))
    caption = escape(str(item.get("caption_th", "") or ""))
    ts = escape(str(item.get("timestamp_hms", "") or ""))

    if render_as == "html_table":
        table_html = str(item.get("table_html", "") or "")
        if table_html:
            return (
                '<div class="agenda-image-wrap">'
                f'<div class="agenda-image-caption"><strong>ตารางที่ {fig_num}</strong> {summary}</div>'
                f"{table_html}"
                f'<div class="agenda-image-link">{caption} <span class="ts">{ts}</span></div>'
                "</div>"
            )

    if render_as == "before_after" or str(item.get("special_pattern", "") or "") == "BEFORE_AFTER":
        before = escape(_pick_image_src(item, preferred="before_base64"))
        after = escape(_pick_image_src(item, preferred="after_base64"))
        return (
            '<div class="agenda-image-wrap">'
            '<div class="before-after-grid">'
            f'<div><img src="{before}" alt="before"><div class="ba-tag">ก่อน</div></div>'
            f'<div><img src="{after}" alt="after"><div class="ba-tag">หลัง</div></div>'
            "</div>"
            f'<div class="agenda-image-caption"><strong>รูปที่ {fig_num}</strong> {caption}</div>'
            f'<div class="agenda-image-link">เวลาอ้างอิง: {ts}</div>'
            "</div>"
        )

    src = escape(_pick_image_src(item))
    if not src:
        return ""
    return (
        '<div class="agenda-image-wrap">'
        f'<img src="{src}" alt="{summary}" loading="lazy"/>'
        f'<div class="agenda-image-caption"><strong>รูปที่ {fig_num}</strong> {caption}</div>'
        f'<div class="agenda-image-link">เวลาอ้างอิง: {ts}</div>'
        "</div>"
    )


def fallback_render_html_react_official(
    meta: dict[str, Any],
    summaries: dict[str, Any],
    kg: dict[str, Any],
    image_by_topic: dict[str, list[dict[str, Any]]],
) -> str:
    attendees = meta.get("attendees", []) if isinstance(meta.get("attendees"), list) else []
    topic_summaries = summaries.get("topic_summaries", [])
    if not isinstance(topic_summaries, list):
        topic_summaries = []

    attendees_main = [a for a in attendees if isinstance(a, dict) and str(a.get("type", "main")) == "main"]
    attendees_supp = [a for a in attendees if isinstance(a, dict) and str(a.get("type", "main")) != "main"]

    def attendee_items(rows: list[dict[str, Any]]) -> str:
        out = []
        for i, a in enumerate(rows, start=1):
            out.append(
                f'<div class="attendee-item">{i}. {escape(str(a.get("name", "") or ""))}'
                f' - {escape(str(a.get("department", "") or ""))}</div>'
            )
        return "".join(out)

    exec_summary = split_paragraphs(str(summaries.get("executive_summary_th", "") or ""))
    if not exec_summary:
        exec_summary = ["ไม่มีข้อมูลบทสรุปผู้บริหาร"]

    decision_rows: list[tuple[str, str, str]] = []
    action_rows: list[tuple[str, str, str, str]] = []
    topic_html: list[str] = []
    figure_num = 1
    mapped_topic_ids: set[str] = set()

    for idx, t in enumerate(topic_summaries, start=1):
        if not isinstance(t, dict):
            continue
        agenda_number = str(t.get("agenda_number", idx) or idx)
        topic_id = str(t.get("topic_id", "") or f"T{idx:03d}")
        mapped_topic_ids.add(topic_id)
        title = str(t.get("title", "") or "")
        department = str(t.get("department", "") or "")
        time_range = str(t.get("time_range", "") or "")
        presenter = str(t.get("presenter", "") or "")

        imgs = list(image_by_topic.get(topic_id, []))
        imgs.sort(
            key=lambda x: (
                -int(x.get("insertion_priority", 0) or 0),
                float(x.get("timestamp_sec", 0) or 0),
            )
        )
        media_blocks: list[str] = []
        for item in imgs:
            block = _render_official_media(item, figure_num)
            if block:
                media_blocks.append(block)
                figure_num += 1

        summary_blocks = "".join(f"<p>{escape(p)}</p>" for p in split_paragraphs(str(t.get("summary_th", "") or "")))
        if not summary_blocks:
            summary_blocks = "<p>ไม่มีข้อมูลสรุป</p>"

        decisions = t.get("decisions", [])
        if not isinstance(decisions, list):
            decisions = []
        decision_list = "".join(f"<li>{escape(str(d))}</li>" for d in decisions) or "<li>-</li>"
        for d in decisions:
            decision_rows.append((agenda_number, str(d), presenter))

        actions = t.get("action_items", [])
        if not isinstance(actions, list):
            actions = []
        action_trs: list[str] = []
        for a in actions:
            if isinstance(a, dict):
                task = str(a.get("task", "") or "")
                owner = str(a.get("owner", presenter) or presenter)
                deadline = str(a.get("deadline", "") or "")
            else:
                task = str(a)
                owner = presenter
                deadline = ""
            action_rows.append((agenda_number, task, owner, deadline))
            action_trs.append(
                "<tr>"
                f"<td>{escape(task)}</td><td>{escape(owner)}</td><td>{escape(deadline)}</td>"
                "</tr>"
            )
        if not action_trs:
            action_trs = ["<tr><td>-</td><td>-</td><td>-</td></tr>"]

        topic_html.append(
            f'<h3>วาระที่ {escape(agenda_number)} - {escape(title)}</h3>'
            '<div><h4>รายละเอียดวาระ</h4>'
            f'<blockquote>หน่วยงาน: {escape(department)} | ช่วงเวลา: {escape(time_range)}</blockquote>'
            f"{''.join(media_blocks)}"
            f"{summary_blocks}"
            "</div>"
            '<div><h4>มติที่ประชุม</h4>'
            f"<ul>{decision_list}</ul></div>"
            '<div><h4>งานที่ต้องดำเนินการ</h4>'
            '<table><tr><th>งาน</th><th>ผู้รับผิดชอบ</th><th>กำหนดเสร็จ</th></tr>'
            f"{''.join(action_trs)}</table></div>"
        )

    unmapped_images = _collect_unmapped_images(image_by_topic, mapped_topic_ids)
    unmapped_blocks: list[str] = []
    for item in unmapped_images:
        block = _render_official_media(item, figure_num)
        if block:
            unmapped_blocks.append(block)
            figure_num += 1
    unmapped_html = ""
    if unmapped_blocks:
        unmapped_html = (
            "<h3>ภาคผนวก - ภาพประกอบที่ยังไม่จับคู่หัวข้อ</h3>"
            "<p>ภาพที่ตรวจพบจาก OCR แต่ไม่ตรงกับวาระที่ถูกสรุปในรอบนี้</p>"
            f"{''.join(unmapped_blocks)}"
        )

    decision_table_rows = "".join(
        "<tr>"
        f"<td>{i}</td><td>{escape(a)}</td><td>{escape(b)}</td><td>{escape(c)}</td>"
        "</tr>"
        for i, (a, b, c) in enumerate(decision_rows, start=1)
    ) or "<tr><td colspan='4'>ไม่มีข้อมูล</td></tr>"

    action_table_rows = "".join(
        "<tr>"
        f"<td>{i}</td><td>{escape(a)}</td><td>{escape(b)}</td><td>{escape(c)}</td><td>{escape(d)}</td>"
        "</tr>"
        for i, (a, b, c, d) in enumerate(action_rows, start=1)
    ) or "<tr><td colspan='5'>ไม่มีข้อมูล</td></tr>"

    html = f"""<!DOCTYPE html>
<html lang="th">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link href="https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;600;700&display=swap" rel="stylesheet">
  <title>{escape(str(meta.get("title", "รายงานการประชุม") or "รายงานการประชุม"))}</title>
  <style>
    * {{ font-family: 'Sarabun', sans-serif !important; box-sizing: border-box; }}
    body {{ max-width: 1000px; margin: 0 auto; padding: 28px 36px; color: #111; line-height: 1.45; background-color: #fff; font-size: 15px; }}
    .header-box {{ text-align: center; margin-bottom: 14px; padding-bottom: 10px; border-bottom: 2px solid #111; }}
    .attendees-box {{ padding: 0; margin-bottom: 18px; font-size: 0.98em; }}
    .attendees-header {{ font-weight: 700; margin-top: 8px; margin-bottom: 2px; }}
    .attendee-item {{ margin-left: 0; }}
    h3 {{ margin-top: 20px; margin-bottom: 8px; padding: 0; font-size: 1.08em; border-bottom: 1px solid #666; }}
    h4 {{ margin-top: 12px; margin-bottom: 6px; font-size: 1.0em; }}
    ul {{ margin-top: 4px; margin-bottom: 8px; }}
    li {{ margin-bottom: 2px; }}
    table {{ width: 100%; border-collapse: collapse; margin: 10px 0 12px; border: 1px solid #000; }}
    th, td {{ border: 1px solid #000; padding: 6px 8px; text-align: left; vertical-align: top; }}
    th {{ background-color: #f5f5f5; font-weight: 700; }}
    blockquote {{ margin: 6px 0; padding: 6px 10px; border-left: 3px solid #888; background: #fafafa; }}
    .agenda-image-wrap {{ margin: 10px 0 14px; border: 1px solid #d4d4d4; background: #fafafa; border-radius: 8px; overflow: hidden; }}
    .agenda-image-wrap img {{ width: 100%; height: auto; display: block; background: #111; }}
    .agenda-image-caption {{ font-size: 0.86em; color: #333; padding: 7px 10px; border-top: 1px solid #ddd; }}
    .agenda-image-link {{ font-size: 0.84em; color: #1a1a1a; padding: 0 10px 9px; }}
    .agenda-image-link .ts {{ margin-left: 8px; color: #666; font-family: monospace; }}
    .before-after-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6px; padding: 8px; background: #f3f3f3; }}
    .before-after-grid > div {{ position: relative; }}
    .ba-tag {{ position: absolute; top: 8px; left: 8px; background: rgba(0,0,0,.65); color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; }}
    .footer {{ text-align: center; color: #333; font-size: 0.85em; margin-top: 28px; border-top: 1px solid #aaa; padding-top: 10px; }}
    @media print {{
      body {{ padding: 12mm; }}
      .agenda-image-wrap, table, blockquote {{ break-inside: avoid; }}
    }}
  </style>
</head>
<body>
  <div class="header-box">
    <div>{escape(str(meta.get("title", "รายงานการประชุมประจำเดือน") or "รายงานการประชุมประจำเดือน"))}</div><br>
    <div>{escape(str(meta.get("company", "บริษัทแสงฟ้าก่อสร้าง จำกัด") or "บริษัทแสงฟ้าก่อสร้าง จำกัด"))}</div><br>
    <div>{escape(str(meta.get("date", "") or ""))} {escape(str(meta.get("time_range", "") or ""))}</div><br>
    <div>{escape(str(meta.get("platform", "ZOOM") or "ZOOM"))}</div>
  </div>

  <div class="attendees-box">
    <div class="attendees-header">รายชื่อผู้เข้าประชุม</div>
    {attendee_items(attendees_main)}
    <div class="attendees-header">รายชื่อผู้เข้าประชุมสมทบ</div>
    {attendee_items(attendees_supp)}
  </div>
  <hr>

  <h3>บทสรุปผู้บริหาร</h3>
  {"".join(f"<p>{escape(p)}</p>" for p in exec_summary)}

  {"".join(topic_html)}

  <h3>ตารางมติที่ประชุม</h3>
  <table>
    <tr><th>ลำดับ</th><th>วาระ</th><th>มติ</th><th>ผู้รับผิดชอบ</th></tr>
    {decision_table_rows}
  </table>

  <h3>ตารางงานที่ต้องดำเนินการ</h3>
  <table>
    <tr><th>ลำดับ</th><th>วาระ</th><th>งาน</th><th>ผู้รับผิดชอบ</th><th>กำหนดเสร็จ</th></tr>
    {action_table_rows}
  </table>

  {unmapped_html}

  <div class="footer">เอกสารสรุปรายงานการประชุม (อัตโนมัติ)</div>
</body>
</html>"""
    return html
