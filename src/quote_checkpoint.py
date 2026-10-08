"""Durable partial exports and a machine-readable batch status report."""
import json
from pathlib import Path

from file_utils import atomic_write_text, reserve_output_path
from quote_markdown import render_quote_batch_markdown


class QuoteCheckpoint:
    def __init__(self, output_dir: Path, stem: str, total: int, raw_ocr_mode: str):
        self.path = reserve_output_path(output_dir, stem)
        self.report_path = self.path.with_suffix(".progress.json")
        self.raw_ocr_mode = raw_ocr_mode
        self.report = {"status": "running", "total": total, "processed": 0,
                       "current_image": None, "failed": [], "notices": []}

    def save(self, records, processed: int, status: str, current_image=None):
        self.report.update(processed=processed, status=status, current_image=current_image)
        markdown = render_quote_batch_markdown(records, raw_ocr_mode=self.raw_ocr_mode)
        markdown += f"\n---\n\n## Conversion report\n\nStatus: {status}\n\n"
        markdown += f"Processed: {processed}/{self.report['total']} images\n"
        for failure in self.report["failed"]:
            markdown += f"\n- Failed: {failure['image']} — {failure['error']}\n"
        atomic_write_text(self.path, markdown)
        atomic_write_text(self.report_path, json.dumps(self.report, indent=2) + "\n")
