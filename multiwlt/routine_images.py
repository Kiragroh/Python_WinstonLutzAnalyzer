"""Static RTIMAGE metrology; no clinical pass/fail without local thresholds.

Panel coordinates follow RTImageOrientation/Position. Patches are sampled in
the nominal MLC frame. Field and ball measurements are independent of the
planned target position except for bounded search and quality checks.
"""
from __future__ import annotations

import hashlib
import math
import numpy as np
from scipy import ndimage
from scipy.optimize import least_squares
from skimage.measure import find_contours
from routine_core import finite, angle_delta, mlc_to_panel, panel_to_mlc, correct_vector


def image_provenance(ds):
    raw=getattr(ds,'ImageType',[])
    image_type=[str(v).strip().upper() for v in raw] if not isinstance(raw,str) else raw.upper().split('\\')
    if len(image_type)<3 or image_type[2]!='PORTAL' or image_type[0] not in ('ORIGINAL','DERIVED'):
        raise ValueError('Nur RTIMAGEs mit eindeutigem PORTAL-Bildtyp werden unterstützt; DRR/Fluenzbilder sind keine Gerätemessung.')
    synthetic=('SYNTHETIC' in image_type[3:] or
               any('SYNTHETIC' in str(getattr(ds,key,'')).upper() for key in ['RTImageDescription','DerivationDescription']))
    derived=image_type[0]=='DERIVED'
    return {'image_type':image_type,'derived':derived,'synthetic':synthetic,
            'provenance_review':derived and not synthetic}


def image_geometry(ds,expected_sad,*,positioned_in_ct=False):
    provenance=image_provenance(ds)
    required=['RTImageSID','RadiationMachineSAD','ImagePlanePixelSpacing','RTImagePosition','RTImageOrientation','RTImagePlane','XRayImageReceptorAngle']
    if any(not hasattr(ds,key) or getattr(ds,key) is None for key in required):raise ValueError('RTIMAGE-Geometrie unvollständig (SID/SAD/Pixelmaß/Orientierung/Position).')
    if str(getattr(ds,'Modality',''))!='RTIMAGE' or str(ds.RTImagePlane)!='NORMAL' or int(getattr(ds,'NumberOfFrames',1))!=1:raise ValueError('Nur einzelne normale RTIMAGE-Projektionen werden unterstützt.')
    sid,sad=finite([ds.RTImageSID,ds.RadiationMachineSAD]);spacing=finite(ds.ImagePlanePixelSpacing,2)
    if sid<=0 or sad<=0 or np.any(spacing<=0) or abs(sad-expected_sad)>.5:raise ValueError('Ungültige oder zum Plan unpassende SAD/SID-/Pixelgeometrie.')
    receptor_angle=finite([ds.XRayImageReceptorAngle],1)[0]
    if angle_delta(receptor_angle,0)>.001:raise ValueError('Gedrehter Bildempfänger derzeit nicht unterstützt.')
    translation_present=hasattr(ds,'XRayImageReceptorTranslation')
    translation=finite(ds.XRayImageReceptorTranslation,3) if translation_present else np.array([0.,0.,sad-sid])
    if abs(translation[2]-(sad-sid))>.5:raise ValueError('Bildempfänger-Translation entlang der Strahlachse passt nicht zu SAD/SID.')
    for owner in [ds,*getattr(ds,'ExposureSequence',[])]:
        for key in ['TableTopPitchAngle','TableTopRollAngle','TableTopEccentricAngle','GantryPitchAngle']:
            # Physical couch encoder corrections are not residual CT-pose angles.
            # This exception is explicit and limited to a confirmed CT-positioned workflow.
            if positioned_in_ct and key in ('TableTopPitchAngle','TableTopRollAngle'):continue
            if hasattr(owner,key) and angle_delta(finite([getattr(owner,key)],1)[0],0)>.001:
                raise ValueError(f'Nicht-null {key} derzeit nicht unterstützt.')
    orientation=finite(ds.RTImageOrientation,6)
    if abs(orientation[2])+abs(orientation[5])>1e-6:raise ValueError('Bildorientierung liegt nicht in der Detektorebene.')
    matrix=np.column_stack([orientation[3:5]*spacing[0],orientation[:2]*spacing[1]])*(sad/sid)
    directions=np.column_stack([orientation[3:5],orientation[:2]])
    if not np.allclose(directions.T@directions,np.eye(2),atol=1e-6):raise ValueError('Nicht-orthogonale Bildorientierung.')
    # For NORMAL images at receptor angle zero, both x/y frames have the same axes.
    origin=(finite(ds.RTImagePosition,2)+translation[:2])*(sad/sid)
    return {'matrix':matrix,'origin':origin,'sid_mm':float(sid),'sad_mm':float(sad),
            'pixel_iso_mm':(spacing*sad/sid).tolist(),
            'receptor_translation_present':translation_present,
            'receptor_translation_mm':translation.tolist() if translation_present else None,
            'assumed_zero_lateral_receptor_translation':not translation_present,**provenance}


def pixel_to_panel(row_col,geometry):
    rc=np.asarray(row_col,float)
    return rc@geometry['matrix'].T+geometry['origin']


def panel_to_pixel(xy,geometry):
    return (np.asarray(xy,float)-geometry['origin'])@np.linalg.inv(geometry['matrix']).T


def match_beam(ds,beams,plan_sop_hash):
    refs=getattr(ds,'ReferencedRTPlanSequence',[])
    if plan_sop_hash is not None:
        if not refs or len(refs)!=1 or not str(getattr(refs[0],'ReferencedSOPInstanceUID','')).strip():
            raise ValueError('Routineauswertung benötigt genau eine vollständige RTPLAN-Referenz im Bild.')
        actual=hashlib.sha256(str(refs[0].ReferencedSOPInstanceUID).encode()).hexdigest()
        if actual!=plan_sop_hash:raise ValueError('Bild referenziert einen anderen RTPLAN als das Referenzprofil.')
        if getattr(ds,'ReferencedBeamNumber',None) is None:
            raise ValueError('Routineauswertung benötigt die ReferencedBeamNumber im Bild.')
    keys=['GantryAngle','BeamLimitingDeviceAngle','PatientSupportAngle']
    if any(not hasattr(ds,k) for k in keys):raise ValueError('Bildwinkel fehlen.')
    angles=finite([getattr(ds,k) for k in keys],3)
    candidates=[b for b in beams if all(angle_delta(v,b[k])<=1.0 for v,k in zip(angles,['gantry_deg','collimator_deg','couch_deg']))]
    if hasattr(ds,'ReferencedBeamNumber'):
        try:beam_number=int(ds.ReferencedBeamNumber)
        except (TypeError,ValueError,OverflowError) as exc:raise ValueError('Ungültige ReferencedBeamNumber im Bild.') from exc
        candidates=[b for b in candidates if b['number']==beam_number]
    if len(candidates)!=1:raise ValueError('Bild-/Feldzuordnung ist nicht eindeutig oder die Winkel passen nicht.')
    return candidates[0],('plan_reference' if plan_sop_hash is not None else 'angles_only')


def _crossing(axis,profile,expected,rising,half):
    outside=np.abs(axis)>half+3
    inside=np.abs(axis)<max(half-2,half*.6)
    low=float(np.median(profile[outside]));high=float(np.percentile(profile[inside],85))
    if high-low<=0:raise ValueError('Feldkante ohne ausreichenden Kontrast.')
    level=(high+low)/2
    values=profile-level
    indices=np.where((values[:-1]<=0)&(values[1:]>0) if rising else (values[:-1]>=0)&(values[1:]<0))[0]
    locations=[float(axis[i]+(axis[i+1]-axis[i])*(-values[i])/(values[i+1]-values[i])) for i in indices]
    locations=[v for v in locations if abs(v-expected)<4]
    if not locations:raise ValueError('Erwartete Feldkante nicht gefunden.')
    return min(locations,key=lambda v:abs(v-expected))


def _field_edges(patch,xaxis,yaxis,width,height):
    left=[];right=[];bottom=[];top=[]
    for y in np.linspace(-height*.35,height*.35,9):
        row=int(np.argmin(abs(yaxis-y)));profile=ndimage.gaussian_filter1d(patch[row],.7)
        try:
            left.append(_crossing(xaxis,profile,-width/2,True,width/2));right.append(_crossing(xaxis,profile,width/2,False,width/2))
        except ValueError:continue
    for x in np.linspace(-width*.35,width*.35,9):
        col=int(np.argmin(abs(xaxis-x)));profile=ndimage.gaussian_filter1d(patch[:,col],.7)
        try:
            bottom.append(_crossing(yaxis,profile,-height/2,True,height/2));top.append(_crossing(yaxis,profile,height/2,False,height/2))
        except ValueError:continue
    if min(map(len,[left,right,bottom,top]))<5:raise ValueError('Zu wenige stabile Feldkantenprofile.')
    scatter=max(float(np.percentile(v,90)-np.percentile(v,10)) for v in [left,right,bottom,top])
    if scatter>.65:raise ValueError('Feldkanten passen nicht zuverlässig zu einem Rechteck.')
    l,r,b,t=map(lambda v:float(np.median(v)),[left,right,bottom,top])
    return np.array([(l+r)/2,(b+t)/2]),[r-l,t-b],scatter


def measure_patch(patch,xaxis,yaxis,size_mm,expected_vector,diameter_mm,rectangular=True):
    patch=np.asarray(patch,float);xaxis=finite(xaxis);yaxis=finite(yaxis);expected=finite(expected_vector,2)
    width,height=finite(size_mm,2);x,y=np.meshgrid(xaxis,yaxis)
    if patch.shape!=x.shape or not np.all(np.isfinite(patch)):raise ValueError('Ungültiger Bildausschnitt.')
    if rectangular:
        centre,measured_size,edge_scatter=_field_edges(patch,xaxis,yaxis,width,height)
    else:
        # Diagnostic only for Paul's contour fields; never used for corrected routine metrics.
        low=float(np.percentile(patch,15));high=float(np.percentile(patch,85))
        binary=ndimage.binary_fill_holes(ndimage.gaussian_filter(patch,.7)>(low+high)/2)
        labels,n=ndimage.label(binary)
        if not n:raise ValueError('Kein Teilfeld gefunden.')
        sizes=np.bincount(labels.ravel());sizes[0]=0;mask=labels==int(np.argmax(sizes))
        centre=np.array([float(x[mask].mean()),float(y[mask].mean())]);measured_size=[float(np.ptp(x[mask])),float(np.ptp(y[mask]))];edge_scatter=None
    inner=(abs(x-centre[0])<measured_size[0]/2-1.5)&(abs(y-centre[1])<measured_size[1]/2-1.5)
    if not rectangular:
        inner=ndimage.distance_transform_edt(mask,sampling=(yaxis[1]-yaxis[0],xaxis[1]-xaxis[0]))>1.5
    if inner.sum()<50:raise ValueError('Zu wenig Innenfläche zur Kugelsuche.')
    bright=inner&(patch>=np.percentile(patch[inner],55))
    if bright.sum()<20:raise ValueError('Zu wenig Hintergrundsignal innerhalb des Feldes.')
    design=np.c_[np.ones(bright.sum()),x[bright],y[bright]]
    coeff=np.linalg.lstsq(design,patch[bright],rcond=None)[0]
    background=coeff[0]+coeff[1]*x+coeff[2]*y
    deficit=ndimage.gaussian_filter(background-patch,.65)
    contrast=float(np.percentile(deficit[inner],97))
    outside=~((abs(x-centre[0])<measured_size[0]/2+2)&(abs(y-centre[1])<measured_size[1]/2+2))
    beam_signal=float(np.median(background[inner])-np.median(patch[outside]))
    noise=float(np.median(abs((patch-background)[bright]-np.median((patch-background)[bright])))*1.4826)
    if contrast<max(.06*beam_signal,6*noise,1e-8):raise ValueError('Keine ausreichend kontrastreiche Kugel gefunden.')
    expected_centre=centre+expected
    fits=[]
    for fraction in (.35,.5,.65):
        search=np.where(inner,deficit,0.)
        candidates=[]
        for contour in find_contours(search,contrast*fraction):
            if len(contour)<20 or np.linalg.norm(contour[0]-contour[-1])>2:continue
            px=np.interp(contour[:,1],np.arange(len(xaxis)),xaxis);py=np.interp(contour[:,0],np.arange(len(yaxis)),yaxis)
            pts=np.c_[px,py];start=np.r_[pts.mean(0),diameter_mm/2]
            fit=least_squares(lambda p:np.linalg.norm(pts-p[:2],axis=1)-p[2],start,loss='soft_l1',f_scale=.15)
            bc=fit.x[:2];radius=fit.x[2];rms=float(np.sqrt(np.mean((np.linalg.norm(pts-bc,axis=1)-radius)**2)))
            # A narrow crescent can have a tiny circle-fit RMS without enclosing
            # that circle. Require at least 300 degrees of angular coverage.
            angles=np.sort(np.arctan2(pts[:,1]-bc[1],pts[:,0]-bc[0]))
            largest_gap=float(np.max(np.diff(np.r_[angles,angles[0]+2*np.pi])))
            if fit.success and largest_gap<np.pi/3 and .25*diameter_mm<radius<.75*diameter_mm and rms<.45 and np.linalg.norm(bc-expected_centre)<5:
                candidates.append((bc,radius,rms))
        if len(candidates)!=1:raise ValueError('Kugelerkennung ist mehrdeutig oder Form/Kontrast passen nicht.')
        fits.append(candidates[0])
    centres=np.array([f[0] for f in fits]);spread=max(float(np.linalg.norm(a-b)) for a in centres for b in centres)
    if spread>.35:raise ValueError('Kugelzentrum hängt zu stark vom Bildschwellwert ab.')
    bc=centres[1];clearance=min(measured_size[0]/2-abs(bc[0]-centre[0]),measured_size[1]/2-abs(bc[1]-centre[1]))-diameter_mm/2
    if clearance<.7:raise ValueError('Kugel ist zu nah am Feldrand oder angeschnitten.')
    return {'field_center_patch_mm':centre.tolist(),'ball_center_patch_mm':bc.tolist(),
            'measured_vector_mlc_mm':(bc-centre).tolist(),'measured_field_size_mm':measured_size,
            'field_size_error_mm':(np.array(measured_size)-[width,height]).tolist(),
            'edge_profile_spread_mm':edge_scatter,'ball_threshold_span_mm':spread,
            'ball_circle_fit_rms_mm':fits[1][2],'ball_contrast_to_noise':contrast/max(noise,1e-8),
            'apparent_ball_diameter_mm':float(2*fits[1][1]),'measured_edge_clearance_mm':float(clearance)}


def image_pixels(ds):
    """Decode once, with malformed/unsupported pixel data reported as image errors."""
    try:sign=int(getattr(ds,'PixelIntensityRelationshipSign',None))
    except (TypeError,ValueError,OverflowError) as exc:raise ValueError('Pixel-Intensitätsrichtung fehlt; keine automatische Polaritätsannahme.') from exc
    if sign not in (-1,1):raise ValueError('Pixel-Intensitätsrichtung fehlt; keine automatische Polaritätsannahme.')
    try:
        slope,intercept=finite([getattr(ds,'RescaleSlope',1),getattr(ds,'RescaleIntercept',0)],2)
        arr=ds.pixel_array.astype(float)*slope+intercept
    except (AttributeError,KeyError,TypeError,ValueError,RuntimeError,NotImplementedError,OSError) as exc:
        raise ValueError(f'Pixeldaten fehlen oder können nicht dekodiert werden ({type(exc).__name__}).') from exc
    if arr.ndim!=2:raise ValueError('Nur einzelne 2D-RTIMAGEs werden unterstützt.')
    if not np.all(np.isfinite(arr)):raise ValueError('Pixeldaten enthalten nicht endliche Werte.')
    return arr if sign==1 else -arr


def sample_target(ds,geometry,beam,target,rectangular=True,pixels=None):
    arr=image_pixels(ds) if pixels is None else pixels
    centre=np.array(target['center_mlc_mm']);size=target['size_mm'];step=min(geometry['pixel_iso_mm'])/1.5
    if not .03<=step<=.6:raise ValueError('Pixelgröße außerhalb des unterstützten Bereichs.')
    xaxis=np.arange(-size[0]/2-7,size[0]/2+7+step/2,step);yaxis=np.arange(-size[1]/2-7,size[1]/2+7+step/2,step)
    xx,yy=np.meshgrid(xaxis+centre[0],yaxis+centre[1]);c=math.radians(beam['collimator_deg'])
    panel=np.stack([xx*np.cos(c)-yy*np.sin(c),xx*np.sin(c)+yy*np.cos(c)],axis=-1)
    pixels=panel_to_pixel(panel,geometry)
    if np.any(pixels[...,0]<0) or np.any(pixels[...,1]<0) or np.any(pixels[...,0]>arr.shape[0]-1) or np.any(pixels[...,1]>arr.shape[1]-1):raise ValueError('Geplantes Teilfeld liegt außerhalb des Detektors.')
    patch=ndimage.map_coordinates(arr,[pixels[...,0],pixels[...,1]],order=1,mode='nearest')
    result=measure_patch(patch,xaxis,yaxis,size,target['expected_vector_mlc_mm'],target['projected_diameter_mm'],rectangular=rectangular)
    measured_panel=mlc_to_panel(result['measured_vector_mlc_mm'],beam['collimator_deg'])
    expected_panel=mlc_to_panel(target['expected_vector_mlc_mm'],beam['collimator_deg'])
    result.update(correct_vector(measured_panel,expected_panel))
    return result,patch,xaxis,yaxis
