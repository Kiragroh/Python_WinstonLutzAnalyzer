from __future__ import annotations

import argparse
import csv
import json
import math
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable

import numpy as np
import pydicom
from scipy import ndimage as ndi
from skimage import filters, measure, morphology


SOURCE_TO_ISO_MM = 1000.0
warnings.filterwarnings("ignore", category=FutureWarning)


@dataclass
class MultiBallSettings:
    expected_fields: int = 3
    median_size_px: int = 10
    field_min_area_px: int = 1000
    field_margin_px: int = 12
    ball_dark_percentile: float = 1.0
    ball_min_area_px: int = 8
    plan_match_tolerance_deg: float = 5.0


@dataclass
class PlanBeam:
    number: int
    name: str
    gantry_deg: float
    collimator_deg: float
    couch_deg: float
    jaw_x_mm: list[float] = field(default_factory=list)
    jaw_y_mm: list[float] = field(default_factory=list)
    mlc_type: str = ""
    mlc_leaf_boundaries_mm: list[float] = field(default_factory=list)
    mlc_leaf_positions_mm: list[float] = field(default_factory=list)


@dataclass
class FieldResult:
    field_index: int
    field_row_px: float
    field_col_px: float
    ball_row_px: float
    ball_col_px: float
    dx_px: float
    dy_px: float
    dx_iso_mm: float
    dy_iso_mm: float
    distance_iso_mm: float
    field_area_px: int
    ball_area_px: int


@dataclass
class ImageResult:
    file: str
    beam_name: str
    plan_beam_number: int
    gantry_deg: float
    collimator_deg: float
    couch_deg: float
    plan_gantry_deg: float
    plan_collimator_deg: float
    plan_couch_deg: float
    plan_match_score_deg: float
    plan_match_warning: str
    sid_mm: float
    row_spacing_mm: float
    col_spacing_mm: float
    max_distance_iso_mm: float
    mean_distance_iso_mm: float
    fields: list[FieldResult]
    preview_png: str = ""
    mlc_png: str = ""


@dataclass
class AnalysisSummary:
    generated_at: str
    image_count: int
    overall_max_distance_iso_mm: float
    overall_mean_distance_iso_mm: float
    output_csv: str
    output_json: str
    preview_png: str
    preview_pngs: list[str]
    mlc_pngs: list[str]
    summary_png: str
    results: list[ImageResult]


def normalize_angle(value: float) -> float:
    return float(value) % 360.0


def angle_delta(a: float, b: float) -> float:
    diff = abs(normalize_angle(a) - normalize_angle(b)) % 360.0
    return min(diff, 360.0 - diff)


def float_list(values: Iterable[object] | None) -> list[float]:
    if values is None:
        return []
    parsed: list[float] = []
    for value in values:
        try:
            parsed.append(float(value))
        except Exception:
            continue
    return parsed


def beam_device_boundaries(beam: pydicom.dataset.Dataset, device_type: str) -> list[float]:
    for device in getattr(beam, "BeamLimitingDeviceSequence", []):
        if str(getattr(device, "RTBeamLimitingDeviceType", "")).upper() == device_type.upper():
            return float_list(getattr(device, "LeafPositionBoundaries", None))
    return []


def control_point_device_positions(cp: pydicom.dataset.Dataset, device_type: str) -> list[float]:
    for device in getattr(cp, "BeamLimitingDevicePositionSequence", []):
        if str(getattr(device, "RTBeamLimitingDeviceType", "")).upper() == device_type.upper():
            return float_list(getattr(device, "LeafJawPositions", None))
    return []


def first_device_type(cp: pydicom.dataset.Dataset, prefix: str, exclude_prefix: str = "") -> str:
    for device in getattr(cp, "BeamLimitingDevicePositionSequence", []):
        device_type = str(getattr(device, "RTBeamLimitingDeviceType", "")).upper()
        if device_type.startswith(prefix.upper()) and (not exclude_prefix or not device_type.startswith(exclude_prefix.upper())):
            return device_type
    return ""


def load_plan(plan_file: str | Path | None) -> list[PlanBeam]:
    if not plan_file:
        return []
    path = Path(plan_file)
    if not path.exists():
        raise FileNotFoundError(f"RTPLAN not found: {path}")

    ds = pydicom.dcmread(str(path), stop_before_pixels=True)
    beams: list[PlanBeam] = []
    for beam in getattr(ds, "BeamSequence", []):
        if not getattr(beam, "ControlPointSequence", None):
            continue
        cp = beam.ControlPointSequence[0]
        mlc_type = first_device_type(cp, "MLC")
        jaw_x_type = first_device_type(cp, "ASYMX") or first_device_type(cp, "X", exclude_prefix="MLC")
        jaw_y_type = first_device_type(cp, "ASYMY") or first_device_type(cp, "Y", exclude_prefix="MLC")
        beams.append(
            PlanBeam(
                number=int(getattr(beam, "BeamNumber", len(beams) + 1)),
                name=str(getattr(beam, "BeamName", f"Beam {len(beams) + 1}")),
                gantry_deg=normalize_angle(float(getattr(cp, "GantryAngle", 0.0))),
                collimator_deg=normalize_angle(float(getattr(cp, "BeamLimitingDeviceAngle", 0.0))),
                couch_deg=normalize_angle(float(getattr(cp, "PatientSupportAngle", 0.0))),
                jaw_x_mm=control_point_device_positions(cp, jaw_x_type),
                jaw_y_mm=control_point_device_positions(cp, jaw_y_type),
                mlc_type=mlc_type,
                mlc_leaf_boundaries_mm=beam_device_boundaries(beam, mlc_type),
                mlc_leaf_positions_mm=control_point_device_positions(cp, mlc_type),
            )
        )
    return beams


def match_plan_beam_details(ds: pydicom.dataset.Dataset, beams: list[PlanBeam], tolerance_deg: float) -> tuple[str, float, str, PlanBeam | None]:
    if not beams:
        return "", 0.0, "no RTPLAN loaded", None
    gantry = normalize_angle(float(getattr(ds, "GantryAngle", 0.0)))
    collimator = normalize_angle(float(getattr(ds, "BeamLimitingDeviceAngle", 0.0)))
    couch = normalize_angle(float(getattr(ds, "PatientSupportAngle", 0.0)))

    scored = []
    for beam in beams:
        score = (
            angle_delta(gantry, beam.gantry_deg)
            + angle_delta(collimator, beam.collimator_deg)
            + angle_delta(couch, beam.couch_deg)
        )
        scored.append((score, beam))
    score, beam = min(scored, key=lambda item: item[0])
    if score <= tolerance_deg * 3:
        return beam.name, float(score), "", beam
    return f"nearest: {beam.name}", float(score), f"angle sum {score:.1f} deg outside tolerance", beam


def match_plan_beam(ds: pydicom.dataset.Dataset, beams: list[PlanBeam], tolerance_deg: float) -> str:
    return match_plan_beam_details(ds, beams, tolerance_deg)[0]


def image_pixel_spacing(ds: pydicom.dataset.Dataset) -> tuple[float, float]:
    spacing = getattr(ds, "ImagePlanePixelSpacing", None) or getattr(ds, "PixelSpacing", None)
    if spacing is None:
        return 1.0, 1.0
    return float(spacing[0]), float(spacing[1])


def get_image_array(ds: pydicom.dataset.Dataset) -> np.ndarray:
    arr = ds.pixel_array.astype(np.float64)
    slope = float(getattr(ds, "RescaleSlope", 1.0))
    intercept = float(getattr(ds, "RescaleIntercept", 0.0))
    return arr * slope + intercept


def largest_regions(mask: np.ndarray, count: int, min_area: int) -> list[measure._regionprops.RegionProperties]:
    cleaned = morphology.remove_small_objects(mask.astype(bool), min_size=min_area)
    labeled = measure.label(cleaned)
    regions = sorted(measure.regionprops(labeled), key=lambda region: region.area, reverse=True)
    if count <= 0:
        return regions
    return regions[:count]


def detect_field_and_ball_results(
    arr: np.ndarray,
    ds: pydicom.dataset.Dataset,
    settings: MultiBallSettings,
) -> tuple[list[FieldResult], np.ndarray, np.ndarray]:
    smoothed = ndi.median_filter(arr, size=max(1, int(settings.median_size_px)))
    threshold = filters.threshold_otsu(smoothed)
    field_regions = largest_regions(
        smoothed > threshold,
        settings.expected_fields,
        settings.field_min_area_px,
    )
    if settings.expected_fields > 0 and len(field_regions) != settings.expected_fields:
        raise RuntimeError(
            f"Expected {settings.expected_fields} fields, detected {len(field_regions)}. "
            "Try a different image or adjust field_min_area_px."
        )
    if settings.expected_fields <= 0 and not field_regions:
        raise RuntimeError("Auto field detection did not find any fields. Try a lower field_min_area_px.")

    labeled_fields = measure.label(morphology.remove_small_objects(smoothed > threshold, min_size=settings.field_min_area_px))
    footprint = morphology.disk(max(1, int(settings.field_margin_px)))
    row_spacing, col_spacing = image_pixel_spacing(ds)
    sid = float(getattr(ds, "RTImageSID", SOURCE_TO_ISO_MM))
    scale = SOURCE_TO_ISO_MM / sid if sid else 1.0

    field_results: list[FieldResult] = []
    ball_mask_all = np.zeros(arr.shape, dtype=bool)

    for field_index, field in enumerate(sorted(field_regions, key=lambda region: region.centroid[1]), start=1):
        field_mask = labeled_fields == field.label
        inside_field = morphology.erosion(field_mask, footprint)
        if not np.any(inside_field):
            inside_field = field_mask

        inside_values = arr[inside_field]
        ball_threshold = np.percentile(inside_values, settings.ball_dark_percentile)
        ball_mask = inside_field & (arr <= ball_threshold)
        ball_mask = morphology.remove_small_objects(ball_mask, min_size=settings.ball_min_area_px)
        ball_regions = sorted(measure.regionprops(measure.label(ball_mask)), key=lambda region: region.area, reverse=True)
        if not ball_regions:
            raise RuntimeError(f"No ball detected in field {field_index}.")

        ball = ball_regions[0]
        ball_mask_all |= measure.label(ball_mask) == ball.label

        field_row, field_col = field.centroid
        ball_row, ball_col = ball.centroid
        dx_px = ball_col - field_col
        dy_px = ball_row - field_row
        dx_iso_mm = dx_px * col_spacing * scale
        dy_iso_mm = dy_px * row_spacing * scale
        distance_iso_mm = math.hypot(dx_iso_mm, dy_iso_mm)

        field_results.append(
            FieldResult(
                field_index=field_index,
                field_row_px=float(field_row),
                field_col_px=float(field_col),
                ball_row_px=float(ball_row),
                ball_col_px=float(ball_col),
                dx_px=float(dx_px),
                dy_px=float(dy_px),
                dx_iso_mm=float(dx_iso_mm),
                dy_iso_mm=float(dy_iso_mm),
                distance_iso_mm=float(distance_iso_mm),
                field_area_px=int(field.area),
                ball_area_px=int(ball.area),
            )
        )

    return field_results, labeled_fields > 0, ball_mask_all


def analyze_rt_image(
    image_file: str | Path,
    beams: list[PlanBeam],
    settings: MultiBallSettings,
) -> tuple[ImageResult, np.ndarray, np.ndarray, np.ndarray]:
    path = Path(image_file)
    ds = pydicom.dcmread(str(path))
    if str(getattr(ds, "Modality", "")).upper() != "RTIMAGE":
        raise RuntimeError(f"Not an RTIMAGE DICOM: {path.name}")

    arr = get_image_array(ds)
    fields, field_mask, ball_mask = detect_field_and_ball_results(arr, ds, settings)
    distances = [field.distance_iso_mm for field in fields]
    row_spacing, col_spacing = image_pixel_spacing(ds)
    beam_name, match_score, match_warning, plan_beam = match_plan_beam_details(ds, beams, settings.plan_match_tolerance_deg)

    result = ImageResult(
        file=path.name,
        beam_name=beam_name,
        plan_beam_number=plan_beam.number if plan_beam else 0,
        gantry_deg=normalize_angle(float(getattr(ds, "GantryAngle", 0.0))),
        collimator_deg=normalize_angle(float(getattr(ds, "BeamLimitingDeviceAngle", 0.0))),
        couch_deg=normalize_angle(float(getattr(ds, "PatientSupportAngle", 0.0))),
        plan_gantry_deg=plan_beam.gantry_deg if plan_beam else 0.0,
        plan_collimator_deg=plan_beam.collimator_deg if plan_beam else 0.0,
        plan_couch_deg=plan_beam.couch_deg if plan_beam else 0.0,
        plan_match_score_deg=match_score,
        plan_match_warning=match_warning,
        sid_mm=float(getattr(ds, "RTImageSID", SOURCE_TO_ISO_MM)),
        row_spacing_mm=row_spacing,
        col_spacing_mm=col_spacing,
        max_distance_iso_mm=float(max(distances)),
        mean_distance_iso_mm=float(np.mean(distances)),
        fields=fields,
    )
    return result, arr, field_mask, ball_mask


def find_rt_image_files(image_dir: str | Path) -> list[Path]:
    directory = Path(image_dir)
    files: list[Path] = []
    for file in sorted(directory.glob("*.dcm")):
        try:
            ds = pydicom.dcmread(str(file), stop_before_pixels=True)
        except Exception:
            continue
        if str(getattr(ds, "Modality", "")).upper() == "RTIMAGE":
            files.append(file)
    return files


def write_csv(summary: AnalysisSummary, csv_path: str | Path) -> None:
    rows: list[dict[str, object]] = []
    for image in summary.results:
        for field in image.fields:
            rows.append(
                {
                    "file": image.file,
                    "beam_name": image.beam_name,
                    "plan_beam_number": image.plan_beam_number,
                    "gantry_deg": f"{image.gantry_deg:.3f}",
                    "collimator_deg": f"{image.collimator_deg:.3f}",
                    "couch_deg": f"{image.couch_deg:.3f}",
                    "plan_gantry_deg": f"{image.plan_gantry_deg:.3f}",
                    "plan_collimator_deg": f"{image.plan_collimator_deg:.3f}",
                    "plan_couch_deg": f"{image.plan_couch_deg:.3f}",
                    "plan_match_score_deg": f"{image.plan_match_score_deg:.3f}",
                    "plan_match_warning": image.plan_match_warning,
                    "field_index": field.field_index,
                    "dx_iso_mm": f"{field.dx_iso_mm:.4f}",
                    "dy_iso_mm": f"{field.dy_iso_mm:.4f}",
                    "distance_iso_mm": f"{field.distance_iso_mm:.4f}",
                    "field_area_px": field.field_area_px,
                    "ball_area_px": field.ball_area_px,
                    "mlc_png": image.mlc_png,
                }
            )
    with Path(csv_path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)


def write_json(summary: AnalysisSummary, json_path: str | Path) -> None:
    Path(json_path).write_text(json.dumps(asdict(summary), indent=2), encoding="utf-8")


def render_preview(
    arr: np.ndarray,
    result: ImageResult,
    field_mask: np.ndarray,
    ball_mask: np.ndarray,
    output_png: str | Path,
) -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    low, high = np.percentile(arr, [1, 99.5])
    fig, ax = plt.subplots(figsize=(8, 8), dpi=140)
    ax.imshow(arr, cmap="gray", vmin=low, vmax=high)
    ax.contour(field_mask, levels=[0.5], colors=["lime"], linewidths=1.1)
    ax.contour(ball_mask, levels=[0.5], colors=["red"], linewidths=1.4)

    for field in result.fields:
        ax.plot(field.field_col_px, field.field_row_px, marker="+", color="#22c55e", markersize=6, markeredgewidth=1.1, linestyle="none")
        ax.plot(field.ball_col_px, field.ball_row_px, marker="+", color="#ef4444", markersize=6, markeredgewidth=1.1, linestyle="none")
        ax.text(
            field.field_col_px + 8,
            field.field_row_px - 8,
            f"{field.field_index}: {field.distance_iso_mm:.2f} mm",
            color="yellow",
            fontsize=7,
            bbox={"facecolor": "black", "alpha": 0.45, "pad": 2, "edgecolor": "none"},
        )
    title = result.beam_name or f"G{result.gantry_deg:.0f} C{result.collimator_deg:.0f} T{result.couch_deg:.0f}"
    ax.set_title(title)
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(output_png)
    plt.close(fig)


def render_summary_graph(summary: AnalysisSummary, output_png: str | Path) -> None:
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    labels = [
        image.beam_name or f"G{image.gantry_deg:.0f} C{image.collimator_deg:.0f} T{image.couch_deg:.0f}"
        for image in summary.results
    ]
    max_values = [image.max_distance_iso_mm for image in summary.results]
    mean_values = [image.mean_distance_iso_mm for image in summary.results]
    x = np.arange(len(labels))

    fig, ax = plt.subplots(figsize=(11, 5.6), dpi=140)
    ax.bar(x, max_values, color="#0ea5e9", alpha=0.82, label="Max je Bild")
    ax.plot(x, mean_values, color="#f59e0b", marker="o", linewidth=2, label="Mittel je Bild")
    ax.axhline(summary.overall_max_distance_iso_mm, color="#ef4444", linestyle="--", linewidth=1, label="Global max")
    ax.set_ylabel("Abstand Feldzentrum zu Kugelzentrum [mm @ Iso]")
    ax.set_title("Multi-Ball WLT Uebersicht")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=35, ha="right")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(output_png)
    plt.close(fig)


def render_mlc_pattern(beam: PlanBeam, output_png: str | Path) -> bool:
    if not beam.mlc_leaf_positions_mm and not beam.jaw_x_mm and not beam.jaw_y_mm:
        return False

    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    mlc_positions = beam.mlc_leaf_positions_mm
    boundaries = beam.mlc_leaf_boundaries_mm
    jaw_x = beam.jaw_x_mm if len(beam.jaw_x_mm) == 2 else []
    jaw_y = beam.jaw_y_mm if len(beam.jaw_y_mm) == 2 else []
    leaf_count = len(mlc_positions) // 2

    x_candidates = []
    y_candidates = []
    if jaw_x:
        x_candidates.extend(jaw_x)
    if jaw_y:
        y_candidates.extend(jaw_y)
    if mlc_positions:
        x_candidates.extend(mlc_positions)
    if boundaries:
        y_candidates.extend(boundaries)

    x_min = min(x_candidates) if x_candidates else -100.0
    x_max = max(x_candidates) if x_candidates else 100.0
    y_min = min(y_candidates) if y_candidates else -100.0
    y_max = max(y_candidates) if y_candidates else 100.0
    x_pad = max(10.0, (x_max - x_min) * 0.12)
    y_pad = max(10.0, (y_max - y_min) * 0.08)
    x_left = x_min - x_pad
    x_right = x_max + x_pad
    y_bottom = y_min - y_pad
    y_top = y_max + y_pad

    fig, ax = plt.subplots(figsize=(7.5, 7.5), dpi=140)
    fig.patch.set_facecolor("#0a0e17")
    ax.set_facecolor("#020617")

    if jaw_x and jaw_y:
        ax.add_patch(
            Rectangle(
                (min(jaw_x), min(jaw_y)),
                abs(jaw_x[1] - jaw_x[0]),
                abs(jaw_y[1] - jaw_y[0]),
                facecolor="#00e5ff",
                edgecolor="#00e5ff",
                linewidth=1.8,
                alpha=0.12,
                label="Jaw aperture",
            )
        )
        ax.plot([jaw_x[0], jaw_x[0]], [y_bottom, y_top], color="#f59e0b", linewidth=1.2)
        ax.plot([jaw_x[1], jaw_x[1]], [y_bottom, y_top], color="#f59e0b", linewidth=1.2)
        ax.plot([x_left, x_right], [jaw_y[0], jaw_y[0]], color="#f59e0b", linewidth=1.2)
        ax.plot([x_left, x_right], [jaw_y[1], jaw_y[1]], color="#f59e0b", linewidth=1.2)

    if beam.mlc_type.upper().endswith("X") and leaf_count and len(boundaries) >= leaf_count + 1:
        bank_a = mlc_positions[:leaf_count]
        bank_b = mlc_positions[leaf_count : leaf_count * 2]
        for idx in range(leaf_count):
            y0 = boundaries[idx]
            y1 = boundaries[idx + 1]
            a = bank_a[idx]
            b = bank_b[idx]
            left_leaf, right_leaf = sorted((a, b))
            ax.add_patch(Rectangle((x_left, y0), max(0.0, left_leaf - x_left), y1 - y0, facecolor="#334155", edgecolor="#1e293b", linewidth=0.25, alpha=0.88))
            ax.add_patch(Rectangle((right_leaf, y0), max(0.0, x_right - right_leaf), y1 - y0, facecolor="#334155", edgecolor="#1e293b", linewidth=0.25, alpha=0.88))
            if right_leaf > left_leaf:
                ax.add_patch(Rectangle((left_leaf, y0), right_leaf - left_leaf, y1 - y0, facecolor="#00e5ff", edgecolor="none", alpha=0.22))
            else:
                ax.plot([left_leaf, left_leaf], [y0, y1], color="#00e5ff", linewidth=0.5, alpha=0.75)
    elif beam.mlc_type.upper().endswith("Y") and leaf_count and len(boundaries) >= leaf_count + 1:
        bank_a = mlc_positions[:leaf_count]
        bank_b = mlc_positions[leaf_count : leaf_count * 2]
        for idx in range(leaf_count):
            x0 = boundaries[idx]
            x1 = boundaries[idx + 1]
            a = bank_a[idx]
            b = bank_b[idx]
            bottom_leaf, top_leaf = sorted((a, b))
            ax.add_patch(Rectangle((x0, y_bottom), x1 - x0, max(0.0, bottom_leaf - y_bottom), facecolor="#334155", edgecolor="#1e293b", linewidth=0.25, alpha=0.88))
            ax.add_patch(Rectangle((x0, top_leaf), x1 - x0, max(0.0, y_top - top_leaf), facecolor="#334155", edgecolor="#1e293b", linewidth=0.25, alpha=0.88))
            if top_leaf > bottom_leaf:
                ax.add_patch(Rectangle((x0, bottom_leaf), x1 - x0, top_leaf - bottom_leaf, facecolor="#00e5ff", edgecolor="none", alpha=0.22))
            else:
                ax.plot([x0, x1], [bottom_leaf, bottom_leaf], color="#00e5ff", linewidth=0.5, alpha=0.75)
    elif mlc_positions:
        ax.text(0.5, 0.5, "MLC-Daten vorhanden,\naber Orientierung nicht erkannt", transform=ax.transAxes, ha="center", va="center", color="#e2e8f0")

    ax.axhline(0, color="#64748b", linewidth=0.8, alpha=0.75)
    ax.axvline(0, color="#64748b", linewidth=0.8, alpha=0.75)
    ax.set_xlim(x_left, x_right)
    ax.set_ylim(y_bottom, y_top)
    ax.set_aspect("equal", adjustable="box")
    ax.grid(color="#1e293b", alpha=0.55, linewidth=0.5)
    ax.tick_params(colors="#94a3b8", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#0d9488")
    ax.set_xlabel("X [mm]", color="#e2e8f0")
    ax.set_ylabel("Y [mm]", color="#e2e8f0")
    ax.set_title(
        f"{beam.name} | G{beam.gantry_deg:.0f} C{beam.collimator_deg:.0f} T{beam.couch_deg:.0f}\n"
        f"{beam.mlc_type or 'Jaws'} | Beam {beam.number}",
        color="#00e5ff",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(output_png, facecolor=fig.get_facecolor())
    plt.close(fig)
    return True


def analyze_folder(
    image_dir: str | Path,
    plan_file: str | Path | None = None,
    output_dir: str | Path | None = None,
    settings: MultiBallSettings | None = None,
) -> AnalysisSummary:
    settings = settings or MultiBallSettings()
    image_dir = Path(image_dir)
    output_dir = Path(output_dir) if output_dir else image_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    beams = load_plan(plan_file)
    image_files = find_rt_image_files(image_dir)
    if not image_files:
        raise RuntimeError(f"No RTIMAGE DICOM files found in {image_dir}")

    results: list[ImageResult] = []
    preview_payloads = []
    for image_file in image_files:
        result, arr, field_mask, ball_mask = analyze_rt_image(image_file, beams, settings)
        results.append(result)
        preview_payloads.append((arr, result, field_mask, ball_mask))

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    csv_path = output_dir / f"multi_ball_wlt_{timestamp}.csv"
    json_path = output_dir / f"multi_ball_wlt_{timestamp}.json"
    preview_dir = output_dir / f"multi_ball_wlt_previews_{timestamp}"
    preview_dir.mkdir(parents=True, exist_ok=True)
    mlc_dir = output_dir / f"multi_ball_mlc_{timestamp}"
    summary_graph_path = output_dir / f"multi_ball_wlt_graph_{timestamp}.png"

    all_distances = [field.distance_iso_mm for image in results for field in image.fields]
    summary = AnalysisSummary(
        generated_at=datetime.now().isoformat(timespec="seconds"),
        image_count=len(results),
        overall_max_distance_iso_mm=float(max(all_distances)),
        overall_mean_distance_iso_mm=float(np.mean(all_distances)),
        output_csv=str(csv_path),
        output_json=str(json_path),
        preview_png="",
        preview_pngs=[],
        mlc_pngs=[],
        summary_png=str(summary_graph_path),
        results=results,
    )
    for index, payload in enumerate(preview_payloads, start=1):
        _, image_result, _, _ = payload
        safe_label = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in (image_result.beam_name or Path(image_result.file).stem))
        preview_path = preview_dir / f"{index:02d}_{safe_label}.png"
        render_preview(*payload, output_png=preview_path)
        image_result.preview_png = str(preview_path)
        summary.preview_pngs.append(str(preview_path))
    summary.preview_png = summary.preview_pngs[0] if summary.preview_pngs else ""
    beam_by_number = {beam.number: beam for beam in beams}
    for index, image_result in enumerate(results, start=1):
        image_result.mlc_png = ""
        beam = beam_by_number.get(image_result.plan_beam_number)
        if beam is not None:
            mlc_dir.mkdir(parents=True, exist_ok=True)
            safe_label = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in (image_result.beam_name or beam.name or Path(image_result.file).stem))
            mlc_path = mlc_dir / f"{index:02d}_{safe_label}_mlc.png"
            if render_mlc_pattern(beam, mlc_path):
                image_result.mlc_png = str(mlc_path)
        summary.mlc_pngs.append(image_result.mlc_png)
    render_summary_graph(summary, summary_graph_path)
    write_csv(summary, csv_path)
    write_json(summary, json_path)
    return summary


def format_summary(summary: AnalysisSummary) -> str:
    lines = [
        "Multi-Ball WLT Ergebnis",
        f"Zeitpunkt: {summary.generated_at}",
        f"Bilder: {summary.image_count}",
        f"Max. Abstand: {summary.overall_max_distance_iso_mm:.3f} mm",
        f"Mittlerer Abstand: {summary.overall_mean_distance_iso_mm:.3f} mm",
        "",
    ]
    for image in summary.results:
        label = image.beam_name or f"G{image.gantry_deg:.0f} C{image.collimator_deg:.0f} T{image.couch_deg:.0f}"
        match = f"Match-Summe {image.plan_match_score_deg:.1f} deg"
        if image.plan_match_warning:
            match += f" | {image.plan_match_warning}"
        plan_angles = (
            f"Planwinkel G{image.plan_gantry_deg:.1f} C{image.plan_collimator_deg:.1f} T{image.plan_couch_deg:.1f}"
            if image.beam_name
            else "Planwinkel n/a"
        )
        lines.append(
            f"{label} | {image.file} | "
            f"Bildwinkel G{image.gantry_deg:.1f} C{image.collimator_deg:.1f} T{image.couch_deg:.1f} | "
            f"{plan_angles} | {match}"
        )
        if image.mlc_png:
            lines.append(f"  MLC-Muster: {image.mlc_png}")
        for field in image.fields:
            lines.append(
                f"  Feld {field.field_index}: "
                f"dx={field.dx_iso_mm:+.3f} mm, dy={field.dy_iso_mm:+.3f} mm, "
                f"d={field.distance_iso_mm:.3f} mm"
            )
        lines.append("")
    lines.extend(
        [
            f"CSV: {summary.output_csv}",
            f"JSON: {summary.output_json}",
            f"Previews: {len(summary.preview_pngs)} Bild(er)",
            f"Graph: {summary.summary_png}",
        ]
    )
    return "\n".join(lines)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze Multi-Ball Winston-Lutz RTIMAGE DICOMs.")
    parser.add_argument("image_dir", help="Folder containing RTIMAGE .dcm files")
    parser.add_argument("--plan", help="Optional RTPLAN DICOM for beam-name matching")
    parser.add_argument("--output", help="Output folder for CSV/JSON/PNG")
    parser.add_argument("--fields", default="3", help='Expected fields per RTIMAGE; integer or "auto"')
    parser.add_argument("--ball-percentile", type=float, default=1.0, help="Dark percentile used for ball detection")
    return parser


def parse_expected_fields(value: str) -> int:
    text = value.strip().lower()
    if text in {"", "auto", "a"}:
        return 0
    fields = int(text)
    if fields < 1:
        raise ValueError("fields must be a positive integer or 'auto'")
    return fields


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    settings = MultiBallSettings(
        expected_fields=parse_expected_fields(args.fields),
        ball_dark_percentile=args.ball_percentile,
    )
    summary = analyze_folder(args.image_dir, args.plan, args.output, settings)
    print(format_summary(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
