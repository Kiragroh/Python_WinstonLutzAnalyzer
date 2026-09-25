from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH)
data = [(str(root / 'PORTABLE.md'), '.'), (str(root.parent / 'LICENSE.txt'), '.'),
        (str(root / 'THIRD_PARTY.md'), '.'), (str(root / 'requirements.txt'), '.')]
data += collect_data_files('pylinac') + collect_data_files('matplotlib')
a = Analysis([str(root / 'gui.py')], pathex=[str(root)], datas=data,
             hiddenimports=['matplotlib.backends.backend_agg', 'routine_registered_report', 'PIL.ImageTk'],
             excludes=['IPython', 'jupyter', 'notebook', 'pandas', 'pyarrow', 'pytest', 'sphinx',
                       'torch', 'tensorflow', 'cv2', 'streamlit', 'numba', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6'])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MultiWLT', console=False)
coll = COLLECT(exe, a.binaries, a.datas, name='MultiWLT')
