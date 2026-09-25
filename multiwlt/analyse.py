"""CT-referenced static MultiWLT analysis; no machine connection."""
import argparse,json
from pathlib import Path
from routine_registered import analyse_registered_folder

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('images');p.add_argument('--profile',required=True)
    p.add_argument('--output',required=True);p.add_argument('--records')
    p.add_argument('--positioned-in-ct',action='store_true',help='Confirm image-guided alignment to the reference CT pose.')
    a=p.parse_args()
    r=analyse_registered_folder(a.images,a.profile,a.output,positioned_in_ct=a.positioned_in_ct,records_folder=a.records)
    print(json.dumps({k:r[k] for k in ['status','valid_count','max_extra_mm','pdf_file']},indent=2))
