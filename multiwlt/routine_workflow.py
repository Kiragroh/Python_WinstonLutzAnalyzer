"""Analysis-only reference loading and synthetic demo; extracted from the main project."""
from pathlib import Path
import hashlib,json
import numpy as np
import pydicom
from pydicom.dataset import Dataset,FileMetaDataset
from pydicom.sequence import Sequence
from pydicom.uid import ExplicitVRLittleEndian,generate_uid
from routine_core import finite,read_static_beams

def sha256(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()

def write_json(path,data):
    Path(path).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')

def load_profile(path):
    from routine_core import project_hfs,mlc_to_panel
    profilepath=Path(path);reference=json.loads(profilepath.read_text(encoding='utf-8'))
    if reference.get('schema_version')!=1 or reference.get('patient_position')!='HFS':raise ValueError('Nicht unterstütztes Referenzprofil.')
    planpath=(profilepath.parent/reference['qa_plan_file']).resolve()
    if planpath.parent!=profilepath.parent.resolve():raise ValueError('Plan muss neben dem Referenzprofil liegen.')
    if sha256(planpath)!=reference['qa_plan_sha256']:raise ValueError('QA-RTPLAN wurde seit der Referenzerstellung verändert.')
    plan=pydicom.dcmread(planpath,stop_before_pixels=True);beams=read_static_beams(plan)
    if hashlib.sha256(str(plan.SOPInstanceUID).encode()).hexdigest()!=reference['qa_plan_sop_hash']:raise ValueError('Planidentität passt nicht zum Profil.')
    if len(beams)!=len(reference['fields']):raise ValueError('Anzahl der Prüffelder passt nicht zum Profil.')
    balls={b['id']:b for b in reference['balls']}
    for beam,field in zip(beams,reference['fields']):
        if beam['number']!=field['beam_number'] or len(beam['apertures'])!=len(field['targets']):raise ValueError('Feld-/Teilfeldanzahl stimmt nicht.')
        if any(abs(beam[k]-field[k])>1e-5 for k in ['gantry_deg','collimator_deg','couch_deg']):raise ValueError('Planwinkel und Referenzwinkel unterscheiden sich.')
        if not np.allclose(beam['iso_lps_mm'],reference['iso_lps_mm'],atol=.001) or abs(beam['sad_mm']-reference['sad_mm'])>.001:raise ValueError('Plan-Isozentrum oder SAD passt nicht zur Referenz.')
        used=set()
        for target in field['targets']:
            if target['id'] not in balls:raise ValueError('Unbekannte Kugelidentität im Profil.')
            projected=project_hfs(balls[target['id']]['center_lps_mm'],reference['iso_lps_mm'],beam['gantry_deg'],beam['collimator_deg'],beam['couch_deg'],reference['sad_mm'])
            distances=[np.linalg.norm(np.array(a['center_mlc_mm'])-target['center_mlc_mm']) for a in beam['apertures']]
            idx=int(np.argmin(distances));aperture=beam['apertures'][idx]
            if idx in used or distances[idx]>.001 or not aperture['rectangular']:raise ValueError('Routineversion benötigt eindeutig zugeordnete Rechtecköffnungen.')
            used.add(idx)
            expected=projected-aperture['center_mlc_mm']
            if not np.allclose(expected,target['expected_vector_mlc_mm'],atol=.001):raise ValueError('Sollvektor stimmt nicht mit CT und Plan überein.')
            if not np.allclose(aperture['bounds_mlc_mm'],target['bounds_mlc_mm'],atol=.001):raise ValueError('Öffnungsgrenzen stimmen nicht mit dem Plan überein.')
            if not np.allclose(mlc_to_panel(expected,beam['collimator_deg']),target['expected_vector_panel_mm'],atol=.001):raise ValueError('Sollvektor-Konvention ist inkonsistent.')
    return reference,beams,plan

def create_demo_images(profile_path,output_folder,shift_panel_mm=(.7,-.4)):
    """Synthetic data explicitly marked as such; no machine accuracy claim."""
    from scipy.ndimage import gaussian_filter
    from pydicom.uid import RTImageStorage
    reference,beams,plan=load_profile(profile_path);shift=finite(shift_panel_mm,2)
    output=Path(output_folder)
    if output.exists() and any(output.iterdir()):raise ValueError('Demo-Bildordner muss leer sein.')
    output.mkdir(parents=True,exist_ok=True)
    n=1024;spacing=.336;sid=1500.;sad=reference['sad_mm'];origin=np.array([-(n-1)*spacing/2,(n-1)*spacing/2])
    rows,cols=np.indices((n,n));xx=(origin[0]+cols*spacing)*sad/sid;yy=(origin[1]-rows*spacing)*sad/sid
    for field in reference['fields']:
        c=np.deg2rad(field['collimator_deg']);u=xx*np.cos(c)+yy*np.sin(c);v=-xx*np.sin(c)+yy*np.cos(c)
        fluence=np.full((n,n),200.,dtype=float)
        for target in field['targets']:
            x0,y0,x1,y1=target['bounds_mlc_mm'];mask=(u>=x0)&(u<=x1)&(v>=y0)&(v<=y1)
            fluence+=25000.*mask
            b=target['projected_mlc_mm'];bx=b[0]*np.cos(c)-b[1]*np.sin(c)+shift[0];by=b[0]*np.sin(c)+b[1]*np.cos(c)+shift[1]
            sphere=(xx-bx)**2+(yy-by)**2<=(target['projected_diameter_mm']*next(b['fitted_diameter_mm']/b['diameter_mm'] for b in reference['balls'] if b['id']==target['id'])/2)**2
            fluence-=12000.*sphere*mask
        arr=np.clip(gaussian_filter(fluence,.65)+np.random.default_rng(field['beam_number']).normal(0,10,(n,n)),0,65535).astype(np.uint16)
        d=Dataset();d.file_meta=FileMetaDataset();d.SOPClassUID=RTImageStorage;d.SOPInstanceUID=generate_uid();d.file_meta.MediaStorageSOPClassUID=d.SOPClassUID;d.file_meta.MediaStorageSOPInstanceUID=d.SOPInstanceUID;d.file_meta.TransferSyntaxUID=ExplicitVRLittleEndian
        d.Modality='RTIMAGE';d.PatientName='SYNTHETIC^MULTIWLT';d.PatientID='SYNTHETIC';d.ImageType=['DERIVED','SECONDARY','PORTAL','SYNTHETIC'];d.RTImageLabel=f'DEMO_{field["beam_number"]:02d}';d.RTImageDescription='SYNTHETIC image, not a machine measurement'
        d.DerivationDescription='SYNTHETIC MultiWLT algorithm demonstration; no acquired machine image'
        d.SeriesDescription='SYNTHETIC MultiWLT demo';d.ReportedValuesOrigin='PLAN'
        d.Rows=n;d.Columns=n;d.SamplesPerPixel=1;d.PhotometricInterpretation='MONOCHROME2';d.BitsAllocated=16;d.BitsStored=16;d.HighBit=15;d.PixelRepresentation=0;d.PixelData=arr.tobytes()
        d.PixelIntensityRelationship='LIN';d.PixelIntensityRelationshipSign=1;d.ImagePlanePixelSpacing=[spacing,spacing];d.RTImagePosition=origin.tolist();d.RTImageOrientation=[1,0,0,0,-1,0];d.RTImagePlane='NORMAL';d.XRayImageReceptorAngle=0;d.RadiationMachineSAD=sad;d.RTImageSID=sid
        d.TableTopPitchAngle=0;d.TableTopRollAngle=0;d.GantryAngle=field['gantry_deg'];d.BeamLimitingDeviceAngle=field['collimator_deg'];d.PatientSupportAngle=field['couch_deg'];d.ReferencedBeamNumber=field['beam_number']
        r=Dataset();r.ReferencedSOPClassUID=plan.SOPClassUID;r.ReferencedSOPInstanceUID=plan.SOPInstanceUID;d.ReferencedRTPlanSequence=Sequence([r]);d.is_little_endian=True;d.is_implicit_VR=False
        d.save_as(output/f'SYNTHETIC_{field["beam_number"]:02d}.dcm',write_like_original=False)
    write_json(output/'synthetic_truth.json',{'synthetic':True,'shift_panel_mm':shift.tolist(),'profile_sha256':sha256(profile_path)})
