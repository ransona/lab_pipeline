import argparse
import json
import os
import pickle
import re
import shutil
from pathlib import Path

import tifffile
from tifffile import read_scanimage_metadata
from tifffile.tifffile import COMPRESSION


def calculate_roi_ranges_from_heights(roi_heights, spacer_pixels=0):
    roi_ranges = []
    current_start = 0
    for height in roi_heights:
        start = current_start
        end = start + int(height)
        roi_ranges.append([start, end])
        current_start = end + int(spacer_pixels)
    return roi_ranges


def extract_full_tiff_metadata(tiff_path):
    metadata = {}
    with tifffile.TiffFile(tiff_path) as tif:
        page = tif.pages[0]
        for tag in page.tags.values():
            metadata[tag.name] = tag.value

        if getattr(page, "imagej_metadata", None):
            metadata["ImageJ_Metadata"] = page.imagej_metadata

        artist_tag = page.tags.get("Artist")
        if not artist_tag:
            metadata["Artist_Parsed"] = None
            return metadata

        artist_text = str(artist_tag.value).strip()
        artist_text = re.sub(r",\s*([}\]])", r"\1", artist_text)
        artist_text = artist_text.replace("NaN", "null")
        try:
            metadata["Artist_Parsed"] = json.loads(artist_text)
        except json.JSONDecodeError as exc:
            metadata["Artist_Parsed"] = f"Failed to parse Artist tag: {exc}"
    return metadata


def _sorted_tifs(path):
    def sort_key(name):
        numbers = re.findall(r"\d+", name)
        return tuple(int(number) for number in numbers) if numbers else (0, name.lower())

    return sorted(
        [name for name in os.listdir(path) if name.lower().endswith((".tif", ".tiff"))],
        key=sort_key,
    )


def split_tiff_to_roi_streamed(tiff_path, roi_divisions=None, chunk_size=100, delete_raw_tif=True):
    if chunk_size < 1:
        raise ValueError("chunk_size must be a positive integer.")

    tiff_path = Path(tiff_path)
    tiff_dir = tiff_path.parent
    tiff_name = tiff_path.stem

    with tifffile.TiffFile(tiff_path) as tif:
        num_frames = len(tif.pages)
        frame_height, _frame_width = tif.pages[0].shape
        if not roi_divisions:
            roi_divisions = [[0, frame_height]]

        for pair in roi_divisions:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise ValueError("Each ROI division must be a [start, end] pair.")
            if pair[0] < 0 or pair[1] > frame_height or pair[0] >= pair[1]:
                raise ValueError(f"Invalid ROI range for {tiff_path}: {pair}")

        compression_tag = tif.pages[0].tags.get("Compression")
        compression = compression_tag.value if compression_tag else None
        if isinstance(compression, int):
            compression = COMPRESSION(compression).name.lower()

        image_description = tif.pages[0].tags.get("ImageDescription")
        description = image_description.value if image_description else ""

        writers = []
        for roi_index in range(len(roi_divisions)):
            roi_name = f"R{roi_index + 1:03d}"
            roi_folder = tiff_dir / roi_name
            roi_folder.mkdir(exist_ok=True)
            writers.append(tifffile.TiffWriter(roi_folder / f"{tiff_name}_{roi_name}_full.tif", bigtiff=True))

        try:
            for start in range(0, num_frames, chunk_size):
                end = min(start + chunk_size, num_frames)
                chunk = tif.asarray(key=range(start, end))
                if chunk.ndim == 2:
                    chunk = chunk[None, :, :]

                for frame in chunk:
                    for roi_index, (top, bottom) in enumerate(roi_divisions):
                        writers[roi_index].write(
                            frame[top:bottom, :],
                            photometric="minisblack",
                            metadata={"ImageJ": True},
                            description=description,
                            compression=compression,
                        )
        finally:
            for writer in writers:
                writer.close()

    if delete_raw_tif:
        print(f"Deleting original TIFF: {tiff_path}")
        tiff_path.unlink()
    print(f"Done. Saved {len(roi_divisions)} ROI TIFF(s) from {num_frames} frame(s): {tiff_path}")


def _enabled_roi_heights(metadata):
    parsed = metadata.get("Artist_Parsed")
    if isinstance(parsed, str):
        raise ValueError(parsed)
    if not isinstance(parsed, dict):
        return []
    rois = (
        parsed.get("RoiGroups", {})
        .get("imagingRoiGroup", {})
        .get("rois", [])
    )
    if isinstance(rois, dict):
        rois = [rois]
    if not isinstance(rois, list):
        return []

    heights = []
    for roi_index, roi in enumerate(rois, start=1):
        if not isinstance(roi, dict) or roi.get("enable") != 1:
            continue
        scanfields = roi.get("scanfields")
        if isinstance(scanfields, list) and scanfields:
            pixel_resolution = scanfields[0].get("pixelResolutionXY")
        elif isinstance(scanfields, dict):
            pixel_resolution = scanfields.get("pixelResolutionXY")
        else:
            print(f"ROI {roi_index}: no scanfields found.")
            continue
        if not pixel_resolution or len(pixel_resolution) < 2:
            print(f"ROI {roi_index}: no pixelResolutionXY found.")
            continue
        heights.append(int(pixel_resolution[1]))
    return heights


def split_meso_rois(exp_dir_raw, delete_raw_tifs=True):
    exp_dir_raw = Path(exp_dir_raw)
    print(f"Splitting mesoscope experiment: {exp_dir_raw}")
    for scanpath_index in range(10):
        scanpath = exp_dir_raw / f"P{scanpath_index}"
        if not scanpath.is_dir():
            continue

        tif_names = _sorted_tifs(scanpath)
        if not tif_names:
            print(f"Found path with no TIFF files: {scanpath}")
            continue

        first_tif = scanpath / tif_names[0]
        metadata = extract_full_tiff_metadata(first_tif)
        with first_tif.open("rb") as handle:
            scanimage_metadata = read_scanimage_metadata(handle)

        si_meta = {"Meta1": scanimage_metadata, "Meta2": metadata}
        roi_heights = _enabled_roi_heights(metadata)

        if not roi_heights:
            r001_path = scanpath / "R001"
            r001_path.mkdir(exist_ok=True)
            print(f"Only one or no explicit ROI found; moving TIFFs to {r001_path}")
            for tif_name in tif_names:
                shutil.move(str(scanpath / tif_name), str(r001_path / tif_name))
        else:
            image_length = int(metadata["ImageLength"])
            if len(roi_heights) > 1:
                spacer_pixels = (image_length - sum(roi_heights)) / (len(roi_heights) - 1)
                if round(spacer_pixels) != spacer_pixels:
                    raise ValueError(f"Spacer pixels are not an integer for {scanpath}: {spacer_pixels}")
                spacer_pixels = int(spacer_pixels)
            else:
                spacer_pixels = 0
            roi_ranges = calculate_roi_ranges_from_heights(roi_heights, spacer_pixels=spacer_pixels)
            print(f"{scanpath}: splitting {len(tif_names)} TIFF(s) into {len(roi_ranges)} ROI folder(s)")
            for tif_name in tif_names:
                split_tiff_to_roi_streamed(scanpath / tif_name, roi_divisions=roi_ranges, delete_raw_tif=delete_raw_tifs)

        with (scanpath / "SI_meta.pickle").open("wb") as handle:
            pickle.dump(si_meta, handle)
        print(f"Wrote {scanpath / 'SI_meta.pickle'}")


def check_and_process_experiments(base_dir, delete_raw_tifs=True):
    base_dir = Path(base_dir)
    if not base_dir.is_dir():
        raise FileNotFoundError(f"Local repository root does not exist: {base_dir}")

    for animal_path in sorted(path for path in base_dir.iterdir() if path.is_dir()):
        for exp_path in sorted(path for path in animal_path.iterdir() if path.is_dir()):
            scanpaths = [exp_path / "P1", exp_path / "P2"]
            needs_processing = any(path.is_dir() and not (path / "SI_meta.pickle").is_file() for path in scanpaths)
            if not needs_processing:
                print(f"Skipping {exp_path}, already processed.")
                continue
            split_meso_rois(exp_path, delete_raw_tifs=delete_raw_tifs)


def main():
    parser = argparse.ArgumentParser(description="Split local mesoscope TIFFs into P*/R* layout.")
    parser.add_argument("local_repository_root", nargs="?", default=r"F:\Local_Repository")
    parser.add_argument("--keep-raw-tifs", action="store_true", help="Do not delete original path-level TIFFs after splitting.")
    args = parser.parse_args()
    check_and_process_experiments(args.local_repository_root, delete_raw_tifs=not args.keep_raw_tifs)


if __name__ == "__main__":
    main()
