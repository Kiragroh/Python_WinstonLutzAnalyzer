# Dependencies and media

Source users install dependencies separately. Portable Windows releases bundle the Python runtime and analysis dependencies, including NumPy, SciPy, pydicom, pylinac, Matplotlib, ReportLab and Pillow. These retain their own licences; see the release's `THIRD_PARTY_LICENSES` folder and `dependency_versions.json`. Pytest is used for source tests and is excluded from the portable application. The repository's MIT licence does not replace dependency licences.

The phantom photograph was supplied by the project owner for this package. Generated measurement plots derive from the initial phantom experiment. The code licence does not grant rights to manufacturer names, trademarks or logos shown in photographs. The de-identified acquired phantom dataset is distributed separately as a GitHub Release asset under the MIT licence included in the archive. The source repository contains the download manifest; no acquired DICOM images are stored in its Git tree.
