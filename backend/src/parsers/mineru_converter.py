"""
MinerU PDF-to-Markdown converter.

Wraps the MinerU CLI tool to convert PDF files into Markdown format,
producing output that can be consumed by the table extraction pipeline.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


class MinerUConverter:
    """
    Converts PDF files to Markdown using the MinerU CLI.

    The converter auto-detects the MinerU binary location, checking:
      1. An explicit path from MINERU_BINARY_PATH env var
      2. A local .venv in the backend directory
      3. The system PATH (global install)
    """

    def __init__(self, mineru_path: str | None = None):
        self.mineru_path = self._resolve_binary(mineru_path)
        self.timeout = int(os.getenv("MINERU_TIMEOUT_SECONDS", "600"))

    @staticmethod
    def _resolve_binary(explicit_path: str | None = None) -> str:
        """Locate the mineru CLI binary."""
        if explicit_path:
            if Path(explicit_path).exists():
                return explicit_path
            raise FileNotFoundError(
                f"MinerU binary not found at specified path: {explicit_path}"
            )

        env_path = os.getenv("MINERU_BINARY_PATH")
        if env_path:
            if Path(env_path).exists():
                return env_path
            raise FileNotFoundError(
                f"MinerU binary not found at MINERU_BINARY_PATH: {env_path}"
            )


        backend_dir = Path(__file__).resolve().parent.parent.parent  # src/parsers -> src -> backend
        is_windows = platform.system() == "Windows"

        venv_candidates = [
            backend_dir / ".venv",
            backend_dir.parent / ".venv",  # project root .venv
        ]

        for venv_dir in venv_candidates:
            if is_windows:
                binary = venv_dir / "Scripts" / "mineru.exe"
            else:
                binary = venv_dir / "bin" / "mineru"

            if binary.exists():
                return str(binary)


        system_binary = shutil.which("mineru")
        if system_binary:
            return system_binary

        raise FileNotFoundError(
            "MinerU CLI not found. Install it with:\n"
            "  pip install 'mineru[all]'\n"
            "Or set MINERU_BINARY_PATH in your .env file."
        )

    def convert(
        self,
        pdf_path: Path | str,
        output_dir: Path | str | None = None,
        print_func=print,
    ) -> Path:
        """
        Convert a PDF file to Markdown using MinerU.

        Args:
            pdf_path: Path to the input PDF file.
            output_dir: Directory to store MinerU output. If None, uses
                        assets/markdown/ relative to the backend directory.
            print_func: Callable for progress messages (print, st.write, etc.)

        Returns:
            Path to the generated .md file.

        Raises:
            FileNotFoundError: If the PDF file doesn't exist.
            RuntimeError: If MinerU fails or produces no output.
        """
        pdf_path = Path(pdf_path).resolve()
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")


        if output_dir is None:
            backend_dir = Path(__file__).resolve().parent.parent.parent
            output_dir = backend_dir / "assets" / "markdown"
        else:
            output_dir = Path(output_dir).resolve()

        pdf_stem = pdf_path.stem
        run_dir = output_dir
        if run_dir.exists():
            pdf_out_dir = run_dir / pdf_stem
            if pdf_out_dir.exists():
                if "assets" in str(pdf_out_dir) and "markdown" in str(pdf_out_dir):
                    shutil.rmtree(pdf_out_dir)
                else:
                    raise RuntimeError(f"Safety check failed: {pdf_out_dir} is not inside assets/markdown")
        run_dir.mkdir(parents=True, exist_ok=True)

        print_func(f"[MinerU] Converting: {pdf_path.name}")
        print_func(f"[MinerU] Output dir: {run_dir}")


        cmd = [
            self.mineru_path,
            "-p", str(pdf_path),
            "-o", str(run_dir),
            "--backend", "pipeline",
            # MinerU's OCR defaults to Chinese; most CNC manuals here are English.
            "--lang", os.getenv("MINERU_LANG", "en"),
            # Formula detection costs ~8 s/page on a CPU and machine manuals rarely
            # need equations; set MINERU_FORMULA=true for documents that do.
            "--formula", os.getenv("MINERU_FORMULA", "false"),
        ]

        print_func(f"[MinerU] Running: {' '.join(cmd)}")

        try:
            # Run without capture_output — MinerU starts an internal API
            # server that needs free stdout/stderr for its process
            # communication.  Capturing those streams causes the server
            # handshake to fail silently, resulting in exit code 1.
            result = subprocess.run(
                cmd,
                timeout=self.timeout,
            )

            if result.returncode != 0:
                raise RuntimeError(
                    f"MinerU exited with code {result.returncode}. "
                    "Check the terminal output above for details."
                )

        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"MinerU timed out after {self.timeout} seconds. "
                "Increase MINERU_TIMEOUT_SECONDS in .env if needed."
            )



        md_file = self._find_markdown(run_dir / pdf_stem, pdf_stem)

        if md_file is None:
            raise RuntimeError(
                f"MinerU completed but no .md file was found in {run_dir / pdf_stem}. "
                "Check MinerU output for errors."
            )

        print_func(f"[MinerU] Markdown saved to: {md_file}")

        images_dir = md_file.parent / "images"
        if images_dir.is_dir():
            image_count = len(list(images_dir.iterdir()))
            if image_count:
                print_func(f"[MinerU] Extracted {image_count} image(s)")

        return md_file

    @staticmethod
    def _find_markdown(search_dir: Path, stem: str) -> Path | None:
        """Walk the output tree looking for the generated .md file."""

        for md_file in search_dir.rglob(f"{stem}.md"):
            return md_file


        for md_file in search_dir.rglob("*.md"):
            return md_file

        return None
