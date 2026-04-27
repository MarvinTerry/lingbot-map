# LingBot-Map Server Phase 1

## 目标

本阶段只做一件事：

- 上传 `mp4`
- 异步排队执行 LingBot-Map
- 导出 `scene.glb`
- 提供状态查询、产物列表、产物下载、任务删除

## 边界

- 固定模型路径，通过环境变量 `LINGBOT_MAP_MODEL_PATH` 配置
- 单机单 GPU 串行执行
- 上传上限固定为 `4GB`
- 必须带 API key
- 不包含第一人称飞行视频
- 不包含推流

## 运行方式

安装依赖：

```bash
export http_proxy="http://127.0.0.1:7890"
export https_proxy="http://127.0.0.1:7890"
export all_proxy="socks5://127.0.0.1:7890"
uv pip install --python .venv/bin/python -e ".[server,vis]"
```

更正式的说明见：

- [`lingbot_map_server/README.md`](../lingbot_map_server/README.md)
- [`../.env.example`](../.env.example)

启动服务：

```bash
cp .env.example .env
./scripts/run_lingbot_map_server.sh
```

如果你会在请求里启用 `mask_sky=true`，并且本地还没有 `skyseg.onnx`，建议启动服务时也保留同样的代理环境变量，这样首次下载 sky segmentation 模型不会卡住。

## API

- `GET /healthz`
- `GET /jobs`
- `POST /jobs`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/artifacts`
- `GET /artifacts/{artifact_id}`
- `DELETE /jobs/{job_id}`

认证方式支持两种：

- `X-API-Key: <key>`
- `Authorization: Bearer <key>`

## POST /jobs 表单字段

- `file`: 必填，`mp4`
- `fps`: 默认 `10`
- `mode`: `streaming` 或 `windowed`
- `window_size`: 默认 `64`
- `overlap_size`: 默认 `16`
- `keyframe_interval`: 可选
- `num_scale_frames`: 默认 `8`
- `mask_sky`: 默认 `false`

## 产物

- `scene.glb`
- `metadata.json`
- `log.txt`

## 目录布局

```text
outputs/jobs/{job_id}/
├── input/input.mp4
├── artifacts/scene.glb
├── artifacts/log.txt
├── metadata.json
├── sky_masks/
└── sky_mask_visualizations/
```

## Smoke Test

```bash
./scripts/smoke_test_lingbot_map_server.sh
```

这个脚本会启动一个临时服务进程，使用仓库里的示例 `mp4` 跑通一条真实的端到端链路：

1. 健康检查
2. 鉴权校验
3. 上传视频创建 job
4. 轮询直到推理成功
5. 校验产物
6. 删除 job 并确认清理完成

## Minimal Web UI

现在还提供了一个最小浏览器界面：

- `/ui/upload`
- `/ui/workspace`

它的职责很克制：

- 上传 `mp4`
- 在左侧列出所有 jobs
- 轮询 job 状态
- 显示排队 / 运行阶段和实时进度
- 在中央大区域预览生成后的 `scene.glb`
- 下载产物
- 删除 job

它不尝试直接把 `viser` 强行嵌进工作台，而是先用 Three.js 把“上传 + jobs 工作台 + GLB 预览”这条最短路径打通。
