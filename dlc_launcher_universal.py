import glob
import os
import shutil
import sys
import time

import cv2
import deeplabcut

import organise_paths


STANDARD_CONFIG_PATH = '/data/common/dlc_models/all_setups-rubencorreia-2025-12-10/config.yaml'
MESO_CONFIG_PATH = '/data/common/dlc_models/EYE-Yannick-2025-05-08/config.yaml'


def is_meso_experiment(exp_dir_raw):
    for entry in sorted(os.listdir(exp_dir_raw)):
        scanpath_root = os.path.join(exp_dir_raw, entry)
        if not entry.startswith('P') or not os.path.isdir(scanpath_root):
            continue
        for roi_entry in sorted(os.listdir(scanpath_root)):
            roi_root = os.path.join(scanpath_root, roi_entry)
            if roi_entry.startswith('R') and os.path.isdir(roi_root):
                return True
    return False


def dlc_config_path_for_experiment(exp_dir_raw):
    return MESO_CONFIG_PATH if is_meso_experiment(exp_dir_raw) else STANDARD_CONFIG_PATH


def crop_vids(userID, expID):
    print('Cropping videos...')
    _, _, _, exp_dir_processed, exp_dir_raw = organise_paths.find_paths(userID, expID)

    habit_video = os.path.join(exp_dir_raw, expID + '_habit.mp4')
    habit_video_pattern = os.path.join(exp_dir_raw, expID + '_Setup_*_habit.mp4')
    habit_video_matches = sorted(glob.glob(habit_video_pattern))
    two_eye_video = os.path.join(exp_dir_raw, expID + '_eye1.mp4')

    if os.path.exists(habit_video):
        eye_video_to_crop = habit_video
        is_habit = True
    elif habit_video_matches:
        eye_video_to_crop = habit_video_matches[0]
        is_habit = True
    else:
        eye_video_to_crop = two_eye_video
        is_habit = False

    cap = cv2.VideoCapture(eye_video_to_crop)
    if not cap.isOpened():
        print(f'Could not open video: {eye_video_to_crop}')
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)

    left_crop = (0, 0, 479, 743)
    right_crop = (744, 0, 479, 743)
    habit_crop = (0, 0, 480, 640)

    left_suffix = '_eye1_left'
    right_suffix = '_eye1_right'
    habit_suffix = '_eye1_right'

    fourcc = cv2.VideoWriter_fourcc(*'XVID')

    if is_habit:
        habit_output_filename = os.path.join(exp_dir_processed, expID + habit_suffix + '.avi')
        habit_out = cv2.VideoWriter(habit_output_filename, fourcc, fps, (habit_crop[3], habit_crop[2]))
        left_out = None
        right_out = None
    else:
        left_output_filename = os.path.join(exp_dir_processed, expID + left_suffix + '.avi')
        right_output_filename = os.path.join(exp_dir_processed, expID + right_suffix + '.avi')
        left_out = cv2.VideoWriter(left_output_filename, fourcc, fps, (left_crop[3], left_crop[2]))
        right_out = cv2.VideoWriter(right_output_filename, fourcc, fps, (right_crop[3], right_crop[2]))
        habit_out = None

    cnt = 0
    progress_marks = [20, 40, 60, 80, 100]
    next_mark_index = 0

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        cnt += 1

        if is_habit:
            x, y, h, w = habit_crop
            habit_frame = frame[y:y + h, x:x + w]
            habit_out.write(habit_frame)
        else:
            x, y, h, w = left_crop
            left_frame = frame[y:y + h, x:x + w]
            left_out.write(left_frame)

            x, y, h, w = right_crop
            right_frame = frame[y:y + h, x:x + w]
            right_frame = cv2.flip(right_frame, 1)
            right_out.write(right_frame)

        if frames:
            pct = cnt * 100 / frames
            if next_mark_index < len(progress_marks) and pct >= progress_marks[next_mark_index]:
                print(f'Cropping {progress_marks[next_mark_index]}% complete')
                next_mark_index += 1

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    if left_out is not None:
        left_out.release()
    if right_out is not None:
        right_out.release()
    if habit_out is not None:
        habit_out.release()


def remove_existing_outputs(exp_dir_processed):
    for filename in os.listdir(exp_dir_processed):
        if 'eye1_left' in filename or 'eye1_right' in filename:
            print('Deleting ' + filename)
            os.remove(os.path.join(exp_dir_processed, filename))


def duplicate_outputs_if_needed(exp_dir_processed, expID):
    left_video = os.path.join(exp_dir_processed, expID + '_eye1_left.avi')
    right_video = os.path.join(exp_dir_processed, expID + '_eye1_right.avi')

    if os.path.exists(right_video) and not os.path.exists(left_video):
        print('Only right eye present; duplicating DLC outputs for left eye...')
        shutil.copy2(right_video, left_video)
        for filename in os.listdir(exp_dir_processed):
            if 'eye1_right' not in filename:
                continue
            src = os.path.join(exp_dir_processed, filename)
            dst = os.path.join(exp_dir_processed, filename.replace('eye1_right', 'eye1_left'))
            shutil.copy2(src, dst)

    if os.path.exists(left_video) and not os.path.exists(right_video):
        print('Only left eye present; duplicating DLC outputs for right eye...')
        shutil.copy2(left_video, right_video)
        for filename in os.listdir(exp_dir_processed):
            if 'eye1_left' not in filename:
                continue
            src = os.path.join(exp_dir_processed, filename)
            dst = os.path.join(exp_dir_processed, filename.replace('eye1_left', 'eye1_right'))
            shutil.copy2(src, dst)


def analyze_if_present(config_path, exp_dir_processed, expID, eye_label, shuffle):
    video_path = os.path.join(exp_dir_processed, f'{expID}_{eye_label}.avi')
    if not os.path.exists(video_path):
        print(f'Skipping {eye_label} video (file not found).')
        return

    print(f'Starting {eye_label} video...')
    deeplabcut.analyze_videos(
        config_path,
        video_path,
        videotype='avi',
        shuffle=shuffle,
        gputouse=0,
        save_as_csv=True,
        destfolder=exp_dir_processed,
    )


def dlc_launcher_run(userID, expID):
    _, _, _, exp_dir_processed, exp_dir_raw = organise_paths.find_paths(userID, expID)
    os.makedirs(exp_dir_processed, exist_ok=True)
    remove_existing_outputs(exp_dir_processed)

    print('Starting cropping videos...')
    crop_vids(userID, expID)

    config_path = dlc_config_path_for_experiment(exp_dir_raw)
    shuffle = 1 if config_path == MESO_CONFIG_PATH else 5

    analyze_if_present(config_path, exp_dir_processed, expID, 'eye1_left', shuffle)
    analyze_if_present(config_path, exp_dir_processed, expID, 'eye1_right', shuffle)
    duplicate_outputs_if_needed(exp_dir_processed, expID)


def main():
    print('Starting DLC Launcher Universal...')
    try:
        userID = sys.argv[1]
        expID = sys.argv[2]
    except Exception:
        expID = '2026-01-20_02_ESRC027'
        userID = 'adamranson'
    start_time = time.time()
    dlc_launcher_run(userID, expID)
    print('Time to run: ' + str(time.time() - start_time) + ' secs')


if __name__ == "__main__":
    main()
