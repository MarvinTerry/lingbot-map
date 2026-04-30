# Copyright (c) Meta Platforms, Inc. and affiliates.
# All rights reserved.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.

"""
Human segmentation utilities for filtering person regions from point clouds.
"""

import glob
import os
from typing import Optional, Tuple

import cv2
import numpy as np
from tqdm.auto import tqdm

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None
    print("ultralytics not found. Human segmentation may not work.")


_PERSON_CLASS_ID = 0
_HUMANSEG_BINARY_THRESHOLD = 0.5
_HUMANSEG_DEFAULT_DILATION_RATIO = 0.05
_HUMANSEG_CACHE_VERSION_BASE = "yolo11n_seg_person_dilate_bbox_v2"
_HUMANSEG_DEFAULT_MODEL = "yolo11n-seg.pt"


def _get_cache_version_path(human_mask_dir: str) -> str:
    return os.path.join(human_mask_dir, ".humanseg_cache_version")


def _cache_version_string(human_mask_dilation_ratio: float) -> str:
    ratio_token = f"{human_mask_dilation_ratio:.4f}".replace(".", "p")
    return f"{_HUMANSEG_CACHE_VERSION_BASE}_{ratio_token}"


def _prepare_human_mask_cache(
    human_mask_dir: Optional[str],
    human_mask_dilation_ratio: float,
) -> None:
    if human_mask_dir is None:
        return
    os.makedirs(human_mask_dir, exist_ok=True)
    version_path = _get_cache_version_path(human_mask_dir)
    expected_version = _cache_version_string(human_mask_dilation_ratio)
    current_version = None
    if os.path.exists(version_path):
        with open(version_path, "r", encoding="utf-8") as f:
            current_version = f.read().strip()
    if current_version != expected_version:
        for entry in os.scandir(human_mask_dir):
            if entry.name == ".humanseg_cache_version" or not entry.is_file():
                continue
            os.remove(entry.path)
        with open(version_path, "w", encoding="utf-8") as f:
            f.write(expected_version)


def _mask_to_float(mask: np.ndarray) -> np.ndarray:
    mask = mask.astype(np.float32)
    if mask.size == 0:
        return mask
    return np.clip(mask, 0.0, 1.0)


def _mask_to_uint8(mask: np.ndarray) -> np.ndarray:
    mask = np.asarray(mask)
    if mask.dtype == np.uint8:
        return mask
    mask = mask.astype(np.float32)
    if mask.size > 0 and mask.max() <= 1.0:
        mask = mask * 255.0
    return np.clip(mask, 0.0, 255.0).astype(np.uint8)


def _image_to_rgb_uint8(image: np.ndarray) -> np.ndarray:
    if image.ndim == 3 and image.shape[0] == 3 and image.shape[-1] != 3:
        image = image.transpose(1, 2, 0)

    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError(f"Expected image with shape (H, W, 3) or (3, H, W), got {image.shape}")

    if image.dtype != np.uint8:
        image = image.astype(np.float32)
        if image.max() <= 1.0:
            image = image * 255.0
        image = np.clip(image, 0.0, 255.0).astype(np.uint8)

    return image


def _list_image_files(image_folder: str) -> list[str]:
    image_files = sorted(glob.glob(os.path.join(image_folder, "*")))
    image_extensions = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp"}
    return [f for f in image_files if os.path.splitext(f.lower())[1] in image_extensions]


def _get_mask_filename(image_paths: Optional[list[str]], index: int) -> str:
    if image_paths is not None and index < len(image_paths):
        return os.path.basename(image_paths[index])
    return f"frame_{index:06d}.png"


def _save_human_mask_visualization(
    image: np.ndarray,
    human_mask: np.ndarray,
    output_path: str,
) -> None:
    image_rgb = _image_to_rgb_uint8(image)
    if human_mask.shape[:2] != image_rgb.shape[:2]:
        human_mask = cv2.resize(
            human_mask,
            (image_rgb.shape[1], image_rgb.shape[0]),
            interpolation=cv2.INTER_NEAREST,
        )

    mask_uint8 = _mask_to_uint8(human_mask)
    mask_rgb = np.repeat(mask_uint8[..., None], 3, axis=2)
    overlay = image_rgb.astype(np.float32).copy()
    human_pixels = _mask_to_float(human_mask) <= _HUMANSEG_BINARY_THRESHOLD
    overlay[human_pixels] = overlay[human_pixels] * 0.35 + np.array([255, 96, 64], dtype=np.float32) * 0.65
    overlay = np.clip(overlay, 0.0, 255.0).astype(np.uint8)

    panel = np.concatenate([image_rgb, mask_rgb, overlay], axis=1)
    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)
    cv2.imwrite(output_path, cv2.cvtColor(panel, cv2.COLOR_RGB2BGR))


def _load_humanseg_model(humanseg_model_path: str):
    if YOLO is None:
        print("Warning: ultralytics not available, skipping human segmentation")
        return None

    model_path = humanseg_model_path or _HUMANSEG_DEFAULT_MODEL
    try:
        return YOLO(model_path)
    except Exception as e:
        print(f"Warning: Failed to load human segmentation model '{model_path}': {e}")
        return None


def _dilate_instance_mask(
    instance_mask: np.ndarray,
    box_xyxy: Optional[np.ndarray],
    dilation_ratio: float,
) -> np.ndarray:
    if dilation_ratio <= 0.0:
        return instance_mask

    binary_mask = (instance_mask > _HUMANSEG_BINARY_THRESHOLD).astype(np.uint8)
    if box_xyxy is not None:
        x1, y1, x2, y2 = box_xyxy.tolist()
        box_w = max(float(x2) - float(x1), 1.0)
        box_h = max(float(y2) - float(y1), 1.0)
    else:
        ys, xs = np.where(binary_mask > 0)
        if len(xs) == 0 or len(ys) == 0:
            return instance_mask
        box_w = max(float(xs.max() - xs.min() + 1), 1.0)
        box_h = max(float(ys.max() - ys.min() + 1), 1.0)

    dilation_radius = int(np.ceil(max(box_w, box_h) * dilation_ratio))
    if dilation_radius <= 0:
        return instance_mask

    kernel_size = dilation_radius * 2 + 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kernel_size, kernel_size))
    dilated_mask = cv2.dilate(binary_mask, kernel, iterations=1)
    return dilated_mask.astype(np.float32)


def segment_humans_from_array(
    image: np.ndarray,
    humanseg_model,
    target_h: int,
    target_w: int,
    human_mask_dilation_ratio: float = _HUMANSEG_DEFAULT_DILATION_RATIO,
) -> np.ndarray:
    image_rgb = _image_to_rgb_uint8(image)
    image_bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)

    results = humanseg_model.predict(
        source=image_bgr,
        classes=[_PERSON_CLASS_ID],
        retina_masks=True,
        verbose=False,
    )

    keep_mask = np.ones((target_h, target_w), dtype=np.float32)
    if not results:
        return keep_mask

    result = results[0]
    if result.masks is None or result.masks.data is None or result.masks.data.shape[0] == 0:
        return keep_mask

    person_masks = result.masks.data.detach().float().cpu().numpy()
    boxes = None
    if result.boxes is not None and result.boxes.xyxy is not None:
        boxes = result.boxes.xyxy.detach().float().cpu().numpy()

    combined_person_mask = np.zeros((target_h, target_w), dtype=np.float32)
    for i, instance_mask in enumerate(person_masks):
        if instance_mask.shape != (target_h, target_w):
            instance_mask = cv2.resize(instance_mask, (target_w, target_h), interpolation=cv2.INTER_LINEAR)
        dilated_mask = _dilate_instance_mask(
            instance_mask,
            None if boxes is None or i >= len(boxes) else boxes[i],
            human_mask_dilation_ratio,
        )
        combined_person_mask = np.maximum(combined_person_mask, dilated_mask)

    keep_mask = 1.0 - np.clip(combined_person_mask, 0.0, 1.0)
    return keep_mask.astype(np.float32)


def load_or_create_human_masks(
    image_folder: Optional[str] = None,
    image_paths: Optional[list[str]] = None,
    images: Optional[np.ndarray] = None,
    humanseg_model_path: str = _HUMANSEG_DEFAULT_MODEL,
    human_mask_dilation_ratio: float = _HUMANSEG_DEFAULT_DILATION_RATIO,
    human_mask_dir: Optional[str] = None,
    human_mask_visualization_dir: Optional[str] = None,
    target_shape: Optional[Tuple[int, int]] = None,
    num_frames: Optional[int] = None,
) -> Optional[np.ndarray]:
    if image_folder is None and image_paths is None and images is None:
        print("Warning: Neither image_folder/image_paths nor images provided, skipping human segmentation")
        return None

    humanseg_model = _load_humanseg_model(humanseg_model_path)
    if humanseg_model is None:
        return None

    human_masks = []

    if human_mask_visualization_dir is not None:
        os.makedirs(human_mask_visualization_dir, exist_ok=True)
        print(f"Saving human mask visualizations to {human_mask_visualization_dir}")

    if images is not None:
        if image_paths is None and image_folder is not None:
            image_paths = _list_image_files(image_folder)

        num_images = images.shape[0]
        if num_frames is not None:
            num_images = min(num_images, num_frames)
        if image_paths is not None:
            image_paths = image_paths[:num_images]

        if human_mask_dir is None and image_folder is not None:
            human_mask_dir = image_folder.rstrip("/") + "_human_masks"
        _prepare_human_mask_cache(human_mask_dir, human_mask_dilation_ratio)

        print("Generating human masks from image array...")
        for i in tqdm(range(num_images)):
            image_rgb = _image_to_rgb_uint8(images[i])
            image_h, image_w = image_rgb.shape[:2]
            image_name = _get_mask_filename(image_paths, i)
            mask_filepath = os.path.join(human_mask_dir, image_name) if human_mask_dir is not None else None

            if mask_filepath is not None and os.path.exists(mask_filepath):
                human_mask = cv2.imread(mask_filepath, cv2.IMREAD_GRAYSCALE)
                if human_mask is not None and human_mask.shape[:2] == (image_h, image_w):
                    human_mask = _mask_to_float(human_mask / 255.0)
                else:
                    human_mask = segment_humans_from_array(
                        image_rgb,
                        humanseg_model,
                        image_h,
                        image_w,
                        human_mask_dilation_ratio=human_mask_dilation_ratio,
                    )
                    cv2.imwrite(mask_filepath, _mask_to_uint8(human_mask))
            else:
                human_mask = segment_humans_from_array(
                    image_rgb,
                    humanseg_model,
                    image_h,
                    image_w,
                    human_mask_dilation_ratio=human_mask_dilation_ratio,
                )
                if mask_filepath is not None:
                    cv2.imwrite(mask_filepath, _mask_to_uint8(human_mask))

            if human_mask_visualization_dir is not None:
                _save_human_mask_visualization(
                    image_rgb,
                    human_mask,
                    os.path.join(human_mask_visualization_dir, image_name),
                )

            if target_shape is not None and human_mask.shape[:2] != target_shape:
                human_mask = cv2.resize(
                    human_mask,
                    (target_shape[1], target_shape[0]),
                    interpolation=cv2.INTER_LINEAR,
                )

            human_masks.append(_mask_to_float(human_mask))

    else:
        if image_paths is None and image_folder is not None:
            image_paths = _list_image_files(image_folder)

    if images is None and image_paths is not None:
        if len(image_paths) == 0:
            print("Warning: No image files provided, skipping human segmentation")
            return None

        if num_frames is not None:
            image_paths = image_paths[:num_frames]

        if human_mask_dir is None:
            if image_folder is None:
                image_folder = os.path.dirname(image_paths[0])
            human_mask_dir = image_folder.rstrip("/") + "_human_masks"
        _prepare_human_mask_cache(human_mask_dir, human_mask_dilation_ratio)

        print("Generating human masks from image files...")
        for image_path in tqdm(image_paths):
            image_name = os.path.basename(image_path)
            mask_filepath = os.path.join(human_mask_dir, image_name)

            if os.path.exists(mask_filepath):
                human_mask = cv2.imread(mask_filepath, cv2.IMREAD_GRAYSCALE)
                if human_mask is None:
                    print(f"Warning: Failed to read cached human mask {mask_filepath}, regenerating it")
                else:
                    human_mask = _mask_to_float(human_mask / 255.0)
            else:
                human_mask = None

            if human_mask is None:
                image_bgr = cv2.imread(image_path)
                if image_bgr is None:
                    print(f"Warning: Failed to read image {image_path}, skipping frame")
                    continue
                image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
                human_mask = segment_humans_from_array(
                    image_rgb,
                    humanseg_model,
                    image_rgb.shape[0],
                    image_rgb.shape[1],
                    human_mask_dilation_ratio=human_mask_dilation_ratio,
                )
                cv2.imwrite(mask_filepath, _mask_to_uint8(human_mask))
            else:
                image_rgb = None

            if human_mask_visualization_dir is not None:
                if image_rgb is None:
                    image_bgr = cv2.imread(image_path)
                    if image_bgr is not None:
                        image_rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
                if image_rgb is not None:
                    _save_human_mask_visualization(
                        image_rgb,
                        human_mask,
                        os.path.join(human_mask_visualization_dir, image_name),
                    )

            if target_shape is not None and human_mask.shape[:2] != target_shape:
                human_mask = cv2.resize(
                    human_mask,
                    (target_shape[1], target_shape[0]),
                    interpolation=cv2.INTER_LINEAR,
                )

            human_masks.append(_mask_to_float(human_mask))

    if len(human_masks) == 0:
        print("Warning: No human masks generated, skipping human segmentation")
        return None

    try:
        return np.stack(human_masks, axis=0)
    except ValueError:
        return np.array(human_masks, dtype=object)


def apply_human_segmentation(
    conf: np.ndarray,
    image_folder: Optional[str] = None,
    image_paths: Optional[list[str]] = None,
    images: Optional[np.ndarray] = None,
    humanseg_model_path: str = _HUMANSEG_DEFAULT_MODEL,
    human_mask_dilation_ratio: float = _HUMANSEG_DEFAULT_DILATION_RATIO,
    human_mask_dir: Optional[str] = None,
    human_mask_visualization_dir: Optional[str] = None,
) -> np.ndarray:
    S, H, W = conf.shape

    human_mask_array = load_or_create_human_masks(
        image_folder=image_folder,
        image_paths=image_paths,
        images=images,
        humanseg_model_path=humanseg_model_path,
        human_mask_dilation_ratio=human_mask_dilation_ratio,
        human_mask_dir=human_mask_dir,
        human_mask_visualization_dir=human_mask_visualization_dir,
        target_shape=(H, W),
        num_frames=S,
    )
    if human_mask_array is None:
        return conf

    if human_mask_array.shape[0] < S:
        print(
            f"Warning: Only {human_mask_array.shape[0]} human masks generated for {S} frames; "
            "leaving the remaining frames unmasked"
        )
        padded = np.ones((S, H, W), dtype=human_mask_array.dtype)
        padded[: human_mask_array.shape[0]] = human_mask_array
        human_mask_array = padded
    elif human_mask_array.shape[0] > S:
        human_mask_array = human_mask_array[:S]

    human_mask_binary = (human_mask_array > _HUMANSEG_BINARY_THRESHOLD).astype(np.float32)
    conf = conf * human_mask_binary

    print("Human segmentation applied successfully")
    return conf
