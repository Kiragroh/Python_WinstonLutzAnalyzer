"""Static multi-target WLT geometry and phantom reference preparation.

HFS DICOM LPS only. Results in the isocentre plane, not target-local 3D error.
The geometric convention is explicit and never inferred by best fitting images.
"""
from __future__ import annotations

import math
import numpy as np
from scipy import ndimage
from scipy.optimize import least_squares
from skimage.measure import marching_cubes

VERSION = '0.2.0'


def finite(values, size=None):
    a = np.asarray(values, dtype=float)
    if not np.all(np.isfinite(a)) or (size is not None and a.shape != (size,)):
        raise ValueError('Geometrie enthält fehlende, ungültige oder nicht endliche Werte.')
    return a


def angle_delta(a, b):
    return abs((float(a) - float(b) + 180) % 360 - 180)


def project_hfs(point_lps, iso_lps, gantry, collimator, couch, sad):
    """Perspective projection to IEC MLC X/Y at isocentre.

    At G=C=T=0, MLC X points to patient left, MLC Y to superior,
    source is anterior. Positive depth is downstream of isocentre.
    """
    x, y, z = finite(point_lps, 3) - finite(iso_lps, 3)
    g, c, t, sad = finite([gantry, collimator, couch, sad])
    if sad <= 0:
        raise ValueError('SAD muss positiv sein.')
    g, c, t = np.deg2rad([g, c, t])
    xt = x * np.cos(t) - z * np.sin(t)
    zt = x * np.sin(t) + z * np.cos(t)
    xg = xt * np.cos(g) + y * np.sin(g)
    depth = y * np.cos(g) - xt * np.sin(g)
    if sad + depth <= 0:
        raise ValueError('Kugel liegt in oder hinter der Quelle.')
    magnification = sad / (sad + depth)
    return np.array([xg * np.cos(c) + zt * np.sin(c),
                     -xg * np.sin(c) + zt * np.cos(c)]) * magnification


def ball_magnification(point_lps, iso_lps, gantry, couch, sad):
    x, y, z = finite(point_lps, 3) - finite(iso_lps, 3)
    g, t = np.deg2rad([gantry, couch])
    depth = y * np.cos(g) - (x * np.cos(t) - z * np.sin(t)) * np.sin(g)
    if sad <= 0 or sad + depth <= 0:
        raise ValueError('Ungültige Quellengeometrie.')
    return float(sad / (sad + depth))


def mlc_to_panel(point, collimator):
    u, v = finite(point, 2)
    c = math.radians(float(collimator))
    return np.array([u * math.cos(c) - v * math.sin(c),
                     u * math.sin(c) + v * math.cos(c)])


def panel_to_mlc(point, collimator):
    return mlc_to_panel(point, -float(collimator))


def correct_vector(measured, expected):
    measured, expected = finite(measured, 2), finite(expected, 2)
    residual = measured - expected
    return {'measured_mm': measured.tolist(), 'expected_mm': expected.tolist(),
            'residual_mm': residual.tolist(), 'distance_mm': float(np.linalg.norm(residual)),
            'raw_distance_mm': float(np.linalg.norm(measured))}


def fit_ct_ball(volume, origin_lps, spacing_xyz, seed_lps, diameter_mm=8.0):
    """Fit a sphere to high-HU isosurfaces; assess threshold sensitivity.

    Volume order Z,Y,X. This entry point only accepts an axial LPS-aligned grid.
    Threshold spread is a robustness measure, not total localisation uncertainty.
    """
    vol = np.asarray(volume, dtype=float)
    origin, spacing, seed = finite(origin_lps, 3), finite(spacing_xyz, 3), finite(seed_lps, 3)
    if vol.ndim != 3 or np.any(spacing <= 0) or diameter_mm <= 0:
        raise ValueError('Ungültiges CT-Raster oder Kugelmaß.')
    half = max(diameter_mm, 8.)
    idx = (seed - origin) / spacing
    lo = np.maximum(0, np.floor(idx - half / spacing).astype(int))
    hi = np.minimum(np.array(vol.shape[::-1]), np.ceil(idx + half / spacing).astype(int) + 1)
    cut = vol[lo[2]:hi[2], lo[1]:hi[1], lo[0]:hi[0]]
    if cut.size == 0 or not np.all(np.isfinite(cut)):
        raise ValueError('Kugelposition außerhalb des CTs.')
    fits = []
    for threshold in (1500., 2000., 2500.):
        labels, n = ndimage.label(cut >= threshold)
        if n == 0:
            raise ValueError('Keine hochdichte Kugel am Referenzpunkt gefunden.')
        sizes = np.bincount(labels.ravel()); sizes[0] = 0
        label = int(np.argmax(sizes)); mask = labels == label
        if sizes[label] < 8 or any(np.any(mask.take(i, axis=ax)) for ax in range(3) for i in (0, -1)):
            raise ValueError('Kugelkomponente zu klein oder am Rand abgeschnitten.')
        # Isolate this component so neighbouring dense structures cannot move the fit.
        near = ndimage.binary_dilation(mask, iterations=2)
        isolated = np.where(near, cut, 0.)
        verts, _, _, _ = marching_cubes(isolated.astype(np.float32), level=threshold,
                                       spacing=tuple(spacing[::-1]))
        pts = verts[:, ::-1] + origin + lo * spacing
        start = np.r_[pts.mean(axis=0), diameter_mm / 2]
        fit = least_squares(lambda p: np.linalg.norm(pts - p[:3], axis=1) - p[3],
                            start, loss='soft_l1', f_scale=.25)
        centre, radius = fit.x[:3], float(fit.x[3])
        rms = float(np.sqrt(np.mean((np.linalg.norm(pts - centre, axis=1) - radius) ** 2)))
        if not fit.success or np.linalg.norm(centre - seed) > diameter_mm / 2 or not .6*diameter_mm < 2*radius < 1.5*diameter_mm or rms > .7:
            raise ValueError('Hochdichte Struktur passt nicht zuverlässig zur erwarteten Kugel.')
        fits.append({'threshold_hu': threshold, 'center_lps_mm': centre.tolist(),
                     'diameter_mm': 2*radius, 'surface_fit_rms_mm': rms})
    centres = np.array([f['center_lps_mm'] for f in fits])
    spread = max(float(np.linalg.norm(a-b)) for a in centres for b in centres)
    if spread > .5:
        raise ValueError('Kugellokalisation hängt zu stark vom CT-Schwellwert ab (>0,5 mm).')
    return {'center_lps_mm': fits[1]['center_lps_mm'], 'diameter_mm': float(diameter_mm),
            'fitted_diameter_mm': fits[1]['diameter_mm'], 'threshold_span_mm': spread,
            'threshold_centres': fits, 'method': '3D high-HU sphere surface fit; primary threshold 2000 HU',
            'uncertainty_note': 'Schwellwertspanne ist keine vollständige Messunsicherheit.'}


def make_rectangles(projected, projected_diameters, boundaries, size_mm=20., min_clearance_mm=3.):
    bounds = finite(boundaries)
    points = finite(projected)
    diameters = finite(projected_diameters)
    if bounds.ndim != 1 or np.any(np.diff(bounds) <= 0) or points.ndim != 2 or points.shape[1] != 2 or len(points) != len(diameters):
        raise ValueError('Ungültige Blattgrenzen oder Kugelprojektionen.')
    if not np.isfinite(size_mm) or size_mm <= 0 or np.any(diameters <= 0):
        raise ValueError('Ungültige Öffnungs- oder Kugelgröße.')
    n = len(bounds)-1
    a, b = np.zeros(n), np.zeros(n)
    occupied = set(); targets = []
    for point, diameter in zip(points, diameters):
        x, y = point
        bottom = int(np.argmin(np.abs(bounds - (y-size_mm/2))))
        top = int(np.argmin(np.abs(bounds - (y+size_mm/2))))
        if bottom >= top or x-size_mm/2 < -200 or x+size_mm/2 > 200:
            raise ValueError('Öffnung außerhalb des unterstützten MLC-Bereichs.')
        rows = set(range(bottom, top))
        if occupied.intersection(rows):
            raise ValueError('Mehrere Kugeln benötigen dieselben Blattreihen; Geometrie aufteilen.')
        occupied.update(rows)
        rect = [float(x-size_mm/2), float(bounds[bottom]), float(x+size_mm/2), float(bounds[top])]
        centre = [(rect[0]+rect[2])/2, (rect[1]+rect[3])/2]
        clearance = min(x-rect[0],rect[2]-x,y-rect[1],rect[3]-y)-diameter/2
        if clearance < min_clearance_mm:
            raise ValueError('Zu kleiner Abstand zwischen Kugel und Feldkante.')
        a[bottom:top], b[bottom:top] = rect[0], rect[2]
        targets.append({'projected_mlc_mm': point.tolist(), 'projected_diameter_mm': float(diameter),
                        'center_mlc_mm': centre, 'bounds_mlc_mm': rect,
                        'size_mm': [rect[2]-rect[0], rect[3]-rect[1]],
                        'expected_vector_mlc_mm': (point-centre).tolist(),
                        'edge_clearance_mm': float(clearance), 'leaf_indices': sorted(rows)})
    gaps = []
    for i, first in enumerate(targets):
        for second in targets[i+1:]:
            r, s = first['bounds_mlc_mm'], second['bounds_mlc_mm']
            dx=max(r[0]-s[2],s[0]-r[2],0);dy=max(r[1]-s[3],s[1]-r[3],0)
            gaps.append(math.hypot(dx,dy))
    if gaps and min(gaps)<5:
        raise ValueError('Teilfelder liegen näher als 5 mm zusammen.')
    rects=np.array([t['bounds_mlc_mm'] for t in targets])
    return {'targets':targets,'leaf_positions_mm':np.r_[a,b].tolist(),
            'jaw_x_mm':[float(rects[:,0].min()-1),float(rects[:,2].max()+1)],
            'jaw_y_mm':[float(rects[:,1].min()-1),float(rects[:,3].max()+1)],
            'min_gap_mm':min(gaps) if gaps else None}


def choose_field(reference, gantry, couch, boundaries, size_mm=20.):
    candidates=[]
    for collimator in range(0,180):
        points=[project_hfs(b['center_lps_mm'],reference['iso_lps_mm'],gantry,collimator,couch,reference['sad_mm']) for b in reference['balls']]
        diameters=[b['diameter_mm']*ball_magnification(b['center_lps_mm'],reference['iso_lps_mm'],gantry,couch,reference['sad_mm']) for b in reference['balls']]
        try:
            rect=make_rectangles(points,diameters,boundaries,size_mm)
        except ValueError:
            continue
        for target,ball in zip(rect['targets'],reference['balls']):
            target['id']=ball['id']
            target['expected_vector_panel_mm']=mlc_to_panel(target['expected_vector_mlc_mm'],collimator).tolist()
        clearance=min(t['edge_clearance_mm'] for t in rect['targets'])
        # Prefer reliable separation; do not choose by the measured result.
        score=min(rect['min_gap_mm'] or 100,30)+clearance-.1*max(np.linalg.norm(t['expected_vector_mlc_mm']) for t in rect['targets'])
        candidates.append((score,{**rect,'gantry_deg':float(gantry),'collimator_deg':float(collimator),
                                  'couch_deg':float(couch),'min_clearance_mm':clearance}))
    if not candidates:
        raise ValueError(f'Keine sichere Dreifeld-Geometrie für G={gantry}, T={couch}.')
    return max(candidates,key=lambda x:x[0])[1]


def aperture_components(boundaries, positions, jaws_x, jaws_y):
    bounds=finite(boundaries);pos=finite(positions);jx=finite(jaws_x,2);jy=finite(jaws_y,2)
    n=len(bounds)-1
    if len(pos)!=2*n or np.any(np.diff(bounds)<=0) or jx[0]>=jx[1] or jy[0]>=jy[1]:
        raise ValueError('Ungültige MLC- oder Backengeometrie.')
    rectangles=[]
    for i in range(n):
        x0=max(pos[i],jx[0]);x1=min(pos[n+i],jx[1]);y0=max(bounds[i],jy[0]);y1=min(bounds[i+1],jy[1])
        if x1-x0>.1 and y1>y0:rectangles.append([x0,y0,x1,y1])
    groups=[]
    for r in rectangles:
        touching=[i for i,g in enumerate(groups) if any(abs(s[3]-r[1])<1e-5 and min(s[2],r[2])-max(s[0],r[0])>=0 for s in g)]
        merged=[r]
        for i in reversed(touching):merged+=groups.pop(i)
        groups.append(merged)
    apertures=[]
    for group in groups:
        rect=np.array(group);areas=(rect[:,2]-rect[:,0])*(rect[:,3]-rect[:,1]);area=float(areas.sum())
        if area<10:continue
        bbox=[float(rect[:,0].min()),float(rect[:,1].min()),float(rect[:,2].max()),float(rect[:,3].max())]
        centre=np.average((rect[:,:2]+rect[:,2:])/2,axis=0,weights=areas)
        apertures.append({'center_mlc_mm':centre.tolist(),'bounds_mlc_mm':bbox,'rectangles':rect.tolist(),
                          'area_mm2':area,'rectangular':abs(area-(bbox[2]-bbox[0])*(bbox[3]-bbox[1]))<.05})
    return apertures


def read_static_beams(plan):
    beams=[]
    for beam in plan.BeamSequence:
        if str(beam.BeamType)!='STATIC':raise ValueError('Nur statische Felder werden unterstützt; Bogen nicht auswerten.')
        mlcs=[d for d in beam.BeamLimitingDeviceSequence if str(d.RTBeamLimitingDeviceType).startswith('MLC')]
        if len(mlcs)!=1 or str(mlcs[0].RTBeamLimitingDeviceType)!='MLCX':raise ValueError('Ein einzelner MLCX wird benötigt.')
        bounds=finite(mlcs[0].LeafPositionBoundaries).tolist()
        states=[];state={};devices={};rotations={}
        rotation_axes={'GantryAngle':'GantryRotationDirection',
                       'BeamLimitingDeviceAngle':'BeamLimitingDeviceRotationDirection',
                       'PatientSupportAngle':'PatientSupportRotationDirection',
                       'TableTopEccentricAngle':'TableTopEccentricRotationDirection',
                       'TableTopPitchAngle':'TableTopPitchRotationDirection',
                       'TableTopRollAngle':'TableTopRollRotationDirection',
                       'GantryPitchAngle':'GantryPitchRotationDirection'}
        required_rotations={rotation_axes[k] for k in ['GantryAngle','BeamLimitingDeviceAngle','PatientSupportAngle']}
        for cp in beam.ControlPointSequence:
            # Equal endpoint angles plus CW/CC mean a full rotation, not a static field.
            # Attributes absent at later control points retain their previous values.
            for angle,direction in rotation_axes.items():
                if hasattr(cp,angle):required_rotations.add(direction)
                if hasattr(cp,direction):rotations[direction]=str(getattr(cp,direction)).strip()
            for direction in required_rotations|rotations.keys():
                if rotations.get(direction)!='NONE':
                    raise ValueError(f'Feld ist nicht eindeutig statisch: Drehrichtung {direction} muss ausdrücklich NONE sein (danach Vererbung erlaubt).')
            for key in ['GantryAngle','BeamLimitingDeviceAngle','PatientSupportAngle','IsocenterPosition']:
                if hasattr(cp,key):state[key]=finite(getattr(cp,key)).copy()
            for key in ['TableTopPitchAngle','TableTopRollAngle']:
                if abs(float(getattr(cp,key,0)))>1e-5:raise ValueError('Nicht-null Tisch-Pitch/Roll derzeit nicht unterstützt.')
            for d in getattr(cp,'BeamLimitingDevicePositionSequence',[]):devices[str(d.RTBeamLimitingDeviceType)]=finite(d.LeafJawPositions).copy()
            if len(state)!=4:raise ValueError('Unvollständige statische Plangeometrie.')
            states.append(({k:v.copy() for k,v in state.items()},{k:v.copy() for k,v in devices.items()}))
        if len(states)<2:raise ValueError('Statisches Feld braucht mindestens zwei Control Points.')
        s0,d0=states[0]
        for s,d in states[1:]:
            if s.keys()!=s0.keys() or d.keys()!=d0.keys() or any(not np.allclose(s[k],s0[k],atol=1e-6,rtol=0) for k in s) or any(not np.allclose(d[k],d0[k],atol=1e-6,rtol=0) for k in d):
                raise ValueError('Feld ist nicht statisch: Control Points unterscheiden sich.')
        jawx=d0.get('ASYMX',d0.get('X'));jawy=d0.get('ASYMY',d0.get('Y'))
        if jawx is None or jawy is None or 'MLCX' not in d0:raise ValueError('MLC-/Backenpositionen fehlen.')
        weights=finite([cp.CumulativeMetersetWeight for cp in beam.ControlPointSequence])
        if abs(weights[0])>1e-8 or weights[-1]<=0 or np.any(np.diff(weights)<0):raise ValueError('Ungültige CumulativeMetersetWeights.')
        beams.append({'number':int(beam.BeamNumber),'name':str(beam.BeamName),
                      'gantry_deg':float(s0['GantryAngle']),'collimator_deg':float(s0['BeamLimitingDeviceAngle']),
                      'couch_deg':float(s0['PatientSupportAngle']),'iso_lps_mm':s0['IsocenterPosition'].tolist(),
                      'sad_mm':float(beam.SourceAxisDistance),'apertures':aperture_components(bounds,d0['MLCX'],jawx,jawy)})
    if not beams:raise ValueError('Keine statischen Prüffelder vorhanden.')
    return beams
