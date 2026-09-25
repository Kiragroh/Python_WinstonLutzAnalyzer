"""Fit CT-visible balls and derive expected offsets for your own static RTPLAN.

Read-only input files. Writes a LOCAL research profile, a byte-identical plan
copy and review plots. It does not adapt treatment delivery or certify a phantom.
"""
import argparse
import csv
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import numpy as np
import pydicom
from routine_core import finite,fit_ct_ball,read_static_beams,project_hfs,ball_magnification,mlc_to_panel
from routine_workflow import load_profile,sha256,write_json


def load_ct(folder,plan):
    files=[]
    for p in sorted(Path(folder).rglob('*.dcm')):
        ds=pydicom.dcmread(p,stop_before_pixels=True)
        if getattr(ds,'Modality','')=='CT':files.append((p,ds))
    if len(files)<3:raise ValueError('At least three conventional CT slices are required.')
    if len({str(d.SeriesInstanceUID) for _,d in files})!=1:raise ValueError('Select exactly one CT series.')
    if len({str(d.SOPInstanceUID) for _,d in files})!=len(files):raise ValueError('Duplicate CT instances.')
    if not getattr(plan,'FrameOfReferenceUID',None) or {str(d.FrameOfReferenceUID) for _,d in files}!={str(plan.FrameOfReferenceUID)}:
        raise ValueError('CT and RTPLAN must share their FrameOfReferenceUID; do not relabel them to bypass this check.')
    files.sort(key=lambda item:float(item[1].ImagePositionPatient[2]))
    first=files[0][1];spacing=finite(first.PixelSpacing,2);origin=finite(first.ImagePositionPatient,3)
    positions=[]
    for _,d in files:
        if getattr(d,'PatientPosition','')!='HFS' or int(getattr(d,'NumberOfFrames',1))!=1:
            raise ValueError('Only conventional single-frame HFS CT is supported.')
        if not np.allclose(finite(d.ImageOrientationPatient,6),[1,0,0,0,1,0],atol=1e-6,rtol=0):
            raise ValueError('Only axial LPS-aligned CT is supported; adapt the geometry implementation for other orientations.')
        if (d.Rows,d.Columns)!=(first.Rows,first.Columns) or not np.allclose(d.PixelSpacing,spacing,atol=1e-6,rtol=0) or not np.allclose(d.ImagePositionPatient[:2],origin[:2],atol=.001,rtol=0):
            raise ValueError('Inconsistent CT grid.')
        positions.append(float(d.ImagePositionPatient[2]))
    dz=np.diff(positions)
    if np.any(spacing<=0) or np.any(dz<=0) or not np.allclose(dz,dz[0],atol=.001,rtol=0):
        raise ValueError('Missing, duplicate or irregular CT slices.')
    volume=[];digest=hashlib.sha256()
    for p,header in files:
        before=sha256(p);d=pydicom.dcmread(p)
        slope,intercept=finite([d.RescaleSlope,d.RescaleIntercept])
        if slope<=0:raise ValueError('Positive HU rescale slope is required.')
        volume.append(d.pixel_array.astype(np.float32)*slope+intercept)
        if sha256(p)!=before:raise ValueError('CT changed during reading.')
        digest.update(bytes.fromhex(before))
    grid={'origin_lps_mm':origin.tolist(),'spacing_xyz_mm':[float(spacing[1]),float(spacing[0]),float(dz[0])],
          'shape_zyx':[len(files),int(first.Rows),int(first.Columns)]}
    return np.stack(volume),grid,digest.hexdigest()


def fit_balls(volume,grid,seeds):
    if len(seeds)!=3 or len({s['id'] for s in seeds})!=3:raise ValueError('Exactly three uniquely named balls are required.')
    balls=[]
    for seed in seeds:
        fit=fit_ct_ball(volume,grid['origin_lps_mm'],grid['spacing_xyz_mm'],seed['approx_center_lps_mm'],float(seed['nominal_diameter_mm']))
        balls.append({'id':seed['id'],**fit})
    for a,b in itertools.combinations(balls,2):
        if np.linalg.norm(np.array(a['center_lps_mm'])-b['center_lps_mm'])<(a['diameter_mm']+b['diameter_mm'])/2:
            raise ValueError('Seeds selected duplicate or overlapping balls.')
    return balls


def derive_reference(plan,balls,minimum_clearance_mm=1.):
    if not np.isfinite(minimum_clearance_mm) or minimum_clearance_mm<1:
        raise ValueError('At least 1 mm nominal geometric clearance is required (not a clinical tolerance).')
    beams=read_static_beams(plan);iso=np.array(beams[0]['iso_lps_mm']);sad=beams[0]['sad_mm'];fields=[]
    for b in beams:
        if not np.allclose(b['iso_lps_mm'],iso,atol=.001,rtol=0) or abs(b['sad_mm']-sad)>.001:
            raise ValueError('One isocentre and SAD are required.')
        if len(b['apertures'])!=3 or any(not a['rectangular'] for a in b['apertures']):
            raise ValueError('Each beam needs exactly three separate rectangular openings; adapt the field/detection logic otherwise.')
        targets=[];used=set()
        for ball in balls:
            q=project_hfs(ball['center_lps_mm'],iso,b['gantry_deg'],b['collimator_deg'],b['couch_deg'],sad)
            diameter=ball['diameter_mm']*ball_magnification(ball['center_lps_mm'],iso,b['gantry_deg'],b['couch_deg'],sad)
            candidates=[]
            for i,a in enumerate(b['apertures']):
                x0,y0,x1,y1=a['bounds_mlc_mm']
                clearance=min(q[0]-x0,x1-q[0],q[1]-y0,y1-q[1])-diameter/2
                if clearance>=minimum_clearance_mm:candidates.append((i,a,float(clearance)))
            if len(candidates)!=1 or candidates[0][0] in used:
                raise ValueError(f'Beam {b["number"]}, {ball["id"]}: no unique opening with the requested ball-edge clearance. Change the plan/logic before analysis.')
            i,a,clearance=candidates[0];used.add(i);bounds=a['bounds_mlc_mm'];expected=q-a['center_mlc_mm']
            size=[bounds[2]-bounds[0],bounds[3]-bounds[1]]
            # The current detector searches three approximately 20-mm rectangles.
            if any(v<15 or v>25 for v in size):
                raise ValueError('Opening size outside the current 15–25 mm detector range; adapt and validate detection first.')
            projected_core=ball['fitted_diameter_mm']*ball_magnification(ball['center_lps_mm'],iso,b['gantry_deg'],b['couch_deg'],sad)
            if max(abs(expected))+projected_core/2>6.5:
                raise ValueError('Ball outside the current 14-mm detection window; adapt and validate detection first.')
            targets.append({'id':ball['id'],'projected_mlc_mm':q.tolist(),'projected_diameter_mm':diameter,
                'center_mlc_mm':a['center_mlc_mm'],'bounds_mlc_mm':bounds,'size_mm':size,
                'expected_vector_mlc_mm':expected.tolist(),'expected_vector_panel_mm':mlc_to_panel(expected,b['collimator_deg']).tolist(),
                'edge_clearance_mm':clearance})
        fields.append({'beam_number':b['number'],'beam_name':b['name'],'gantry_deg':b['gantry_deg'],
            'collimator_deg':b['collimator_deg'],'couch_deg':b['couch_deg'],'targets':targets})
    balls=[{**ball,'distance_from_iso_mm':float(np.linalg.norm(np.array(ball['center_lps_mm'])-iso))} for ball in balls]
    return {'schema_version':1,'patient_position':'HFS','iso_lps_mm':iso.tolist(),'sad_mm':sad,'balls':balls,'fields':fields,
            'status':'RESEARCH_PROFILE_REQUIRES_LOCAL_REVIEW','nominal_clearance_requirement_mm':minimum_clearance_mm}


def compare_layout(balls,baseline):
    lookup={b['id']:b for b in baseline['balls']}
    if set(lookup)!={b['id'] for b in balls}:raise ValueError('Ball IDs must correspond to the comparison reference.')
    pairs=[]
    for a,b in itertools.combinations(balls,2):
        measured=float(np.linalg.norm(np.array(a['center_lps_mm'])-b['center_lps_mm']))
        original=float(np.linalg.norm(np.array(lookup[a['id']]['center_lps_mm'])-lookup[b['id']]['center_lps_mm']))
        pairs.append({'pair':a['id']+'–'+b['id'],'reference_distance_mm':original,'own_distance_mm':measured,'difference_mm':measured-original})
    return {'pairs':pairs,'max_pairwise_difference_mm':max(abs(p['difference_mm']) for p in pairs),
        'assessment':'REVIEW_REQUIRED: pairwise distances compare the internal ball layout, not its orientation or isocentre. No automatic equivalence claim.'}


def save_review_plots(volume,grid,profile,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,3,figsize=(12,4))
    for ax,b in zip(axes,profile['balls']):
        idx=(np.array(b['center_lps_mm'])-grid['origin_lps_mm'])/grid['spacing_xyz_mm']
        z=int(round(idx[2]));x,y=idx[:2]
        ax.imshow(volume[z],cmap='gray',vmin=-300,vmax=3000);ax.plot(x,y,'+',color='red',ms=12)
        ax.set_xlim(x-18/grid['spacing_xyz_mm'][0],x+18/grid['spacing_xyz_mm'][0]);ax.set_ylim(y+18/grid['spacing_xyz_mm'][1],y-18/grid['spacing_xyz_mm'][1])
        ax.set_title(f'{b["id"]}: CT-visible centre\nCore Ø {b["fitted_diameter_mm"]:.2f} mm; threshold span {b["threshold_span_mm"]:.3f} mm');ax.set_axis_off()
    fig.tight_layout();fig.savefig(output/'ct_centres.png',dpi=150);plt.close(fig)


def inspect(ct,planpath,seedsfile,baselinepath,output,minimum_clearance_mm=1.):
    output=Path(output)
    if output.exists():raise ValueError('Use a new output folder; no existing results are overwritten.')
    planpath=Path(planpath);plan_hash=sha256(planpath);plan=pydicom.dcmread(planpath)
    if getattr(plan,'Modality','')!='RTPLAN':raise ValueError('Input plan must be RTPLAN.')
    volume,grid,ct_hash=load_ct(ct,plan)
    seeds=json.loads(Path(seedsfile).read_text(encoding='utf-8'))['balls']
    balls=fit_balls(volume,grid,seeds)
    # Fit and comparison are retained even if this plan cannot expose the balls.
    comparison=compare_layout(balls,json.loads(Path(baselinepath).read_text(encoding='utf-8')))
    output.mkdir(parents=True,exist_ok=False)
    write_json(output/'ball_layout_comparison.json',comparison)
    write_json(output/'ct_ball_fits.json',{'balls':balls,'ct_grid':grid,'ct_content_sha256':ct_hash})
    save_review_plots(volume,grid,{'balls':balls},output)
    try:profile=derive_reference(plan,balls,minimum_clearance_mm)
    except ValueError as exc:
        write_json(output/'PLAN_NOT_SUPPORTED.json',{'status':'NO_ANALYSIS_PROFILE_CREATED','reason':str(exc)})
        raise
    if sha256(planpath)!=plan_hash:raise ValueError('Source plan changed during inspection.')
    profile.update(ct_content_sha256=ct_hash,ct_grid=grid,qa_plan_file='local_plan.dcm',qa_plan_sha256=plan_hash,
                   qa_plan_sop_hash=hashlib.sha256(str(plan.SOPInstanceUID).encode()).hexdigest())
    shutil.copy2(planpath,output/'local_plan.dcm')
    write_json(output/'reference.json',profile);load_profile(output/'reference.json')
    with (output/'expected_offsets.csv').open('w',encoding='utf-8',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['beam','gantry','collimator','couch','ball','expected_panel_x_mm','expected_panel_y_mm','nominal_edge_clearance_mm'])
        for f in profile['fields']:
            for t in f['targets']:writer.writerow([f['beam_number'],f['gantry_deg'],f['collimator_deg'],f['couch_deg'],t['id'],*t['expected_vector_panel_mm'],t['edge_clearance_mm']])
    return {'status':'RESEARCH_PROFILE_REQUIRES_LOCAL_REVIEW','max_pairwise_difference_mm':comparison['max_pairwise_difference_mm'],
            'profile':str(output/'reference.json'),'note':'Review CT centre plots, nominal diameter, correspondences, field clearances and an independent known-shift acquisition.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ct',required=True);p.add_argument('--plan',required=True)
    p.add_argument('--seeds',required=True,help='JSON with three approximate CT-visible ball positions in DICOM LPS mm.')
    p.add_argument('--compare-reference',required=True);p.add_argument('--output',required=True)
    p.add_argument('--minimum-clearance-mm',type=float,default=1.)
    a=p.parse_args();print(json.dumps(inspect(a.ct,a.plan,a.seeds,a.compare_reference,a.output,a.minimum_clearance_mm),indent=2))
