import os
import pathlib
import subprocess
import sys


def ensure_venv_python_has_onnxruntime():
    try:
        import onnxruntime  # noqa: F401
        return
    except Exception:
        pass

    search_roots = [pathlib.Path.cwd(), *pathlib.Path(__file__).resolve().parents]
    venv_python = None
    for parent in search_roots:
        for venv_name in ('.venv', 'venv'):
            candidate = parent / venv_name / 'bin' / 'python'
            if not candidate.exists():
                continue

            try:
                subprocess.run(
                    [str(candidate), '-c', 'import onnxruntime'],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                continue

            venv_python = candidate
            break
        if venv_python is not None:
            break

    if venv_python is None:
        raise RuntimeError(
            'onnxruntime is not available in the current interpreter or any local venv. '
            'Install it into the project venv with `pip install onnxruntime` before launching.'
        )

    current_python = pathlib.Path(sys.executable).resolve()
    if current_python == venv_python.resolve():
        return

    os.execv(str(venv_python), [str(venv_python), *sys.argv])