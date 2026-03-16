import argparse
import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

DEFAULT_API_BASE_URL = "https://meet-extrack.sp2ai.club"
DEFAULT_TASK_URL = (
    "https://meet-extrack.sp2ai.club/tasks-video/53403fad-0465-4703-b522-ba2de87d0d87"
)
DEFAULT_TASK_ID = "53403fad-0465-4703-b522-ba2de87d0d87"
DEFAULT_BEARER_TOKEN = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiJhZTZmYjMxZi1hN2RlLTRkMDktOTVhNS0xYmY4ZjhlYWNkNzYiLCJpYXQiOjE3NzMzNjU2ODUs"
    "Im5iZiI6MTc3MzM2NTY4NSwiZXhwIjoxNzczMzcyODg1LCJpc3MiOiJjb25uZWN0dG9yLW1lZXQiLCJhdWQi"
    "OiJjb25uZWN0dG9yLW1lZXQtdXNlcnMiLCJlbWFpbCI6ImFkbWluQHNwLmNvbSJ9."
    "CJCLZPy0QQ5v8o7NYx4v3O-oV9WoOOxs8TEw7mgStoA"
)
SUMMARY_ATTENDEES_DEFAULT = "Auto-generated from source task"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _normalize_api_base_url(url: str) -> str:
    return str(url or "").rstrip("/")


def _build_auth_headers(token: str) -> dict[str, str]:
    headers = {"accept": "application/json"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    return headers


def _normalize_summary_mode(value: str | None) -> str:
    mode = str(value or "").strip().lower()
    if mode in {"agenda", "auto"}:
        return mode
    return "agenda" if mode == "standard" else "auto"


def _build_summary_form_data(
    *,
    agenda_text: str,
    attendees_text: str,
    summary_mode: str,
    params: dict[str, Any],
) -> dict[str, str]:
    report_layout = str(params.get("report_layout") or "react_official").strip() or "react_official"
    if report_layout not in {"current", "react_official"}:
        report_layout = "react_official"
    return {
        "attendees_text": attendees_text,
        "agenda_text": agenda_text,
        "mode": summary_mode,
        "report_layout": report_layout,
    }


def _extract_ocr_payload(result: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("video_change_ocr_data", "capture_ocr_results", "video_ocr"):
        value = result.get(key)
        if isinstance(value, dict):
            captures = value.get("captures")
            if key == "video_ocr" and not isinstance(captures, list):
                continue
            return value
    return None


def _parse_task_reference(task_ref: str) -> tuple[str, str]:
    raw = str(task_ref or "").strip()
    if not raw:
        return DEFAULT_API_BASE_URL, DEFAULT_TASK_ID
    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[-2] == "tasks-video":
            api_base_url = f"{parsed.scheme}://{parsed.netloc}"
            return api_base_url, parts[-1]
        raise RuntimeError(f"Unsupported task URL: {raw}")
    return DEFAULT_API_BASE_URL, raw


async def _fetch_task(
    api_base_url: str,
    task_id: str,
    token: str,
) -> dict[str, Any]:
    url = f"{api_base_url}/tasks-video/{task_id}"
    req = Request(url, headers=_build_auth_headers(token))
    with urlopen(req, timeout=120) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Unexpected task payload")
    return payload


async def _fetch_result_json_from_storage(
    api_base_url: str,
    task_id: str,
    token: str,
) -> dict[str, Any] | None:
    link_url = f"{api_base_url}/tasks-video/{task_id}/getlinkresult?kind=result"
    try:
        link_req = Request(link_url, headers=_build_auth_headers(token))
        with urlopen(link_req, timeout=120) as resp:
            link_payload = json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None
    if not isinstance(link_payload, dict):
        return None
    result_url = str(link_payload.get("url") or "").strip()
    if not result_url:
        return None
    try:
        result_req = Request(result_url, headers={"accept": "application/json"})
        with urlopen(result_req, timeout=120) as resp:
            result_payload = json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        return None
    if isinstance(result_payload, dict):
        return result_payload
    return None


def _build_transcript_from_result(result: dict[str, Any]) -> dict[str, Any]:
    segments = result.get("segments")
    if not isinstance(segments, list):
        segments = []
    return {
        "segments": segments,
        "full_text": str(result.get("full_text", "") or ""),
    }


def _build_pipeline_config(*, attendees_text: str, agenda_text: str) -> dict[str, Any]:
    config = {"MEETING_INFO": attendees_text}
    if agenda_text.strip():
        config["AGENDA_TEXT"] = agenda_text
    return config


def _build_orchestrator_script(
    *,
    project_root: Path,
    output_dir: Path,
    transcript_path: Path,
    config_path: Path,
    ocr_path: Path | None,
    mode: str,
    report_layout: str,
) -> str:
    output_html_path = output_dir / "meeting_report.html"
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"cd {_shell_quote(str(project_root.resolve()))}",
        (
            "TRANSCRIPT_PATH="
            f"{_shell_quote(str(transcript_path.resolve()))} "
            "CONFIG_PATH="
            f"{_shell_quote(str(config_path.resolve()))} "
            + (
                f"OCR_PATH={_shell_quote(str(ocr_path.resolve()))} " if ocr_path is not None else ""
            )
            + f"INCLUDE_OCR={'true' if ocr_path is not None else 'false'} "
            "IMAGE_INSERT_ENABLED=true "
            "PIPELINE_MAX_CONCURRENCY=1 "
            "IMAGE_MIN_FILE_SIZE_KB=0 "
            "OUTPUT_HTML_PATH="
            f"{_shell_quote(str(output_html_path.resolve()))} "
            "python orchestrator.py "
            f"--mode {_shell_quote(mode)} "
            f"--report-layout {_shell_quote(report_layout)} "
            f"--output {_shell_quote(str(output_html_path.resolve()))} "
            "--save-artifacts true \"$@\""
        ),
    ]
    return "\n".join(lines) + "\n"


def _resolve_target_url(
    summary_mode: str,
    target_base_url: str,
    target_path: str,
) -> tuple[str, str]:
    base_url = str(target_base_url or "").strip()
    if not base_url:
        raise RuntimeError(
            "Missing --target-base-url. Set it explicitly to avoid using wrong environment values."
        )
    path = str(target_path or "").strip() or "/generate"
    if not path.startswith("/"):
        path = "/" + path
    return base_url.rstrip("/"), path


async def _build_payload_files(
    *,
    api_base_url: str,
    token: str,
    task_id: str,
    summary_mode: str,
    target_base_url: str,
    target_path: str,
    output_dir: Path,
) -> dict[str, Any]:
    task = await _fetch_task(api_base_url, task_id, token)
    result_payload_from_storage = await _fetch_result_json_from_storage(
        api_base_url, task_id, token
    )

    params = dict(task.get("params") or {})
    result = dict(task.get("result") or {})
    if result_payload_from_storage:
        result = dict(result_payload_from_storage)

    selected_mode = _normalize_summary_mode(summary_mode or params.get("summary_mode"))
    agenda_text = str(params.get("agenda_text") or "").strip()
    attendees_text = str(params.get("attendees_text") or SUMMARY_ATTENDEES_DEFAULT).strip()
    transcript = _build_transcript_from_result(result)
    ocr_payload = _extract_ocr_payload(result)

    form_data = _build_summary_form_data(
        agenda_text=agenda_text,
        attendees_text=attendees_text,
        summary_mode=selected_mode,
        params=params,
    )
    base_url, request_path = _resolve_target_url(
        selected_mode,
        target_base_url=target_base_url,
        target_path=target_path,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    transcript_path = output_dir / "transcript.json"
    form_data_path = output_dir / "form_data.json"
    request_meta_path = output_dir / "request_meta.json"
    ocr_path = output_dir / "ocr_payload.json"
    task_path = output_dir / "task_payload.json"
    api_payload_path = output_dir / "api_payload.json"
    config_path = output_dir / "config.json"
    run_orchestrator_path = output_dir / "run_orchestrator.sh"

    _write_json(transcript_path, transcript)
    _write_json(form_data_path, form_data)
    _write_json(task_path, task)

    request_meta = {
        "task_id": task_id,
        "summary_mode": selected_mode,
        "base_url": base_url,
        "request_path": request_path,
        "url": f"{base_url}{request_path}",
        "has_ocr_payload": isinstance(ocr_payload, dict),
        "transcript_segments": len(transcript.get("segments") or []),
        "source_api_base_url": api_base_url,
        "form_data": form_data,
    }
    _write_json(request_meta_path, request_meta)

    if isinstance(ocr_payload, dict):
        _write_json(ocr_path, ocr_payload)
    elif ocr_path.exists():
        ocr_path.unlink()

    pipeline_config = _build_pipeline_config(
        attendees_text=attendees_text,
        agenda_text=agenda_text,
    )
    _write_json(config_path, pipeline_config)

    api_payload = {
        "MEETING_INFO": attendees_text,
        "AGENDA_TEXT": agenda_text,
        "segments": transcript.get("segments", []),
        "full_text": transcript.get("full_text", ""),
        "capture_ocr_results": ocr_payload,
        "report_layout": form_data.get("report_layout", "react_official"),
        "mode": selected_mode,
        "image_insert_enabled": True,
        "save_artifacts": True,
    }
    _write_json(api_payload_path, api_payload)

    run_orchestrator_path.write_text(
        _build_orchestrator_script(
            project_root=Path.cwd(),
            output_dir=output_dir,
            transcript_path=transcript_path,
            config_path=config_path,
            ocr_path=ocr_path if isinstance(ocr_payload, dict) else None,
            mode=selected_mode,
            report_layout=form_data.get("report_layout", "react_official"),
        ),
        encoding="utf-8",
    )
    run_orchestrator_path.chmod(0o755)

    return {
        "summary_mode": selected_mode,
        "base_url": base_url,
        "request_path": request_path,
        "transcript_path": transcript_path,
        "form_data_path": form_data_path,
        "request_meta_path": request_meta_path,
        "ocr_path": ocr_path if isinstance(ocr_payload, dict) else None,
        "task_path": task_path,
        "api_payload_path": api_payload_path,
        "config_path": config_path,
        "run_orchestrator_path": run_orchestrator_path,
        "form_data": form_data,
    }


def _build_curl_command(payload: dict[str, Any]) -> str:
    url = f"{payload['base_url']}{payload['request_path']}"
    form_data = payload["form_data"]
    transcript_path = str(payload["transcript_path"])
    lines = [f"curl -X POST {_shell_quote(url)} \\"]

    for key in sorted(form_data.keys()):
        lines.append(f"  -F {_shell_quote(f'{key}={form_data[key]}')} \\")

    lines.append(f"  -F {_shell_quote(f'file=@{transcript_path};type=application/json')} \\")

    ocr_path = payload.get("ocr_path")
    if ocr_path is not None:
        lines.append(f"  -F {_shell_quote(f'ocr_file=@{ocr_path};type=application/json')} \\")

    lines[-1] = lines[-1].rstrip(" \\")
    return "\n".join(lines)


async def _submit_payload(payload: dict[str, Any], timeout_sec: float) -> dict[str, Any]:
    url = f"{payload['base_url']}{payload['request_path']}"
    form_data = payload["form_data"]
    transcript_path = Path(payload["transcript_path"])
    ocr_path = payload.get("ocr_path")
    boundary = "----MeetSumPayloadBoundary"

    def add_field(parts: list[bytes], name: str, value: str) -> None:
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(value.encode("utf-8"))
        parts.append(b"\r\n")

    def add_file(parts: list[bytes], name: str, filename: str, content_type: str, data: bytes) -> None:
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
        parts.append(data)
        parts.append(b"\r\n")

    body_parts: list[bytes] = []
    for key, value in form_data.items():
        add_field(body_parts, key, str(value))
    add_file(body_parts, "file", "transcript.json", "application/json", transcript_path.read_bytes())
    if ocr_path is not None:
        ocr_file_path = Path(ocr_path)
        add_file(body_parts, "ocr_file", "ocr_payload.json", "application/json", ocr_file_path.read_bytes())
    body_parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(body_parts)

    req = Request(
        url,
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=timeout_sec) as response:
            body_text = response.read().decode("utf-8", errors="replace")
            status_code = getattr(response, "status", 200)
            headers = dict(response.headers)
    except HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="replace")
        status_code = exc.code
        headers = dict(exc.headers)
    return {
        "url": url,
        "status_code": status_code,
        "headers": headers,
        "body_text": body_text,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build summary payload from existing API responses and optionally submit it."
    )
    parser.add_argument(
        "task_ref",
        nargs="?",
        default=DEFAULT_TASK_URL,
        help="Video task ID or full tasks-video URL",
    )
    parser.add_argument(
        "--api-base-url",
        default="",
        help="Connecttor Meet API base URL. Defaults from task URL or built-in default.",
    )
    parser.add_argument("--token", default=DEFAULT_BEARER_TOKEN, help="Bearer token for API")
    parser.add_argument(
        "--summary-mode",
        default="",
        help="Override summary mode (standard, react, new_agent). Defaults to task params.",
    )
    parser.add_argument(
        "--target-base-url",
        required=True,
        help="Summary service base URL to submit payload to",
    )
    parser.add_argument(
        "--target-path",
        default="/generate",
        help="Summary service request path (default: /generate)",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Output directory. Defaults to ./payload_exports/<task_id>",
    )
    parser.add_argument("--submit", action="store_true", help="Submit generated payload")
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="HTTP timeout in seconds when used with --submit.",
    )
    args = parser.parse_args()

    parsed_api_base_url, task_id = _parse_task_reference(args.task_ref)
    api_base_url = _normalize_api_base_url(args.api_base_url or parsed_api_base_url)
    output_dir = Path(args.output_dir or Path("payload_exports") / task_id)

    payload = await _build_payload_files(
        api_base_url=api_base_url,
        token=args.token,
        task_id=task_id,
        summary_mode=args.summary_mode,
        target_base_url=args.target_base_url,
        target_path=args.target_path,
        output_dir=output_dir,
    )

    print(f"Output dir: {output_dir}")
    print(f"Summary mode: {payload['summary_mode']}")
    print(f"Target URL: {payload['base_url']}{payload['request_path']}")
    print(f"Task payload: {payload['task_path']}")
    print(f"Form data: {payload['form_data_path']}")
    print(f"Transcript: {payload['transcript_path']}")
    print(f"API payload: {payload['api_payload_path']}")
    print(f"Config: {payload['config_path']}")
    print(f"Run orchestrator: {payload['run_orchestrator_path']}")
    if payload.get("ocr_path") is not None:
        print(f"OCR payload: {payload['ocr_path']}")
    print()
    print("Replay curl:")
    print(_build_curl_command(payload))

    if args.submit:
        print()
        print("Submitting request...")
        response_payload = await _submit_payload(payload, timeout_sec=args.timeout)
        response_path = output_dir / "response.json"
        _write_json(response_path, response_payload)
        print(f"Response status: {response_payload['status_code']}")
        print(f"Response saved: {response_path}")
        print("Response body:")
        print(response_payload["body_text"])


if __name__ == "__main__":
    asyncio.run(main())
