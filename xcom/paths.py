"""应用数据目录：打包成 exe 后 __file__ 在临时解压目录，须改用 exe 所在目录。"""

import sys
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):  # PyInstaller 打包运行
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
