import argparse
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from PIL import Image, ImageOps


JPEG_EXTENSIONS = {".jpg", ".jpeg"}


def process_image(src, input_path, output_path, scale_percentage, jpeg_quality):
    relative_path = src.relative_to(input_path)
    dst = output_path / relative_path
    dst.parent.mkdir(parents=True, exist_ok=True)

    with Image.open(src) as img:
        img = ImageOps.exif_transpose(img)

        new_width = max(1, round(img.width * scale_percentage / 100))
        new_height = max(1, round(img.height * scale_percentage / 100))

        resized = img.resize(
            (new_width, new_height),
            Image.Resampling.LANCZOS
        )

        if resized.mode not in ("RGB", "L", "CMYK"):
            resized = resized.convert("RGB")

        save_kwargs = {
            "quality": jpeg_quality,
            "subsampling": 0,
        }

        if "icc_profile" in img.info:
            save_kwargs["icc_profile"] = img.info["icc_profile"]

        resized.save(dst, "JPEG", **save_kwargs)

    return relative_path


def resize_jpegs(input_folder, output_folder, scale_percentage, jpeg_quality, workers):
    input_path = Path(input_folder).resolve()
    output_path = Path(output_folder).resolve()

    if not input_path.exists() or not input_path.is_dir():
        raise ValueError(f"Input folder does not exist: {input_path}")

    if scale_percentage <= 0:
        raise ValueError("scale_percentage must be greater than 0")

    if not 1 <= jpeg_quality <= 100:
        raise ValueError("jpeg_quality must be between 1 and 100")

    files = [
        p for p in input_path.rglob("*")
        if p.is_file() and p.suffix.lower() in JPEG_EXTENSIONS
    ]

    print(f"Found {len(files)} JPEG files.")
    print(f"Using {workers} worker threads.")

    completed = 0
    failed = 0

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                process_image,
                src,
                input_path,
                output_path,
                scale_percentage,
                jpeg_quality
            )
            for src in files
        ]

        for future in as_completed(futures):
            try:
                relative_path = future.result()
                completed += 1
                print(f"OK {completed}/{len(files)}: {relative_path}")
            except Exception as e:
                failed += 1
                print(f"FAILED: {e}")

    print(f"Done. Completed: {completed}, Failed: {failed}")


def main():
    parser = argparse.ArgumentParser(
        description="Resize all JPEG images in a folder and its subfolders using multithreading."
    )

    parser.add_argument("input_folder")
    parser.add_argument("output_folder")
    parser.add_argument("scale_percentage", type=float)
    parser.add_argument("jpeg_quality", type=int)

    parser.add_argument(
        "--workers",
        type=int,
        default=os.cpu_count() or 8,
        help="Number of worker threads. Default: CPU thread count."
    )

    args = parser.parse_args()

    resize_jpegs(
        args.input_folder,
        args.output_folder,
        args.scale_percentage,
        args.jpeg_quality,
        args.workers,
    )


if __name__ == "__main__":
    main()