# MultiWLT 0.2.0 — portable Windows GUI

This interface runs the **CT-referenced evaluator**, including the expected opening offset. It is separate from the legacy raw-distance Multi-Ball tab in the older general WLT application.

## No Python installation required

Download `MultiWLT-0.2.0-Windows-x64.zip` from the repository's GitHub Releases. Extract the **entire folder** and start `MultiWLT.exe`. Keep `_internal` next to the EXE. This is a portable folder build, not a single self-extracting executable.

## Analyse the four published MV images

1. Download the [R6 plan/reference](https://github.com/Kiragroh/Python_WinstonLutzAnalyzer/releases/download/multiwlt-data-20260925-v1/MultiWLT_RTPLAN_R6_v1.zip) and [MV images/delivery records](https://github.com/Kiragroh/Python_WinstonLutzAnalyzer/releases/download/multiwlt-data-20260925-v1/MultiWLT_MV_20260925_v1.zip). Extract both ZIPs into the same parent folder. CT download is not required for this supplied-reference analysis.
2. In the GUI, select `MultiWLT_Leipzig_Initial_20260925/MV` as the image folder and `RT/reference.json` as the reference. Keep its matching plan DICOM beside the JSON.
3. Select `Records` as the delivery-record folder. These records are required for the initial dataset because the acquired images refer to the imported plan rather than the source plan identity.
4. Choose a writable output folder. Confirm image-guided positioning to the reference CT pose; this is documented for the initial acquisition. For your own data, confirm only when actually performed.
5. Click **Analyse and create PDF / CSV / JSON**. A new timestamped subfolder contains the English report, figures, `results.csv` and `result.json`. Paths are displayed for copying; the app does not invoke a shell or external viewer.

Expected initial result: **12/12 pairs**, maximum extra 2D displacement **0.508 mm**, pooled local ray-envelope diameter approximately **0.735 mm**, status **REVIEW_FIELD_METHOD**. The BB03/G285 field-centre comparison requires review. This status is not a clinical pass/fail result.

Extra displacement is `(measured ball − measured field) − (projected CT ball − planned opening)`, as a vector. The planned opening offset is already subtracted. The report includes expected/observed overlays and individual and pooled ray envelopes.

## Your own data

Supply the matching CT/plan-derived profile. The reference is not interchangeable between phantom geometries or plans. See [the main guide](https://github.com/Kiragroh/Python_WinstonLutzAnalyzer/tree/main/multiwlt) and `inspect_phantom.py`. Do not change image/plan UIDs to bypass identity checks. This detector expects three separated target apertures per image and one image per reference field. Initial acquired-image verification covers the four-view R6 test; DCA/cine and expanded couch/collimator measurements remain research outlook.

## Run or build from source

From the repository's `multiwlt` directory:

```powershell
python -m pip install -r requirements.txt
python gui.py
# Optional portable build, using the tested Python 3.13 environment:
python -m pip install pyinstaller==6.20.0
python -m PyInstaller --noconfirm --distpath dist --workpath build portable.spec
```

The build contains analysis code and dependencies only, no local institution settings, original DICOM data or credentials. Dependency versions, source revision and checksums accompany each published binary. Research software under the MIT license; local measurement uncertainty and tolerances require validation.
