"""HTML validation and deterministic fallback renderer."""

from __future__ import annotations

import re
from html import escape
from typing import Any

from pipeline_utils import hms_to_sec
from prompts import HTML_CSS_JS_BUNDLE


REACT_OFFICIAL_THEME_OVERRIDE = """
<style id="react-official-theme">
:root {
  --navy: #1f2937 !important;
  --orange: #9a6700 !important;
  --gray: #374151 !important;
  --light: #f6f3ed !important;
  --border: #d6cec1 !important;
}
body {
  background: transparent !important;
  color: #111111 !important;
}
.page {
  background: #ffffff !important;
  border: none !important;
  box-shadow: none !important;
  border-radius: 0 !important;
  max-width: 980px !important;
  padding: 30px 30px !important;
}
.cover {
  background: linear-gradient(180deg, #f7f2e8 0%, #ece4d5 100%) !important;
  color: #1f2937 !important;
  box-shadow: none !important;
  border: 1px solid #d6cec1 !important;
}
.cover h1, .cover h2 {
  letter-spacing: 0.2px;
}
.section-title {
  border-left: none !important;
  background: #ffffff !important;
  padding-left: 0 !important;
}
.topic-section {
  border: none !important;
  box-shadow: none !important;
  border-radius: 6px !important;
}
.topic-header {
  background: transparent !important;
}
.agenda-meta {
  margin: 0 0 10px 0 !important;
  color: #4b5563 !important;
  font-size: 13px !important;
}
.agenda-group-header {
  margin: 18px 0 8px !important;
  padding: 0 0 4px 0 !important;
  border-bottom: 1px solid #c9d0da !important;
  font-size: 18px !important;
  font-weight: 700 !important;
  color: #1f2937 !important;
}
.toc {
  border: 1px solid #d9d2c5 !important;
}
.toc-toggle {
  background: #ffffff !important;
  border: 1px solid #d9d2c5 !important;
}
.header-box {
  text-align: center !important;
  margin-bottom: 14px !important;
  padding-bottom: 10px !important;
  border-bottom: 2px solid #1f2937 !important;
}
.header-box .line1 {
  font-size: 28px !important;
  font-weight: 700 !important;
  color: #1f2937 !important;
}
.header-box .line2,
.header-box .line3,
.header-box .line4 {
  color: #374151 !important;
  font-size: 15px !important;
}
.exec-stats .stat-card {
  border-radius: 8px !important;
  box-shadow: none !important;
  border: 1px solid #d9d2c5 !important;
}
.decisions-box,
.actions-box {
  border-width: 1px !important;
}
.log-table th,
.actions-table th,
.attendees th {
  background: #1f2937 !important;
}
.slide-figure {
  box-shadow: none !important;
  border: 1px solid #d9d2c5 !important;
}
.fig-timestamp {
  background: #f2ede3 !important;
  color: #374151 !important;
}
@page {
  size: A4;
  margin: 10mm 12mm;
}
@media print {
  html, body {
    background: #ffffff !important;
  }
  body {
    margin: 0 !important;
    padding: 0 !important;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }
  .page {
    border: none !important;
    box-shadow: none !important;
    border-radius: 0 !important;
    max-width: none !important;
    margin: 0 !important;
    padding: 0 !important;
    background: #ffffff !important;
  }
  .cover {
    border: none !important;
    box-shadow: none !important;
  }
}
</style>
""".strip()


def apply_react_official_theme(html: str) -> str:
    if not html:
        return html
    if 'id="react-official-theme"' in html:
        return html
    marker = "</head>"
    if marker in html:
        return html.replace(marker, f"{REACT_OFFICIAL_THEME_OVERRIDE}\n{marker}", 1)
    return REACT_OFFICIAL_THEME_OVERRIDE + html


def _filter_images_by_time_range(
    images: list[dict[str, Any]],
    time_range_str: str,
    margin_sec: int = 45,
) -> list[dict[str, Any]]:
    """Keep only images whose timestamp falls within the given time range.

    This prevents multiple agendas sharing the same topic_id from all
    receiving identical image sets.
    """
    if not time_range_str:
        return images
    parts = [x.strip() for x in time_range_str.replace("–", "-").split("-")]
    if len(parts) < 2:
        return images
    lo = max(hms_to_sec(parts[0]) - margin_sec, 0)
    hi = hms_to_sec(parts[1]) + margin_sec
    return [
        img for img in images
        if lo <= float(img.get("timestamp_sec", 0) or 0) <= hi
    ]


def _agenda_sort_key(agenda_number: Any) -> tuple:
    raw = str(agenda_number or "").strip()
    if not raw:
        return (999999,)
    parts = []
    for part in raw.split("."):
        token = part.strip()
        if token.isdigit():
            parts.append(int(token))
            continue
        m = re.match(r"(\d+)", token)
        if m:
            parts.append(int(m.group(1)))
        else:
            parts.append(999999)
    return tuple(parts)


def _agenda_parts(agenda_number: Any) -> list[str]:
    raw = str(agenda_number or "").strip()
    if not raw:
        return []
    return [p.strip() for p in raw.split(".") if p.strip()]


def _agenda_depth(agenda_number: Any) -> int:
    return len(_agenda_parts(agenda_number))


def _agenda_prefixes(agenda_number: Any, include_self: bool = False) -> list[str]:
    parts = _agenda_parts(agenda_number)
    if not parts:
        return []
    upto = len(parts) if include_self else max(0, len(parts) - 1)
    return [".".join(parts[:i]) for i in range(1, upto + 1)]


def _is_generic_group_title(text: str) -> bool:
    t = re.sub(r"\s+", "", str(text or ""))
    if not t:
        return True
    return t in {"หัวข้อกลุ่ม", "หัวข้อ", "วาระ"} or t.startswith("วาระที่")


def _build_group_title_map(
    topic_summaries: list[dict[str, Any]],
    explicit_title_map: dict[str, str],
) -> dict[str, str]:
    group_depts: dict[str, set[str]] = {}
    group_titles: dict[str, list[str]] = {}
    for t in topic_summaries:
        if not isinstance(t, dict):
            continue
        ag = str(t.get("agenda_number", "") or "").strip()
        if not ag:
            continue
        dept = str(t.get("department", "") or "").strip()
        title = str(t.get("title", "") or "").strip()
        for pref in _agenda_prefixes(ag, include_self=False):
            if dept:
                group_depts.setdefault(pref, set()).add(dept)
            if title:
                group_titles.setdefault(pref, []).append(title)

    out: dict[str, str] = {}
    all_prefixes = set(group_depts.keys()) | set(group_titles.keys()) | set(explicit_title_map.keys())
    for pref in sorted(all_prefixes, key=_agenda_sort_key):
        explicit = str(explicit_title_map.get(pref, "") or "").strip()
        if explicit and not _is_generic_group_title(explicit):
            out[pref] = explicit
            continue

        depts = sorted(group_depts.get(pref, set()))
        if len(depts) == 1:
            out[pref] = depts[0]
            continue
        if 1 < len(depts) <= 3:
            out[pref] = " / ".join(depts)
            continue
        if len(depts) > 3:
            out[pref] = f"หลายหน่วยงาน ({len(depts)} หน่วย)"
            continue

        titles = group_titles.get(pref, [])
        if titles:
            out[pref] = titles[0]
    return out


def _is_container_agenda_item(item: dict[str, Any], all_agenda_numbers: set[str]) -> bool:
    num = str(item.get("agenda_number", "") or "").strip()
    if not num:
        return False
    prefix = f"{num}."
    has_child = any(n != num and n.startswith(prefix) for n in all_agenda_numbers)
    if not has_child:
        return False

    title = re.sub(r"\s+", "", str(item.get("title", "") or ""))
    dept = re.sub(r"\s+", "", str(item.get("department", "") or ""))

    # Generic parent rows (e.g., department-only headings) should not be
    # rendered as standalone sections when child agendas are present.
    if not title:
        return True
    if dept and title == dept:
        return True
    if title.startswith("ฝ่าย"):
        return True
    if len(title) <= 14 and ("ฝ่าย" in title or "โกดัง" in title):
        return True
    return False


def _time_range_bounds_sec(time_range_str: str) -> tuple[int, int] | None:
    if not time_range_str:
        return None
    parts = [x.strip() for x in time_range_str.replace("–", "-").split("-")]
    if len(parts) < 2:
        return None
    lo = hms_to_sec(parts[0])
    hi = hms_to_sec(parts[1])
    if hi < lo:
        hi = lo
    return lo, hi


def _select_images_for_section(
    remaining_images: list[dict[str, Any]],
    topic_id: str,
    time_range_str: str,
    max_per_section: int = 3,
    prefer_topic_id: bool = True,
) -> list[dict[str, Any]]:
    if not remaining_images:
        return []
    bounds = _time_range_bounds_sec(time_range_str)
    if bounds is not None:
        lo, hi = bounds
        mid = (lo + hi) / 2.0
    else:
        lo, hi = (0, 10**9)
        mid = 0.0

    def in_range(item: dict[str, Any]) -> bool:
        sec = float(item.get("timestamp_sec", 0) or 0)
        return lo - 30 <= sec <= hi + 30

    def score(item: dict[str, Any]) -> tuple:
        sec = float(item.get("timestamp_sec", 0) or 0)
        pr = -int(item.get("insertion_priority", 0) or 0)
        dist = abs(sec - mid)
        return (pr, dist, sec)

    ranged = [img for img in remaining_images if in_range(img)]
    if ranged:
        def ranked(item: dict[str, Any]) -> tuple:
            same_topic = (
                0
                if (
                    prefer_topic_id
                    and topic_id
                    and str(item.get("topic_id", "") or "") == topic_id
                )
                else 1
            )
            base = score(item)
            return (same_topic, *base)

        ranged.sort(key=ranked)
        return ranged[:max_per_section]

    # Fallback: if no image falls inside the time window, choose the nearest
    # remaining image by timestamp so that sections are not visually empty.
    if bounds is None:
        remaining_images.sort(key=score)
        return remaining_images[:max_per_section]

    nearest = sorted(
        remaining_images,
        key=lambda item: abs(float(item.get("timestamp_sec", 0) or 0) - mid),
    )
    if not nearest:
        return []
    nearest_dist = abs(float(nearest[0].get("timestamp_sec", 0) or 0) - mid)
    # Borrow only when the nearest capture is still reasonably close.
    if nearest_dist > 1800:
        return []
    return nearest[:1]


def strip_markdown_fences(html: str) -> str:
    """Normalize LLM output by removing optional markdown code fences."""
    if not html:
        return html
    text = html.strip()
    if not text.startswith("```"):
        return html
    text = re.sub(r"^\s*```[a-zA-Z0-9_-]*\s*\n?", "", text, count=1)
    text = re.sub(r"\n?\s*```\s*$", "", text, count=1)
    return text.strip()


def html_compliance_issues(html: str, expected_topic_sections: int = 0) -> list[str]:
    issues: list[str] = []
    lower = html.lower()
    required = ["<!doctype html", "<style>", "<script>", "id=\"lb-overlay\""]
    for marker in required:
        if marker not in lower:
            issues.append(f"missing_marker:{marker}")

    staged_cues: list[tuple[str, list[str]]] = [
        ("cover", ["รายงานการประชุม"]),
        ("attendees", ["ผู้เข้าประชุม", "ผู้เข้าร่วมประชุม"]),
        ("toc", ["สารบัญ"]),
        ("executive_summary", ["บทสรุปผู้บริหาร", "สาระสำคัญ"]),
        ("topics", ["วาระที่", "หัวข้อการประชุม"]),
        ("decisions", ["มติ", "การตัดสินใจ"]),
        ("actions", ["งานที่ต้องดำเนินการ", "รายการการดำเนินการ"]),
        ("appendix", ["ภาคผนวก"]),
    ]
    pos = -1
    for stage, options in staged_cues:
        indices = [html.find(opt) for opt in options if html.find(opt) >= 0]
        if not indices:
            issues.append(f"missing_stage:{stage}")
            continue
        i = min(indices)
        if i < pos:
            issues.append(f"out_of_order:{stage}")
        pos = max(pos, i)

    if expected_topic_sections > 0:
        topic_section_count = lower.count('class="topic-section"') + lower.count("class='topic-section'")
        min_required = max(1, int(expected_topic_sections * 0.4))
        if topic_section_count < min_required:
            issues.append(
                f"topic_coverage:{topic_section_count}/{expected_topic_sections}(min:{min_required})"
            )

    return issues


def html_has_sections_in_order(html: str, expected_topic_sections: int = 0) -> bool:
    return not html_compliance_issues(html, expected_topic_sections=expected_topic_sections)


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


def _image_identity(item: dict[str, Any]) -> str:
    keys = [
        "image_base64",
        "resolved_image_path",
        "image_path",
        "image_presigned_url",
        "image_url",
        "presigned_url",
        "s3_presigned_url",
        "s3_url",
        "url",
    ]
    for key in keys:
        value = str(item.get(key, "") or "").strip()
        if value:
            return value
    return ""


def render_figure(item: dict[str, Any], fig_num: int, table_num: int) -> str:
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
            f'<span class="fig-num">ตารางที่ {table_num}</span>'
            f'<span class="fig-caption">{caption}</span>'
            f'<span class="fig-timestamp">{ts}</span>'
            "</figcaption>"
            "</figure>"
        )

    if render_as == "before_after" or str(item.get("special_pattern", "")) == "BEFORE_AFTER":
        before_raw = _pick_image_src(item, preferred="before_base64")
        after_raw = _pick_image_src(item, preferred="after_base64")
        if not before_raw:
            before_raw = _pick_image_src(item)
        if not after_raw:
            after_raw = before_raw
        if not before_raw:
            return ""
        before = escape(before_raw)
        after = escape(after_raw)
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
            f"<div><strong>รูปที่ {fig_num} — {content_summary}</strong><p>{caption}</p></div>"
            f'<span class="fig-timestamp">{ts}</span>'
            "</div>"
        )

    img_raw = _pick_image_src(item)
    if not img_raw:
        return ""
    img = escape(img_raw)
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


def render_images_block(
    images: list[dict[str, Any]],
    start_fig_num: int,
    start_table_num: int,
) -> tuple[str, int, int]:
    html_parts: list[str] = []
    fig_n = start_fig_num
    table_n = start_table_num
    for i, item in enumerate(images):
        render_as = str(item.get("render_as", "") or "")
        html_parts.append(render_figure(item, fig_n, table_n))
        if render_as == "html_table":
            table_n += 1
        else:
            fig_n += 1
        if i < len(images) - 1:
            cur = str(item.get("render_as", ""))
            nxt = str(images[i + 1].get("render_as", ""))
            if cur in {"photo_lightbox", "before_after"} and nxt in {"photo_lightbox", "before_after"}:
                html_parts.append('<p class="summary-text">รายละเอียดประกอบเพิ่มเติมตามภาพถัดไป</p>')
    return "\n".join(html_parts), fig_n, table_n


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
    if not isinstance(topic_summaries, list):
        topic_summaries = []
    topic_summaries = sorted(
        topic_summaries,
        key=lambda t: _agenda_sort_key(t.get("agenda_number", "")) if isinstance(t, dict) else (999999,),
    )
    agenda_title_map: dict[str, str] = {}
    for t in topic_summaries:
        if not isinstance(t, dict):
            continue
        ag = str(t.get("agenda_number", "") or "").strip()
        title = str(t.get("title", "") or "").strip()
        if ag and title and ag not in agenda_title_map:
            agenda_title_map[ag] = title
    agenda_numbers = {
        str(t.get("agenda_number", "") or "").strip()
        for t in topic_summaries
        if isinstance(t, dict)
    }
    skip_set = {
        str(t.get("agenda_number", "") or "").strip()
        for t in topic_summaries
        if isinstance(t, dict) and _is_container_agenda_item(t, agenda_numbers)
    }
    if skip_set:
        topic_summaries = [
            t
            for t in topic_summaries
            if isinstance(t, dict) and str(t.get("agenda_number", "") or "").strip() not in skip_set
        ]
    topic_id_counts: dict[str, int] = {}
    for t in topic_summaries:
        if not isinstance(t, dict):
            continue
        tid = str(t.get("topic_id", "") or "").strip()
        if not tid:
            continue
        topic_id_counts[tid] = topic_id_counts.get(tid, 0) + 1
    group_title_map = _build_group_title_map(topic_summaries, agenda_title_map)
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
    seen_toc_groups: set[str] = set()
    for idx, t in enumerate(topic_summaries, start=1):
        ag = str(t.get("agenda_number", idx))
        title = escape(str(t.get("title", "")))
        dept = escape(str(t.get("department", "")))
        trange = escape(str(t.get("time_range", "")))
        for pref in _agenda_prefixes(ag, include_self=False):
            if pref in seen_toc_groups:
                continue
            seen_toc_groups.add(pref)
            lvl = _agenda_depth(pref)
            ptitle = escape(group_title_map.get(pref, "หัวข้อกลุ่ม"))
            toc_rows.append(
                '<div class="toc-item toc-group" '
                f'style="padding-left:{max(0, (lvl - 1) * 16)}px; opacity:0.88; pointer-events:none;">'
                f'<span class="toc-num">{escape(pref)}</span>'
                f'<span class="toc-title">{ptitle}</span>'
                "</div>"
            )
        depth = _agenda_depth(ag)
        toc_rows.append(
            f'<a class="toc-item" href="#topic-{idx}" style="padding-left:{max(0, (depth - 1) * 16)}px;">'
            f'<span class="toc-num">{escape(ag)}</span>'
            f'<span class="toc-title">{title}</span>'
            f'<span class="badge badge-dept">{dept}</span>'
            f'<span class="badge badge-time">{trange}</span>'
            "</a>"
        )

    topic_html: list[str] = []
    fig_counter = 1
    table_counter = 1
    
    all_imgs_flat: list[dict[str, Any]] = []
    for imgs_list in image_by_topic.values():
        all_imgs_flat.extend(imgs_list)
    rendered_image_urls: set[str] = set()
    seen_section_groups: set[str] = set()

    for idx, t in enumerate(topic_summaries, start=1):
        agenda_number = str(t.get("agenda_number", idx) or idx)
        topic_id = str(t.get("topic_id", "") or "")
        dept = str(t.get("department", "") or "")
        trange = str(t.get("time_range", "") or "")
        start_hms = "00:00:00"
        if trange:
            parts = [x.strip() for x in trange.replace("–", "-").split("-")]
            if parts:
                start_hms = parts[0]

        remaining = [
            img
            for img in all_imgs_flat
            if _image_identity(img) not in rendered_image_urls
        ]
        imgs = _select_images_for_section(
            remaining_images=remaining,
            topic_id=topic_id,
            time_range_str=trange,
            max_per_section=3,
            prefer_topic_id=bool(topic_id and topic_id_counts.get(topic_id, 0) == 1),
        )
        for img in imgs:
            img_url = _image_identity(img)
            if img_url:
                rendered_image_urls.add(img_url)
        p5 = [x for x in imgs if int(x.get("insertion_priority", 0) or 0) >= 5]
        p4 = [x for x in imgs if int(x.get("insertion_priority", 0) or 0) == 4]
        p3 = [x for x in imgs if int(x.get("insertion_priority", 0) or 0) == 3]
        p_other = [x for x in imgs if int(x.get("insertion_priority", 0) or 0) < 3]

        paras = split_paragraphs(str(t.get("summary_th", "")))
        if not paras:
            paras = ["ไม่มีข้อมูลสรุป"]

        before_text, fig_counter, table_counter = render_images_block(
            p5,
            fig_counter,
            table_counter,
        )
        after_p1, fig_counter, table_counter = render_images_block(
            p4,
            fig_counter,
            table_counter,
        )
        end_block, fig_counter, table_counter = render_images_block(
            p3,
            fig_counter,
            table_counter,
        )
        tail_block, fig_counter, table_counter = render_images_block(
            p_other,
            fig_counter,
            table_counter,
        )

        summary_chunks: list[str] = []
        # if not imgs:
        #     summary_chunks.append(
        #         '<p class="summary-text"><em>หมายเหตุ: ไม่พบภาพประกอบที่จับคู่ได้ในช่วงเวลาวาระนี้ '
        #         '(ระบบหลีกเลี่ยงการยัดรูปต่างช่วงเพื่อไม่ให้เนื้อหาคลาดเคลื่อน)</em></p>'
        #     )
        if before_text:
            summary_chunks.append(before_text)

        summary_chunks.append(f"<p>{escape(paras[0])}</p>")
        if after_p1:
            summary_chunks.append(after_p1)
        for p in paras[1:]:
            summary_chunks.append(f"<p>{escape(p)}</p>")
        if end_block:
            summary_chunks.append(end_block)
        if tail_block:
            summary_chunks.append(tail_block)

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

        for pref in _agenda_prefixes(agenda_number, include_self=False):
            if pref in seen_section_groups:
                continue
            seen_section_groups.add(pref)
            ptitle = group_title_map.get(pref, "").strip()
            header_text = f"วาระ {pref}"
            if ptitle:
                header_text = f"{header_text} {escape(ptitle)}"
            topic_html.append(
                f'<h3 class="agenda-group-header">{header_text}</h3>'
            )

        topic_html.append(
            f'<section id="topic-{idx}" class="topic-section" data-dept="{escape(dept)}" data-start="{escape(start_hms)}">'
            '<div class="topic-header">'
            f'<h3 class="agenda-title">วาระที่ {escape(agenda_number)} {escape(str(t.get("title", "")))}</h3>'
            "</div>"
            f'<div class="agenda-meta">หน่วยงาน: {escape(dept)} | ช่วงเวลา: {escape(trange)}</div>'
            f'<div class="summary-text">{"".join(summary_chunks)}</div>'
            '<div class="decisions-box"><h4>มติที่ประชุม</h4><ol>'
            f"{decisions_html}</ol></div>"
            '<div class="actions-box"><h4>งานที่ได้รับมอบหมาย</h4>'
            '<table class="actions-table"><thead><tr><th>งาน</th><th>ผู้รับผิดชอบ</th><th>กำหนดเสร็จ</th></tr></thead><tbody>'
            f"{''.join(action_trs)}</tbody></table></div>"
            "</section>"
        )

    unmatched_images = []
    seen = set()
    for item in all_imgs_flat:
        img_url = _image_identity(item)
        if not img_url or img_url in rendered_image_urls or img_url in seen:
            continue
        seen.add(img_url)
        unmatched_images.append(item)
    unmatched_images.sort(key=lambda x: float(x.get("timestamp_sec", 0) or 0))
    unmatched_html = '<h2 class="section-title">ภาคผนวก — ภาพประกอบที่ยังไม่จับคู่หัวข้อ</h2>'
    if unmatched_images:
        unmapped_blocks, fig_counter, table_counter = render_images_block(
            unmatched_images,
            fig_counter,
            table_counter,
        )
        unmatched_html += (
            '<div class="summary-text"><p>'
            f"ตรวจพบภาพจาก OCR เพิ่มเติม {len(unmatched_images)} รายการ "
            "แต่ไม่พบหัวข้อสรุปที่แมปตรงกันในรอบนี้ จึงแสดงรวมในภาคผนวก"
            "</p></div>"
            f'<div class="summary-text">{unmapped_blocks}</div>'
        )
    else:
        unmatched_html += '<div class="summary-text"><p>ไม่มีภาพประกอบเพิ่มเติมในภาคผนวก</p></div>'

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
<main class="page">
  <div class="header-box">
    <div class="line1">{escape(str(meta.get('title', 'รายงานการประชุมประจำเดือน')))}</div><br>
    <div class="line2">{escape(str(meta.get('company', 'บริษัทแสงฟ้าก่อสร้าง จำกัด')))}</div><br>
    <div class="line3">วันที่ {escape(str(meta.get('date', '')))} เวลา {escape(str(meta.get('time_range', '')))}</div><br>
    <div class="line4">ประชุมออนไลน์ด้วยโปรแกรม {escape(str(meta.get('platform', 'ZOOM')))}</div>
  </div>

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
    candidates: list[str] = []
    if preferred:
        candidates.append(str(item.get(preferred, "") or ""))
        if preferred.endswith("_base64"):
            candidates.append(str(item.get(preferred.replace("_base64", "_image_path"), "") or ""))
    candidates.extend(
        [
            str(item.get("image_base64", "") or ""),
            str(item.get("before_base64", "") or ""),
            str(item.get("after_base64", "") or ""),
            str(item.get("before_image_path", "") or ""),
            str(item.get("after_image_path", "") or ""),
            str(item.get("resolved_image_path", "") or ""),
            str(item.get("image_presigned_url", "") or ""),
            str(item.get("image_url", "") or ""),
            str(item.get("presigned_url", "") or ""),
            str(item.get("s3_presigned_url", "") or ""),
            str(item.get("s3_url", "") or ""),
            str(item.get("url", "") or ""),
            str(item.get("image_path", "") or ""),
        ]
    )
    for src in candidates:
        if src:
            return src
    return ""


def _render_official_media(item: dict[str, Any], fig_num: int, table_num: int) -> str:
    render_as = str(item.get("render_as", "") or "")
    summary = escape(str(item.get("content_summary", "") or "ภาพประกอบ"))
    caption = escape(str(item.get("caption_th", "") or ""))
    ts = escape(str(item.get("timestamp_hms", "") or ""))

    if render_as == "html_table":
        table_html = str(item.get("table_html", "") or "")
        if table_html:
            return (
                '<div class="agenda-image-wrap">'
                f'<div class="agenda-image-caption"><strong>ตารางที่ {table_num}</strong> {summary}</div>'
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
    topic_summaries = sorted(
        topic_summaries,
        key=lambda t: _agenda_sort_key(t.get("agenda_number", "")) if isinstance(t, dict) else (999999,),
    )
    agenda_numbers = {
        str(t.get("agenda_number", "") or "").strip()
        for t in topic_summaries
        if isinstance(t, dict)
    }
    skip_set = {
        str(t.get("agenda_number", "") or "").strip()
        for t in topic_summaries
        if isinstance(t, dict) and _is_container_agenda_item(t, agenda_numbers)
    }
    if skip_set:
        topic_summaries = [
            t
            for t in topic_summaries
            if isinstance(t, dict) and str(t.get("agenda_number", "") or "").strip() not in skip_set
        ]

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
    table_num = 1
    
    all_imgs_flat: list[dict[str, Any]] = []
    for imgs_list in image_by_topic.values():
        all_imgs_flat.extend(imgs_list)
    rendered_image_urls: set[str] = set()

    for idx, t in enumerate(topic_summaries, start=1):
        if not isinstance(t, dict):
            continue
        agenda_number = str(t.get("agenda_number", idx) or idx)
        topic_id = str(t.get("topic_id", "") or "")
        title = str(t.get("title", "") or "")
        department = str(t.get("department", "") or "")
        time_range = str(t.get("time_range", "") or "")
        presenter = str(t.get("presenter", "") or "")

        remaining = [
            img
            for img in all_imgs_flat
            if _image_identity(img) not in rendered_image_urls
        ]
        imgs = _select_images_for_section(
            remaining_images=remaining,
            topic_id=topic_id,
            time_range_str=time_range,
            max_per_section=3,
        )
        media_blocks: list[str] = []
        for item in imgs:
            img_url = _image_identity(item)
            if not img_url or img_url in rendered_image_urls:
                continue
            block = _render_official_media(item, figure_num, table_num)
            if block:
                rendered_image_urls.add(img_url)
                media_blocks.append(block)
                if str(item.get("render_as", "") or "") == "html_table":
                    table_num += 1
                else:
                    figure_num += 1

        summary_blocks = "".join(f"<p>{escape(p)}</p>" for p in split_paragraphs(str(t.get("summary_th", "") or "")))
        if not summary_blocks:
            summary_blocks = "<p>ไม่มีข้อมูลสรุป</p>"
        if not imgs:
            summary_blocks = (
                "<p><em>หมายเหตุ: ไม่พบภาพประกอบที่จับคู่ได้ในช่วงเวลาวาระนี้ "
                "(ระบบหลีกเลี่ยงการยัดรูปต่างช่วงเพื่อไม่ให้เนื้อหาคลาดเคลื่อน)</em></p>"
                + summary_blocks
            )

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

    unmapped_images = []
    seen = set()
    for item in all_imgs_flat:
        img_url = _image_identity(item)
        if not img_url or img_url in rendered_image_urls or img_url in seen:
            continue
        seen.add(img_url)
        unmapped_images.append(item)
    unmapped_images.sort(key=lambda x: float(x.get("timestamp_sec", 0) or 0))

    unmapped_blocks: list[str] = []
    for item in unmapped_images:
        block = _render_official_media(item, figure_num, table_num)
        if block:
            unmapped_blocks.append(block)
            if str(item.get("render_as", "") or "") == "html_table":
                table_num += 1
            else:
                figure_num += 1
    unmapped_html = "<h3>ภาคผนวก - ภาพประกอบที่ยังไม่จับคู่หัวข้อ</h3>"
    if unmapped_blocks:
        unmapped_html += (
            "<p>ภาพที่ตรวจพบจาก OCR แต่ไม่ตรงกับวาระที่ถูกสรุปในรอบนี้</p>"
            f"{''.join(unmapped_blocks)}"
        )
    else:
        unmapped_html += "<p>ไม่มีภาพประกอบเพิ่มเติมในภาคผนวก</p>"

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
    @page {{
      size: A4;
      margin: 10mm 12mm;
    }}
    @media print {{
      body {{
        max-width: none;
        margin: 0;
        padding: 0;
        -webkit-print-color-adjust: exact;
        print-color-adjust: exact;
      }}
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
