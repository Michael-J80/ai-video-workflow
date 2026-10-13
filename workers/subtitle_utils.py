import math

def cues_from_words(words,language='zh',gap=0.55,max_chars=18,max_seconds=5.0):
    cues=[];current=None;prefix='';joiner='' if language in ['zh','ja'] else ' '
    for word in words:
        text=str(word.get('word','')).strip()
        if not text:continue
        if word.get('start') is None or word.get('end') is None:
            if current is not None:current['text']+=text
            else:prefix+=text
            continue
        start=float(word['start']);end=float(word['end'])
        if current is not None and (start-current['end']>gap or len(current['text'])+len(text)+len(joiner)>max_chars or end-current['start']>max_seconds):
            cues.append(current);current=None
        if current is None:
            current={'start':start,'end':end,'text':prefix+text};prefix=''
        else:
            current['end']=max(current['end'],end);current['text']+=joiner+text
    if current is not None:cues.append(current)
    if prefix:raise ValueError('Text has no aligned timestamps')
    return cues

def timestamp(seconds):
    value=round(seconds*1000)
    hours,value=divmod(value,3600000);minutes,value=divmod(value,60000);seconds,ms=divmod(value,1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{ms:03}'

def make_srt(segments,duration):
    result=[];last_end=0.0
    for segment in segments:
        start=float(segment['start']);end=float(segment['end']);text=str(segment['text']).strip()
        if not all(math.isfinite(x) for x in [start,end,duration]) or start<0 or start<last_end-0.001 or end<=start or end>duration+0.05:
            raise ValueError(f'Invalid subtitle interval {start}--{end} (duration={duration})')
        if not text:continue
        result.append(f'{len(result)+1}\n{timestamp(start)} --> {timestamp(end)}\n{text}\n')
        last_end=end
    return '\n'.join(result)
