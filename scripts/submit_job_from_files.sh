#!/usr/bin/env bash
set -euo pipefail

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required (brew install jq)" >&2
  exit 1
fi

API_URL="${API_URL:-http://127.0.0.1:8000}"
CONFIG_PATH="${1:-./data/config_2025-01-04_with_agenda.json}"
TRANSCRIPT_PATH="${2:-./data/transcript_2025-01-04.json}"
OCR_PATH="${3:-./data/video_change_ocr/run_20260213_163003/capture_ocr_results.json}"
MODE="${MODE:-agenda}"
REPORT_LAYOUT="${REPORT_LAYOUT:-react_official}"

for f in "$CONFIG_PATH" "$TRANSCRIPT_PATH" "$OCR_PATH"; do
  if [[ ! -f "$f" ]]; then
    echo "missing file: $f" >&2
    exit 1
  fi
done

tmp_payload="$(mktemp)"
trap 'rm -f "$tmp_payload"' EXIT

jq -n \
  --argjson cfg "$(cat "$CONFIG_PATH")" \
  --argjson transcript "$(cat "$TRANSCRIPT_PATH")" \
  --argjson ocr "$(cat "$OCR_PATH")" \
  --arg mode "$MODE" \
  --arg report_layout "$REPORT_LAYOUT" \
  '{
    MEETING_INFO: ($cfg.MEETING_INFO // ""),
    AGENDA_TEXT: ($cfg.AGENDA_TEXT // null),
    TOPIC_TIME_OVERRIDES: ($cfg.TOPIC_TIME_OVERRIDES // []),
    segments: ($transcript.segments // []),
    full_text: ($transcript.full_text // ""),
    capture_ocr_results: $ocr,
    mode: $mode,
    report_layout: $report_layout,
    image_insert_enabled: true,
    save_artifacts: true
  }' > "$tmp_payload"

echo "POST $API_URL/jobs"
curl -sS -X POST "$API_URL/jobs" \
  -H "Content-Type: application/json" \
  --data-binary "@$tmp_payload"
echo
