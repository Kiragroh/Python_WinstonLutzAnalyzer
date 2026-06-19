from __future__ import annotations

import contextlib
import csv
import ctypes
import io
import json
import os
import queue
import statistics
import sys
import threading
import time
import warnings
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
import tkinter as tk

import pylinac
from PIL import Image
from pylinac import WinstonLutz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from multi_ball_wlt import MultiBallSettings, analyze_folder, format_summary, parse_expected_fields


APP_TITLE = "WLT v3.0 Open"
warnings.filterwarnings("ignore", category=FutureWarning)
PROJECT_DIR = Path(__file__).resolve().parent
WORKSPACE_DIR = PROJECT_DIR.parent
DEFAULT_MULTI_IMAGE_DIR = PROJECT_DIR / "examples" / "multi_ball" / "rtimages"
DEFAULT_MULTI_PLAN = PROJECT_DIR / "examples" / "multi_ball" / "rtplan.dcm"
DEFAULT_WLT_DIR = PROJECT_DIR / "examples" / "standard_wlt"
OUTPUT_DIR = PROJECT_DIR / "output"
APP_ICON_PATH = PROJECT_DIR / "assets" / "wlt_icon.ico"
HISTORY_CSV = OUTPUT_DIR / "wlt_history.csv"
GUI_SETTINGS_JSON = OUTPUT_DIR / "gui_settings.json"
HISTORY_COLUMNS = [
    "timestamp",
    "workflow",
    "linac",
    "source",
    "image_count",
    "max_mm",
    "mean_mm",
    "median_mm",
    "gantry_iso_mm",
    "pdf",
    "txt",
    "csv",
    "graph",
    "notes",
]

BG = "#0a0e17"
PANEL = "#111827"
PANEL_2 = "#1a2332"
TEXT = "#e2e8f0"
MUTED = "#94a3b8"
DIM = "#64748b"
ACCENT = "#00e5ff"
ACCENT_2 = "#0d9488"
ACCENT_PURPLE = "#a855f7"
GOOD = "#22c55e"
WARN = "#f59e0b"
ERR = "#ef4444"
LOG_BG = "#020617"
TABLE_BG = "#0f172a"
TABLE_ALT = "#111827"
TABLE_HEAD = "#1e293b"
TABLE_TEXT = "#e2e8f0"
TABLE_SELECT = "#0d9488"
HAMBURG_BLUE = "#003c5f"
HAMBURG_CYAN = "#00a6c8"
HAMBURG_RED = "#e30613"


def path_or_empty(path: Path) -> str:
    return str(path) if path.exists() else ""


def append_history_row(row: dict[str, object]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    exists = HISTORY_CSV.exists()
    with HISTORY_CSV.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=HISTORY_COLUMNS)
        if not exists:
            writer.writeheader()
        writer.writerow({column: row.get(column, "") for column in HISTORY_COLUMNS})


def load_history_rows() -> list[dict[str, str]]:
    if not HISTORY_CSV.exists():
        return []
    with HISTORY_CSV.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def load_gui_settings() -> dict[str, object]:
    if not GUI_SETTINGS_JSON.exists():
        return {}
    try:
        return json.loads(GUI_SETTINGS_JSON.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_gui_settings(settings: dict[str, object]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    GUI_SETTINGS_JSON.write_text(json.dumps(settings, indent=2), encoding="utf-8")


@contextlib.contextmanager
def quiet_future_warnings():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", FutureWarning)
        with contextlib.redirect_stderr(io.StringIO()):
            yield


def metric_text(data: dict[str, object], key: str, suffix: str = " mm") -> str:
    try:
        return f"{float(data.get(key, 0.0)):.3f}{suffix}"
    except Exception:
        return "n/a"


def safe_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def dicom_date_text(value: object) -> str:
    text = str(value or "").strip()
    if len(text) >= 8:
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    return text or "n/a"


def dicom_time_text(value: object) -> str:
    text = str(value or "").split(".")[0].strip()
    if len(text) >= 6:
        return f"{text[:2]}:{text[2:4]}:{text[4:6]}"
    return text or "n/a"


def metadata_value(image: object, key: str, default: object = None) -> object:
    metadata = getattr(image, "metadata", None)
    if metadata is None:
        return default
    return getattr(metadata, key, default)


def normalized_linac_number(value: object) -> str:
    text = str(value or "").strip()
    upper = text.upper()
    mapping = {"1334": "1", "1233": "2", "2479": "3", "6738": "4"}
    for suffix, number in mapping.items():
        if upper.endswith(suffix):
            return number
    for number in ("1", "2", "3", "4"):
        if f"L{number}" in upper or f"LINAC{number}" in upper or f"LINAC_{number}" in upper:
            return number
    if upper.startswith("L") and upper[1:].isdigit():
        return upper[1:]
    return text or "Unbekannt"


def uke_linac_label(wl: object, fallback: str) -> str:
    images = list(getattr(wl, "images", []) or [])
    if images:
        station = metadata_value(images[0], "StationName", "") or metadata_value(images[0], "RadiationMachineName", "")
        number = normalized_linac_number(station)
        if number != "Unbekannt":
            return f"Linac_{number}"
    number = normalized_linac_number(fallback)
    return f"Linac_{number}" if number != "Unbekannt" else "Linac_Unbekannt"


def unique_float_count(values: list[object]) -> int:
    parsed = [safe_float(value) for value in values]
    return len({round(value, 2) for value in parsed if value is not None})


def first_image_by_gantry(images: list[object], preferred_angles: tuple[int, ...]) -> object | None:
    by_angle: dict[int, object] = {}
    for image in images:
        angle = safe_float(metadata_value(image, "GantryAngle", getattr(image, "gantry_angle", None)))
        if angle is None:
            continue
        rounded = int(round(angle)) % 360
        by_angle.setdefault(rounded, image)
    for angle in preferred_angles:
        image = by_angle.get(angle % 360)
        if image is not None:
            return image
    return None


def select_uke_preview_images(wl: object) -> list[object]:
    images = list(getattr(wl, "images", []) or [])
    selected: list[object] = []
    for angles in ((0, 360), (180,), (90,), (270,)):
        image = first_image_by_gantry(images, angles)
        if image is not None and image not in selected:
            selected.append(image)
    for image in images:
        if len(selected) >= 4:
            break
        if image not in selected:
            selected.append(image)
    return selected[:4]


def shift_vector_values(wl: object, data: dict[str, object]) -> tuple[float | None, float | None, float | None]:
    vector = getattr(wl, "bb_shift_vector", None)
    if vector is not None:
        return safe_float(getattr(vector, "x", None)), safe_float(getattr(vector, "y", None)), safe_float(getattr(vector, "z", None))
    shift = data.get("bb_shift_vector", {})
    if isinstance(shift, dict):
        return safe_float(shift.get("x")), safe_float(shift.get("y")), safe_float(shift.get("z"))
    return None, None, None


def format_shift_cm(wl: object, data: dict[str, object]) -> str:
    x, y, z = shift_vector_values(wl, data)
    if None in (x, y, z):
        return "n/a"
    return f"B-D: {z / 10:2.3f}; T-G: {y / 10:2.3f}; A-B: {x / 10:2.3f}"


def couch_position_text(wl: object, data: dict[str, object], recommended: bool = False) -> str:
    images = list(getattr(wl, "images", []) or [])
    if not images:
        return "n/a"
    image = images[0]
    vrt = safe_float(metadata_value(image, "TableTopVerticalPosition"))
    lng = safe_float(metadata_value(image, "TableTopLongitudinalPosition"))
    lat = safe_float(metadata_value(image, "TableTopLateralPosition"))
    if None in (vrt, lng, lat):
        return "n/a"
    if recommended:
        x, y, z = shift_vector_values(wl, data)
        if None in (x, y, z):
            return "n/a"
        vrt += z
        lng += y
        lat += x
    return f"VRT: {vrt / 10:3.2f}; LNG: {lng / 10:3.2f}; LAT: {lat / 10:3.2f}"


def draw_text_lines(canvas: Canvas, lines: list[str], x_cm: float, y_cm: float, font_size: int = 10, bold: bool = False, color: str = "#000000") -> None:
    textobj = canvas.beginText()
    textobj.setTextOrigin(x_cm * cm, y_cm * cm)
    textobj.setFont("Helvetica-Bold" if bold else "Helvetica", font_size)
    textobj.setFillColor(colors.HexColor(color))
    for line in lines:
        textobj.textLine(line)
    canvas.drawText(textobj)


def pylinac_logo_path() -> Path | None:
    root = Path(pylinac.__file__).resolve().parent
    for name in ("Pylinac-GREEN.png", "Pylinac Full cropped.png"):
        path = root / "files" / name
        if path.exists():
            return path
    return None


def configure_windows_app_id() -> None:
    if os.name != "nt":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("medphy.wlt.open.v3")
    except Exception:
        pass


def app_icon_path() -> Path | None:
    candidates: list[Path] = []
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        candidates.append(Path(bundle_dir) / "assets" / "wlt_icon.ico")
        candidates.append(Path(bundle_dir) / "wlt_icon.ico")
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "assets" / "wlt_icon.ico")
        candidates.append(Path(sys.executable).resolve().parent / "wlt_icon.ico")
    candidates.append(APP_ICON_PATH)
    candidates.append(PROJECT_DIR / "ico.ico")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def draw_metric_card(canvas: Canvas, x: float, y: float, width: float, title: str, value: str, accent: str) -> None:
    canvas.setFillColor(colors.HexColor("#f8fafc"))
    canvas.roundRect(x, y, width, 2.2 * cm, 6, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor(accent))
    canvas.rect(x, y, 0.12 * cm, 2.2 * cm, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor("#334155"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(x + 0.45 * cm, y + 1.45 * cm, title)
    canvas.setFillColor(colors.HexColor("#0f172a"))
    canvas.setFont("Helvetica-Bold", 17)
    canvas.drawString(x + 0.45 * cm, y + 0.55 * cm, value)


def create_wlt_cover_pdf(
    cover_pdf: Path,
    data: dict[str, object],
    folder: Path,
    output: Path,
    linac: str,
    timestamp: str,
    notes: str,
) -> None:
    cover_pdf.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(str(cover_pdf), pagesize=A4)
    width, height = A4

    canvas.setFillColor(colors.white)
    canvas.rect(0, 0, width, height, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor(HAMBURG_BLUE))
    canvas.rect(0, height - 3.2 * cm, width, 3.2 * cm, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor(HAMBURG_CYAN))
    canvas.rect(0, height - 3.35 * cm, width * 0.72, 0.15 * cm, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor(HAMBURG_RED))
    canvas.rect(width * 0.72, height - 3.35 * cm, width * 0.28, 0.15 * cm, stroke=0, fill=1)

    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 22)
    canvas.drawString(1.4 * cm, height - 1.65 * cm, "Winston-Lutz Analyse")
    canvas.setFont("Helvetica", 9)
    canvas.drawString(1.45 * cm, height - 2.28 * cm, f"{APP_TITLE} | pylinac v{pylinac.__version__}")

    logo = pylinac_logo_path()
    if logo:
        try:
            canvas.drawImage(ImageReader(str(logo)), width - 5.4 * cm, height - 2.55 * cm, 4.1 * cm, 1.55 * cm, preserveAspectRatio=True, mask="auto")
        except Exception:
            pass

    canvas.setFillColor(colors.HexColor("#0f172a"))
    canvas.setFont("Helvetica-Bold", 18)
    canvas.drawString(1.4 * cm, height - 4.9 * cm, "QA Summary")
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.setFont("Helvetica", 9)
    canvas.drawString(1.4 * cm, height - 5.55 * cm, "Kompaktes Deckblatt; detaillierte pylinac-Auswertung folgt auf den naechsten Seiten.")

    card_y = height - 9.0 * cm
    card_w = 5.7 * cm
    draw_metric_card(canvas, 1.4 * cm, card_y, card_w, "Max CAX -> BB", metric_text(data, "max_2d_cax_to_bb_mm"), HAMBURG_RED)
    draw_metric_card(canvas, 7.55 * cm, card_y, card_w, "Median CAX -> BB", metric_text(data, "median_2d_cax_to_bb_mm"), HAMBURG_CYAN)
    draw_metric_card(canvas, 13.7 * cm, card_y, card_w, "Gantry Iso Diameter", metric_text(data, "gantry_3d_iso_diameter_mm"), HAMBURG_BLUE)

    rows = [
        ("Linac", linac),
        ("Bilder", str(data.get("num_total_images", "n/a"))),
        ("Analyseordner", str(folder)),
        ("Output", str(output)),
        ("Zeitstempel", timestamp),
        ("Notiz", notes or "-"),
    ]
    y = height - 11.3 * cm
    canvas.setFillColor(colors.HexColor("#0f172a"))
    canvas.setFont("Helvetica-Bold", 11)
    canvas.drawString(1.4 * cm, y, "Kontext")
    y -= 0.65 * cm
    for label, value in rows:
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(1.4 * cm, y, label.upper())
        canvas.setFillColor(colors.HexColor("#0f172a"))
        canvas.setFont("Helvetica", 8)
        canvas.drawString(5.0 * cm, y, str(value)[:118])
        y -= 0.58 * cm

    canvas.setFillColor(colors.HexColor("#f1f5f9"))
    canvas.roundRect(1.4 * cm, 2.0 * cm, width - 2.8 * cm, 2.0 * cm, 6, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor("#334155"))
    canvas.setFont("Helvetica", 8)
    canvas.drawString(1.8 * cm, 3.15 * cm, "Hinweis")
    canvas.setFont("Helvetica", 9)
    canvas.drawString(1.8 * cm, 2.65 * cm, "Bewertung weiterhin gegen lokale Toleranzen und klinische SOP pruefen.")
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawRightString(width - 1.4 * cm, 0.9 * cm, "Deckblatt erzeugt durch WLT v3.0 Open")
    canvas.showPage()
    canvas.save()


def render_wlt_marker_plot(image: object) -> io.BytesIO:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    arr = getattr(image, "array", None)
    if arr is None:
        raise RuntimeError("WLT image array fehlt")

    field_point = getattr(image, "field_cax", None) or getattr(image, "cax", None)
    bb_point = getattr(image, "bb", None)
    points = [point for point in (field_point, bb_point) if point is not None]
    if points:
        center_x = statistics.mean([float(point.x) for point in points])
        center_y = statistics.mean([float(point.y) for point in points])
    else:
        center_y = arr.shape[0] / 2
        center_x = arr.shape[1] / 2

    margin = 145
    y0 = max(0, int(center_y - margin))
    y1 = min(arr.shape[0], int(center_y + margin))
    x0 = max(0, int(center_x - margin))
    x1 = min(arr.shape[1], int(center_x + margin))
    crop = arr[y0:y1, x0:x1]
    low, high = np_percentiles(crop, [1, 99.5])

    fig, ax = plt.subplots(figsize=(4.8, 4.8), dpi=160)
    ax.imshow(crop, cmap="gray", vmin=low, vmax=high)
    if field_point is not None:
        ax.plot(float(field_point.x) - x0, float(field_point.y) - y0, marker="+", color="#22c55e", markersize=5.5, markeredgewidth=1.0, linestyle="none", label="Feld")
    if bb_point is not None:
        ax.plot(float(bb_point.x) - x0, float(bb_point.y) - y0, marker="+", color="#ef4444", markersize=5.5, markeredgewidth=1.0, linestyle="none", label="BB")
    gantry = safe_float(metadata_value(image, "GantryAngle"))
    collimator = safe_float(metadata_value(image, "BeamLimitingDeviceAngle"))
    couch = safe_float(metadata_value(image, "PatientSupportAngle"))
    title_parts = []
    if gantry is not None:
        title_parts.append(f"G{gantry:.0f}")
    if collimator is not None:
        title_parts.append(f"C{collimator:.0f}")
    if couch is not None:
        title_parts.append(f"T{couch:.0f}")
    ax.set_title(" ".join(title_parts), fontsize=9)
    ax.set_axis_off()
    if field_point is not None or bb_point is not None:
        ax.legend(loc="lower right", fontsize=6, framealpha=0.55)
    fig.tight_layout(pad=0.1)
    stream = io.BytesIO()
    fig.savefig(stream, format="png")
    plt.close(fig)
    stream.seek(0)
    return stream


def np_percentiles(values: object, percentiles: list[float]) -> tuple[float, float]:
    import numpy as np

    low, high = np.percentile(values, percentiles)
    return float(low), float(high)


def create_uke_summary_pdf(
    summary_pdf: Path,
    wl: object,
    data: dict[str, object],
    folder: Path,
    linac: str,
    timestamp: str,
) -> None:
    summary_pdf.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(str(summary_pdf), pagesize=A4)

    logo = pylinac_logo_path()
    if logo:
        try:
            canvas.drawImage(
                str(logo),
                1 * cm,
                26.5 * cm,
                width=5 * cm,
                height=3 * cm,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception:
            pass
    canvas.setStrokeColor(colors.black)
    canvas.line(1 * cm, 26.5 * cm, 20 * cm, 26.5 * cm)
    draw_text_lines(canvas, ["", "Winston-Lutz-Test Analysis"], 7, 28.5, font_size=24)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(20 * cm, 26.75 * cm, f"pylinac v{pylinac.__version__}")
    canvas.drawString(0.5 * cm, 0.5 * cm, str(summary_pdf).replace("\\", "/"))

    images = list(getattr(wl, "images", []) or [])
    first_image = images[0] if images else None
    avg_sid_values = [safe_float(metadata_value(image, "RTImageSID")) for image in images]
    avg_sid = statistics.mean([value for value in avg_sid_values if value is not None]) if any(value is not None for value in avg_sid_values) else 0.0
    study_date = dicom_date_text(metadata_value(first_image, "StudyDate")) if first_image else "n/a"
    study_time = dicom_time_text(metadata_value(first_image, "StudyTime")) if first_image else "n/a"
    linac_label = uke_linac_label(wl, linac)
    max_bb = safe_float(data.get("max_2d_cax_to_bb_mm"))
    median_bb = safe_float(data.get("median_2d_cax_to_bb_mm"))
    gantry_iso = safe_float(data.get("gantry_3d_iso_diameter_mm")) or 0.0
    coll_iso = safe_float(data.get("coll_2d_iso_diameter_mm"))
    couch_iso = safe_float(data.get("couch_2d_iso_diameter_mm"))
    gantry_coll_iso = safe_float(data.get("gantry_coll_3d_iso_diameter_mm"))
    num_total = int(safe_float(data.get("num_total_images")) or len(images))
    num_gantry_coll = int(safe_float(data.get("num_gantry_coll_images")) or 0)
    vrt_count = unique_float_count([metadata_value(image, "TableTopVerticalPosition") for image in images])
    lng_count = unique_float_count([metadata_value(image, "TableTopLongitudinalPosition") for image in images])
    lat_count = unique_float_count([metadata_value(image, "TableTopLateralPosition") for image in images])

    lines = [
        "Winston-Lutz-Test results:",
        f"Study Date: {study_date} ({study_time})",
        f"Treatment machine: {linac_label}",
        f"Number of images: {num_total}  [ Average SID (mm): {avg_sid:2.0f} ]",
    ]
    value_lines: list[str] = []

    if gantry_iso > 1.5:
        lines.extend([" ", "Comment: Unable to locate the BB. No automated analysis possible."])
    elif vrt_count > 1 and lng_count > 1 and lat_count > 1:
        lines.extend(
            [
                " ",
                "ERROR: The DICOM images in the selected folder have different couch positions.",
                f"gantry.isoSize_{gantry_iso:2.2f}",
                f"TableVRT_{vrt_count}",
                f"TableLng_{lng_count}",
                f"TableLat_{lat_count}",
            ]
        )
    else:
        lines.extend(
            [
                f"Maximum  \\  Median distance to BB (mm): {(max_bb or 0.0):2.2f}  \\  {(median_bb or 0.0):2.2f}",
                f"Gantry 3D isocenter diameter (mm): {gantry_iso:2.2f}",
                "Shift BB to radiation isocenter (cm):",
                "Actual couch position in IEC-61217 (cm):",
                "Recommended couch position (cm):",
            ]
        )
        value_lines = [
            format_shift_cm(wl, data),
            couch_position_text(wl, data, recommended=False),
            couch_position_text(wl, data, recommended=True),
        ]

    if gantry_coll_iso is not None and num_gantry_coll:
        lines.append(f"Gantry+Collimator 3D isocenter diameter (mm): {gantry_coll_iso:.2f} ({num_gantry_coll}/{num_total} images considered)")
    if coll_iso is not None and coll_iso > 0:
        lines.append(f"Collimator 2D isocenter diameter (mm): {coll_iso:2.2f}")
    if couch_iso is not None and couch_iso > 0:
        lines.append(f"Couch 2D isocenter diameter (mm): {couch_iso:2.2f}")

    draw_text_lines(canvas, lines, 4, 25.5, font_size=12)
    if value_lines:
        draw_text_lines(canvas, value_lines, 13.6, 22.45, font_size=12, color="#0000ff")

    plot_locations = [(3, 10.8), (3, 1.8), (11.2, 10.8), (11.2, 1.8)]
    for image, location in zip(select_uke_preview_images(wl), plot_locations):
        plot_stream = io.BytesIO()
        try:
            with quiet_future_warnings():
                plot_stream = render_wlt_marker_plot(image)
            plot_stream.seek(0)
            canvas.drawImage(
                ImageReader(Image.open(plot_stream)),
                location[0] * cm,
                location[1] * cm,
                width=9 * cm,
                height=9 * cm,
                preserveAspectRatio=True,
                mask="auto",
            )
        except Exception as exc:
            canvas.setFillColor(colors.HexColor("#f8fafc"))
            canvas.rect(location[0] * cm, location[1] * cm, 9 * cm, 9 * cm, stroke=1, fill=1)
            canvas.setFillColor(colors.HexColor("#334155"))
            canvas.setFont("Helvetica", 8)
            canvas.drawString((location[0] + 0.4) * cm, (location[1] + 4.5) * cm, f"Plot nicht verfuegbar: {exc}")

    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.HexColor("#64748b"))
    canvas.drawRightString(20 * cm, 0.9 * cm, f"UKE legacy summary ohne Signatur | {APP_TITLE} | {timestamp}")
    canvas.showPage()
    canvas.save()


def merge_pdfs(pdf_paths: list[Path], output_pdf: Path) -> bool:
    try:
        from pypdf import PdfWriter
    except Exception:
        try:
            from PyPDF2 import PdfMerger
        except Exception:
            return False
        merger = PdfMerger()
        for path in pdf_paths:
            merger.append(str(path))
        with output_pdf.open("wb") as handle:
            merger.write(handle)
        merger.close()
        return True

    writer = PdfWriter()
    for path in pdf_paths:
        writer.append(str(path))
    with output_pdf.open("wb") as handle:
        writer.write(handle)
    return True


class OpenWltApp(tk.Tk):
    def __init__(self) -> None:
        configure_windows_app_id()
        super().__init__()
        self.title(f"{APP_TITLE} | pylinac v{pylinac.__version__}")
        self._app_icon_image = None
        self._set_window_icon()
        self.geometry("1480x920")
        self.minsize(1240, 760)
        self.configure(bg=BG)

        self.worker: threading.Thread | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.preview_image_ref = None
        self.multi_preview_paths: list[str] = []
        self.multi_mlc_paths: list[str] = []
        self.multi_preview_index = 0
        self.multi_mlc_index = 0
        self.multi_preview_mode = "image"
        self.multi_graph_path = ""
        self._drain_after_id: str | None = None
        self._busy_animation_after_id: str | None = None
        self._busy_step = 0
        self.gui_settings = load_gui_settings()
        self._path_vars: dict[str, tk.StringVar] = {}
        self._keep_path_vars: dict[str, tk.BooleanVar] = {}
        self._path_display_vars: dict[str, tk.StringVar] = {}
        self._path_entry_widgets: dict[str, ttk.Entry] = {}
        self._path_tail_vars: dict[str, tk.StringVar] = {}

        self.wlt_folder_var = tk.StringVar(value=self._initial_path("wlt_folder", DEFAULT_WLT_DIR))
        self.wlt_output_var = tk.StringVar(value=self._initial_path("wlt_output", OUTPUT_DIR))
        self.wlt_use_analysis_output_var = tk.BooleanVar(value=True)
        self.wlt_write_txt_var = tk.BooleanVar(value=True)
        self.wlt_write_pdf_var = tk.BooleanVar(value=True)
        self.wlt_write_history_var = tk.BooleanVar(value=True)
        self.wlt_notes_var = tk.StringVar(value="WLT v3.0 Open")
        self.wlt_folder_keep_var = tk.BooleanVar(value=self._initial_keep("wlt_folder"))
        self.wlt_output_keep_var = tk.BooleanVar(value=self._initial_keep("wlt_output"))

        self.multi_image_var = tk.StringVar(value=self._initial_path("multi_image", DEFAULT_MULTI_IMAGE_DIR))
        self.multi_plan_var = tk.StringVar(value=self._initial_path("multi_plan", DEFAULT_MULTI_PLAN))
        self.multi_output_var = tk.StringVar(value=self._initial_path("multi_output", OUTPUT_DIR))
        self.multi_use_analysis_output_var = tk.BooleanVar(value=True)
        self.multi_write_history_var = tk.BooleanVar(value=True)
        self.multi_expected_fields_var = tk.StringVar(value="3")
        self.multi_ball_percentile_var = tk.StringVar(value="1.0")
        self.multi_margin_var = tk.StringVar(value="12")
        self.history_filter_var = tk.StringVar(value="Alle")
        self.multi_image_keep_var = tk.BooleanVar(value=self._initial_keep("multi_image"))
        self.multi_plan_keep_var = tk.BooleanVar(value=self._initial_keep("multi_plan"))
        self.multi_output_keep_var = tk.BooleanVar(value=self._initial_keep("multi_output"))

        self._path_vars = {
            "wlt_folder": self.wlt_folder_var,
            "wlt_output": self.wlt_output_var,
            "multi_image": self.multi_image_var,
            "multi_plan": self.multi_plan_var,
            "multi_output": self.multi_output_var,
        }
        self._keep_path_vars = {
            "wlt_folder": self.wlt_folder_keep_var,
            "wlt_output": self.wlt_output_keep_var,
            "multi_image": self.multi_image_keep_var,
            "multi_plan": self.multi_plan_keep_var,
            "multi_output": self.multi_output_keep_var,
        }

        self._configure_style()
        self._build_ui()
        self._load_readme_text()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._schedule_drain()

    def _set_window_icon(self) -> None:
        icon = app_icon_path()
        if not icon:
            return

        try:
            self.iconbitmap(default=str(icon))
        except Exception:
            pass

        try:
            from PIL import Image, ImageTk

            image = Image.open(icon)
            if getattr(image, "n_frames", 1) > 1:
                image.seek(image.n_frames - 1)
            image = image.convert("RGBA")
            if max(image.size) < 256:
                image = image.resize((256, 256), Image.Resampling.LANCZOS)
            self._app_icon_image = ImageTk.PhotoImage(image)
            self.iconphoto(True, self._app_icon_image)
        except Exception:
            pass

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=PANEL_2, font=("Segoe UI", 10))
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(20, 11), borderwidth=0, font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", PANEL_2), ("active", "#162233")], foreground=[("selected", ACCENT), ("active", TEXT)])
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL, borderwidth=1, relief="solid")
        style.configure("AltPanel.TFrame", background=PANEL_2, borderwidth=1, relief="solid")
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("PanelTitle.TLabel", background=PANEL, foreground=ACCENT, font=("Segoe UI", 13, "bold"))
        style.configure("Muted.TLabel", background=BG, foreground=MUTED)
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
        style.configure("TButton", background=ACCENT_2, foreground="#ffffff", padding=(13, 9), borderwidth=0, font=("Segoe UI", 10, "bold"))
        style.map("TButton", background=[("active", "#14b8a6"), ("disabled", "#223042")], foreground=[("disabled", "#65717d")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#06111d")
        style.map("Accent.TButton", background=[("active", "#67e8f9")], foreground=[("active", "#06111d")])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        style.map("TCheckbutton", background=[("active", PANEL)], foreground=[("active", ACCENT)])
        style.configure("TEntry", fieldbackground=PANEL_2, foreground=TEXT, insertcolor=ACCENT, borderwidth=1)
        style.configure("Path.TButton", background=ACCENT_2, foreground="#ffffff", padding=(6, 4), borderwidth=0, font=("Segoe UI", 9, "bold"))
        style.map("Path.TButton", background=[("active", "#14b8a6"), ("disabled", "#223042")], foreground=[("disabled", "#65717d")])
        style.configure("Path.TCheckbutton", background=PANEL, foreground=TEXT, padding=(0, 0), font=("Segoe UI", 9))
        style.map("Path.TCheckbutton", background=[("active", PANEL)], foreground=[("active", ACCENT)])
        style.configure("Path.TEntry", fieldbackground=PANEL_2, foreground=TEXT, insertcolor=ACCENT, borderwidth=1, padding=(2, 1))
        style.configure("InlineSettings.TFrame", background=PANEL, borderwidth=0, relief="flat")
        style.configure("TCombobox", fieldbackground=PANEL_2, background=PANEL_2, foreground=TEXT, arrowcolor=ACCENT)
        style.map("TCombobox", fieldbackground=[("readonly", PANEL_2)], foreground=[("readonly", TEXT)])
        style.configure("Treeview", background=TABLE_BG, fieldbackground=TABLE_BG, foreground=TABLE_TEXT, rowheight=30, borderwidth=0, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background=TABLE_HEAD, foreground=TABLE_TEXT, relief="flat", font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", TABLE_SELECT)], foreground=[("selected", "#ffffff")])
        style.map("Treeview.Heading", background=[("active", "#263449")], foreground=[("active", ACCENT)])
        style.configure("Busy.Horizontal.TProgressbar", troughcolor=PANEL_2, background=ACCENT, bordercolor=PANEL_2, lightcolor=ACCENT, darkcolor=ACCENT)

    def _settings_dict(self, name: str) -> dict[str, object]:
        value = self.gui_settings.get(name, {})
        return value if isinstance(value, dict) else {}

    def _initial_keep(self, key: str) -> bool:
        return bool(self._settings_dict("keep_paths").get(key, False))

    def _initial_path(self, key: str, default: Path) -> str:
        paths = self._settings_dict("paths")
        pinned_paths = self._settings_dict("pinned_paths")
        keep = bool(self._settings_dict("keep_paths").get(key, False))
        value = pinned_paths.get(key, "") if keep else paths.get(key, "")
        if isinstance(value, str) and value.strip():
            return value
        if key.endswith("output"):
            return str(default)
        return path_or_empty(default)

    def _save_gui_settings(self, update_pinned: bool = False) -> None:
        paths = dict(self._settings_dict("paths"))
        pinned_paths = dict(self._settings_dict("pinned_paths"))
        keep_paths: dict[str, bool] = {}

        for key, var in self._path_vars.items():
            value = var.get().strip()
            keep = bool(self._keep_path_vars[key].get())
            keep_paths[key] = keep
            if keep:
                if value and (update_pinned or not pinned_paths.get(key)):
                    pinned_paths[key] = value
            elif value:
                paths[key] = value

        self.gui_settings = {
            "paths": paths,
            "pinned_paths": pinned_paths,
            "keep_paths": keep_paths,
        }
        write_gui_settings(self.gui_settings)

    def _on_keep_path_toggle(self, key: str) -> None:
        self._save_gui_settings(update_pinned=bool(self._keep_path_vars[key].get()))

    def _compact_path_tail(self, value: str, segments: int = 2) -> str:
        text = value.strip().replace("\\", "/").rstrip("/")
        if not text:
            return "-"
        parts = [part for part in text.split("/") if part]
        if not parts:
            return text
        tail = "/".join(parts[-segments:])
        return f".../{tail}" if len(parts) > segments else tail

    def _register_path_entry(self, key: str, var: tk.StringVar, entry: ttk.Entry, tail_var: tk.StringVar) -> None:
        self._path_display_vars[key] = var
        self._path_entry_widgets[key] = entry
        self._path_tail_vars[key] = tail_var
        var.trace_add("write", lambda *_args, key=key: self._refresh_path_display(key))
        self._refresh_path_display(key)

    def _refresh_path_display(self, key: str) -> None:
        var = self._path_display_vars.get(key)
        entry = self._path_entry_widgets.get(key)
        tail_var = self._path_tail_vars.get(key)
        if var is None:
            return
        if tail_var is not None:
            tail_var.set(self._compact_path_tail(var.get()))
        if entry is not None:
            try:
                entry.xview_moveto(1.0)
            except tk.TclError:
                pass

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=BG, padx=30, pady=22)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)
        tk.Label(header, text="WINSTON-LUTZ ANALYSE", bg=BG, fg=ACCENT, font=("Segoe UI", 27, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(
            header,
            text=f"{APP_TITLE} | Open-source source tree | pylinac v{pylinac.__version__}",
            bg=BG,
            fg=MUTED,
            font=("Segoe UI", 10),
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        self.status_var = tk.StringVar(value="Bereit")
        tk.Label(header, textvariable=self.status_var, bg=BG, fg=GOOD, font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="e")
        self.busy_progress = ttk.Progressbar(header, mode="indeterminate", length=190, style="Busy.Horizontal.TProgressbar")
        self.busy_progress.grid(row=1, column=1, sticky="e", pady=(6, 0))
        self.busy_progress.grid_remove()

        separator = tk.Frame(header, bg=ACCENT, height=2)
        separator.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(16, 0))

        notebook = ttk.Notebook(self)
        notebook.grid(row=1, column=0, sticky="nsew", padx=30, pady=(0, 30))
        self.notebook = notebook

        self.wlt_tab = ttk.Frame(notebook)
        self.multi_tab = ttk.Frame(notebook)
        self.history_tab = ttk.Frame(notebook)
        notebook.add(self.wlt_tab, text="Standard WLT")
        notebook.add(self.multi_tab, text="Multi-Ball Off-Iso")
        notebook.add(self.history_tab, text="Verlauf")

        self._build_wlt_tab()
        self._build_multi_tab()
        self._build_history_tab()

    def _build_wlt_tab(self) -> None:
        self.wlt_tab.columnconfigure(1, weight=1)
        self.wlt_tab.rowconfigure(0, weight=1)

        controls = ttk.Frame(self.wlt_tab, style="Panel.TFrame", padding=22)
        controls.grid(row=0, column=0, sticky="nsw", padx=(0, 18))
        controls.columnconfigure(0, weight=1)

        ttk.Label(controls, text="WLT MIT PYLINAC", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            controls,
            text="Nutzt die aktuelle pylinac-WinstonLutz-Klasse und erzeugt optional einen PDF-Report.",
            style="PanelMuted.TLabel",
            wraplength=320,
        ).grid(row=1, column=0, sticky="w", pady=(4, 18))

        self._path_row(controls, 2, "Analyseordner", self.wlt_folder_var, self._choose_wlt_folder, self.wlt_folder_keep_var, "wlt_folder")
        ttk.Checkbutton(
            controls,
            text="Output im Analyseordner speichern",
            variable=self.wlt_use_analysis_output_var,
        ).grid(row=4, column=0, sticky="w", pady=(8, 4))
        self._path_row(controls, 5, "Allgemeiner Output-Ordner (optional)", self.wlt_output_var, self._choose_wlt_output, self.wlt_output_keep_var, "wlt_output")

        ttk.Label(controls, text="Dateien", style="Panel.TLabel").grid(row=7, column=0, sticky="w", pady=(14, 4))
        ttk.Checkbutton(controls, text="TXT-Zusammenfassung schreiben", variable=self.wlt_write_txt_var).grid(row=8, column=0, sticky="w", pady=(0, 3))
        ttk.Checkbutton(controls, text="PDF-Report schreiben", variable=self.wlt_write_pdf_var).grid(row=9, column=0, sticky="w", pady=(0, 3))
        ttk.Checkbutton(controls, text="Messung in Verlauf-CSV schreiben", variable=self.wlt_write_history_var).grid(row=10, column=0, sticky="w", pady=(0, 8))

        ttk.Label(controls, text="Notiz", style="Panel.TLabel").grid(row=11, column=0, sticky="w", pady=(8, 4))
        ttk.Entry(controls, textvariable=self.wlt_notes_var, width=42).grid(row=12, column=0, sticky="ew")
        self.wlt_button = ttk.Button(controls, text="WLT auswerten", style="Accent.TButton", command=self._start_standard_wlt)
        self.wlt_button.grid(row=13, column=0, sticky="ew", pady=(14, 6))
        ttk.Button(controls, text="Output oeffnen", command=self._open_current_wlt_output).grid(row=14, column=0, sticky="ew")

        log_panel = ttk.Frame(self.wlt_tab, style="Panel.TFrame", padding=14)
        log_panel.grid(row=0, column=1, sticky="nsew")
        log_panel.columnconfigure(0, weight=1)
        log_panel.rowconfigure(0, weight=1)
        self.wlt_log = self._text_widget(log_panel)
        self.wlt_log.grid(row=0, column=0, sticky="nsew")
        self._write(self.wlt_log, "Bereit. Ordner waehlen und 'WLT auswerten' starten.\n", "muted")

    def _build_multi_tab(self) -> None:
        self.multi_tab.columnconfigure(1, weight=1)
        self.multi_tab.rowconfigure(0, weight=1)

        controls = ttk.Frame(self.multi_tab, style="Panel.TFrame", padding=22)
        controls.grid(row=0, column=0, sticky="nsw", padx=(0, 18))
        controls.columnconfigure(0, weight=1)

        ttk.Label(controls, text="MULTI-BALL OFF-ISO", style="PanelTitle.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            controls,
            text="Python-Auswertung fuer mehrere Subfelder: Feldzentrum, Kugelzentrum und Abstand je Subfeld.",
            style="PanelMuted.TLabel",
            wraplength=340,
        ).grid(row=1, column=0, sticky="w", pady=(4, 18))

        self._path_row(controls, 2, "RTIMAGE-Ordner", self.multi_image_var, self._choose_multi_image_dir, self.multi_image_keep_var, "multi_image")
        self._file_row(controls, 4, "RTPLAN optional", self.multi_plan_var, self._choose_multi_plan, self.multi_plan_keep_var, "multi_plan")
        ttk.Checkbutton(
            controls,
            text="Output im RTIMAGE-Ordner speichern",
            variable=self.multi_use_analysis_output_var,
        ).grid(row=6, column=0, sticky="w", pady=(8, 4))
        self._path_row(controls, 7, "Allgemeiner Output-Ordner (optional)", self.multi_output_var, self._choose_multi_output, self.multi_output_keep_var, "multi_output")

        settings_frame = ttk.Frame(controls, style="InlineSettings.TFrame")
        settings_frame.grid(row=9, column=0, sticky="w", pady=(14, 4))
        ttk.Label(settings_frame, text="Mets/Bild", style="Panel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Entry(settings_frame, textvariable=self.multi_expected_fields_var, width=7).grid(row=0, column=1, sticky="w")
        ttk.Label(settings_frame, text="Ball-Perzentil", style="Panel.TLabel").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Entry(settings_frame, textvariable=self.multi_ball_percentile_var, width=7).grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Label(settings_frame, text="Feldrand px", style="Panel.TLabel").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(8, 0))
        ttk.Entry(settings_frame, textvariable=self.multi_margin_var, width=7).grid(row=2, column=1, sticky="w", pady=(8, 0))
        ttk.Checkbutton(controls, text="Messung in Verlauf-CSV schreiben", variable=self.multi_write_history_var).grid(row=10, column=0, sticky="w", pady=(8, 0))

        self.multi_button = ttk.Button(controls, text="Multi-Ball auswerten", style="Accent.TButton", command=self._start_multi_ball)
        self.multi_button.grid(row=11, column=0, sticky="ew", pady=(16, 6))
        ttk.Button(controls, text="README im Explorer", command=lambda: self._open_path(PROJECT_DIR / "README.md")).grid(row=12, column=0, sticky="ew")
        ttk.Button(controls, text="Output oeffnen", command=self._open_current_multi_output).grid(row=13, column=0, sticky="ew", pady=(6, 0))

        right = ttk.Frame(self.multi_tab)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=2)
        right.rowconfigure(1, weight=1)

        result_panel = ttk.Frame(right, style="Panel.TFrame", padding=14)
        result_panel.grid(row=0, column=0, sticky="nsew")
        result_panel.columnconfigure(0, weight=2)
        result_panel.columnconfigure(1, weight=3)
        result_panel.rowconfigure(1, weight=1)
        ttk.Label(result_panel, text="ERGEBNIS UND VORSCHAU", style="PanelTitle.TLabel", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        self.multi_log = self._text_widget(result_panel, height=17)
        self.multi_log.grid(row=1, column=0, sticky="nsew", padx=(0, 10))
        preview_frame = ttk.Frame(result_panel, style="Panel.TFrame")
        preview_frame.grid(row=1, column=1, sticky="nsew")
        preview_frame.columnconfigure(0, weight=1)
        preview_frame.rowconfigure(1, weight=1)
        nav_frame = ttk.Frame(preview_frame, style="Panel.TFrame")
        nav_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        nav_frame.columnconfigure(1, weight=1)
        ttk.Button(nav_frame, text="<", width=3, command=self._show_previous_preview).grid(row=0, column=0, sticky="w")
        self.preview_title_var = tk.StringVar(value="Preview")
        ttk.Label(nav_frame, textvariable=self.preview_title_var, style="PanelMuted.TLabel", anchor="center").grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(nav_frame, text=">", width=3, command=self._show_next_preview).grid(row=0, column=2, sticky="e")
        ttk.Button(nav_frame, text="Graph", command=self._show_multi_graph).grid(row=0, column=3, sticky="e", padx=(8, 0))
        ttk.Button(nav_frame, text="MLC", command=self._show_multi_mlc).grid(row=0, column=4, sticky="e", padx=(8, 0))
        self.preview_label = tk.Label(preview_frame, bg=LOG_BG, fg=MUTED, text="Preview erscheint nach der Analyse", highlightbackground=ACCENT_2, highlightthickness=1)
        self.preview_label.grid(row=1, column=0, sticky="nsew")

        readme_panel = ttk.Frame(right, style="Panel.TFrame", padding=14)
        readme_panel.grid(row=1, column=0, sticky="nsew", pady=(14, 0))
        readme_panel.columnconfigure(0, weight=1)
        readme_panel.rowconfigure(1, weight=1)
        ttk.Label(readme_panel, text="ABLAUF / README", style="PanelTitle.TLabel", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.readme_text = self._text_widget(readme_panel, height=9)
        self.readme_text.grid(row=1, column=0, sticky="nsew")

    def _build_history_tab(self) -> None:
        self.history_tab.columnconfigure(0, weight=1)
        self.history_tab.rowconfigure(1, weight=1)

        controls = ttk.Frame(self.history_tab, style="Panel.TFrame", padding=14)
        controls.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        controls.columnconfigure(4, weight=1)
        ttk.Label(controls, text="Linac", style="Panel.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.history_filter_combo = ttk.Combobox(
            controls,
            textvariable=self.history_filter_var,
            values=["Alle"],
            state="readonly",
            width=22,
        )
        self.history_filter_combo.grid(row=0, column=1, sticky="w", padx=(0, 8))
        self.history_filter_combo.bind("<<ComboboxSelected>>", lambda _event: self._refresh_history())
        ttk.Button(controls, text="Aktualisieren", command=self._refresh_history).grid(row=0, column=2, sticky="w", padx=(0, 8))
        ttk.Button(controls, text="CSV oeffnen", command=lambda: self._open_path(HISTORY_CSV)).grid(row=0, column=3, sticky="w")
        self.history_info_var = tk.StringVar(value=f"CSV: {HISTORY_CSV}")
        ttk.Label(controls, textvariable=self.history_info_var, style="PanelMuted.TLabel").grid(row=0, column=4, sticky="e")

        table_frame = ttk.Frame(self.history_tab, style="Panel.TFrame", padding=14)
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        columns = ("timestamp", "workflow", "linac", "image_count", "max_mm", "mean_mm", "median_mm", "gantry_iso_mm", "source")
        self.history_tree = ttk.Treeview(table_frame, columns=columns, show="headings", height=18)
        headings = {
            "timestamp": "Zeitpunkt",
            "workflow": "Workflow",
            "linac": "Linac",
            "image_count": "Bilder",
            "max_mm": "Max [mm]",
            "mean_mm": "Mean [mm]",
            "median_mm": "Median [mm]",
            "gantry_iso_mm": "Gantry-Iso [mm]",
            "source": "Quelle",
        }
        widths = {
            "timestamp": 140,
            "workflow": 110,
            "linac": 90,
            "image_count": 60,
            "max_mm": 80,
            "mean_mm": 80,
            "median_mm": 85,
            "gantry_iso_mm": 100,
            "source": 340,
        }
        for column in columns:
            self.history_tree.heading(column, text=headings[column])
            self.history_tree.column(column, width=widths[column], anchor="w")
        self.history_tree.tag_configure("odd", background=TABLE_BG, foreground=TABLE_TEXT)
        self.history_tree.tag_configure("even", background=TABLE_ALT, foreground=TABLE_TEXT)
        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=y_scroll.set)
        self.history_tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        self._refresh_history()

    def _path_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        var: tk.StringVar,
        command,
        keep_var: tk.BooleanVar | None = None,
        keep_key: str | None = None,
    ) -> None:
        ttk.Label(parent, text=label, style="Panel.TLabel").grid(row=row, column=0, sticky="w", pady=(0, 4))
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=(4, 4, 4, 3))
        frame.grid(row=row + 1, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(0, weight=1)
        frame.columnconfigure(1, weight=0)
        entry = ttk.Entry(frame, textvariable=var, width=12, style="Path.TEntry")
        entry.grid(row=0, column=0, sticky="ew", padx=(0, 6), pady=(0, 3))
        ttk.Button(frame, text="...", width=3, style="Path.TButton", command=command).grid(row=0, column=1, sticky="e", pady=(0, 3))
        tail_var = tk.StringVar(value=self._compact_path_tail(var.get()))
        ttk.Label(frame, textvariable=tail_var, style="PanelMuted.TLabel", anchor="w").grid(row=1, column=0, sticky="ew", padx=(2, 6))
        if keep_var is not None and keep_key is not None:
            ttk.Checkbutton(
                frame,
                text="keep",
                variable=keep_var,
                command=lambda key=keep_key: self._on_keep_path_toggle(key),
                style="Path.TCheckbutton",
            ).grid(row=1, column=1, sticky="e")
        self._register_path_entry(keep_key or f"path_{id(var)}", var, entry, tail_var)

    def _file_row(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        var: tk.StringVar,
        command,
        keep_var: tk.BooleanVar | None = None,
        keep_key: str | None = None,
    ) -> None:
        self._path_row(parent, row, label, var, command, keep_var, keep_key)

    def _text_widget(self, parent: ttk.Frame, height: int = 10) -> scrolledtext.ScrolledText:
        widget = scrolledtext.ScrolledText(
            parent,
            wrap="word",
            height=height,
            bg=LOG_BG,
            fg="#dff9ff",
            insertbackground=ACCENT,
            relief="flat",
            borderwidth=0,
            padx=12,
            pady=10,
            font=("Cascadia Code", 9),
        )
        widget.tag_config("ok", foreground=GOOD)
        widget.tag_config("warn", foreground=WARN)
        widget.tag_config("err", foreground=ERR)
        widget.tag_config("muted", foreground=MUTED)
        return widget

    def _write(self, widget: scrolledtext.ScrolledText, text: str, tag: str = "") -> None:
        widget.insert("end", text, tag)
        widget.see("end")

    def _emit_log(self, event: str, text: str) -> None:
        print(text, end="", flush=True)
        self.events.put((event, text))

    def _wlt_output_dir(self) -> Path:
        return Path(self.wlt_folder_var.get()) if self.wlt_use_analysis_output_var.get() else Path(self.wlt_output_var.get())

    def _multi_output_dir(self) -> Path:
        return Path(self.multi_image_var.get()) if self.multi_use_analysis_output_var.get() else Path(self.multi_output_var.get())

    def _open_current_wlt_output(self) -> None:
        self._open_path(self._wlt_output_dir())

    def _open_current_multi_output(self) -> None:
        self._open_path(self._multi_output_dir())

    def _detect_linac(self, folder: Path) -> str:
        try:
            import pydicom

            for file in sorted(folder.glob("*.dcm")):
                ds = pydicom.dcmread(str(file), stop_before_pixels=True)
                station = str(getattr(ds, "StationName", "") or getattr(ds, "RadiationMachineName", "") or "").strip()
                machine = str(getattr(ds, "RadiationMachineName", "") or "").strip()
                if station:
                    return machine or station
                if machine:
                    return machine
        except Exception:
            pass
        folder_name = folder.name.upper()
        for token in ("L1", "L2", "L3", "L4"):
            if token in folder_name:
                return token
        return "Unbekannt"

    def _refresh_history(self) -> None:
        rows = load_history_rows()
        linacs = ["Alle"] + sorted({row.get("linac", "") for row in rows if row.get("linac", "")})
        self.history_filter_combo.configure(values=linacs)
        if self.history_filter_var.get() not in linacs:
            self.history_filter_var.set("Alle")
        selected = self.history_filter_var.get()
        for item in self.history_tree.get_children():
            self.history_tree.delete(item)
        filtered = [row for row in rows if selected == "Alle" or row.get("linac", "") == selected]
        for index, row in enumerate(reversed(filtered)):
            self.history_tree.insert(
                "",
                "end",
                tags=("even" if index % 2 else "odd",),
                values=(
                    row.get("timestamp", ""),
                    row.get("workflow", ""),
                    row.get("linac", ""),
                    row.get("image_count", ""),
                    row.get("max_mm", ""),
                    row.get("mean_mm", ""),
                    row.get("median_mm", ""),
                    row.get("gantry_iso_mm", ""),
                    row.get("source", ""),
                ),
            )
        self.history_info_var.set(f"{len(filtered)} / {len(rows)} Eintraege | CSV: {HISTORY_CSV}")

    def _record_history(self, row: dict[str, object]) -> None:
        append_history_row(row)
        self.events.put(("history_refresh", None))

    def _show_preview_path(self, path: str, title: str) -> None:
        self._load_preview(path)
        self.preview_title_var.set(title)

    def _show_previous_preview(self) -> None:
        if self.multi_preview_mode == "mlc":
            self._step_multi_mlc(-1)
            return
        if not self.multi_preview_paths:
            return
        self.multi_preview_mode = "image"
        self.multi_preview_index = (self.multi_preview_index - 1) % len(self.multi_preview_paths)
        self._show_preview_path(self.multi_preview_paths[self.multi_preview_index], f"Bild {self.multi_preview_index + 1}/{len(self.multi_preview_paths)}")

    def _show_next_preview(self) -> None:
        if self.multi_preview_mode == "mlc":
            self._step_multi_mlc(1)
            return
        if not self.multi_preview_paths:
            return
        self.multi_preview_mode = "image"
        self.multi_preview_index = (self.multi_preview_index + 1) % len(self.multi_preview_paths)
        self._show_preview_path(self.multi_preview_paths[self.multi_preview_index], f"Bild {self.multi_preview_index + 1}/{len(self.multi_preview_paths)}")

    def _show_multi_graph(self) -> None:
        if self.multi_graph_path:
            self.multi_preview_mode = "graph"
            self._show_preview_path(self.multi_graph_path, "Uebersichtsgraph")

    def _valid_mlc_paths(self) -> list[tuple[int, str]]:
        return [(index, path) for index, path in enumerate(self.multi_mlc_paths) if path]

    def _show_mlc_at_index(self, index: int) -> bool:
        if not self.multi_mlc_paths:
            return False
        count = len(self.multi_mlc_paths)
        for offset in range(count):
            candidate = (index + offset) % count
            path = self.multi_mlc_paths[candidate]
            if path:
                self.multi_mlc_index = candidate
                self.multi_preview_mode = "mlc"
                self._show_preview_path(path, f"MLC-Muster {candidate + 1}/{count}")
                return True
        return False

    def _step_multi_mlc(self, step: int) -> None:
        valid = self._valid_mlc_paths()
        if not valid:
            self.preview_label.configure(image="", text="Kein MLC-Muster verfuegbar.\nBitte RTPLAN laden und Analyse starten.")
            self.preview_title_var.set("MLC-Muster")
            return
        current_pos = 0
        for pos, (image_index, _path) in enumerate(valid):
            if image_index == self.multi_mlc_index:
                current_pos = pos
                break
        image_index, path = valid[(current_pos + step) % len(valid)]
        self.multi_mlc_index = image_index
        self.multi_preview_mode = "mlc"
        self._show_preview_path(path, f"MLC-Muster {image_index + 1}/{len(self.multi_mlc_paths)}")

    def _show_multi_mlc(self) -> None:
        if not self._show_mlc_at_index(self.multi_preview_index):
            self.preview_label.configure(image="", text="Kein MLC-Muster verfuegbar.\nBitte RTPLAN laden und Analyse starten.")
            self.preview_title_var.set("MLC-Muster")

    def _animate_busy(self) -> None:
        frames = ("Analyse laeuft |", "Analyse laeuft /", "Analyse laeuft -", "Analyse laeuft \\")
        self.status_var.set(frames[self._busy_step % len(frames)])
        self._busy_step += 1
        self._busy_animation_after_id = self.after(140, self._animate_busy)

    def _start_busy_animation(self) -> None:
        self._busy_step = 0
        self.busy_progress.grid()
        self.busy_progress.start(14)
        if self._busy_animation_after_id:
            self.after_cancel(self._busy_animation_after_id)
        self._animate_busy()

    def _stop_busy_animation(self) -> None:
        if self._busy_animation_after_id:
            try:
                self.after_cancel(self._busy_animation_after_id)
            except tk.TclError:
                pass
            self._busy_animation_after_id = None
        self.busy_progress.stop()
        self.busy_progress.grid_remove()

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.wlt_button.configure(state=state)
        self.multi_button.configure(state=state)
        if busy:
            self._start_busy_animation()
        else:
            self._stop_busy_animation()
            self.status_var.set("Bereit")

    def _choose_wlt_folder(self) -> None:
        self._choose_dir(self.wlt_folder_var, "wlt_folder")

    def _choose_wlt_output(self) -> None:
        self._choose_dir(self.wlt_output_var, "wlt_output")

    def _choose_multi_image_dir(self) -> None:
        self._choose_dir(self.multi_image_var, "multi_image")

    def _choose_multi_output(self) -> None:
        self._choose_dir(self.multi_output_var, "multi_output")

    def _choose_multi_plan(self) -> None:
        filename = filedialog.askopenfilename(parent=self, title="RTPLAN DICOM waehlen", filetypes=[("DICOM", "*.dcm"), ("Alle Dateien", "*.*")])
        if filename:
            self.multi_plan_var.set(filename)
            self._save_gui_settings(update_pinned=bool(self.multi_plan_keep_var.get()))

    def _choose_dir(self, var: tk.StringVar, keep_key: str) -> None:
        initial = var.get() if Path(var.get()).exists() else str(WORKSPACE_DIR)
        selected = filedialog.askdirectory(parent=self, initialdir=initial)
        if selected:
            var.set(selected)
            self._save_gui_settings(update_pinned=bool(self._keep_path_vars[keep_key].get()))

    def _open_path(self, path: str | Path) -> None:
        path = Path(path)
        if path.exists():
            if os.name == "nt":
                os.startfile(str(path))
            else:
                webbrowser.open(path.as_uri())

    def _start_thread(self, target, args=()) -> None:
        if self.worker and self.worker.is_alive():
            return
        self._set_busy(True)
        self.worker = threading.Thread(target=target, args=args, daemon=True)
        self.worker.start()

    def _schedule_drain(self) -> None:
        self._drain_after_id = self.after(120, self._drain_events)

    def _close(self) -> None:
        self._save_gui_settings(update_pinned=False)
        if self._busy_animation_after_id:
            try:
                self.after_cancel(self._busy_animation_after_id)
            except tk.TclError:
                pass
            self._busy_animation_after_id = None
        if self._drain_after_id:
            try:
                self.after_cancel(self._drain_after_id)
            except tk.TclError:
                pass
            self._drain_after_id = None
        self.destroy()

    def _start_standard_wlt(self) -> None:
        folder = Path(self.wlt_folder_var.get())
        output = self._wlt_output_dir()
        if not folder.exists():
            messagebox.showerror("Ordner fehlt", f"Analyseordner nicht gefunden:\n{folder}")
            return
        if not self.wlt_write_txt_var.get() and not self.wlt_write_pdf_var.get():
            messagebox.showerror("Output", "Bitte mindestens TXT oder PDF aktivieren.")
            return
        self._save_gui_settings(update_pinned=False)
        self.wlt_log.delete("1.0", "end")
        self._start_thread(
            self._standard_wlt_worker,
            (
                folder,
                output,
                self.wlt_use_analysis_output_var.get(),
                self.wlt_folder_keep_var.get(),
                self.wlt_output_keep_var.get(),
                self.wlt_write_txt_var.get(),
                self.wlt_write_pdf_var.get(),
                self.wlt_write_history_var.get(),
                self.wlt_notes_var.get(),
            ),
        )

    def _standard_wlt_worker(
        self,
        folder: Path,
        output: Path,
        output_in_analysis: bool,
        folder_keep: bool,
        output_keep: bool,
        make_txt: bool,
        make_pdf: bool,
        write_history: bool,
        notes: str,
    ) -> None:
        try:
            output.mkdir(parents=True, exist_ok=True)
            timestamp = time.strftime("%Y%m%d-%H%M%S")
            linac = self._detect_linac(folder)
            log = lambda text: self._emit_log("wlt_log", text)
            log("Standard-WLT Settings\n")
            log(f"  Settings-Datei: {GUI_SETTINGS_JSON}\n")
            log(f"  Analyseordner: {folder}\n")
            log(f"  Analyseordner keep: {folder_keep}\n")
            log(f"  Output-Ordner: {output}\n")
            log(f"  Output-Ordner keep: {output_keep}\n")
            log(f"  Output im Analyseordner: {output_in_analysis}\n")
            log(f"  TXT: {make_txt}\n")
            log(f"  PDF: {make_pdf}\n")
            log(f"  Verlauf CSV: {write_history} -> {HISTORY_CSV}\n")
            log(f"  Linac: {linac}\n")
            log(f"  Notiz: {notes}\n\n")
            with quiet_future_warnings():
                wl = WinstonLutz(str(folder))
                wl.analyze()
                result_text = wl.results()
                data = wl.results_data(as_dict=True)
            summary_path = ""
            if make_txt:
                txt_file = output / f"wlt_results_{timestamp}.txt"
                txt_file.write_text(result_text + "\n", encoding="utf-8")
                if not txt_file.exists() or txt_file.stat().st_size == 0:
                    raise RuntimeError(f"TXT wurde nicht geschrieben: {txt_file}")
                summary_path = str(txt_file)
            pdf_path = ""
            if make_pdf:
                pdf_file = output / f"wlt_report_{timestamp}.pdf"
                cover_file = output / f"wlt_report_cover_{timestamp}.pdf"
                uke_file = output / f"wlt_report_uke_{timestamp}.pdf"
                pylinac_file = output / f"wlt_report_pylinac_{timestamp}.pdf"
                with quiet_future_warnings():
                    wl.publish_pdf(
                        str(pylinac_file),
                        notes=[notes, f"pylinac v{pylinac.__version__}", APP_TITLE],
                        metadata={"App": APP_TITLE, "pylinac": pylinac.__version__},
                    )
                if not pylinac_file.exists() or pylinac_file.stat().st_size == 0:
                    raise RuntimeError(f"PDF wurde nicht geschrieben: {pylinac_file}")
                try:
                    create_wlt_cover_pdf(cover_file, data, folder, output, linac, timestamp, notes)
                    create_uke_summary_pdf(uke_file, wl, data, folder, linac, timestamp)
                    if merge_pdfs([cover_file, uke_file, pylinac_file], pdf_file):
                        if not pdf_file.exists() or pdf_file.stat().st_size == 0:
                            raise RuntimeError(f"PDF wurde nicht geschrieben: {pdf_file}")
                        cover_file.unlink(missing_ok=True)
                        uke_file.unlink(missing_ok=True)
                        pylinac_file.unlink(missing_ok=True)
                        pdf_path = str(pdf_file)
                        log(f"  PDF-Report: {pdf_file} (Deckblatt + UKE-Seite ohne Signatur + pylinac)\n")
                    else:
                        pdf_path = str(pylinac_file)
                        log(f"  PDF-Report: {pylinac_file} (pylinac)\n")
                        log(f"  PDF-Deckblatt separat: {cover_file} (pypdf/PyPDF2 nicht installiert)\n")
                        log(f"  PDF-UKE-Seite separat: {uke_file} (pypdf/PyPDF2 nicht installiert)\n")
                except Exception as pdf_style_exc:
                    pdf_path = str(pylinac_file)
                    log(f"  PDF-Deckblatt/UKE-Seite konnte nicht erstellt/gemerged werden: {pdf_style_exc}\n")
                    log(f"  PDF-Report: {pylinac_file} (pylinac)\n")
            if write_history:
                self._record_history(
                    {
                        "timestamp": timestamp,
                        "workflow": "Standard WLT",
                        "linac": linac,
                        "source": str(folder),
                        "image_count": data.get("num_total_images", ""),
                        "max_mm": f"{float(data.get('max_2d_cax_to_bb_mm', 0.0)):.4f}",
                        "mean_mm": f"{float(data.get('mean_2d_cax_to_bb_mm', 0.0)):.4f}",
                        "median_mm": f"{float(data.get('median_2d_cax_to_bb_mm', 0.0)):.4f}",
                        "gantry_iso_mm": f"{float(data.get('gantry_3d_iso_diameter_mm', 0.0)):.4f}",
                        "pdf": pdf_path,
                        "txt": summary_path,
                        "notes": notes,
                    }
                )
            self.events.put(("wlt_done", (result_text, summary_path, pdf_path, str(output))))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _start_multi_ball(self) -> None:
        image_dir = Path(self.multi_image_var.get())
        plan = Path(self.multi_plan_var.get()) if self.multi_plan_var.get().strip() else None
        output = self._multi_output_dir()
        if not image_dir.exists():
            messagebox.showerror("Ordner fehlt", f"RTIMAGE-Ordner nicht gefunden:\n{image_dir}")
            return
        if plan is not None and not plan.exists():
            messagebox.showerror("Plan fehlt", f"RTPLAN nicht gefunden:\n{plan}")
            return
        try:
            expected_fields = parse_expected_fields(self.multi_expected_fields_var.get())
            percentile = float(self.multi_ball_percentile_var.get().replace(",", "."))
            margin = int(float(self.multi_margin_var.get().replace(",", ".")))
        except ValueError:
            messagebox.showerror("Settings", "Mets/Bild muss eine Zahl oder 'auto' sein; Ball-Perzentil und Feldrand muessen Zahlen sein.")
            return
        self._save_gui_settings(update_pinned=False)
        self.multi_log.delete("1.0", "end")
        self._start_thread(
            self._multi_ball_worker,
            (
                image_dir,
                plan,
                output,
                self.multi_use_analysis_output_var.get(),
                self.multi_image_keep_var.get(),
                self.multi_plan_keep_var.get(),
                self.multi_output_keep_var.get(),
                expected_fields,
                percentile,
                margin,
                self.multi_write_history_var.get(),
            ),
        )

    def _multi_ball_worker(
        self,
        image_dir: Path,
        plan: Path | None,
        output: Path,
        output_in_analysis: bool,
        image_keep: bool,
        plan_keep: bool,
        output_keep: bool,
        expected_fields: int,
        percentile: float,
        margin: int,
        write_history: bool,
    ) -> None:
        try:
            output.mkdir(parents=True, exist_ok=True)
            field_mode = "auto" if expected_fields <= 0 else str(expected_fields)
            linac = self._detect_linac(image_dir)
            log = lambda text: self._emit_log("multi_log", text)
            log("Multi-Ball Settings\n")
            log(f"  Settings-Datei: {GUI_SETTINGS_JSON}\n")
            log(f"  RTIMAGE-Ordner: {image_dir}\n")
            log(f"  RTIMAGE-Ordner keep: {image_keep}\n")
            log(f"  RTPLAN: {plan or 'nicht geladen'}\n")
            log(f"  RTPLAN keep: {plan_keep}\n")
            log(f"  Output-Ordner: {output}\n")
            log(f"  Output-Ordner keep: {output_keep}\n")
            log(f"  Output im RTIMAGE-Ordner: {output_in_analysis}\n")
            log(f"  Mets/Bild: {field_mode}\n")
            log(f"  Ball-Perzentil: {percentile}\n")
            log(f"  Feldrand px: {margin}\n")
            log(f"  Verlauf CSV: {write_history} -> {HISTORY_CSV}\n")
            log(f"  Linac: {linac}\n\n")
            settings = MultiBallSettings(expected_fields=expected_fields, ball_dark_percentile=percentile, field_margin_px=margin)
            summary = analyze_folder(image_dir, plan, output, settings)
            if write_history:
                distances = [field.distance_iso_mm for image in summary.results for field in image.fields]
                self._record_history(
                    {
                        "timestamp": summary.generated_at,
                        "workflow": "Multi-Ball",
                        "linac": linac,
                        "source": str(image_dir),
                        "image_count": summary.image_count,
                        "max_mm": f"{summary.overall_max_distance_iso_mm:.4f}",
                        "mean_mm": f"{summary.overall_mean_distance_iso_mm:.4f}",
                        "median_mm": f"{statistics.median(distances):.4f}" if distances else "",
                        "csv": summary.output_csv,
                        "graph": summary.summary_png,
                        "notes": f"plan={plan or ''}; fields={field_mode}",
                    }
                )
            self.events.put(("multi_done", summary))
        except Exception as exc:
            self.events.put(("error", str(exc)))

    def _load_preview(self, path: str) -> None:
        try:
            from PIL import ImageTk

            image = Image.open(path)
            image.thumbnail((780, 650))
            photo = ImageTk.PhotoImage(image)
            self.preview_image_ref = photo
            self.preview_label.configure(image=photo, text="")
        except Exception as exc:
            self.preview_label.configure(image="", text=f"Preview konnte nicht geladen werden:\n{exc}")

    def _load_readme_text(self) -> None:
        readme = PROJECT_DIR / "README.md"
        if readme.exists():
            text = readme.read_text(encoding="utf-8")
        else:
            text = "README.md ist noch nicht geschrieben."
        self.readme_text.delete("1.0", "end")
        self.readme_text.insert("end", text)
        self.readme_text.configure(state="disabled")

    def _drain_events(self) -> None:
        self._drain_after_id = None
        try:
            while True:
                event, payload = self.events.get_nowait()
                if event == "wlt_log":
                    self._write(self.wlt_log, str(payload), "muted")
                elif event == "multi_log":
                    self._write(self.multi_log, str(payload), "muted")
                elif event == "wlt_done":
                    result_text, summary_path, pdf_path, output_path = payload
                    self._write(self.wlt_log, result_text + "\n\n", "ok")
                    self._write(self.wlt_log, f"Output: {output_path}\n", "muted")
                    self._write(self.wlt_log, f"TXT: {summary_path or 'deaktiviert'}\n", "muted")
                    self._write(self.wlt_log, f"PDF: {pdf_path or 'deaktiviert'}\n", "muted")
                    self._refresh_history()
                    self._set_busy(False)
                    if pdf_path:
                        self._open_path(pdf_path)
                elif event == "multi_done":
                    summary = payload
                    self._write(self.multi_log, format_summary(summary) + "\n", "ok")
                    self.multi_preview_paths = list(summary.preview_pngs)
                    self.multi_mlc_paths = list(getattr(summary, "mlc_pngs", []))
                    self.multi_preview_index = 0
                    self.multi_mlc_index = 0
                    self.multi_graph_path = summary.summary_png
                    if summary.summary_png:
                        self._show_multi_graph()
                    elif summary.preview_png:
                        self._show_preview_path(summary.preview_png, "Bild 1/1")
                    self._refresh_history()
                    self._set_busy(False)
                elif event == "history_refresh":
                    self._refresh_history()
                elif event == "error":
                    self._write(self.wlt_log, f"Fehler: {payload}\n", "err")
                    self._write(self.multi_log, f"Fehler: {payload}\n", "err")
                    self._set_busy(False)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self._schedule_drain()


def main() -> int:
    app = OpenWltApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
