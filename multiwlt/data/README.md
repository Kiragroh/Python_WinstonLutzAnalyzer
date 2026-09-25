# Acquired phantom data

## Separate downloads

CT and structures are stable. Plans and their matching analysis profiles are versioned separately so plan revisions do not require another CT download.

| Package | Size | SHA-256 |
|---|---|---|
| [CT + RTSTRUCT (stable anatomy v1)](https://github.com/Kiragroh/Python_WinstonLutzAnalyzer/releases/download/multiwlt-data-20260925-v1/MultiWLT_CT_RTSTRUCT_v1.zip) | 77.77 MB | [2c8133268547…](https://github.com/Kiragroh/Python_WinstonLutzAnalyzer/releases/download/multiwlt-data-20260925-v1/MultiWLT_CT_RTSTRUCT_v1.zip.sha256) |
| [RTPLAN R6 + matching reference profile](https://github.com/Kiragroh/Python_WinstonLutzAnalyzer/releases/download/multiwlt-data-20260925-v1/MultiWLT_RTPLAN_R6_v1.zip) | 9.3 kB | [c5e5a894e049…](https://github.com/Kiragroh/Python_WinstonLutzAnalyzer/releases/download/multiwlt-data-20260925-v1/MultiWLT_RTPLAN_R6_v1.zip.sha256) |
| [MV images + delivery records + example results](https://github.com/Kiragroh/Python_WinstonLutzAnalyzer/releases/download/multiwlt-data-20260925-v1/MultiWLT_MV_20260925_v1.zip) | 6.16 MB | [095cc5c99fef…](https://github.com/Kiragroh/Python_WinstonLutzAnalyzer/releases/download/multiwlt-data-20260925-v1/MultiWLT_MV_20260925_v1.zip.sha256) |

Extract the required ZIPs into the **same parent directory**, e.g. `multiwlt/local_data`. They merge into `MultiWLT_Leipzig_Initial_20260925/` with CT, RT, MV and Records subfolders. For complete reproduction, use all three. Plan + measurement packages suffice for the supplied reference-based analysis; the CT/RTSTRUCT package is additionally needed for CT inspection or TPS import.

**Compatibility:** anatomy ID `leipzig-brainlab-ct-v1`. All 297 DICOM files and the reference profile are byte-identical to the original full release: no pixel, UID or geometry changes. Future plan revisions must state the compatible anatomy ID and ship a newly verified reference profile. Do not silently pair a revised plan with the initial R6 profile or measurements. CT/RTSTRUCT v1 stays immutable.

The [original full ZIP](https://github.com/Kiragroh/Python_WinstonLutzAnalyzer/releases/download/multiwlt-data-20260925-v1/MultiWLT_Leipzig_Initial_20260925_v1.zip) remains available for existing links. [Release notes](https://github.com/Kiragroh/Python_WinstonLutzAnalyzer/releases/tag/multiwlt-data-20260925-v1) · [Full manifest](manifest.json).

## All five RTPLANs

[Download all five de-identified plans (42 kB)](https://github.com/Kiragroh/Python_WinstonLutzAnalyzer/releases/download/multiwlt-data-20260925-v1/MultiWLT_All_RTPLANs_v2.zip) · [SHA-256](https://github.com/Kiragroh/Python_WinstonLutzAnalyzer/releases/download/multiwlt-data-20260925-v1/MultiWLT_All_RTPLANs_v2.zip.sha256)

Includes **traditional Standard-WLT**, **MultiWLT R6**, **BB01-ISO**, **DCA D2** and **combined gantry/couch/collimator variation**. Machine/tolerance labels are `RESEARCH_TB`; patient is `PHANTOM^MULTIWLT` / `MULTIWLT_PHANTOM`. All plans remain UNAPPROVED. The R6 plan is byte-identical to the initial data release. The other plans are preparation/outlook, not additional measured results.

Collection v2 replaces plan 05 with **16 static fields**: fields 1–4 reproduce R6 (G20/105/195/285, T0), followed by twelve G0 fields with four couch angles and three collimators each. Plans 01–04 are byte-identical to v1. The original four-view routine uses fields 1–4; an eight-image extension adds fields 5/8/11/14; the full extension uses all sixteen. The planned openings and profile are verified; device import, collision clearance and acquired-image analysis are pending. Only T0 has multiple gantry views; the rotated couch positions cannot yield independent 3D spheres from one gantry direction. The public plan references the published anonymized RTSTRUCT, not a local Eclipse UID.

**Standard-WLT anatomy exception:** the traditional plan retains a separate, remapped original CT/RTSTRUCT reference; those objects are not included. It must not be associated with the Brainlab CT by simply changing a UID. Plans R6, BB01, DCA and the combined plan use the stable Brainlab anatomy package. See the archive README and per-plan catalog before local adaptation/import.

## Reproduce

Extract below `multiwlt/local_data`, retaining the archive folder name. From `multiwlt`, run:

```sh
python analyse.py local_data/MultiWLT_Leipzig_Initial_20260925/MV --profile local_data/MultiWLT_Leipzig_Initial_20260925/RT/reference.json --records local_data/MultiWLT_Leipzig_Initial_20260925/Records --positioned-in-ct --output results
```

Expected: 12 ball–field pairs, maximum extra 2D displacement 0.5078018875 mm and `REVIEW_FIELD_METHOD`. The BB03/G285 field-centre comparison remains a method-review flag.

The included plan is the source R6 plan; the imported ARIA RTPLAN return export is still unavailable. Its identity remains distinct in the acquired images and delivery records. The four records are required to corroborate source geometry. Do not change these references merely to bypass the check.

For your own phantom, inspect its CT and derive a new reference; our expected vectors are specific to this CT/plan combination. See the main [MultiWLT guide](../README.md#use-your-own-phantom-ct-and-plan).

The component READMEs document de-identification, retained geometry, auxiliary reference removal, validation and MIT licensing. It is a research dataset, not a commissioned treatment package. Review any import or delivery independently with local machine configuration.
