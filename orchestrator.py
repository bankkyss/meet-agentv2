from __future__ import annotations

import argparse
import os

from dotenv import load_dotenv

from pipeline_utils import PipelineConfig, env_bool, env_int
from workflow_graph import MeetingWorkflow


def build_config(args: argparse.Namespace) -> PipelineConfig:
    return PipelineConfig(
        typhoon_api_key=os.getenv("TYPHOON_API_KEY", "").strip(),
        typhoon_base_url=os.getenv("TYPHOON_BASE_URL", "https://api.opentyphoon.ai/v1").strip(),
        typhoon_model=os.getenv("TYPHOON_MODEL", "typhoon-v2.5-30b-a3b-instruct").strip(),
        typhoon_max_tokens=env_int("TYPHOON_MAX_TOKENS", 8192),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip(),
        ollama_embed_model=os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text").strip(),
        ollama_chat_model=os.getenv(
            "OLLAMA_CHAT_MODEL",
            os.getenv("OLLAMA_MODEL", "scb10x/typhoon2.5-qwen3-30b-a3b:latest"),
        ).strip(),
        allow_ollama_chat_fallback=env_bool("ALLOW_OLLAMA_CHAT_FALLBACK", False),
        summarize_mode=(args.mode or os.getenv("SUMMARIZE_MODE", "agenda")).strip().lower(),
        include_ocr=env_bool("INCLUDE_OCR", True),
        image_insert_enabled=env_bool("IMAGE_INSERT_ENABLED", True),
        image_base_dir=os.getenv("IMAGE_BASE_DIR", "./data/video_change_ocr/run_20260213_163003").strip(),
        image_embed_mode=os.getenv("IMAGE_EMBED_MODE", "base64").strip().lower(),
        image_max_per_topic=env_int("IMAGE_MAX_PER_TOPIC", 4),
        image_min_file_size_kb=env_int("IMAGE_MIN_FILE_SIZE_KB", 30),
        output_html_path=(args.output or os.getenv("OUTPUT_HTML_PATH", "./output/meeting_report.html")).strip(),
        transcript_path=os.getenv("TRANSCRIPT_PATH", "./data/transcript_2025-01-04.json").strip(),
        config_path=os.getenv("CONFIG_PATH", "./data/config_2025-01-04.json").strip(),
        ocr_path=os.getenv(
            "OCR_PATH", "./data/video_change_ocr/run_20260213_163003/capture_ocr_results.json"
        ).strip(),
        save_intermediate=(
            env_bool("SAVE_INTERMEDIATE", True)
            if args.save_artifacts is None
            else str(args.save_artifacts).lower() in {"1", "true", "yes", "y"}
        ),
        llm_max_retries=env_int("LLM_MAX_RETRIES", 3),
        llm_timeout_sec=env_int("LLM_TIMEOUT_SEC", 120),
        agent1_chunk_size=env_int("AGENT1_CHUNK_SIZE", 120),
        agent1_chunk_overlap=env_int("AGENT1_CHUNK_OVERLAP", 1),
        agent1_subchunk_on_failure=env_bool("AGENT1_SUBCHUNK_ON_FAILURE", True),
        agent1_subchunk_size=env_int("AGENT1_SUBCHUNK_SIZE", 40),
        agent1_ocr_max_captures=max(1, env_int("AGENT1_OCR_MAX_CAPTURES", 3)),
        agent1_ocr_snippet_chars=max(120, env_int("AGENT1_OCR_SNIPPET_CHARS", 220)),
        agent2_chunk_size=env_int("AGENT2_CHUNK_SIZE", 160),
        agent25_chunk_size=env_int("AGENT25_CHUNK_SIZE", 12),
        resume_artifact_dir=(args.resume_artifact_dir or "").strip(),
        pipeline_max_concurrency=max(1, env_int("PIPELINE_MAX_CONCURRENCY", 1)),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Meeting summarizer orchestrator (LangGraph)")
    parser.add_argument("--mode", choices=["agenda", "auto"], help="Summarization mode")
    parser.add_argument("--output", help="Output HTML path")
    parser.add_argument("--save-artifacts", choices=["true", "false"], help="Save intermediate files")
    parser.add_argument(
        "--resume-artifact-dir",
        help="Resume from previous artifacts directory (expects agent1_cleaned.json)",
    )
    return parser.parse_args()


def run() -> None:
    load_dotenv()
    args = parse_args()
    cfg = build_config(args)
    workflow = MeetingWorkflow(cfg)
    workflow.run()


if __name__ == "__main__":
    run()
