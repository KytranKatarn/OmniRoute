"""
Build script for ARCHIE Node Installer .exe

Installs PyInstaller if needed, then packages archie_node_installer.py
into a standalone single-file Windows executable.

Run on a Windows machine with Python 3.8+ installed:
    python build_installer.py

Output: dist/ARCHIE-Node-Setup.exe
"""

import os
import subprocess
import sys


def ensure_pyinstaller():
    """Install PyInstaller if not already available."""
    try:
        import PyInstaller  # noqa: F401

        print("[OK] PyInstaller is installed.")
    except ImportError:
        print("[>>] Installing PyInstaller...")
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pyinstaller"],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        print("[OK] PyInstaller installed.")


def build():
    """Run PyInstaller to create the standalone .exe."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    main_script = os.path.join(script_dir, "archie_node_installer.py")
    dist_dir = os.path.join(script_dir, "dist")
    build_dir = os.path.join(script_dir, "build")
    icon_path = os.path.join(script_dir, "archie_icon.ico")

    if not os.path.exists(main_script):
        print(f"[!!] Main script not found: {main_script}")
        sys.exit(1)

    print("[>>] Building ARCHIE-Node-Setup.exe ...")
    print(f"     Source: {main_script}")
    print(f"     Output: {dist_dir}")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        "--windowed",
        "--name",
        "ARCHIE-Node-Setup",
        "--distpath",
        dist_dir,
        "--workpath",
        build_dir,
        "--specpath",
        script_dir,
        "--clean",
    ]

    # Add icon if it exists
    if os.path.exists(icon_path):
        cmd.extend(["--icon", icon_path])
        print(f"     Icon: {icon_path}")
    else:
        print("     Icon: (none — place archie_icon.ico in this folder to include one)")

    # No hidden imports needed — we only use stdlib
    cmd.append(main_script)

    print()
    print("     Running PyInstaller...")
    print("     " + "-" * 50)

    result = subprocess.run(cmd, cwd=script_dir)

    if result.returncode != 0:
        print()
        print("[!!] Build FAILED. Check the output above for errors.")
        sys.exit(1)

    exe_path = os.path.join(dist_dir, "ARCHIE-Node-Setup.exe")
    if os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)
        print()
        print("     " + "=" * 50)
        print(f"     [OK] Build successful!")
        print(f"     Output: {exe_path}")
        print(f"     Size:   {size_mb:.1f} MB")
        print("     " + "=" * 50)
    else:
        print()
        print("[!!] Build completed but .exe not found at expected location.")
        sys.exit(1)


def main():
    print()
    print("  ========================================")
    print("  A.R.C.H.I.E. Node Installer — Builder")
    print("  ========================================")
    print()

    ensure_pyinstaller()
    print()
    build()


if __name__ == "__main__":
    main()
