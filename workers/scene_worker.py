import argparse, csv
from pathlib import Path
from common import setup_env,write_json,read_config

def main():
    setup_env()
    parser=argparse.ArgumentParser()
    parser.add_argument('--input',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--detector',choices=['content','adaptive'],default='content')
    args=parser.parse_args()
    from scenedetect import open_video,SceneManager
    from scenedetect.detectors import ContentDetector,AdaptiveDetector
    from scenedetect.scene_manager import save_images
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    config=read_config();threshold=float(config.get('scene_threshold',27.0));minimum=int(config.get('minimum_scene_frames',15))
    video=open_video(args.input,backend='opencv')
    manager=SceneManager()
    manager.add_detector(ContentDetector(threshold=threshold,min_scene_len=minimum) if args.detector=='content' else AdaptiveDetector(min_scene_len=minimum))
    manager.detect_scenes(video,show_progress=False)
    scenes=manager.get_scene_list(start_in_scene=True)
    if not scenes:raise ValueError('No decoded video frames or scene intervals')
    rows=[dict(scene=i+1,start_frame=a.get_frames(),end_frame_exclusive=b.get_frames(),start_seconds=a.get_seconds(),end_seconds=b.get_seconds(),start_timecode=a.get_timecode(),end_timecode=b.get_timecode()) for i,(a,b) in enumerate(scenes)]
    write_json(output/'scenes.json',rows)
    with (output/'scenes.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    files=save_images(scenes,video,num_images=3,output_dir=str(output/'frames'),show_progress=False,image_name_template='scene-$SCENE_NUMBER-$IMAGE_NUMBER')
    write_json(output/'scene_detection.json',{'backend':'opencv','detector':args.detector,'threshold':threshold if args.detector=='content' else 3.0,'min_scene_len_frames':minimum,'scene_count':len(rows),'frames':files})
    print(f'Detected {len(rows)} scenes; exported {sum(len(v) for v in files.values())} frames')

if __name__=='__main__':main()
