"""Local corrected radiation-ray envelopes, not tumour volumes or confidence balls.

Following the WL minimum-maximum distance-to-lines principle. Each off-axis
ray is translated to its own CT BB origin before pooling. Radii are physical
target-local mm, whereas the primary 2D residuals remain isocentre-plane mm.
"""
import numpy as np
from scipy.optimize import minimize
from routine_core import project_hfs


def beam_basis(gantry,couch):
    g,t=np.deg2rad([gantry,couch])
    return np.array([[np.cos(g)*np.cos(t),np.sin(g),-np.cos(g)*np.sin(t)],
                     [np.sin(t),0,np.cos(t)],
                     [-np.sin(g)*np.cos(t),np.cos(g),np.sin(g)*np.sin(t)]])


def corrected_ray(ball,iso,gantry,couch,sad,residual):
    basis=beam_basis(gantry,couch)
    projected=project_hfs(ball,iso,gantry,0,couch,sad)
    # Field ray relative to the BB: opposite sign to BB-minus-field residual.
    q=projected-np.asarray(residual,float)
    source=np.asarray(iso)-sad*basis[2]
    point=np.asarray(iso)+basis[0]*q[0]+basis[1]*q[1]
    direction=point-source;direction/=np.linalg.norm(direction)
    return source-np.asarray(ball),direction


def envelope(origins,directions):
    origins=np.asarray(origins,float);directions=np.asarray(directions,float)
    if len(origins)<3: return {'status':'insufficient_views','sample_count':len(origins)}
    directions=directions/np.linalg.norm(directions,axis=1)[:,None]
    # Same lines with origins nearest local zero: avoid large source coordinates
    # in numerical optimization of sub-millimetre envelopes.
    origins=origins-np.sum(origins*directions,axis=1)[:,None]*directions
    projectors=np.eye(3)[None,:,:]-directions[:,:,None]*directions[:,None,:]
    normal=projectors.sum(0);eigen=np.linalg.eigvalsh(normal)
    condition=float(eigen[-1]/max(eigen[0],1e-15))
    if condition>1000:
        # Same source/gantry with a varying collimator cannot identify depth.
        # Intersect rays with a local plane instead of reporting a fake 3D sphere.
        d=directions[0];_,_,v=np.linalg.svd(d.reshape(1,3));basis=v[1:]
        denominators=directions@d
        if np.min(abs(denominators))<.8:return {'status':'ill_conditioned','condition':condition}
        points=origins-(origins@d/denominators)[:,None]*directions
        xy=points@basis.T;start=xy.mean(0)
        distances=lambda x:np.linalg.norm(x-xy,axis=1)
        fit=minimize(lambda z:z[-1],np.r_[start,max(distances(start))+1e-6],method='SLSQP',
            bounds=[(None,None),(None,None),(0,None)],constraints=[{'type':'ineq','fun':lambda z:z[-1]-distances(z[:2])}],
            options={'ftol':1e-11,'maxiter':1000})
        if not fit.success or np.max(distances(fit.x[:2]))>fit.x[-1]+1e-6:raise ValueError('2D envelope circle did not converge.')
        return {'status':'plane_only','sample_count':len(origins),'diameter_mm':float(2*max(distances(fit.x[:2]))),
            'observable_center_lps_mm':(fit.x[:2]@basis).tolist(),'plane_basis_lps':basis.tolist(),
            'condition':condition,'note':'Depth is not observable: 2D envelope circle, not a 3D sphere.'}
    start=np.linalg.solve(normal,np.einsum('nij,nj->i',projectors,origins))
    distances=lambda x:np.linalg.norm(np.einsum('nij,nj->ni',projectors,x-origins),axis=1)
    radius=max(distances(start))
    if radius<1e-8:centre=start
    else:
        fit=minimize(lambda z:z[-1],np.r_[start,radius+1e-6],method='SLSQP',
            bounds=[(None,None)]*3+[(0,None)],constraints=[{'type':'ineq','fun':lambda z:z[-1]-distances(z[:3])}],
            options={'ftol':1e-11,'maxiter':1000})
        if not fit.success or np.max(distances(fit.x[:3]))>fit.x[-1]+1e-6:raise ValueError('3D envelope sphere did not converge.')
        centre=fit.x[:3]
    distance=distances(centre)
    return {'status':'sphere_3d','sample_count':len(origins),'center_lps_mm':centre.tolist(),
        'center_distance_mm':float(np.linalg.norm(centre)),'radius_mm':float(max(distance)),
        'diameter_mm':float(2*max(distance)),'rms_line_distance_mm':float(np.sqrt(np.mean(distance**2))),
        'condition':condition,'per_ray_distance_mm':distance.tolist()}


def analyse_spheres(result,reference,beams):
    beammap={b['number']:b for b in beams};by_ball=[];all_o=[];all_d=[]
    for ball in reference['balls']:
        origins=[];directions=[];residuals=[]
        for image in result['images']:
            target=next(t for t in image['targets'] if t['id']==ball['id'])
            if target['status']!='measured':continue
            beam=beammap[image['beam_number']]
            o,d=corrected_ray(ball['center_lps_mm'],reference['iso_lps_mm'],image['gantry_deg'],beam['couch_deg'],beam['sad_mm'],target['residual_mm'])
            origins.append(o);directions.append(d);residuals.append(target['residual_mm'])
        values=envelope(origins,directions)
        values.update(id=ball['id'],distance_from_iso_mm=ball['distance_from_iso_mm'],
            max_2d_extra_mm=float(np.max(np.linalg.norm(residuals,axis=1))) if residuals else None)
        by_ball.append(values);all_o.extend(origins);all_d.extend(directions)
    pooled=envelope(all_o,all_d)
    centres=[b['center_lps_mm'] for b in by_ball if b['status']=='sphere_3d']
    mean=np.mean(centres,axis=0).tolist() if len(centres)==len(by_ball) else None
    return {'definition':'Smallest sphere intersecting every corrected ray; each target uses its CT ball centre as the local origin.',
        'sign_convention':'Radiation reference relative to the ball: corrected field projection = CT ball projection minus (observed-expected). LPS: +L left, +P posterior, +S superior.',
        'coverage':'Sampled angles only. No full-rotation claim; mixed-axis acquisitions do not isolate gantry or collimator performance.',
        'primary_metric':'Maximum extra 2D displacement before any 3D fit.',
        'reference':'https://pylinac.readthedocs.io/en/latest/winston_lutz.html',
        'per_ball':by_ball,'pooled_all_rays':pooled,'mean_centres_lps_mm':mean,
        'mean_diameter_mm':float(np.mean([b['diameter_mm'] for b in by_ball])) if all('diameter_mm' in b for b in by_ball) else None,
        'averaging_note':'Mean centres and diameters are descriptive only. The pooled sphere uses all rays without first averaging out opposing errors.'}


def plot_spheres(summary,path):
    import matplotlib.pyplot as plt
    fig=plt.figure(figsize=(9,6));ax=fig.add_subplot(111,projection='3d')
    colors=['#008ac9','#008377','#b145a4','#243357'];data=[*summary['per_ball'],dict(summary['pooled_all_rays'],id='Pooled')]
    u,v=np.meshgrid(np.linspace(0,2*np.pi,40),np.linspace(0,np.pi,22));limits=[.5]
    for color,item in zip(colors,data):
        if item['status']!='sphere_3d':continue
        x,y,z=item['center_lps_mm'];r=item['radius_mm'];limits.append(max(abs(np.array([x,y,z])))+r)
        ax.plot_surface(x+r*np.cos(u)*np.sin(v),y+r*np.sin(u)*np.sin(v),z+r*np.cos(v),color=color,alpha=.14,linewidth=0)
        ax.scatter(x,y,z,color=color,s=50,label=f'{item["id"]}: Ø {item["diameter_mm"]:.3f} mm')
        ax.quiver(0,0,0,x,y,z,color=color,linewidth=1.5,arrow_length_ratio=.15)
    lim=max(limits)*1.15;ax.scatter(0,0,0,color='#bd3443',marker='+',s=100,label='CT ball centre (0, 0, 0)')
    if summary['mean_centres_lps_mm'] is not None:ax.scatter(*summary['mean_centres_lps_mm'],color='#333333',marker='D',s=40,label='Mean of three centres')
    ax.set(xlim=(-lim,lim),ylim=(-lim,lim),zlim=(-lim,lim),xlabel='L / mm',ylabel='P / mm',zlabel='S / mm');ax.set_box_aspect((1,1,1))
    ax.view_init(elev=23,azim=135);ax.legend(loc='upper left',bbox_to_anchor=(-.28,1.02),fontsize=9)
    fig.suptitle('Local isocentre spheres from corrected rays\nExpected offsets already removed · Arrows: remaining 3D displacement',fontsize=11,color='#243357')
    fig.tight_layout();fig.savefig(path,dpi=160);plt.close(fig)
