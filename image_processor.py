"""Helpers for image path resolution and manifest grouping."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any


MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _as_path(path_like: str | Path) -> Path:
    return path_like if isinstance(path_like, Path) else Path(path_like)


def resolve_image_path(
    raw_image_path: str,
    image_base_dir: str | Path,
    ocr_path: str | Path,
) -> Path | None:
    """
    Resolve OCR-provided image path with fallback strategy:
    1) direct path
    2) image_base_dir / raw
    3) map output/video_change_ocr/... -> data/video_change_ocr/...
    4) basename lookup under OCR run directory
    """
    if not raw_image_path:
        return None

    candidates: list[Path] = []
    raw = _as_path(raw_image_path)
    base = _as_path(image_base_dir)
    ocr_file = _as_path(ocr_path)

    candidates.append(raw)
    candidates.append(base / raw)

    text = raw_image_path.replace("\\", "/")
    if "output/video_change_ocr/" in text:
        mapped = text.replace("output/video_change_ocr/", "data/video_change_ocr/")
        candidates.append(_as_path(mapped))

    # also try stripping leading "output/"
    if text.startswith("output/"):
        candidates.append(_as_path(text[len("output/") :]))

    # basename lookup in the OCR run's captures directory
    run_dir = ocr_file.parent
    basename = raw.name
    candidates.append(run_dir / "captures" / basename)

    # near-run wildcard scan as the final fallback
    if basename:
        try:
            for p in run_dir.rglob(basename):
                candidates.append(p)
                break
        except OSError:
            pass

    for cand in candidates:
        try:
            c = cand.expanduser().resolve()
        except OSError:
            c = cand
        if c.exists() and c.is_file():
            return c

    return None


def image_to_base64_data_uri(path: str | Path) -> str | None:
    p = _as_path(path)
    if not p.exists() or not p.is_file():
        return None
    mime = MIME_BY_EXT.get(p.suffix.lower(), "image/jpeg")
    data = base64.b64encode(p.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def group_manifest_by_topic(
    manifest: list[dict[str, Any]],
    max_per_topic: int,
    min_file_size_kb: int,
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    min_bytes = min_file_size_kb * 1024

    for item in manifest:
        if int(item.get("insertion_priority", 0) or 0) < 3:
            continue
        if int(item.get("ocr_file_size_bytes", 0) or 0) < min_bytes:
            continue

        topic_id = str(item.get("topic_id", "") or "")
        if not topic_id:
            topic_id = "UNMAPPED"

        grouped.setdefault(topic_id, []).append(item)

    for topic_id, items in grouped.items():
        items.sort(
            key=lambda x: (
                -int(x.get("insertion_priority", 0) or 0),
                float(x.get("timestamp_sec", 0) or 0),
            )
        )
        grouped[topic_id] = items[:max_per_topic]

    return grouped


def merge_partial_image_outputs(partials: list[dict[str, Any]]) -> dict[str, Any]:
    by_capture: dict[int, dict[str, Any]] = {}
    total = 0
    filtered = 0
    by_type: dict[str, int] = {}
    before_after_pairs: list[list[int]] = []
    data_series: list[list[int]] = []

    for part in partials:
        for item in part.get("image_manifest", []):
            idx = int(item.get("capture_index", 0) or 0)
            if idx <= 0:
                continue
            existing = by_capture.get(idx)
            if existing is None or int(item.get("insertion_priority", 0) or 0) > int(
                existing.get("insertion_priority", 0) or 0
            ):
                by_capture[idx] = item

        stats = part.get("statistics", {})
        total += int(stats.get("total", 0) or 0)
        filtered += int(stats.get("filtered", 0) or 0)

        bt = stats.get("by_type", {})
        if isinstance(bt, dict):
            for k, v in bt.items():
                by_type[k] = by_type.get(k, 0) + int(v or 0)

        for pair in stats.get("before_after_pairs", []) or []:
            if pair and pair not in before_after_pairs:
                before_after_pairs.append(pair)

        for ds in stats.get("data_series", []) or []:
            if ds and ds not in data_series:
                data_series.append(ds)

    merged_manifest = sorted(
        by_capture.values(),
        key=lambda x: int(x.get("capture_index", 0) or 0),
    )

    return {
        "image_manifest": merged_manifest,
        "statistics": {
            "total": total,
            "filtered": filtered,
            "by_type": by_type,
            "before_after_pairs": before_after_pairs,
            "data_series": data_series,
        },
    }
