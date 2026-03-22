"""
Build script for A.R.C.H.I.E. Node v4.0 .exe

Wraps PyInstaller to package archie_node_installer.py into a standalone
single-file Windows executable with no console window.

Run on a Windows machine with Python 3.8+ and PyInstaller installed:
    python build_installer.py

Output: dist/ARCHIE-Node.exe (app binary — Inno Setup wraps this into the final installer)
"""

import os
import shutil
import sys


def build():
    """Run PyInstaller to create the standalone .exe."""
    try:
        from PyInstaller import __main__ as pyi_main
    except ImportError:
        print("[!!] PyInstaller is not installed.")
        print("     Install it with:  pip install pyinstaller")
        sys.exit(1)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    main_script = os.path.join(script_dir, "archie_node_installer.py")
    dist_dir = os.path.join(script_dir, "dist")
    build_dir = os.path.join(script_dir, "build")
    icon_path = os.path.join(script_dir, "archie_icon.ico")

    if not os.path.exists(main_script):
        print(f"[!!] Main script not found: {main_script}")
        sys.exit(1)

    print("[>>] Building ARCHIE-Node.exe ...")
    print(f"     Source: {main_script}")
    print(f"     Output: {dist_dir}")

    args = [
        "--onefile",
        "--windowed",
        "--name=ARCHIE-Node",
        "--distpath", dist_dir,
        "--workpath", build_dir,
        "--specpath", script_dir,
        "--clean",
    ]

    if os.path.exists(icon_path):
        args.extend(["--icon", icon_path])
        print(f"     Icon: {icon_path}")
    else:
        print("     Icon: (none)")

    args.append(main_script)

    print()
    pyi_main.run(args)

    exe_path = os.path.join(dist_dir, "ARCHIE-Node.exe")
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print()
        print(f"     [OK] Build successful!")
        print(f"     Output: {exe_path}")
        print(f"     Size:   {size_mb:.1f} MB")
    else:
        print()
        print("[!!] Build completed but .exe not found at expected location.")
        sys.exit(1)


if __name__ == "__main__":
    print()
    print("  ========================================")
    print("  A.R.C.H.I.E. Node — by Kytran Empowerment — Builder")
    print("  ========================================")
    print()
    build()
