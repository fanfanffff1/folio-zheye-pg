#!/usr/bin/env python3
"""Deprecated: use upload_user_uploads_s3.py --kind avatars"""
from __future__ import annotations

import runpy
import sys
from pathlib import Path

sys.argv = [str(Path(__file__).with_name("upload_user_uploads_s3.py")), "--kind", "avatars", *sys.argv[1:]]
runpy.run_path(sys.argv[0], run_name="__main__")
