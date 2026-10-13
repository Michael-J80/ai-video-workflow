"""Task-local worker helpers; no machine-specific paths or runtime binaries."""
from pathlib import Path
import os
import json
import re
import sys
import tempfile

ROOT = Path(os.environ['WORKFLOW_DATA']).resolve()


def read_config():
    return {'scene_threshold': 27, 'minimum_scene_frames': 15, 'vad_onset': .3, 'vad_offset': .2}


def setup_env():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    os.environ.setdefault('HF_HOME', str(ROOT/'cache/huggingface'))
    os.environ.setdefault('TORCH_HOME', str(ROOT/'cache/torch'))
    os.environ.update(HF_HUB_DISABLE_TELEMETRY='1', DO_NOT_TRACK='1')


def sanitize(text):
    return re.sub(r'\b(?:sk-|hf_)[A-Za-z0-9_-]{10,}', '[REDACTED]', str(text))


def write_json(path, data):
    path = Path(path).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError('Worker output outside task directory')
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    temp.replace(path)
