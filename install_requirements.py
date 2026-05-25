"""
install_requirements.py

Run with the same Python you use to launch main_gui.py, e.g.:
    /opt/anaconda3/bin/python install_requirements.py   # macOS/Linux
    python install_requirements.py                      # Windows (from the right env)

Steps:
  1. Remove PyQt5 if present (conflicts with PyQt6 platform plugins).
  2. Install packages from requirements.txt.
  3. Verify PyQt6 can find its Qt platform plugin for this OS.
"""

import subprocess
import sys
import importlib.util
import pathlib
import os


def run(cmd):
    print(f"  > {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0 and result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode == 0


def step_remove_pyqt5():
    print("\n[1/3] Checking for PyQt5 conflicts...")
    pyqt5_packages = ["PyQt5", "PyQt5-sip", "PyQtWebEngine", "PyQtWebEngine-Qt5"]
    installed = []
    for pkg in pyqt5_packages:
        if importlib.util.find_spec(pkg.replace("-", "_").split("-")[0]) is not None:
            installed.append(pkg)
        # Also check via pip (handles packages not importable by spec)
    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=columns"],
        capture_output=True, text=True
    )
    pip_names = {line.split()[0].lower() for line in result.stdout.splitlines() if line.strip()}
    to_remove = [pkg for pkg in pyqt5_packages if pkg.lower() in pip_names]

    if not to_remove:
        print("  No PyQt5 packages found — OK.")
        return True

    print(f"  Found: {to_remove}. Removing...")
    return run([sys.executable, "-m", "pip", "uninstall", "-y"] + to_remove)


def step_install_requirements():
    print("\n[2/3] Installing requirements.txt...")
    req_file = pathlib.Path(__file__).parent / "requirements.txt"
    if not req_file.exists():
        print(f"  ERROR: {req_file} not found.")
        return False
    return run([sys.executable, "-m", "pip", "install", "-r", str(req_file)])


def step_verify_qt():
    print("\n[3/3] Verifying Qt platform plugin...")
    try:
        import PyQt6.QtCore
    except ImportError:
        print("  ERROR: PyQt6 could not be imported after install. Check your environment.")
        return False

    pyqt6_dir = pathlib.Path(PyQt6.QtCore.__file__).parent
    plugins_dir = pyqt6_dir / "Qt6" / "plugins" / "platforms"

    if sys.platform == "darwin":
        expected = plugins_dir / "libqcocoa.dylib"
        plugin_name = "cocoa"
    elif sys.platform == "win32":
        expected = plugins_dir / "qwindows.dll"
        plugin_name = "windows"
    else:
        expected = plugins_dir / "libqxcb.so"
        plugin_name = "xcb"

    if not plugins_dir.exists():
        print(f"  WARNING: Plugins directory not found: {plugins_dir}")
        print("  Qt may not have bundled platform plugins. Try: pip install --force-reinstall PyQt6")
        return False

    if not expected.exists():
        print(f"  WARNING: Expected plugin not found: {expected}")
        print(f"  Available: {list(plugins_dir.iterdir())}")
        return False

    print(f"  Found {plugin_name} plugin: {expected}")

    # Smoke-test: set the plugin path and import QApplication
    os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(plugins_dir)
    try:
        from PyQt6.QtWidgets import QApplication
        print("  QApplication import OK.")
    except Exception as e:
        print(f"  WARNING: QApplication import failed: {e}")
        return False

    print(f"\n  Plugin path for this environment:")
    print(f"    {plugins_dir}")
    print(f"  main_gui.py sets this automatically at startup — no manual export needed.")
    return True


def main():
    print(f"Python: {sys.executable} ({sys.version.split()[0]})")
    print(f"Platform: {sys.platform}")

    ok1 = step_remove_pyqt5()
    ok2 = step_install_requirements()
    ok3 = step_verify_qt()

    print("\n" + "=" * 50)
    if ok1 and ok2 and ok3:
        print("Setup complete. Run with:")
        print(f"  {sys.executable} main_gui.py")
    else:
        print("Setup finished with warnings — see above.")
    print("=" * 50)


if __name__ == "__main__":
    main()
