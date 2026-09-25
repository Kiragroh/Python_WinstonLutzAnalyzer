# Winston–Lutz Analyzer

Python tools for standard Winston–Lutz analysis and CT-referenced, off-isocentre MultiWLT. The desktop application uses [pylinac](https://pylinac.readthedocs.io/); the new [`multiwlt/`](multiwlt/) research module explicitly subtracts the expected CT/plan offset before evaluating measured deviations.

## Choose a workflow

| Workflow | Entry point | What it reports |
|---|---|---|
| Standard single-ball WLT | Desktop GUI, **Standard WLT** tab | Standard pylinac results and PDF report |
| Existing multi-ball exploration | Desktop GUI, **Multi-Ball Off-Iso** tab | Detected ball-to-field distances and aperture previews |
| **CT-referenced MultiWLT** | [`multiwlt/analyse.py`](multiwlt/analyse.py) | Measured minus expected vectors, local 3D ray envelopes, compact PDF |

**The existing GUI multi-ball tab does not apply the new CT-reference correction.** Use the new module's CLI for the corrected workflow. The original desktop application remains available; its [German guide](README.de.md) is preserved.

## CT-referenced MultiWLT

![Brainlab head phantom used for the initial MultiWLT test](multiwlt/assets/phantom.png)

Four acquired MVHighQuality images, three balls, twelve ball–field pairs. The initial test was performed on **25 September 2026 by Dr. Sebastian Schäfer** in Leipzig. The largest additional 2D displacement was **0.508 mm**; one field-centre method comparison remains flagged for review. These are initial research results, not clinical acceptance criteria.

**Start with the [English MultiWLT guide](multiwlt/README.md).** It includes the measured results, expected-versus-observed plots, a synthetic demo, a machine-name adapter and a tool for inspecting your own CT and plan.

**Expected offsets are specific to the CT ball centres, plan isocentre, angles and apertures.** Do not reuse our offsets for a different CT/plan combination. Even with the same phantom model, verify your own ball layout and derive your own reference. [`inspect_phantom.py`](multiwlt/inspect_phantom.py) performs that check; unsupported ball arrangements, openings or image geometry require adapting and validating the logic.

```sh
git clone https://github.com/Kiragroh/Python_WinstonLutzAnalyzer.git
cd Python_WinstonLutzAnalyzer/multiwlt
python -m pip install -r requirements.txt
python demo.py --output demo_output
python -m pytest tests -q
```

The demo uses labelled synthetic images and an incomplete synthetic geometry fixture, **not a deliverable treatment plan**. The deidentified acquired-image download is still pending; its link will be added to [`data/manifest.json`](multiwlt/data/manifest.json). No acquired DICOM datasets or institution-specific deployment configuration are committed.

## Existing desktop application

Python 3.13 is the tested interpreter. From the repository root:

```powershell
py -3.13 -m pip install -r requirements.txt
.\start_open_gui.cmd
```

The GUI supports folder selection, standard WLT reports, exploratory multi-ball aperture views and local history. Output and saved settings remain local in `output/`. See the [desktop guide](README.de.md) for startup checks, CLI options and screenshots.

## Scope and contribution

Only the initial four-view MultiWLT measurements are presented as acquired results. Couch/collimator variations, comparisons with and without ExacTrac correction, conventional WLT on BB01, and DCA/cine are research outlook. This repository does not operate a treatment machine or establish a clinical tolerance.

Reproducible, deidentified cases, known-shift checks and independent localisation comparisons are welcome. Document the CT/plan reference and acquisition geometry with each case. The software is released under the [MIT licence](LICENSE.txt); dependency and media details for the extension are in [THIRD_PARTY.md](multiwlt/THIRD_PARTY.md).
