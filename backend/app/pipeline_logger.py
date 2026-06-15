# backend/app/pipeline_logger.py
"""
Structured logging for the receipt OCR pipeline.

Captures input/output of each stage, timing, routing decisions.
Supports verbose terminal output and JSON export to debug_logs/.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Generator, Optional


@dataclass
class StageLog:
    """Log entry for a single pipeline stage."""

    stage_name: str
    status: str = "OK"  # "OK" | "SKIP" | "FAIL" | "NO_AI"
    duration_ms: float = 0.0
    input_summary: dict[str, Any] = field(default_factory=dict)
    output_summary: dict[str, Any] = field(default_factory=dict)
    route_chosen: Optional[str] = None
    error: Optional[str] = None


_STATUS_ICONS = {
    "OK": "✅",
    "SKIP": "⏭️",
    "FAIL": "❌",
    "NO_AI": "🚫",
}


class PipelineLogger:
    """
    Structured logger for receipt pipeline debug runs.

    Usage:
        logger = PipelineLogger(verbose=True)
        logger.set_file_info("receipt.pdf", file_bytes)

        with logger.stage("source_detection", {"filename": "receipt.pdf"}) as log:
            source = detect(...)
            log.output_summary = {"source": source.value}
            log.route_chosen = source.value

        logger.print_summary()
        logger.save("debug_logs/")
    """

    def __init__(self, verbose: bool = True) -> None:
        self.verbose = verbose
        self.run_id: str = str(uuid.uuid4())[:8]
        self.started_at: datetime = datetime.now(timezone.utc)
        self.file_info: dict[str, Any] = {}
        self.stages: list[StageLog] = []

    # ── File info ──────────────────────────────────────────────────────────────

    def set_file_info(self, filename: str, file_bytes: bytes) -> None:
        """Record metadata about the input file."""
        self.file_info = {
            "filename": filename,
            "size_bytes": len(file_bytes),
            "size_human": _human_size(len(file_bytes)),
            "sha256": hashlib.sha256(file_bytes).hexdigest()[:16],
            "magic_bytes": file_bytes[:4].hex() if file_bytes else "",
        }
        if self.verbose:
            print(f"\n🔬 Pipeline Debug Run: {self.started_at.strftime('%Y-%m-%dT%H:%M:%S')}")
            print(f"   Run ID: {self.run_id}")
            print(
                f"   File: {filename} "
                f"({self.file_info['size_human']}, "
                f"SHA256: {self.file_info['sha256']}…)"
            )

    # ── Stage context manager ──────────────────────────────────────────────────

    @contextmanager
    def stage(
        self, name: str, input_data: Optional[dict[str, Any]] = None
    ) -> Generator[StageLog, None, None]:
        """
        Context manager wrapping a pipeline stage.

        Measures duration, captures input/output, prints to terminal if verbose.
        Sets status to FAIL on exception and re-raises.
        """
        stage_log = StageLog(stage_name=name, input_summary=input_data or {})

        stage_num = len(self.stages) + 1
        display_name = name.upper().replace("_", " ")

        if self.verbose:
            print(f"\n{'─' * 60}")
            print(f"  Stage {stage_num}: {display_name}")
            print(f"{'─' * 60}")
            if input_data:
                for k, v in input_data.items():
                    print(f"  Input:  {k}={_truncate(str(v), 120)}")

        start = time.perf_counter()
        try:
            yield stage_log
        except Exception as e:
            stage_log.status = "FAIL"
            stage_log.error = str(e)
            if self.verbose:
                print(f"  ❌ FAILED: {e}")
            raise
        finally:
            stage_log.duration_ms = round((time.perf_counter() - start) * 1000, 2)
            self.stages.append(stage_log)

            if self.verbose:
                if stage_log.route_chosen:
                    print(f"  Route:  → {stage_log.route_chosen}")
                # Print compact output summary (skip keys handled by detail methods)
                for k, v in stage_log.output_summary.items():
                    if k.startswith("_"):
                        continue  # internal keys, already printed via detail methods
                    print(f"  Output: {k}={_truncate(str(v), 120)}")
                icon = _STATUS_ICONS.get(stage_log.status, "❓")
                print(f"  Status: {icon} {stage_log.status} [{stage_log.duration_ms}ms]")

    # ── Detail helpers (called inside `with stage(...)` blocks) ────────────────

    def detail(self, text: str) -> None:
        """Print a single detail line during a stage (verbose only)."""
        if self.verbose:
            print(f"  {text}")

    def detail_lines(
        self, title: str, lines: list[str], max_show: int = 20
    ) -> None:
        """Print a numbered list of lines (verbose only)."""
        if not self.verbose:
            return
        print(f"  {title} ({len(lines)} total):")
        for i, line in enumerate(lines[:max_show]):
            print(f"    {i + 1:3}  {line}")
        if len(lines) > max_show:
            print(f"    ... ({len(lines) - max_show} more)")

    def detail_items(self, items: list[dict[str, Any]], max_show: int = 15) -> None:
        """Print parsed receipt items as a formatted table (verbose only)."""
        if not self.verbose:
            return
        print(f"  Items ({len(items)}):")
        for item in items[:max_show]:
            name = str(item.get("name", "?"))[:40]
            price = float(item.get("price", 0))
            qty = float(item.get("quantity", 1))
            parts = [f"    {name:40} {price:>8.2f} PLN  x{qty}"]
            if item.get("discount_total"):
                parts.append(f" (rabat: {item['discount_total']:.2f})")
            if item.get("is_adjustment"):
                parts.append(" [adj]")
            print("".join(parts))
        if len(items) > max_show:
            print(f"    ... ({len(items) - max_show} more)")

    # ── Summary & export ───────────────────────────────────────────────────────

    def print_summary(self) -> None:
        """Print final pipeline summary to terminal."""
        total_ms = sum(s.duration_ms for s in self.stages)
        failed = [s for s in self.stages if s.status == "FAIL"]

        print(f"\n{'═' * 60}")
        print(f"  PIPELINE COMPLETE — {len(self.stages)} stages, {total_ms:.0f}ms total")
        if failed:
            names = ", ".join(s.stage_name for s in failed)
            print(f"  Result: ❌ FAILED at: {names}")
        else:
            print("  Result: ✅ ALL STAGES PASSED")
        print(f"{'═' * 60}")

    def to_dict(self) -> dict[str, Any]:
        """Serialize full pipeline log to JSON-compatible dict."""
        return {
            "run_id": self.run_id,
            "started_at": self.started_at.isoformat(),
            "file_info": self.file_info,
            "stages": [
                {
                    "stage_name": s.stage_name,
                    "status": s.status,
                    "duration_ms": s.duration_ms,
                    "input_summary": _make_serializable(s.input_summary),
                    "output_summary": _make_serializable(s.output_summary),
                    "route_chosen": s.route_chosen,
                    "error": s.error,
                }
                for s in self.stages
            ],
            "total_duration_ms": round(sum(s.duration_ms for s in self.stages), 2),
        }

    def save(self, output_dir: str) -> str:
        """Save JSON log to output directory. Returns file path."""
        os.makedirs(output_dir, exist_ok=True)

        ts = self.started_at.strftime("%Y%m%d_%H%M%S")
        filename = self.file_info.get("filename", "unknown")
        safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)
        log_filename = f"{ts}_{safe_name}.json"
        log_path = os.path.join(output_dir, log_filename)

        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

        if self.verbose:
            print(f"  Log saved: {log_path}")

        return log_path


# ── Utility functions ──────────────────────────────────────────────────────────


def _human_size(size_bytes: int) -> str:
    for unit in ("B", "KB", "MB"):
        if size_bytes < 1024:
            return f"{size_bytes:.0f} {unit}"
        size_bytes /= 1024  # type: ignore[assignment]
    return f"{size_bytes:.1f} GB"


def _truncate(s: str, max_len: int = 120) -> str:
    return s if len(s) <= max_len else s[:max_len] + "…"


def _make_serializable(obj: Any) -> Any:
    """Convert non-serializable objects for JSON export."""
    if isinstance(obj, dict):
        return {k: _make_serializable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_make_serializable(item) for item in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)
