# Validation scope

The extension was tested locally with Python 3.13 on 25 September 2026.

- 17 package tests: plan-name adaptation, preservation of control points, rejected invalid names, reference binding, 3D ray geometry, changed ball positions, CT fitting independent of approximate seeds, CT rescaling, rejected mismatched reference frames and irregular slices.
- Synthetic four-image end-to-end demo: twelve detections, known injected displacement recovered within 0.034 mm in the local run.
- Local source-data check: independent CT fits starting from deliberately displaced seeds reproduced the reference ball distances within 0.000001 mm. This checks reproducibility on the same CT, not manufacturing equivalence of different phantoms or absolute localisation accuracy.
- End-to-end local acquired-data check with that newly generated CT/plan profile: all twelve pairs detected; the reported extra distances reproduced the established reference analysis within 0.000001 mm. The field-centre review flag remained unchanged. Acquired data are available separately as a GitHub Release asset.
- The locally used standalone implementation had 63 regression tests passing and one optional test skipped before this public add-on; those full local tests/data are not claimed to be bundled here.

Acquired results and the remaining field-centre method review are described in the README. Repeatability, acquisition-mode comparisons and a clinical uncertainty budget remain open. No clinical pass/fail threshold is supplied. CI runs the bundled package tests and synthetic demo only.

English publication check: report/plot labels and diagnostic messages were translated without changing the analysis expressions. All twelve acquired residual vectors and the pooled sphere match the previous implementation exactly. The six-page English example report was checked for layout and identifying text.

Dataset release validation: 297 de-identified DICOM files. All CT/MV pixels, plan control points and RTSTRUCT contour coordinates were checked against the original inputs. Analysis of the public copy reproduced all twelve residual vectors and the pooled sphere exactly. An independent CT fit reproduced inter-ball distances within 0.000001 mm. See the release archive validation.json for details.
