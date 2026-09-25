"""CT-positioned static MultiWLT: expected versus observed relative BB position.

Couch encoders describe the positioning correction, not a residual phantom
rotation. The caller must explicitly confirm registration to the planned CT
pose. No pose is fitted to the MV images and no measured residual is removed.
"""
from datetime import datetime
import csv
import hashlib
import json
from pathlib import Path

import numpy as np
import pydicom
from scipy import ndimage
from scipy.optimize import linear_sum_assignment
from pylinac.core.image import ArrayImage
from pylinac.metrics.image import GlobalSizedFieldLocator, SizedDiskLocator
from routine_core import angle_delta, mlc_to_panel, project_hfs, correct_vector
from routine_images import image_geometry, image_pixels, pixel_to_panel, panel_to_pixel, _field_edges
from routine_workflow import load_profile, sha256, write_json


def plan_reference(ds):
    refs=getattr(ds,'ReferencedRTPlanSequence',[])
    if len(refs)!=1 or not getattr(refs[0],'ReferencedSOPInstanceUID',None):
        raise ValueError('Exactly one RTPLAN reference is required.')
    return hashlib.sha256(str(refs[0].ReferencedSOPInstanceUID).encode()).hexdigest()


def record_evidence(folder, plan, expected_ref, beam_numbers):
    """Corroborate source aperture, never replace it with delivered leaf positions."""
    if not folder:raise ValueError('Different plan identity: bind the returned RTPLAN export or provide matching delivery records.')
    source={int(b.BeamNumber):b for b in plan.BeamSequence};found={}
    for path in sorted(Path(folder).glob('*.dcm')):
        ds=pydicom.dcmread(path,stop_before_pixels=True)
        if str(getattr(ds,'Modality',''))!='RTRECORD':continue
        if plan_reference(ds)!=expected_ref:continue
        for session in ds.TreatmentSessionBeamSequence:
            n=int(session.ReferencedBeamNumber)
            if n not in beam_numbers:continue
            if n in found:raise ValueError('Multiple delivery records for the same field; select a single session.')
            beam=source[n];cp=beam.ControlPointSequence[0]
            if str(session.BeamName)!=str(beam.BeamName) or str(session.BeamType)!='STATIC':raise ValueError('Beam name/type does not match the reference plan.')
            if str(session.TreatmentTerminationStatus)!='NORMAL':raise ValueError('Delivery did not terminate normally.')
            if str(ds.TreatmentMachineSequence[0].TreatmentMachineName)!=str(beam.TreatmentMachineName):raise ValueError('Machine in the delivery record does not match.')
            planned={str(d.RTBeamLimitingDeviceType).replace('ASYM',''):np.asarray(d.LeafJawPositions,float) for d in cp.BeamLimitingDevicePositionSequence}
            maximum=0.
            for delivered in session.ControlPointDeliverySequence:
                devices={str(d.RTBeamLimitingDeviceType).replace('ASYM',''):np.asarray(d.LeafJawPositions,float) for d in delivered.BeamLimitingDevicePositionSequence}
                if planned.keys()!=devices.keys():raise ValueError('MLC/jaw types differ.')
                for kind in planned:
                    if planned[kind].shape!=devices[kind].shape:raise ValueError('Leaf counts differ.')
                    error=float(np.max(np.abs(planned[kind]-devices[kind])))
                    if not np.isfinite(error) or error>.05:raise ValueError('Recorded aperture differs from the reference plan by more than 0.05 mm.')
                    maximum=max(maximum,error)
                for key in ['GantryAngle','BeamLimitingDeviceAngle']:
                    if hasattr(delivered,key) and angle_delta(float(getattr(delivered,key)),float(getattr(cp,key)))>.1:raise ValueError('Recorded angle does not match.')
                if hasattr(delivered,'NominalBeamEnergy') and abs(float(delivered.NominalBeamEnergy)-float(cp.NominalBeamEnergy))>.01:raise ValueError('Energy does not match.')
            found[n]={'record_sha256':sha256(path),'max_device_difference_mm':maximum}
    if set(found)!=set(beam_numbers):raise ValueError('Matching delivery records are required for all fields.')
    return found


def expected_vector(ball, reference, beam, target, gantry, collimator):
    """Actual beam axes, planned CT pose; do not apply couch setup correction twice."""
    bb=project_hfs(ball['center_lps_mm'],reference['iso_lps_mm'],gantry,0,beam['couch_deg'],beam['sad_mm'])
    opening=mlc_to_panel(target['center_mlc_mm'],collimator)
    return bb-opening


def measure_local(pixels,geometry,field_panel,collimator,size,diameter):
    """Opposing 50% edge centres; independent disk detection around measured field."""
    step=min(geometry['pixel_iso_mm']);axis=np.arange(-17,17+step/2,step)
    xx,yy=np.meshgrid(axis,axis)
    local=np.stack([xx,yy],axis=-1)
    c=np.deg2rad(collimator);rotation=np.array([[np.cos(c),-np.sin(c)],[np.sin(c),np.cos(c)]])
    ij=panel_to_pixel(local@rotation.T+field_panel,geometry)
    if np.any(ij<0) or np.any(ij[...,0]>pixels.shape[0]-1) or np.any(ij[...,1]>pixels.shape[1]-1):raise ValueError('Search window is outside the detector.')
    patch=ndimage.map_coordinates(pixels,[ij[...,0],ij[...,1]],order=1)
    edge,size_found,spread=_field_edges(patch,axis,axis,*size)
    if np.linalg.norm(edge)>.7:raise ValueError('Pylinac area centroid and edge centre disagree (>0.7 mm).')
    image=ArrayImage(patch,dpi=25.4/step,sid=1000)
    bb=image.compute(SizedDiskLocator.from_center_physical(expected_position_mm=(0,0),search_window_mm=(14,14),
        radius_mm=diameter/2,radius_tolerance_mm=.8,invert=True))
    if len(bb)!=1:raise ValueError('No unique ball detected.')
    ball_local=np.array([axis[0]+bb[0].x*step,axis[0]+bb[0].y*step])
    clearance=min(np.asarray(size_found)/2-np.abs(ball_local-edge))-diameter/2
    if clearance<.7:raise ValueError('Ball is too close to the field edge.')
    fc=field_panel+rotation@edge;bc=field_panel+rotation@ball_local
    return {'field_panel_mm':fc.tolist(),'ball_panel_mm':bc.tolist(),
        'measured_field_size_mm':size_found,'edge_profile_spread_mm':spread,
        'centroid_edge_difference_mm':float(np.linalg.norm(edge)),
        'field_method_review':bool(np.linalg.norm(edge)>.5),
        'core_edge_clearance_mm':float(clearance)},patch,axis


def analyse_registered_folder(image_folder,profile_path,output_root,*,positioned_in_ct=False,records_folder=None):
    if not positioned_in_ct:raise ValueError('Image-guided positioning to the CT reference pose must be confirmed.')
    ref,beams,plan=load_profile(profile_path)
    if len(ref['balls'])!=3:raise ValueError('This detector supports three balls per image.')
    datasets=[]
    for path in sorted(Path(image_folder).glob('*.dcm')):
        ds=pydicom.dcmread(path)
        if str(getattr(ds,'Modality',''))!='RTIMAGE':raise ValueError('Only RTIMAGE files are expected in the MV folder.')
        datasets.append((path,ds,sha256(path)))
    if len(datasets)!=len(beams):raise ValueError('Exactly one MV image is required per reference field.')
    refs={plan_reference(d) for _,d,_ in datasets}
    if len(refs)!=1:raise ValueError('Images reference different plans.')
    actual_ref=refs.pop();numbers=[int(d.ReferencedBeamNumber) for _,d,_ in datasets]
    if len(set(numbers))!=len(numbers) or set(numbers)!={b['number'] for b in beams}:raise ValueError('Beam numbers are missing or duplicated.')
    evidence={} if actual_ref==ref['qa_plan_sop_hash'] else record_evidence(records_folder,plan,actual_ref,numbers)
    if any(not hasattr(d,k) for _,d,_ in datasets for k in ['PatientSupportAngle','TableTopPitchAngle','TableTopRollAngle']):raise ValueError('All couch angles must be documented.')
    poses=np.array([[float(getattr(d,k)) for k in ['PatientSupportAngle','TableTopPitchAngle','TableTopRollAngle']] for _,d,_ in datasets])
    planned_couch={b['number']:b['couch_deg'] for b in beams}
    # A planned couch rotation is a measurement angle. Only its difference from
    # the encoder is a common setup correction; it must remain stable.
    poses[:,0]-=np.array([planned_couch[int(d.ReferencedBeamNumber)] for _,d,_ in datasets])
    if any(angle_delta(a,b)>.05 for pose in poses for a,b in zip(pose,poses[0])):raise ValueError('Couch position changed between images; no common setup state.')
    output=Path(output_root)/('multiwlt_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));output.mkdir(parents=True,exist_ok=False)
    result={'schema_version':1,'mode':'ct_positioned_multiwlt','status':'RESEARCH_EVALUATION',
        'reference_status':'same_plan_identity' if not evidence else 'record_supported_source_plan',
        'reference_note':'Expected geometry from the CT and source reference plan, corroborated by delivery records. Return export of the imported RTPLAN remains pending.' if evidence else 'Image references match the geometrically checked reference profile.',
        'positioning':'User-confirmed image-guided CT reference pose; couch values describe setup corrections, not additional residual rotations to apply.',
        'no_pose_fit_to_mv':True,'synthetic':False,'profile_sha256':sha256(profile_path),'plan_sha256':ref['qa_plan_sha256'],
        'record_evidence':evidence,'clinical_assessment':'No clinical tolerance decision; measurement uncertainty still requires validation.',
        'images':[],'output_folder':str(output)}
    fields={f['beam_number']:f for f in ref['fields']};beammap={b['number']:b for b in beams};balls={b['id']:b for b in ref['balls']}
    for path,ds,digest in sorted(datasets,key=lambda item:int(item[1].ReferencedBeamNumber)):
        beam=beammap[int(ds.ReferencedBeamNumber)];field=fields[beam['number']]
        g=float(ds.GantryAngle);c=float(ds.BeamLimitingDeviceAngle)
        if angle_delta(g,beam['gantry_deg'])>.1 or angle_delta(c,beam['collimator_deg'])>.1:raise ValueError('Image angle does not match the reference field.')
        geometry=image_geometry(ds,beam['sad_mm'],positioned_in_ct=True);pixels=image_pixels(ds)
        result['synthetic']=result['synthetic'] or geometry['synthetic']
        if not np.isclose(*geometry['pixel_iso_mm'],rtol=1e-5):raise ValueError('This detector requires square pixels.')
        image=ArrayImage(pixels-pixels.min(),dpi=25.4/min(geometry['pixel_iso_mm']),sid=1000)
        detected=image.compute(GlobalSizedFieldLocator.from_physical(field_width_mm=20,field_height_mm=20,field_tolerance_mm=5,min_number=3,max_number=3))
        centres=[pixel_to_panel([p.y,p.x],geometry) for p in detected]
        planned=[mlc_to_panel(t['center_mlc_mm'],c) for t in field['targets']]
        costs=np.array([[np.linalg.norm(p-f) for f in centres] for p in planned]);ii,jj=linear_sum_assignment(costs)
        if max(costs[ii,jj])>3:raise ValueError('Subfields do not uniquely match the reference plan (3 mm search limit).')
        if any(sum(row<3)!=1 for row in costs):raise ValueError('Ambiguous subfield assignment.')
        assignment=dict(zip(ii,jj))
        entry={'beam_number':beam['number'],'gantry_deg':g,'collimator_deg':c,
            'synthetic':geometry['synthetic'],
            'planned_couch_deg':beam['couch_deg'],'analysis_group':field.get('analysis_group','all'),
            'source_sha256':digest,'couch_encoder_deg':float(ds.PatientSupportAngle),
            'pitch_encoder_deg':float(ds.TableTopPitchAngle),'roll_encoder_deg':float(ds.TableTopRollAngle),
            'time':str(getattr(ds,'AcquisitionTime','')),'targets':[]}
        for i,t in enumerate(field['targets']):
            ball=balls[t['id']];row={'id':t['id'],'status':'invalid'}
            try:
                measured,_,_=measure_local(pixels,geometry,centres[assignment[i]],c,t['size_mm'],ball['fitted_diameter_mm'])
                fc=np.array(measured['field_panel_mm']);bc=np.array(measured['ball_panel_mm'])
                expected=expected_vector(ball,ref,beam,t,g,c)
                row.update(measured,**correct_vector(bc-fc,expected),
                    expected_ball_panel_mm=(fc+expected).tolist(),status='measured',
                    source_expected_vector_mm=t['expected_vector_panel_mm'],distance_from_iso_mm=ball['distance_from_iso_mm'])
            except ValueError as exc:row['reason']=str(exc)
            entry['targets'].append(row)
        result['images'].append(entry)
        if sha256(path)!=digest:raise ValueError('Source file changed during analysis.')
        from routine_registered_report import plot_field
        entry['figure']=plot_field(entry,pixels,geometry,output)
    valid=[t for im in result['images'] for t in im['targets'] if t['status']=='measured']
    result.update(valid_count=len(valid),expected_count=sum(len(f['targets']) for f in ref['fields']),
        max_extra_mm=max((t['distance_mm'] for t in valid),default=None))
    if len(valid)!=result['expected_count']:result['status']='INCOMPLETE'
    result['field_method_review']=[{'beam':im['beam_number'],'ball':t['id'],'difference_mm':t['centroid_edge_difference_mm']}
        for im in result['images'] for t in im['targets'] if t.get('field_method_review')]
    if result['field_method_review'] and result['status']!='INCOMPLETE':result['status']='REVIEW_FIELD_METHOD'
    from routine_spheres import analyse_spheres,plot_spheres
    result['spheres']=analyse_spheres(result,ref,beams)
    result['sphere_groups']={}
    for group in sorted({im['analysis_group'] for im in result['images']}):
        subset={**result,'images':[im for im in result['images'] if im['analysis_group']==group]}
        result['sphere_groups'][group]=analyse_spheres(subset,ref,beams)
    plot_spheres(result['spheres'],output/'Ray_Envelopes.png')
    from routine_registered_report import write_report
    write_report(result,output)
    write_json(output/'result.json',result)
    with (output/'results.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        w=csv.writer(stream,delimiter=';');w.writerow(['Gantry','BB','Expected_X_mm','Expected_Y_mm','Observed_X_mm','Observed_Y_mm','Extra_X_mm','Extra_Y_mm','Extra_Magnitude_mm'])
        for im in result['images']:
            for t in im['targets']:
                if t['status']=='measured':w.writerow([im['gantry_deg'],t['id'],*t['expected_mm'],*t['measured_mm'],*t['residual_mm'],t['distance_mm']])
    return result
