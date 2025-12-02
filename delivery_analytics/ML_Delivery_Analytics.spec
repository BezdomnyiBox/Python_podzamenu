# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec файл для ML-Аналитики доставок
"""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Собираем все подмодули sklearn (важно для ML)
sklearn_hidden = collect_submodules('sklearn')
scipy_hidden = collect_submodules('scipy')

# Данные для matplotlib и других библиотек
datas = []
datas += collect_data_files('matplotlib')
datas += collect_data_files('tkcalendar')

a = Analysis(
    ['ML_Анализ_Доставки.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        # ML библиотеки
        'sklearn',
        'sklearn.ensemble',
        'sklearn.ensemble._forest',
        'sklearn.ensemble._gb',
        'sklearn.ensemble._iforest',
        'sklearn.linear_model',
        'sklearn.linear_model._base',
        'sklearn.linear_model._ridge',
        'sklearn.preprocessing',
        'sklearn.preprocessing._data',
        'sklearn.preprocessing._label',
        'sklearn.model_selection',
        'sklearn.model_selection._split',
        'sklearn.cluster',
        'sklearn.cluster._dbscan',
        'sklearn.utils',
        'sklearn.utils._cython_blas',
        'sklearn.utils._typedefs',
        'sklearn.neighbors._typedefs',
        'sklearn.neighbors._quad_tree',
        'sklearn.tree._utils',
        'sklearn.tree',
        
        # Scipy
        'scipy',
        'scipy.special',
        'scipy.special._cdflib',
        'scipy.linalg',
        
        # Pandas и numpy
        'pandas',
        'pandas._libs',
        'pandas._libs.tslibs.timedeltas',
        'numpy',
        'numpy.core._methods',
        'numpy.lib.format',
        
        # GUI
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'tkcalendar',
        
        # Matplotlib
        'matplotlib',
        'matplotlib.pyplot',
        'matplotlib.backends.backend_tkagg',
        'matplotlib.figure',
        
        # Сеть и Excel
        'requests',
        'openpyxl',
        'openpyxl.styles',
        
        # Локальный модуль
        'ml_predictor',
    ] + sklearn_hidden + scipy_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'pytest',
        'sphinx',
        'IPython',
        'jupyter',
        'notebook',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='ML_Delivery_Analytics',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # Без консоли (GUI приложение)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # Можно добавить иконку: icon='icon.ico'
)

