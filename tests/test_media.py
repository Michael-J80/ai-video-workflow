import asyncio
import importlib.util
import json
import shutil
import subprocess
import pytest


def test_media_module_exists():
    assert importlib.util.find_spec('app.media'), 'media adapter missing'


def test_real_local_video(tmp_path):
    from app.media import Analyzer
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg required')
    source = tmp_path/'source.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=128x128:r=24:d=1', '-c:v', 'libx264', str(source)], check=True)
    task = dict(id='media-test', duration_seconds=1, ratio='1:1', require_audio=False, device='cpu', skip_speech=True)
    receipt = asyncio.run(Analyzer({}).analyze(task, source, tmp_path/'delivery'))
    assert receipt['technical_status'] == 'PASS'
    assert receipt['content_status'] == 'UNVERIFIED'
    assert receipt['input_sha256']
    assert 'task_run.json' in receipt['artifacts']
    assert 'analysis/scenes.json' in receipt['artifacts']


def test_corrupt_download_is_not_pass(tmp_path):
    from app.media import Analyzer
    if not shutil.which('ffprobe'):
        pytest.skip('FFprobe required')
    source = tmp_path/'bad.mp4'
    source.write_bytes(b'not a video')
    task = dict(id='bad', duration_seconds=1, ratio='1:1', require_audio=False, device='cpu', skip_speech=True)
    receipt = asyncio.run(Analyzer({}).analyze(task, source, tmp_path/'delivery'))
    assert receipt['technical_status'] == 'FAIL'
