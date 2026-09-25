import numpy as np
import pytest
from routine_spheres import beam_basis,corrected_ray,envelope
from routine_core import project_hfs


@pytest.mark.parametrize('couch',[0,35,315])
def test_known_offset_of_offaxis_rays_recovers_sphere_centre(couch):
    ball=np.array([25.,-42.,70.]);iso=np.zeros(3);shift=np.array([.4,-.3,.2])
    origins=[];directions=[]
    for gantry in [20,105,195,285]:
        residual=project_hfs(ball,iso,gantry,0,couch,1000)-project_hfs(ball+shift,iso,gantry,0,couch,1000)
        o,d=corrected_ray(ball,iso,gantry,couch,1000,residual);origins.append(o);directions.append(d)
        basis=beam_basis(gantry,couch);assert basis@basis.T==pytest.approx(np.eye(3),abs=1e-12)
    got=envelope(origins,directions)
    assert got['status']=='sphere_3d'
    assert got['center_lps_mm']==pytest.approx(shift,abs=1e-8)
    assert got['diameter_mm']<1e-8


def test_same_gantry_cannot_identify_depth():
    directions=np.tile([0,1.,0],(4,1));origins=np.array([[1,0,0],[-1,0,0],[0,0,1],[0,0,-1.]])
    got=envelope(origins,directions)
    assert got['status']=='plane_only'
    assert got['diameter_mm']==pytest.approx(2.,abs=1e-6)
    assert 'center_lps_mm' not in got


def test_minimum_radius_is_not_largest_error_or_mean_offset():
    # Orthogonal lines at +/-1 mm: centre zero, radius 1, diameter 2.
    origins=np.array([[0,0,1],[0,0,-1],[0,0,1],[0,0,-1.]])
    directions=np.array([[1,0,0],[1,0,0],[0,1,0],[0,1,0.]])
    got=envelope(origins,directions)
    assert got['diameter_mm']==pytest.approx(2.,abs=1e-6)
    assert got['center_distance_mm']<1e-6
