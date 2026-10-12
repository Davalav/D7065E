"""Convert D2's SVG output to page-sized vector PDFs with headless Chrome.

D2's own PNG export downloads a Playwright driver whose host no longer exists,
so the figures are rendered as SVG and printed to PDF instead:

    python svg2pdf.py build/svg/*.svg      # writes figures/<name>.pdf
"""
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "google-chrome",
    "chromium",
    "chromium-browser",
]
OUTPUT_DIR = Path(__file__).resolve().parent / "figures"


def find_chrome():
    for candidate in CHROME_CANDIDATES:
        path = shutil.which(candidate) or (candidate if Path(candidate).exists() else None)
        if path:
            return path
    raise SystemExit("No Chrome, Edge or Chromium found")


def svg_size(svg_text):
    match = re.search(r'viewBox="[-\d.]+ [-\d.]+ ([\d.]+) ([\d.]+)"', svg_text)
    if not match:
        raise ValueError("SVG has no viewBox")
    return float(match.group(1)), float(match.group(2))


def convert(chrome, svg_path, profile_dir):
    svg_text = svg_path.read_text(encoding="utf-8")
    width, height = svg_size(svg_text)
    html = (
        "<!doctype html><meta charset='utf-8'><style>"
        f"@page{{size:{width}px {height}px;margin:0}}"
        "html,body{margin:0;padding:0}svg{display:block}"
        f"</style>{svg_text[svg_text.index('<svg'):]}"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as page:
        page.write(html)
    output = OUTPUT_DIR / f"{svg_path.stem}.pdf"
    subprocess.run(
        [
            chrome,
            "--headless=new",
            f"--user-data-dir={profile_dir}",
            "--no-pdf-header-footer",
            f"--print-to-pdf={output}",
            Path(page.name).as_uri(),
        ],
        check=True,
        capture_output=True,
    )
    Path(page.name).unlink()
    compress(output)
    print(f"{svg_path.name} -> {output.relative_to(OUTPUT_DIR.parent)} ({width:.0f}x{height:.0f})")


def compress(pdf_path):
    # Chrome embeds full fonts; Ghostscript rewrites the PDF about 10x smaller.
    gs = shutil.which("gs") or shutil.which("gswin64c")
    if not gs:
        return
    smaller = pdf_path.with_suffix(".small.pdf")
    subprocess.run(
        [gs, "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.5", "-dNOPAUSE",
         "-dBATCH", "-dQUIET", f"-sOutputFile={smaller}", str(pdf_path)],
        check=True,
    )
    smaller.replace(pdf_path)


def main():
    chrome = find_chrome()
    OUTPUT_DIR.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as profile_dir:
        for argument in sys.argv[1:]:
            convert(chrome, Path(argument), profile_dir)


if __name__ == "__main__":
    main()
