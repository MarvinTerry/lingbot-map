# LingBot-Map Server API 调试文档

这份文档面向需要联调上传接口的工程师，目标是尽快跑通：

- 上传 `mp4`
- 创建 job
- 轮询状态
- 下载产物
- 删除 job

对应服务端实现见 [app.py](/home/ubuntu/lingbot-map/lingbot_map_server/app.py)。

## 基本信息

- Base URL: `http://127.0.0.1:8000`
- 鉴权: 必须带 API key
- 支持两种 header
  - `X-API-Key: <key>`
  - `Authorization: Bearer <key>`

## 端点总览

公开接口：

- `GET /healthz`

鉴权接口：

- `GET /jobs`
- `POST /jobs`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/artifacts`
- `GET /artifacts/{artifact_id}`
- `DELETE /jobs/{job_id}`

## 创建 Job

`POST /jobs`

请求类型：

- `multipart/form-data`

表单字段：

- `file`: 必填，必须是 `.mp4`
- `fps`: 可选，默认 `10`
- `mode`: 可选，`streaming` 或 `windowed`
- `window_size`: 可选，默认 `64`
- `overlap_size`: 可选，默认 `16`
- `keyframe_interval`: 可选，正整数
- `num_scale_frames`: 可选，默认 `8`
- `mask_sky`: 可选，默认 `false`

最小 `curl` 示例：

```bash
curl -X POST "http://lingbotmap.entropix.online:8000/jobs" \
  -H "X-API-Key: change-me" \
  -F "file=@ad59d7bf169eff909f269107aa9aa379.mp4" \
  -F "fps=10" \
  -F "mode=streaming" \
  -F "num_scale_frames=8"
```

返回值示例：

```json
{
  "job_id": "a8b20d171f4c4940b95e7704d4a0a6eb",
  "status": "queued",
  "progress": {
    "phase": "queued",
    "label": "Waiting in queue"
  }
}
```

## 查询 Job

`GET /jobs/{job_id}`

示例：

```bash
curl "http://127.0.0.1:8000/jobs/a8b20d171f4c4940b95e7704d4a0a6eb" \
  -H "X-API-Key: change-me"
```

重点字段：

- `status`
  - `queued`
  - `running`
  - `succeeded`
  - `failed`
- `progress`
- `artifacts`
- `preview`
- `error`

## 列出所有 Jobs

`GET /jobs`

示例：

```bash
curl "http://127.0.0.1:8000/jobs" \
  -H "X-API-Key: change-me"
```

## 列出产物

`GET /jobs/{job_id}/artifacts`

示例：

```bash
curl "http://127.0.0.1:8000/jobs/a8b20d171f4c4940b95e7704d4a0a6eb/artifacts" \
  -H "X-API-Key: change-me"
```

常见产物：

- `scene.glb`
- `metadata.json`
- `log.txt`

## 下载产物

`GET /artifacts/{artifact_id}`

下载 `scene.glb` 示例：

```bash
curl "http://127.0.0.1:8000/artifacts/a8b20d171f4c4940b95e7704d4a0a6eb:scene_glb" \
  -H "X-API-Key: change-me" \
  -o scene.glb
```

## 删除 Job

`DELETE /jobs/{job_id}`

示例：

```bash
curl -X DELETE "http://127.0.0.1:8000/jobs/a8b20d171f4c4940b95e7704d4a0a6eb" \
  -H "X-API-Key: change-me"
```

成功时返回：

- HTTP `204 No Content`

## 调试建议

- 先用 `GET /healthz` 确认服务活着。
- 先用一个小 `mp4` 验证接口，再切大视频。
- 上传成功后优先轮询 `GET /jobs/{job_id}`，不要靠前端页面人工看状态。
- 如果 job 失败，优先下载 `log.txt` 排查。
- 如果启用了 `mask_sky=true`，首次运行可能触发 `skyseg.onnx` 下载。

## 参考代码

仓库里附带了一个可直接运行的参考脚本：

- [lingbot_map_server_api_example.py](/home/ubuntu/lingbot-map/scripts/lingbot_map_server_api_example.py)

示例：

```bash
.venv/bin/python scripts/lingbot_map_server_api_example.py \
  --base-url http://127.0.0.1:8000 \
  --api-key change-me \
  --video 58aceb3121bdd696e377637a4e3b58b7.mp4 \
  --fps 10 \
  --mode streaming \
  --download-dir /tmp/lingbot-map-artifacts
```

这个脚本会：

1. 上传视频创建 job
2. 轮询直到 `succeeded` 或 `failed`
3. 列出产物
4. 下载全部产物到本地目录

