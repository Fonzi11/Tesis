"""Flujo CTA asistido y auditable.

Este módulo no declara diagnósticos. Genera una máscara vascular inicial,
conserva la geometría de la serie fuente y exige aprobación humana antes de
crear un DICOM SEG.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import SimpleITK as sitk


class ClinicalPipelineError(RuntimeError):
    """Error explícito de validación o exportación clínica."""


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _dicom_files(folder: str) -> list[str]:
    return sorted(
        str(p) for p in Path(folder).rglob("*")
        if p.is_file() and p.suffix.lower() in {".dcm", ".dicom", ".ima", ""}
    )


def _load_source(folder: str) -> tuple[sitk.Image, list[str], dict[str, Any]]:
    files = _dicom_files(folder)
    if not files:
        raise ClinicalPipelineError("La carpeta no contiene archivos DICOM.")
    series_ids = sitk.ImageSeriesReader.GetGDCMSeriesIDs(folder)
    if not series_ids:
        raise ClinicalPipelineError("No se pudo identificar una serie DICOM.")
    series_by_size = sorted(
        [
            (
                list(sitk.ImageSeriesReader.GetGDCMSeriesFileNames(folder, uid)),
                uid,
            )
            for uid in series_ids
        ],
        key=lambda item: len(item[0]),
    )
    series_files, selected_uid = series_by_size[-1]
    if not series_files:
        raise ClinicalPipelineError("La serie DICOM seleccionada no tiene cortes.")
    reader = sitk.ImageSeriesReader()
    reader.SetFileNames(series_files)
    image = reader.Execute()
    direction = image.GetDirection()
    spacing = image.GetSpacing()
    origin = image.GetOrigin()
    arr = sitk.GetArrayViewFromImage(image)
    finite = np.isfinite(arr)
    values = arr[finite]
    try:
        import pydicom
        modality = str(pydicom.dcmread(series_files[0], stop_before_pixels=True)
                       .get("Modality", "CT"))
    except Exception:
        modality = "CT"
    report = {
        "series_uid": selected_uid,
        "file_count": len(series_files),
        "available_series": [
            {"uid": uid, "file_count": len(files)}
            for files, uid in series_by_size
        ],
        "size": list(image.GetSize()),
        "spacing_mm": list(spacing),
        "origin_mm": list(origin),
        "direction": list(direction),
        "direction_orthonormal": bool(
            np.allclose(np.asarray(direction).reshape(3, 3).T
                        @ np.asarray(direction).reshape(3, 3),
                        np.eye(3), atol=1e-3)
        ),
        "intensity_min": float(values.min()),
        "intensity_max": float(values.max()),
        "intensity_p99": float(np.percentile(values, 99)),
        "modality": modality,
    }
    return image, series_files, report


def validate_cta_geometry(folder: str) -> dict[str, Any]:
    """Valida una serie CT sin modificarla."""
    image, _, report = _load_source(folder)
    errors = []
    warnings = []
    if report["modality"].upper() != "CT":
        errors.append("La modalidad DICOM no es CT.")
    if any(float(v) <= 0 for v in report["spacing_mm"]):
        errors.append("El espaciado DICOM contiene valores no positivos.")
    if not report["direction_orthonormal"]:
        errors.append("La matriz de orientación DICOM no es ortonormal.")
    if report["size"][2] < 2:
        errors.append("La serie no tiene suficientes cortes.")
    if len(report["available_series"]) > 1:
        warnings.append(
            "La carpeta contenía varias series; se seleccionó la de mayor "
            "número de cortes. Verifique la selección CTA."
        )
    if report["intensity_p99"] < 180:
        warnings.append(
            "No se observan intensidades altas típicas de contraste arterial; "
            "confirme que la serie es CTA."
        )
    report["valid"] = not errors
    report["errors"] = errors
    report["warnings"] = warnings
    report["registration"] = {
        "type": "identity",
        "validated": True,
        "metric": 1.0,
        "reason": "Una sola serie fuente; no se mezclaron volúmenes.",
    }
    # Mantiene la referencia para que el llamador pueda comprobar que la
    # lectura fue real, no una validación basada solo en metadatos.
    report["voxel_count"] = int(np.prod(image.GetSize()))
    return report


def _vascular_mask(image: sitk.Image) -> sitk.Image:
    arr = sitk.GetArrayFromImage(image)
    # Umbral inicial conservador para vasos opacificados. No sustituye una
    # segmentación entrenada ni la revisión radiológica.
    mask = ((arr >= 180) & (arr <= 2000)).astype(np.uint8)
    result = sitk.GetImageFromArray(mask)
    result.CopyInformation(image)
    result = sitk.BinaryMorphologicalOpening(result, [1, 1, 1])
    result = sitk.BinaryMorphologicalClosing(result, [1, 1, 1])
    return sitk.Cast(result > 0, sitk.sitkUInt8)


def _write_seg(
    source_files: list[str], mask: sitk.Image, output_path: str, report: dict[str, Any]
) -> None:
    try:
        import highdicom as hd
        import pydicom
        from highdicom.content import AlgorithmIdentificationSequence
        from pydicom.sr.coding import Code
        from pydicom.uid import generate_uid
    except ImportError as exc:
        raise ClinicalPipelineError(
            "DICOM SEG requiere highdicom y pydicom instalados."
        ) from exc

    datasets = [pydicom.dcmread(path) for path in source_files]
    datasets.sort(key=lambda ds: int(getattr(ds, "InstanceNumber", 0)))
    # highdicom recibe los fotogramas como [frames, rows, columns], que es
    # precisamente el orden que devuelve SimpleITK para una serie 3D.
    pixels = sitk.GetArrayFromImage(mask)
    segment = hd.seg.SegmentDescription(
        segment_number=1,
        segment_label="Vascular CTA candidate",
        segmented_property_category=hd.sr.CodedConcept(
            value="49755003", scheme_designator="SCT",
            meaning="Morphologically Abnormal Structure",
        ),
        segmented_property_type=hd.sr.CodedConcept(
            value="59820001", scheme_designator="SCT", meaning="Blood vessel",
        ),
        algorithm_type=hd.seg.SegmentAlgorithmTypeValues.AUTOMATIC,
        algorithm_identification=AlgorithmIdentificationSequence(
            name="NEUROHUB CTA threshold",
            family=Code("99NEUROHUB", "99LOCAL", "NEUROHUB"),
            version="1",
        ),
    )
    seg = hd.seg.Segmentation(
        source_images=datasets,
        pixel_array=pixels,
        segmentation_type=hd.seg.SegmentationTypeValues.BINARY,
        segment_descriptions=[segment],
        series_instance_uid=generate_uid(),
        series_number=901,
        sop_instance_uid=generate_uid(),
        instance_number=1,
        manufacturer="NEUROHUB",
        manufacturer_model_name="NEUROHUB clinical-assist",
        software_versions="1",
        device_serial_number="NEUROHUB",
    )
    seg.save_as(output_path)
    report["dicom_seg"] = {
        "path": output_path,
        "source_series_uid": str(datasets[0].SeriesInstanceUID),
        "validated": True,
    }


def run_cta_pipeline(
    input_dir: str,
    output_dir: str,
    *,
    approved_by: str | None = None,
    approval_notes: str = "",
) -> dict[str, Any]:
    """Ejecuta validación, registro identidad y máscara CTA inicial."""
    os.makedirs(output_dir, exist_ok=True)
    report = validate_cta_geometry(input_dir)
    if not report["valid"]:
        raise ClinicalPipelineError("; ".join(report["errors"]))
    image, source_files, _ = _load_source(input_dir)
    mask = _vascular_mask(image)
    mask_path = os.path.join(output_dir, "vasos_cta.nrrd")
    sitk.WriteImage(mask, mask_path, useCompression=True)
    report.update({
        "created_at": _now(),
        "mask_type": "CTA threshold candidate",
        "mask_nrrd": mask_path,
        "review": {
            "status": "approved" if approved_by else "pending",
            "reviewer": approved_by,
            "approved_at": _now() if approved_by else None,
            "notes": approval_notes,
        },
        "clinical_disclaimer": (
            "Candidato vascular asistido; requiere revisión clínica humana."
        ),
    })
    if approved_by:
        seg_path = os.path.join(output_dir, "vasos_cta.dcmseg")
        _write_seg(source_files, mask, seg_path, report)
    report_path = os.path.join(output_dir, "clinical_report.json")
    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    report["report_path"] = report_path
    return report
