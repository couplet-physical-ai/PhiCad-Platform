#!/usr/bin/env python3
"""Render an project MP4 from a completed, hashed V1 demo run.

The video contains only evidence read from the run directory plus static product
copy.  It does not simulate a successful command or invent a board screenshot.
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

WIDTH = 1280
HEIGHT = 720
BG = "#f5f7fa"
INK = "#1f2430"
MUTED = "#626b78"
LINE = "#cbd1da"
RED = "#e32611"
ORANGE = "#ff7a1a"
GREEN = "#16794a"
AMBER = "#a96000"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
SANS = "Inter, Avenir Next, Helvetica Neue, Arial, sans-serif"


class RenderError(RuntimeError):
    pass


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RenderError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RenderError(f"expected a JSON object: {path}")
    return value


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def text(x: int, y: int, value: object, *, size: int = 24, weight: int = 400, color: str = INK, family: str = SANS, anchor: str = "start") -> str:
    return (
        f'<text x="{x}" y="{y}" fill="{color}" font-family="{family}" '
        f'font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">{esc(value)}</text>'
    )


def lines(x: int, y: int, values: Iterable[object], *, size: int = 22, gap: int = 34, color: str = INK, family: str = SANS) -> str:
    return "".join(text(x, y + index * gap, value, size=size, color=color, family=family) for index, value in enumerate(values))


def shell(slide: str, body: str, index: int, total: int, *, eyebrow: str, title: str, subtitle: str) -> str:
    progress = int((WIDTH - 112) * index / total)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="title desc" viewBox="0 0 {WIDTH} {HEIGHT}">
<title id="title">{esc(title)}</title><desc id="desc">{esc(subtitle)}</desc>
<defs><linearGradient id="accent" x1="0" y1="0" x2="1" y2="0"><stop stop-color="{RED}"/><stop offset="1" stop-color="{ORANGE}"/></linearGradient></defs>
<rect width="{WIDTH}" height="{HEIGHT}" fill="{BG}"/>
<rect x="0" y="0" width="14" height="{HEIGHT}" fill="url(#accent)"/>
{text(58, 58, eyebrow.upper(), size=14, weight=700, color=RED)}
{text(58, 108, title, size=42, weight=750)}
{text(58, 144, subtitle, size=19, color=MUTED)}
<line x1="58" y1="174" x2="1222" y2="174" stroke="{LINE}" stroke-width="2"/>
{body}
<line x1="58" y1="679" x2="1222" y2="679" stroke="{LINE}" stroke-width="6" stroke-linecap="round"/>
<line x1="58" y1="679" x2="{58 + progress}" y2="679" stroke="url(#accent)" stroke-width="6" stroke-linecap="round"/>
{text(58, 706, 'PHICAD PLATFORM · V1 DEVELOPER PREVIEW', size=12, weight=700, color=MUTED)}
{text(1222, 706, f'{index:02d}/{total:02d}', size=12, weight=700, color=MUTED, anchor='end')}
</svg>'''


def frames(run_dir: Path) -> list[tuple[str, str]]:
    diagnostics = read_json(run_dir / "diagnostics.json")
    tools = read_json(run_dir / "tool-versions.json")
    run = read_json(run_dir / "run.json")
    manifest = read_json(run_dir / "manifest.json")
    observed = diagnostics.get("observed", {})
    engine = observed.get("engine_check", {})
    verify = observed.get("build_and_verify", {})
    if engine.get("ok") is not True or verify.get("ok") is not True:
        raise RenderError("the selected run is not a successful engine + Verify evidence run")
    if diagnostics.get("fixture_match", {}).get("match") is not True:
        raise RenderError("the selected run does not match its checked fixture")
    if manifest.get("fabrication_ready") is not False:
        raise RenderError("the demo manifest must explicitly record fabrication_ready=false")

    engine_codes = engine.get("finding_codes", [])
    verify_codes = verify.get("verification_finding_codes", [])
    kicad_version = tools.get("verifier", {}).get("reported_version") or "version unavailable"
    duration = run.get("duration_ms", 0)
    total = 6

    pipeline = "Phi → Circuit Source → Circuit Engine → PhiCad (Studio · Verify)"
    body1 = (
        '<rect x="58" y="218" width="1164" height="250" rx="20" fill="#ffffff" stroke="#d6dbe3"/>'
        + text(640, 282, "ONE PROJECT · FIVE LINKED VIEWS", size=18, weight=700, color=MUTED, anchor="middle")
        + text(640, 346, pipeline, size=31, weight=720, anchor="middle")
        + text(640, 398, "Phi is the sole AI harness. Every artifact is manifest-bound.", size=20, color=MUTED, anchor="middle")
        + text(58, 532, "Evidence source", size=15, weight=700, color=RED)
        + lines(58, 568, (f"run: {run.get('run_id')}", f"duration: {duration:.0f} ms", "fixture: exact match"), size=18, gap=28, family=MONO)
    )

    code = (
        '<board width="18mm" height="12mm" defaultTraceWidth="0.25mm">',
        '  <resistor name="R1" resistance="1k" footprint="0402" />',
        '  <led name="D1" color="red" footprint="0603" />',
        '  <trace from=".R1 > .pin2" to=".D1 > .anode" />',
        '</board>',
    )
    body2 = (
        '<rect x="58" y="210" width="1164" height="360" rx="18" fill="#202630"/>'
        + text(86, 246, "examples/demo-v1-led.tsx", size=16, weight=700, color="#ff8b3d", family=MONO)
        + lines(86, 292, code, size=21, gap=48, color="#f3f5f8", family=MONO)
        + text(58, 622, "Intentional one-net fragment: workflow evidence, not an electrically complete design.", size=18, color=MUTED)
    )

    body3 = (
        '<rect x="58" y="216" width="310" height="178" rx="18" fill="#eaf7f0" stroke="#9fd1b6"/>'
        + text(86, 260, "CIRCUIT ENGINE", size=15, weight=700, color=GREEN)
        + text(86, 323, "PASS", size=54, weight=800, color=GREEN)
        + text(86, 364, f"0 errors · {len(engine_codes)} warnings", size=18, color=INK)
        + text(420, 232, "Observed warning origins", size=17, weight=700, color=MUTED)
        + lines(420, 272, (f"• {code}" for code in engine_codes), size=16, gap=42, family=MONO)
        + text(58, 620, "Warnings stay visible; a green engine verdict does not become a native PhiCad verdict.", size=18, color=MUTED)
    )

    body4 = (
        '<rect x="58" y="216" width="310" height="178" rx="18" fill="#eaf7f0" stroke="#9fd1b6"/>'
        + text(86, 260, "PHICAD VERIFY", size=15, weight=700, color=GREEN)
        + text(86, 323, "PASS", size=54, weight=800, color=GREEN)
        + text(86, 364, f"{verify.get('verification_errors', 0)} errors · {verify.get('verification_warnings', 0)} warnings", size=18, color=INK)
        + text(420, 232, f"Independent from Circuit Engine · kicad-cli {kicad_version}", size=17, weight=700, color=MUTED)
        + lines(420, 282, (f"• {code}" for code in verify_codes), size=17, gap=47, family=MONO)
        + text(58, 620, "Verify checked a generated artifact — not fabrication approval or an applied native revision.", size=18, color=AMBER)
    )

    commands = (
        "phicad-platform open phi --manifest phicad.design.json",
        "phicad-platform open studio --manifest phicad.design.json",
        "phicad-platform open circuit-source --manifest phicad.design.json",
        "phicad-platform open verify --manifest phicad.design.json",
        "phicad-platform open docs --manifest phicad.design.json",
    )
    body5 = (
        '<rect x="58" y="210" width="1164" height="368" rx="18" fill="#ffffff" stroke="#d6dbe3"/>'
        + lines(86, 260, commands, size=18, gap=55, family=MONO)
        + text(86, 548, "stale manifest → blocked · credentials in handoff → forbidden", size=17, weight=700, color=RED, family=MONO)
        + text(58, 620, "Every view opens every other view through one validated Platform contract.", size=18, color=MUTED)
    )

    body6 = (
        '<rect x="58" y="214" width="1164" height="250" rx="20" fill="#ffffff" stroke="#d6dbe3"/>'
        + text(92, 270, "DEVELOPER PREVIEW", size=15, weight=800, color=RED)
        + text(92, 329, "Build evidence: PASS", size=30, weight=750, color=GREEN)
        + text(92, 376, "Fabrication status: NOT CLAIMED", size=30, weight=750, color=AMBER)
        + text(92, 422, "PhiCad native materialization: UNAVAILABLE IN V1", size=20, weight=700, color=MUTED)
        + text(58, 528, "Next review", size=15, weight=700, color=RED)
        + lines(58, 566, ("Inspect PhiCad native source pin and the native-mode contracts", "Re-run the manifest-bound Platform Verify service", "Keep mechanical, sourcing, CAM/DFM, assembly, and first-article gates closed"), size=18, gap=31)
    )

    slides = (
        ("One Phi-driven PCB workflow", "Actual small-board run evidence", body1, "overview"),
        ("Reviewable circuit source", "Pinned TSX input; no runtime package download", body2, "source"),
        ("Circuit Engine result", "tscircuit diagnostics retain their own origin", body3, "engine"),
        ("PhiCad Verify result", "The same native application family checks the exact generated artifact", body4, "verify"),
        ("Every view opens the others", "Manifest identity travels; credentials and mutations do not", body5, "links"),
        ("Evidence without overclaiming", "The workflow ran; manufacturing gates remain independent", body6, "status"),
    )
    return [
        (name, shell(name, body, index, total, eyebrow="PhiCad Platform", title=title, subtitle=subtitle))
        for index, (title, subtitle, body, name) in enumerate(slides, 1)
    ]


def run(command: Sequence[str]) -> None:
    completed = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
    if completed.returncode:
        detail = (completed.stderr or completed.stdout).strip()
        raise RenderError(f"command failed ({command[0]}): {detail}")


def render(run_dir: Path, output: Path, poster: Path, seconds_per_slide: float) -> None:
    rsvg = shutil.which("rsvg-convert")
    ffmpeg = shutil.which("ffmpeg")
    if not rsvg or not ffmpeg:
        raise RenderError("rsvg-convert and ffmpeg are required to render the demo video")
    output.parent.mkdir(parents=True, exist_ok=True)
    poster.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="phicad-video-") as temporary:
        work = Path(temporary)
        concat_lines = []
        pngs = []
        for index, (name, svg) in enumerate(frames(run_dir), 1):
            svg_path = work / f"{index:02d}-{name}.svg"
            png_path = work / f"{index:02d}-{name}.png"
            svg_path.write_text(svg, encoding="utf-8")
            run((rsvg, "-w", str(WIDTH), "-h", str(HEIGHT), str(svg_path), "-o", str(png_path)))
            pngs.append(png_path)
            concat_lines.extend((f"file '{png_path}'", f"duration {seconds_per_slide:.3f}"))
        concat_lines.append(f"file '{pngs[-1]}'")
        concat = work / "slides.txt"
        concat.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")
        shutil.copyfile(pngs[0], poster)
        run(
            (
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat),
                "-vf",
                "fps=24,format=yuv420p",
                "-c:v",
                "libx264",
                "-profile:v",
                "high",
                "-movflags",
                "+faststart",
                str(output),
            )
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--poster", type=Path)
    parser.add_argument("--seconds-per-slide", type=float, default=4.0)
    parser.add_argument("--check", action="store_true", help="validate evidence and dependencies without rendering")
    args = parser.parse_args(argv)
    try:
        slides = frames(args.run_dir.resolve())
        if not shutil.which("rsvg-convert") or not shutil.which("ffmpeg"):
            raise RenderError("rsvg-convert and ffmpeg are required")
        if args.check:
            print(f"video evidence valid: {len(slides)} slides")
            return 0
        poster = args.poster or args.output.with_suffix(".png")
        render(args.run_dir.resolve(), args.output.resolve(), poster.resolve(), args.seconds_per_slide)
        print(args.output.resolve())
        print(poster.resolve())
        return 0
    except RenderError as exc:
        print(f"video render error: {exc}", file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
