from pathlib import Path
import copy
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pydicom
import pytest
from adapt_truebeam_plan import adapt
from routine_workflow import load_profile

ROOT=Path(__file__).resolve().parents[1]

def test_rename_preserves_geometry_and_updates_reference(tmp_path):
    src=ROOT/'example_reference'/'SYNTHETIC_geometry.dcm'
    output,profile=adapt(src,tmp_path/'renamed.dcm','TEST_TB',profile=src.with_name('reference.json'))
    old=pydicom.dcmread(src);new=pydicom.dcmread(output)
    assert new.SOPInstanceUID!=old.SOPInstanceUID
    assert new.ApprovalStatus=='UNAPPROVED'
    for a,b in zip(old.BeamSequence,new.BeamSequence):
        assert b.TreatmentMachineName=='TEST_TB'
        assert a.ControlPointSequence==b.ControlPointSequence
        assert a.BeamLimitingDeviceSequence==b.BeamLimitingDeviceSequence
    assert load_profile(profile)[2].SOPInstanceUID==new.SOPInstanceUID
    with pytest.raises(ValueError):adapt(src,output,'TEST_TB')

@pytest.mark.parametrize('name',['','X'*17,'A\\B','A\nB'])
def test_bad_name_rejected(tmp_path,name):
    with pytest.raises(ValueError):adapt(ROOT/'example_reference'/'SYNTHETIC_geometry.dcm',tmp_path/'out.dcm',name)

def test_unknown_tolerance_table_not_created(tmp_path):
    with pytest.raises(ValueError,match='No tolerance'):
        adapt(ROOT/'example_reference'/'SYNTHETIC_geometry.dcm',tmp_path/'out.dcm','TEST_TB','LOCAL')
