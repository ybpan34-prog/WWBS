# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

template_data = [
    (str(path), f'templates/{path.name}' if path.is_dir() else 'templates')
    for path in sorted(Path('templates').iterdir())
    if path.name != 'match3'
]

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=template_data+[
        ('weekly_tasks.json', '.'),
        ('wwbs-version.json', '.'),
        ('wwbs.ico', '.'),
        ('assets/run-notice', 'assets/run-notice'),
        ('assets/rain', 'assets/rain'),
        ('pet-assets/pink-lace-chibi/frames', 'pet-assets/pink-lace-chibi/frames'),
        ('pet-assets/aemeath-chibi/frames-sharp', 'pet-assets/aemeath-chibi/frames-sharp'),
        ('pet-assets/jingran-chibi/frames', 'pet-assets/jingran-chibi/frames'),
        ('pet-assets/jingran-chibi/pet.json', 'pet-assets/jingran-chibi'),
        ('pet-assets/jingran-chibi/spritesheet.webp', 'pet-assets/jingran-chibi'),
        ('pet-assets/cartethyia-chibi/frames', 'pet-assets/cartethyia-chibi/frames'),
        ('pet-assets/cartethyia-chibi/pet.json', 'pet-assets/cartethyia-chibi'),
        ('pet-assets/cartethyia-chibi/spritesheet.webp', 'pet-assets/cartethyia-chibi'),
        ('optional-themes/daniya-theme.wwbstheme', 'optional-themes'),
        ('optional-themes/aemeath-theme.wwbstheme', 'optional-themes'),
        ('optional-themes/jingran-theme.wwbstheme', 'optional-themes'),
        ('optional-themes/cartethyia-theme.wwbstheme', 'optional-themes'),
        ('sillytavern-cards', 'sillytavern-cards'),
        ('sillytavern-extension', 'sillytavern-extension'),
        ('SILLYTAVERN.md', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'torch',
        'matplotlib',
        'pandas',
        'pyarrow',
        'sklearn',
        'sympy',
        'IPython',
        'jupyter',
        'notebook',
        'pytest',
        'psutil',
        'jinja2',
        'dateutil',
        'pytz',
        'cryptography',
        'urllib3',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='wwbs',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['wwbs.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='wwbs',
)
