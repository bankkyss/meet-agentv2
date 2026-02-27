"""Shared utilities and core data helpers for the meeting pipeline."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class PipelineError(Exception):
    pass


@dataclass
class PipelineConfig:
    typhoon_api_key: str
    typhoon_base_url: str
    typhoon_model: str
    typhoon_max_tokens: int
    chat_fallback_provider: str
    embedding_provider: str
    ollama_base_url: str
    ollama_embed_model: str
    ollama_chat_model: str
    ollama_num_predict: int
    vllm_base_url: str
    vllm_api_key: str
    vllm_chat_model: str
    vllm_embed_model: str
    allow_ollama_chat_fallback: bool
    summarize_mode: str
    include_ocr: bool
    image_insert_enabled: bool
    report_layout_mode: str
    image_base_dir: str
    image_embed_mode: str
    image_max_per_topic: int
    image_min_file_size_kb: int
    output_html_path: str
    transcript_path: str
    config_path: str
    ocr_path: str
    save_intermediate: bool
    llm_max_retries: int
    llm_timeout_sec: int
    agent1_chunk_size: int
    agent1_chunk_overlap: int
    agent1_subchunk_on_failure: bool
    agent1_subchunk_size: int
    agent1_ocr_max_captures: int
    agent1_ocr_snippet_chars: int
    agent2_chunk_size: int
    agent25_chunk_size: int
    resume_artifact_dir: str
    pipeline_max_concurrency: int


def env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def sec_to_hms(sec: float | int) -> str:
    total = max(int(float(sec)), 0)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def hms_to_sec(hms: str) -> int:
    parts = [int(p) for p in str(hms).split(":") if p.strip().isdigit()]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    return 0


def chunked(items: list[Any], size: int, overlap: int = 0) -> list[list[Any]]:
    if not items:
        return []
    if size <= 0:
        return [items]
    step = max(size - overlap, 1)
    out: list[list[Any]] = []
    for i in range(0, len(items), step):
        out.append(items[i : i + size])
        if i + size >= len(items):
            break
    return out


def fill_template(template: str, **kwargs: str) -> str:
    out = template
    for k, v in kwargs.items():
        out = out.replace(f"<<{k}>>", v)
    return out


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    n = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(n))
    na = math.sqrt(sum(a[i] * a[i] for i in range(n)))
    nb = math.sqrt(sum(b[i] * b[i] for i in range(n)))
    return dot / (na * nb + 1e-9)


def normalize_meeting_meta(meta: dict[str, Any], config_data: dict[str, Any]) -> dict[str, Any]:
    out = dict(meta or {})
    out.setdefault("title", "รายงานการประชุมประจำเดือน")
    out.setdefault("date", "")
    out.setdefault("time_range", "")
    out.setdefault("platform", "ZOOM")
    out.setdefault("company", "บริษัทแสงฟ้าก่อสร้าง จำกัด")
    out.setdefault("chairperson", "")
    attendees = out.get("attendees")
    if not isinstance(attendees, list):
        out["attendees"] = []

    if not out["attendees"] and isinstance(config_data.get("MEETING_INFO"), str):
        parsed = []
        for line in config_data["MEETING_INFO"].splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^\d+\.\s*(.+)$", line)
            if not m:
                continue
            raw = m.group(1)
            parts = re.split(r"\t+|\s{2,}", raw)
            name = parts[0].strip() if parts else raw.strip()
            dept = parts[-1].strip() if len(parts) > 1 else ""
            parsed.append({"name": name, "department": dept, "type": "main"})
        out["attendees"] = parsed

    return out


def reduce_agent1_maps(
    cleaned_chunks: list[dict[str, Any]],
    config_data: dict[str, Any],
) -> dict[str, Any]:
    if not cleaned_chunks:
        raise PipelineError("Agent 1 returned no chunks")

    meeting_meta = {}
    all_timeline: list[dict[str, Any]] = []
    all_slides: list[dict[str, Any]] = []

    for chunk in cleaned_chunks:
        if not meeting_meta:
            meeting_meta = chunk.get("meeting_meta", {})
        all_timeline.extend(chunk.get("timeline", []))
        all_slides.extend(chunk.get("slides", []))

    meeting_meta = normalize_meeting_meta(meeting_meta, config_data)

    slide_keyed: dict[tuple[str, str], dict[str, Any]] = {}
    for s in all_slides:
        ts = str(s.get("timestamp_hms", "") or "")
        path = str(s.get("image_path", "") or "")
        key = (ts, path)
        if key not in slide_keyed:
            slide_keyed[key] = s
    slides = list(slide_keyed.values())

    slide_sec: list[tuple[int, str]] = []
    for s in slides:
        sec = hms_to_sec(str(s.get("timestamp_hms", "")))
        slide_sec.append((sec, str(s.get("ocr_text", "") or "")))

    normalized: list[dict[str, Any]] = []
    for t in all_timeline:
        sec = float(t.get("timestamp_sec", 0) or 0)
        item = {
            "timestamp_sec": sec,
            "timestamp_hms": sec_to_hms(sec),
            "speaker": str(t.get("speaker", "") or "UNKNOWN"),
            "text": str(t.get("text", "") or "").strip(),
            "slide_context": t.get("slide_context"),
        }
        if item["text"]:
            normalized.append(item)

    normalized.sort(key=lambda x: x["timestamp_sec"])

    merged: list[dict[str, Any]] = []
    for item in normalized:
        if not merged:
            merged.append(item)
            continue
        prev = merged[-1]
        if (
            item["speaker"] == prev["speaker"]
            and item["timestamp_sec"] - prev["timestamp_sec"] < 3.0
        ):
            prev["text"] = (prev["text"] + " " + item["text"]).strip()
            continue
        merged.append(item)

    for item in merged:
        if item.get("slide_context"):
            continue
        ts = int(item["timestamp_sec"])
        nearest = None
        nearest_d = 10**9
        for s_sec, s_text in slide_sec:
            d = abs(s_sec - ts)
            if d <= 60 and d < nearest_d:
                nearest_d = d
                nearest = s_text
        item["slide_context"] = nearest

    return {
        "meeting_meta": meeting_meta,
        "timeline": merged,
        "slides": slides,
    }


def build_topic_text(topic: dict[str, Any]) -> str:
    name = str(topic.get("name", "") or topic.get("title", ""))
    points = topic.get("summary_points", [])
    if not isinstance(points, list):
        points = []
    return (name + " " + " ".join(str(p) for p in points)).strip()


def timeline_snippet_by_range(
    timeline: list[dict[str, Any]],
    start_sec: int,
    end_sec: int,
    margin_sec: int = 60,
) -> list[dict[str, Any]]:
    lo = max(start_sec - margin_sec, 0)
    hi = end_sec + margin_sec
    out = [t for t in timeline if lo <= float(t.get("timestamp_sec", 0) or 0) <= hi]
    return out


def sanitize_kg_for_output(kg: dict[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(kg, ensure_ascii=False))
    topics = out.get("topics", [])
    if isinstance(topics, list):
        for t in topics:
            if isinstance(t, dict):
                t.pop("_vec", None)
    return out
