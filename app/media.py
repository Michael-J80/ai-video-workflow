"""Portable local analysis, reusing the existing scene/speech worker algorithms."""
import asyncio
import csv
import hashlib
import json
import os
import shutil
import sys
from pathlib import Path
from .engine import write_json

WORKERS = Path(__file__).resolve().parents[1]/'workers'


class Analyzer:
    def __init__(self, config):
        self.config = config

    async def analyze(self, task, source, directory):
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True)
        analysis = directory/'analysis'
        analysis.mkdir(exist_ok=True)
        logs = directory/'logs'
        logs.mkdir(exist_ok=True)
        receipt = dict(schema_version=1, task_id=task['id'], technical_status='FAIL', content_status='UNVERIFIED',
                       analysis_run_dir=str(analysis), artifacts=[], stages={}, input_sha256='', speech_state='UNVERIFIED')
        source = Path(source).resolve()
        ffprobe = self.config.get('ffprobe') or shutil.which('ffprobe')
        ffmpeg = self.config.get('ffmpeg') or shutil.which('ffmpeg')
        env = dict(os.environ, WORKFLOW_DATA=str(directory), PYTHONIOENCODING='utf-8')

        async def run(name, argv, timeout=1800):
            proc = None
            try:
                proc = await asyncio.create_subprocess_exec(*map(str, argv), stdout=asyncio.subprocess.PIPE,
                       stderr=asyncio.subprocess.PIPE, env=env, creationflags=0x08000000 if os.name == 'nt' else 0)
                out, err = await asyncio.wait_for(proc.communicate(), timeout)
                # Local logs never contain model credentials; commands are fixed media utilities.
                (logs/(name+'.log')).write_bytes(out+err)
                receipt['stages'][name] = {'status': 'PASS' if proc.returncode == 0 else 'FAIL', 'exit_code': proc.returncode}
                if proc.returncode:
                    raise RuntimeError(f'{name} 失败，见本地阶段日志')
                return out
            except Exception:
                receipt['stages'][name] = {'status': 'FAIL'}
                raise
            finally:
                if proc and proc.returncode is None:
                    proc.kill()
                    await proc.wait()

        try:
            if not ffprobe or not ffmpeg:
                raise RuntimeError('需要安装FFmpeg/FFprobe并加入PATH或配置完整路径')
            data = await run('probe', [ffprobe, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', source], 120)
            info = json.loads(data)
            videos = [s for s in info['streams'] if s['codec_type'] == 'video']
            if not videos:
                raise ValueError('下载文件无视频流')
            write_json(analysis/'video_info.json', info)
            await run('decode', [ffmpeg, '-v', 'error', '-xerror', '-nostdin', '-i', source, '-f', 'null', '-'], 600)
            with source.open('rb') as source_file:
                receipt['input_sha256'] = hashlib.file_digest(source_file, 'sha256').hexdigest()
            original = directory/'original.mp4'
            if source != original:
                shutil.copy2(source, original)
            has_audio = any(s['codec_type'] == 'audio' for s in info['streams'])
            flags = []
            if abs(float(info['format']['duration'])-task['duration_seconds']) > .5:
                flags.append('DURATION_MISMATCH')
            a, b = map(int, task['ratio'].split(':'))
            if abs(videos[0]['width']/videos[0]['height'] - a/b) > .02:
                flags.append('RATIO_MISMATCH')
            if task['require_audio'] and not has_audio:
                flags.append('MISSING_AUDIO')
            write_json(directory/'quality_flags.json', {'flags': flags, 'content_status': 'UNVERIFIED'})
            try:
                await run('scenes', [sys.executable, WORKERS/'scene_worker.py', '--input', original, '--output', analysis])
            except Exception:
                pass
            if task['skip_speech'] or not has_audio:
                receipt['speech_state'] = 'SKIPPED' if task['skip_speech'] else 'NO_AUDIO'
                receipt['stages']['speech'] = {'status': 'SKIPPED', 'reason': receipt['speech_state']}
            else:
                speech_python = self.config.get('speech_python') or str(WORKERS.parent/'.venv-whisper/Scripts/python.exe')
                try:
                    if not Path(speech_python).is_file():
                        raise RuntimeError('语音环境未安装；运行 install-speech.ps1 或显式跳过语音')
                    await run('audio', [ffmpeg, '-v', 'error', '-nostdin', '-y', '-i', original, '-map', '0:a:0', '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', analysis/'audio.wav'])
                    await run('speech', [speech_python, WORKERS/'speech_worker.py', '--audio', analysis/'audio.wav', '--output', analysis, '--device', task['device']])
                    speech = json.loads((analysis/'speech_status.json').read_text(encoding='utf-8-sig'))
                    receipt['speech_state'] = 'NO_SPEECH_DETECTED' if speech['stages']['alignment']['status'] == 'SKIPPED' else 'HAS_SPEECH'
                except Exception as exc:
                    receipt['speech_state'] = 'SPEECH_FAILED'
                    receipt['stages']['speech'] = {'status': 'FAIL', 'error': str(exc)}
            receipt['technical_status'] = 'PARTIAL' if any(s['status'] == 'FAIL' for s in receipt['stages'].values()) or flags else 'PASS'
            with (directory/'review.csv').open('w', encoding='utf-8-sig', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['criterion', 'status', 'notes'])
                for key in ['人物与参考', '镜头与动作连续性', '音乐与声音', '口型', '水印与AI标识', '整体质量']:
                    writer.writerow([key, 'UNVERIFIED', '需要实际视听，技术检查不代表内容合格'])
        except Exception as exc:
            receipt['error'] = str(exc)
        receipt['artifacts'] = [str(p.relative_to(directory)).replace('\\', '/') for p in directory.rglob('*')
                                if p.is_file() and p.suffix.lower() in ('.mp4', '.png', '.srt', '.csv', '.json', '.md') and 'references' not in p.parts and p.name != 'hermes-request.txt']
        if 'task_run.json' not in receipt['artifacts']:
            receipt['artifacts'].append('task_run.json')
        write_json(directory/'task_run.json', receipt)
        lines = []
        for name in receipt['artifacts']:
            with (directory/name).open('rb') as f:
                lines.append(hashlib.file_digest(f, 'sha256').hexdigest()+'  '+name)
        (directory/'SHA256SUMS.txt').write_text('\n'.join(lines)+'\n', encoding='utf-8')
        return receipt
