from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from lingbot_map.vis.point_cloud_viewer import PointCloudViewer


@dataclass
class PreviewServerHandle:
    bundle_path: Path
    port: int
    viewer: PointCloudViewer

    def stop(self) -> None:
        self.viewer.stop()


def load_preview_bundle(path: Path) -> dict:
    with np.load(path, allow_pickle=False) as bundle:
        return {key: bundle[key] for key in bundle.files}


def start_preview_server(bundle_path: Path, port: int) -> PreviewServerHandle:
    pred_dict = load_preview_bundle(bundle_path)
    viewer_pred_dict = {
        "images": pred_dict["images"],
        "extrinsic": pred_dict["extrinsic"],
        "intrinsic": pred_dict["intrinsic"],
    }
    use_point_map = "depth" not in pred_dict

    if use_point_map:
        viewer_pred_dict["world_points"] = pred_dict["world_points"]
        viewer_pred_dict["world_points_conf"] = pred_dict["world_points_conf"]
        viewer_pred_dict["point_frame"] = pred_dict.get("point_frame", "camera")
    else:
        viewer_pred_dict["depth"] = pred_dict["depth"]
        viewer_pred_dict["depth_conf"] = pred_dict["depth_conf"]

    viewer = PointCloudViewer(
        pred_dict=viewer_pred_dict,
        port=port,
        show_camera=True,
        vis_threshold=0.0,
        downsample_factor=1,
        point_size=0.0015,
        use_point_map=use_point_map,
        depth_stride=1,
    )
    viewer.run(background_mode=True)
    return PreviewServerHandle(bundle_path=bundle_path, port=port, viewer=viewer)
