# Acquired phantom data

[Download the initial dataset ZIP](https://github.com/Kiragroh/Python_WinstonLutzAnalyzer/releases/download/multiwlt-data-20260925-v1/MultiWLT_Leipzig_Initial_20260925_v1.zip) · [Release notes](https://github.com/Kiragroh/Python_WinstonLutzAnalyzer/releases/tag/multiwlt-data-20260925-v1) · [SHA-256](https://github.com/Kiragroh/Python_WinstonLutzAnalyzer/releases/download/multiwlt-data-20260925-v1/MultiWLT_Leipzig_Initial_20260925_v1.zip.sha256)

Approximately 84 MB compressed, containing 297 DICOM files: 287 CT, one source RTPLAN, one RTSTRUCT, four MV RTIMAGEs and four delivery RTRECORDs. Includes the matching reference, CT-fit seeds and English example report. Dates/identifiers were replaced; image pixels and geometric measurements were preserved. No RTDOSE or experimental DCA/couch plans are included.

## Reproduce

Extract below `multiwlt/local_data`, retaining the archive folder name. From `multiwlt`, run:

```sh
python analyse.py local_data/MultiWLT_Leipzig_Initial_20260925/MV --profile local_data/MultiWLT_Leipzig_Initial_20260925/RT/reference.json --records local_data/MultiWLT_Leipzig_Initial_20260925/Records --positioned-in-ct --output results
```

Expected: 12 ball–field pairs, maximum extra 2D displacement 0.5078018875 mm and `REVIEW_FIELD_METHOD`. The BB03/G285 field-centre comparison remains a method-review flag.

The included plan is the source R6 plan; the imported ARIA RTPLAN return export is still unavailable. Its identity remains distinct in the acquired images and delivery records. The four records are required to corroborate source geometry. Do not change these references merely to bypass the check.

For your own phantom, inspect its CT and derive a new reference; our expected vectors are specific to this CT/plan combination. See the main [MultiWLT guide](../README.md#use-your-own-phantom-ct-and-plan).

The archive README documents de-identification, retained geometry, auxiliary reference removal, validation and MIT licensing. It is a research dataset, not a commissioned treatment package. Review any import or delivery independently with local machine configuration.
