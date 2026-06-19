from core.timeline import Timeline
from core.canvas_composer import CanvasComposer
from core.writer import VideoWriter
from sources.video_bin_source import VideoBinSource
from sources.stimulus_video_source import StimulusVideoSource
from sources.line_plot_source import LinePlotSource
import os
import numpy as np
from preprocess_pipeline.shared import paths
import pickle


def main():
    # ------------------------------
    # --- Experiment configuration
    # ------------------------------
    # Example timeline: from 1000 s to 1020 s, 10 fps
    timeline = Timeline(1500, 2100, 10.0)

    expID = "2025-07-04_06_ESPM154"
    userID = "pmateosaparicio"

    animalID, remote_repository_root, processed_root, exp_dir_processed, exp_dir_raw = paths.find_paths(userID, expID)
    exp_dir_processed_recordings = os.path.join(exp_dir_processed,'recordings')
    exp_dir_processed_cut = os.path.join(exp_dir_processed,'cut')    
    Ch = 0

    # Base directories for mapping Bonsai resource paths
    bonsai_root = "D:\\bonsai_resources\\"
    stim_base_dir = "/home/adamranson/data/vid_for_decoder/"

    # ------------------------------
    # --- Data sources
    # ------------------------------

    # Neural imaging data
    video_cfg = {
        "user": "pmateosaparicio",
        "expID": "2025-07-04_04_ESPM154",
        "planes": [2], #,3,4,5],
        "height": 512,
        "width": 512,
        "spatial_sigma": 1.0,
        "temporal_window": 3,
        "enable_spatial_filter": False,
        "enable_temporal_filter": True,
        "interpolate": True,
        "tile_layout": {
            "rows": 2,
            "cols": 2,
            "order": [0], #,1,2,3],
            "gap": 4
        },
    }
    video_src = VideoBinSource(video_cfg)

    # for the stimulus video source
    stim_cfg = {
        "user": userID,
        "expID": expID,
    }
    stim_src = StimulusVideoSource(
        config=stim_cfg,
        bonsai_root=bonsai_root,
        stimulus_base_dir=stim_base_dir,
        fps=30,
    )

    # for line plot 1 - load OASIS neural activity 
    with open(os.path.join(exp_dir_processed_recordings,('s2p_oasis_ch' + str(Ch)+'.pickle')),'rb') as file: oasis_data = pickle.load(file)
    oasis_time = oasis_data['t']
    oasis_traces = np.mean(oasis_data['oasis_spikes'],axis=0).T

    plot_oasis = LinePlotSource(
        config={},
        time_vector=oasis_time,
        y_values=[oasis_traces],
        colors=["cyan", "magenta"],
        title="Population activity (spikes)",
        y_label="Signal (a.u.)",
        time_window=(-5, 0),
        y_range_mode="global",
        interpolate=True,  # NEW
    )
     

    # for line plot 2 - running speed
    with open(os.path.join(exp_dir_processed_recordings,('s2p_oasis_ch' + str(Ch)+'.pickle')),'rb') as file: oasis_data = pickle.load(file)

    wheel_data = pickle.load(open(os.path.join(exp_dir_processed_recordings,('wheel.pickle')), "rb"))

    wheel_time = wheel_data['t']
    wheel_trace = wheel_data['speed']

    plot_wheel = LinePlotSource(
        config={},
        time_vector=wheel_time,
        y_values=[wheel_trace],
        colors=["cyan"],
        title="Wheel speed",
        y_label="Signal (a.u.)",
        time_window=(-5, 5),
        y_range_mode="global",
        interpolate=True,  # NEW
    )

    sources = {
        "video0": video_src,
        "stimulus": stim_src,
        "plot_oasis": plot_oasis,
        "plot_wheel": plot_wheel        
    }

    # ------------------------------
    # --- Canvas layout
    # ------------------------------
    layout_cfg = {
        "canvas_size": (1008, 1008),  # (width, height)
        "elements": {
            # Neural activity video (left)
            "main_video": {
                "source": "video0",
                "x": 0,
                "y": 0,
                "w": 500,
                "h": 500,
            },

            # Stimulus presentation video (right)
            "stimulus_video": {
                "source": "stimulus",
                "x": 500,
                "y": 0,
                "w": 500,
                "h": 500,
            },

            # OASIS Line plot visualizer (bottom, spanning full width)
            "line_plot_oasis": {
                "source": "plot_oasis",  # name of your LinePlotSource instance
                "x": 0,
                "y": 500,               # positioned below the videos
                "w": 500,              # span full width of both videos
                "h": 500,               # height of the plot area
            },

            # WHEEL Line plot visualizer (bottom, spanning full width)
            "line_plot_wheel": {
                "source": "plot_wheel",  # name of your LinePlotSource instance
                "x": 500,
                "y": 500,               # positioned below the videos
                "w": 500,              # span full width of both videos
                "h": 500,               # height of the plot area
            }          
        },
    }

    # ------------------------------
    # --- Initialize composer
    # ------------------------------
    composer = CanvasComposer(sources, layout_cfg)
    composer.initialize()



    # Prepare output writer
    frame0 = composer.draw_composite(timeline.times[0])
    H, W = frame0.shape[:2]
    writer = VideoWriter("canvas_output.mp4", fps=timeline.fps, frame_size=(W, H))

    # ------------------------------
    # --- Render loop
    # ------------------------------
    for t in timeline:
        frame = composer.draw_composite(t)
        writer.write(frame)

    writer.close()
    print("✅ Done — combined canvas video saved as canvas_output.mp4")


if __name__ == "__main__":
    main()
