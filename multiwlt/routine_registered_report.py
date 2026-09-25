"""Distinct MultiWLT report: measured field, expected BB, measured BB, residual."""
from pathlib import Path
import html
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import ndimage
from routine_images import panel_to_pixel

COLORS={'field':'#008ac9','expected':'#008377','measured':'#bd3443'}


def plot_field(entry,pixels,geometry,output):
    fig,axes=plt.subplots(2,3,figsize=(12,7))
    for i,t in enumerate(entry['targets']):
        if t['status']!='measured':
            for ax in axes[:,i]:ax.axis('off')
            axes[0,i].text(.05,.5,t['id']+'\n'+t.get('reason','Not measurable'),wrap=True)
            continue
        fc=np.array(t['field_panel_mm']);v=np.array(t['measured_mm']);s=np.array(t['expected_mm'])
        axis=np.linspace(-14,14,181);xx,yy=np.meshgrid(axis,axis[::-1])
        ij=panel_to_pixel(np.stack([xx,yy],-1)+fc,geometry)
        patch=ndimage.map_coordinates(pixels,[ij[...,0],ij[...,1]],order=1)
        top,bottom=axes[:,i]
        top.imshow(patch,cmap='gray',extent=[-14,14,-14,14],vmin=np.percentile(patch,2),vmax=np.percentile(patch,99))
        top.set_title(f'{t["id"]} · additional {t["distance_mm"]:.3f} mm',fontweight='bold',color='#243357')
        top.set_xlabel('EPID-X / mm');top.set_ylabel('EPID-Y / mm')
        for ax in [top,bottom]:
            ax.plot(0,0,'+',color=COLORS['field'],ms=12,mew=2,label='Field centre')
            ax.plot(*s,'s',mfc='none',mec=COLORS['expected'],mew=2,ms=10,label='Expected ball')
            ax.plot(*v,'o',mfc='none',mec=COLORS['measured'],mew=2,ms=10,label='Observed ball')
            ax.set_aspect('equal')
        bottom.annotate('',xy=s,xytext=(0,0),arrowprops=dict(arrowstyle='->',color=COLORS['expected'],lw=1.8))
        bottom.annotate('',xy=v,xytext=s,arrowprops=dict(arrowstyle='->',color=COLORS['measured'],lw=2.2))
        bottom.axhline(0,color='#dde2e8',lw=.7);bottom.axvline(0,color='#dde2e8',lw=.7)
        extent=max(1.4,float(np.max(abs(np.r_[s,v])))*1.35)
        bottom.set(xlim=(-extent,extent),ylim=(-extent,extent),xlabel='EPID-X / mm',ylabel='EPID-Y / mm')
        bottom.set_title(f'Enlarged centres · Expected {np.linalg.norm(s):.3f} mm\nObserved {np.linalg.norm(v):.3f} mm · Extra {t["distance_mm"]:.3f} mm',fontsize=10)
        bottom.grid(alpha=.15)
    kind='SYNTHETIC test image' if entry.get('synthetic') else 'acquired MV image'
    fig.suptitle(f'Gantry {entry["gantry_deg"]:.0f}° · Collimator {entry["collimator_deg"]:.0f}° | {kind}\nBlue + Field centre · Green square Expected ball · Red circle Observed ball · Red arrow: extra displacement',fontsize=12,color='#243357')
    fig.tight_layout(rect=[0,0,1,.92]);path=Path(output)/f'G{entry["gantry_deg"]:03.0f}_Expected_Observed.png'
    fig.savefig(path,dpi=160);plt.close(fig);return path.name


from routine_standard_report import write_report
