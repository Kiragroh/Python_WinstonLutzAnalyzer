"""Generate four explicitly synthetic images and test recovery of a known shift."""
import argparse,json
from pathlib import Path
import numpy as np
from routine_workflow import create_demo_images
from routine_registered import analyse_registered_folder

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',default='demo_output');a=p.parse_args()
    folder=Path(a.output);profile=Path(__file__).parent/'example_reference'/'reference.json'
    shift=np.array([.55,-.35]);create_demo_images(profile,folder/'images',shift)
    r=analyse_registered_folder(folder/'images',profile,folder/'reports',positioned_in_ct=True)
    assert r['synthetic'] and r['valid_count']==12
    error=max(np.linalg.norm(np.array(t['residual_mm'])-shift) for im in r['images'] for t in im['targets'])
    assert error<.12, f'Synthetic shift recovery error: {error:.4f} mm'
    print(json.dumps({'synthetic':True,'valid_count':r['valid_count'],'max_shift_recovery_error_mm':error,'pdf_file':r['pdf_file']},indent=2))
