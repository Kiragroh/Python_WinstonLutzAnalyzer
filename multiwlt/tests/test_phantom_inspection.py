import copy,json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
import pydicom
from pydicom.dataset import Dataset,FileMetaDataset
from pydicom.uid import CTImageStorage,ExplicitVRLittleEndian,generate_uid
import pytest
from inspect_phantom import compare_layout,derive_reference,fit_balls,load_ct
from routine_workflow import load_profile
from routine_core import project_hfs,mlc_to_panel

ROOT=Path(__file__).resolve().parents[1]

def test_own_ball_location_changes_expected_offsets():
    ref,beams,plan=load_profile(ROOT/'example_reference/reference.json')
    original=derive_reference(plan,copy.deepcopy(ref['balls']))
    moved=copy.deepcopy(ref['balls']);moved[0]['center_lps_mm'][0]+=.4
    own=derive_reference(plan,moved)
    for b,f in zip(beams,own['fields']):
        t=f['targets'][0];bb=project_hfs(moved[0]['center_lps_mm'],ref['iso_lps_mm'],b['gantry_deg'],b['collimator_deg'],b['couch_deg'],b['sad_mm'])
        assert t['expected_vector_panel_mm']==pytest.approx(mlc_to_panel(bb-t['center_mlc_mm'],b['collimator_deg']))
    assert own['fields'][0]['targets'][0]['expected_vector_panel_mm']!=original['fields'][0]['targets'][0]['expected_vector_panel_mm']
    assert compare_layout(moved,ref)['max_pairwise_difference_mm']>.05

def test_pairwise_geometry_is_translation_invariant_but_not_a_pose_certificate():
    ref,_,_=load_profile(ROOT/'example_reference/reference.json');balls=copy.deepcopy(ref['balls'])
    for b in balls:b['center_lps_mm']=(np.array(b['center_lps_mm'])+[22,-17,35]).tolist()
    result=compare_layout(balls,ref)
    assert result['max_pairwise_difference_mm']<1e-10
    assert 'No automatic equivalence' in result['assessment']

def test_outside_field_fails_instead_of_reusing_original_offsets():
    ref,_,plan=load_profile(ROOT/'example_reference/reference.json');balls=copy.deepcopy(ref['balls']);balls[0]['center_lps_mm'][0]+=50
    with pytest.raises(ValueError,match='no unique opening'):derive_reference(plan,balls)

def test_ct_fit_uses_pixels_not_seed_positions():
    z,y,x=np.indices((31,61,111));volume=np.zeros_like(x,dtype=np.float32)
    truth=[[22.3,30.1,15.2],[55.2,30.4,15.1],[87.4,30.2,15.3]]
    for a,b,c in truth:
        distance=np.sqrt((x-a)**2+(y-b)**2+(z-c)**2)
        volume+=4000*np.clip(3.5-distance,0,1)
    seeds=[{'id':f'BB{i+1:02d}','approx_center_lps_mm':(np.array(v)+[1,-1,0]).tolist(),'nominal_diameter_mm':8} for i,v in enumerate(truth)]
    balls=fit_balls(volume,{'origin_lps_mm':[0,0,0],'spacing_xyz_mm':[1,1,1]},seeds)
    assert np.array([b['center_lps_mm'] for b in balls])==pytest.approx(np.array(truth),abs=.15)
    with pytest.raises(ValueError,match='duplicate or overlapping'):
        fit_balls(volume,{'origin_lps_mm':[0,0,0],'spacing_xyz_mm':[1,1,1]},[seeds[0],{**seeds[0],'id':'BB02'},seeds[2]])

def ct_fixture(folder,zs=(0,1,2)):
    series,frame=generate_uid(),generate_uid()
    for i,z in enumerate(zs):
        d=Dataset();d.file_meta=FileMetaDataset();d.file_meta.TransferSyntaxUID=ExplicitVRLittleEndian
        d.SOPClassUID=CTImageStorage;d.SOPInstanceUID=generate_uid();d.file_meta.MediaStorageSOPClassUID=d.SOPClassUID;d.file_meta.MediaStorageSOPInstanceUID=d.SOPInstanceUID
        d.is_little_endian=True;d.is_implicit_VR=False;d.Modality='CT';d.SeriesInstanceUID=series;d.FrameOfReferenceUID=frame
        d.PatientPosition='HFS';d.Rows=d.Columns=8;d.PixelSpacing=[1,1];d.ImagePositionPatient=[0,0,z];d.ImageOrientationPatient=[1,0,0,0,1,0]
        d.RescaleSlope=2;d.RescaleIntercept=-1000;d.SamplesPerPixel=1;d.PhotometricInterpretation='MONOCHROME2';d.BitsAllocated=d.BitsStored=16;d.HighBit=15;d.PixelRepresentation=0;d.PixelData=np.full((8,8),600,dtype=np.uint16).tobytes()
        d.save_as(folder/f'{i}.dcm',write_like_original=False)
    plan=Dataset();plan.FrameOfReferenceUID=frame
    return plan

def test_ct_scaling_and_reference_frame(tmp_path):
    plan=ct_fixture(tmp_path);volume,grid,_=load_ct(tmp_path,plan)
    assert np.all(volume==200);assert grid['spacing_xyz_mm']==[1,1,1]
    plan.FrameOfReferenceUID=generate_uid()
    with pytest.raises(ValueError,match='FrameOfReferenceUID'):load_ct(tmp_path,plan)

def test_missing_slice_rejected(tmp_path):
    plan=ct_fixture(tmp_path,(0,1,3))
    with pytest.raises(ValueError,match='irregular CT slices'):load_ct(tmp_path,plan)
