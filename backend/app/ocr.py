"""Local OCR for scanned case PDFs; no model service or network calls."""
import csv
import io
import shutil
import subprocess
import tempfile
from pathlib import Path


def recognize_pages(raw, pages):
    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        raise ValueError("PDF содержит сканы. Для OCR запустите Docker-комплект с Poppler и Tesseract rus+eng.")
    results = {}
    with tempfile.TemporaryDirectory(prefix="bank-pdf-") as tmp:
        root = Path(tmp)
        pdf = root / "input.pdf"
        pdf.write_bytes(raw)
        for page in pages:
            stem = root / "page"
            subprocess.run(["pdftoppm", "-q", "-f", str(page), "-l", str(page), "-singlefile", "-scale-to", "2400",
                            "-png", str(pdf), str(stem)], check=True, capture_output=True, timeout=45)
            subprocess.run(["tesseract", str(stem.with_suffix('.png')), str(stem), "-l", "rus+eng", "--psm", "3", "txt", "tsv"],
                           check=True, capture_output=True, timeout=90)
            rows = csv.DictReader(io.StringIO(stem.with_suffix('.tsv').read_text(encoding='utf8')), delimiter='\t', quoting=csv.QUOTE_NONE)
            scores = [float(row['conf']) for row in rows if row.get('text', '').strip() and float(row['conf']) >= 0]
            results[page] = {"text": stem.with_suffix('.txt').read_text(encoding='utf8'),
                             "confidence": round(sum(scores) / len(scores), 1) if scores else 0}
    return results
