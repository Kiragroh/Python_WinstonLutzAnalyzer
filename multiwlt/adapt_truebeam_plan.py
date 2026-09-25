"""Rename a research RTPLAN's machine without changing its delivery geometry."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import pydicom
from pydicom.uid import generate_uid


def checked_sh(value):
    if not value or len(value)>16 or any(ord(c)<32 or ord(c)>126 or c=='\\' for c in value):
        raise ValueError('Use 1–16 printable ASCII characters, without a backslash.')
    return value


def adapt(source, output, machine, tolerance_label=None, profile=None):
    source=Path(source).resolve();output=Path(output).resolve();checked_sh(machine)
    if tolerance_label is not None:checked_sh(tolerance_label)
    if source==output or output.exists():raise ValueError('Choose a new output file; existing files are never overwritten.')
    ds=pydicom.dcmread(source)
    if str(getattr(ds,'Modality',''))!='RTPLAN':raise ValueError('Input must be an RTPLAN.')
    if not getattr(ds,'BeamSequence',None):raise ValueError('No beams in input plan.')
    reference=None;profile_out=output.with_suffix('.reference.json')
    if profile:
        profile=Path(profile).resolve();reference=json.loads(profile.read_text(encoding='utf-8'))
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        if (profile.parent/reference['qa_plan_file']).resolve()!=source or reference['qa_plan_sha256']!=digest:
            raise ValueError('Reference profile does not match the input plan.')
        if profile_out.exists():raise ValueError('Output reference profile already exists.')
    original=copy.deepcopy(ds)
    for beam in ds.BeamSequence:beam.TreatmentMachineName=machine
    if tolerance_label is not None:
        if not getattr(ds,'ToleranceTableSequence',None):raise ValueError('No tolerance table to rename; specify one in the TPS.')
        for table in ds.ToleranceTableSequence:table.ToleranceTableLabel=tolerance_label
    ds.SOPInstanceUID=generate_uid();ds.SeriesInstanceUID=generate_uid()
    ds.file_meta.MediaStorageSOPInstanceUID=ds.SOPInstanceUID
    ds.ApprovalStatus='UNAPPROVED'
    for key in ['ReviewDate','ReviewTime','ReviewerName']:
        if hasattr(ds,key):delattr(ds,key)
    # This is a name adaptation, not a machine/MLC conversion.
    for before,after in zip(original.BeamSequence,ds.BeamSequence):
        restored=copy.deepcopy(after);restored.TreatmentMachineName=before.TreatmentMachineName
        if restored!=before:raise AssertionError('Unexpected beam change.')
    if getattr(original,'FractionGroupSequence',None)!=getattr(ds,'FractionGroupSequence',None):
        raise AssertionError('Unexpected MU/fraction change.')
    output.parent.mkdir(parents=True,exist_ok=True)
    # Exclusive creation also protects against a concurrent overwrite.
    with output.open('xb') as stream:ds.save_as(stream,write_like_original=False)
    if reference is not None:
        reference.update(qa_plan_file=output.name,
            qa_plan_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
            qa_plan_sop_hash=hashlib.sha256(str(ds.SOPInstanceUID).encode()).hexdigest())
        with profile_out.open('x',encoding='utf-8') as stream:
            json.dump(reference,stream,indent=2,ensure_ascii=False,allow_nan=False)
    saved=pydicom.dcmread(output)
    if saved.BeamSequence!=ds.BeamSequence or saved.ApprovalStatus!='UNAPPROVED':raise AssertionError('Readback failed.')
    return output,profile_out if reference is not None else None


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source');p.add_argument('output');p.add_argument('--machine',required=True)
    p.add_argument('--tolerance-label',help='Exact existing local table label; no table is guessed or created.')
    p.add_argument('--profile',help='Optionally write an updated analysis reference next to the new plan.')
    a=p.parse_args();output,profile=adapt(a.source,a.output,a.machine,a.tolerance_label,a.profile)
    print('Created UNAPPROVED copy:',output)
    if profile:print('Updated reference:',profile)


if __name__=='__main__':main()
