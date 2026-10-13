"""WhisperX transcription + alignment on a local standard WAV, no diarization."""
import argparse,importlib.metadata as metadata,time,traceback,wave,gc
from pathlib import Path
from common import ROOT,setup_env,write_json,sanitize,read_config
from subtitle_utils import make_srt,cues_from_words

def main():
    setup_env()
    p=argparse.ArgumentParser()
    p.add_argument('--audio',required=True);p.add_argument('--output',required=True)
    p.add_argument('--device',choices=['cuda','cpu'],default='cuda');p.add_argument('--language',default='zh')
    p.add_argument('--model',default='small');p.add_argument('--batch-size',type=int,default=4)
    args=p.parse_args();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    config=read_config()
    vad={'vad_onset':config.get('vad_onset',0.3),'vad_offset':config.get('vad_offset',0.2)}
    result={'device_requested':args.device,'model':args.model,'language':args.language,'compute_type':'float16' if args.device=='cuda' else 'int8','batch_size':args.batch_size,'vad':vad,'diarization':False,'decode_backend':'stdlib.wave PCM16 -> numpy float32','stages':{}}
    def step(name,fn):
        started=time.perf_counter()
        try:
            value=fn();result['stages'][name]={'status':'PASS','elapsed_seconds':round(time.perf_counter()-started,3)}
            return value
        except Exception as e:
            result['stages'][name]={'status':'FAIL','elapsed_seconds':round(time.perf_counter()-started,3),'error_type':type(e).__name__,'error':sanitize(e),'traceback':sanitize(traceback.format_exc())}
            raise
        finally:write_json(out/'speech_status.json',result)
    try:
        def imports():
            import numpy as np,torch,whisperx
            result['versions']={n:metadata.version(n) for n in ['whisperx','torch','torchaudio','torchcodec','ctranslate2','faster-whisper','transformers']}
            if args.device=='cuda' and not torch.cuda.is_available():raise RuntimeError('CUDA requested but unavailable; no implicit CPU fallback')
            return np,torch,whisperx
        np,torch,whisperx=step('import',imports)
        def decode():
            with wave.open(args.audio,'rb') as f:
                if (f.getnchannels(),f.getframerate(),f.getsampwidth())!=(1,16000,2):raise ValueError('Expected PCM16 mono 16000Hz WAV')
                a=np.frombuffer(f.readframes(f.getnframes()),dtype=np.int16).astype(np.float32)/32768.0
            if len(a)==0:raise ValueError('Empty audio')
            result['duration_seconds']=len(a)/16000;return a
        audio=step('decode',decode)
        model=step('load_model',lambda:whisperx.load_model(args.model,args.device,compute_type=result['compute_type'],language=args.language,download_root=str(ROOT/'cache'/'whisper'),vad_method='pyannote',vad_options=vad,threads=4))
        result['actual_model_device']=model.model.model.device
        if result['actual_model_device']!=args.device:raise RuntimeError('Model device does not match requested device')
        raw=step('transcription',lambda:model.transcribe(audio,batch_size=args.batch_size,language=args.language))
        write_json(out/'transcript_unaligned.json',raw)
        del model;gc.collect()
        if args.device=='cuda':torch.cuda.empty_cache()
        if not raw['segments']:
            result['stages']['alignment']={'status':'SKIPPED','reason':'No speech detected'}
            aligned={'segments':[],'word_segments':[]}
        else:
            align_model,align_meta=step('load_alignment_model',lambda:whisperx.load_align_model(language_code=args.language,device=args.device,model_dir=str(ROOT/'cache'/'huggingface'/'hub')))
            aligned=step('alignment',lambda:whisperx.align(raw['segments'],align_model,align_meta,audio,args.device,return_char_alignments=False))
            timed_words=[w for w in aligned.get('word_segments',[]) if 'start' in w and 'end' in w]
            if not timed_words:
                result['stages']['alignment'].update(status='FAIL',error='No aligned word timestamps');raise ValueError('Alignment returned no timed words')
            result['aligned_word_count']=len(timed_words)
        transcript={'language':args.language,'device':args.device,'model':args.model,'alignment_status':result['stages']['alignment']['status'],'duration_seconds':result['duration_seconds'],**aligned}
        transcript['subtitle_segments']=cues_from_words(aligned.get('word_segments',[]),args.language)
        write_json(out/'transcript.json',transcript)
        srt=step('subtitle_validation',lambda:make_srt(transcript['subtitle_segments'],result['duration_seconds']))
        (out/'subtitles.srt').write_text(srt,encoding='utf-8-sig')
        result['status']='PASS'
    except Exception as e:
        result['status']='FAIL';result['error']=sanitize(e)
        print(sanitize(traceback.format_exc()))
    write_json(out/'speech_status.json',result)
    print(f"Speech workflow {result['status']}; requested device={args.device}")
    return 0 if result['status']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())
