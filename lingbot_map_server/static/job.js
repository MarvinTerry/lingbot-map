(function () {
  const jobId = window.LINGBOT_JOB_UI.jobId;
  const storageKey = "lingbot_map_server_api_key";
  const apiKey = window.localStorage.getItem(storageKey) || "";
  const statusPill = document.getElementById("status-pill");
  const progressLabel = document.getElementById("progress-label");
  const progressPercent = document.getElementById("progress-percent");
  const progressFill = document.getElementById("job-progress-fill");
  const progressMeta = document.getElementById("progress-meta");
  const jobState = document.getElementById("job-state");
  const createdAt = document.getElementById("created-at");
  const startedAt = document.getElementById("started-at");
  const finishedAt = document.getElementById("finished-at");
  const inputFile = document.getElementById("input-file");
  const inputVideo = document.getElementById("input-video");
  const requestSummary = document.getElementById("request-summary");
  const runtimeSummary = document.getElementById("runtime-summary");
  const artifactList = document.getElementById("artifact-list");
  const refreshButton = document.getElementById("refresh-button");
  const deleteButton = document.getElementById("delete-button");
  const messageBox = document.getElementById("message-box");
  const previewPlaceholder = document.getElementById("preview-placeholder");
  const glbViewer = document.getElementById("glb-viewer");

  let pollTimer = null;
  let loadedGlbArtifactId = null;

  function showMessage(text, tone) {
    messageBox.hidden = false;
    messageBox.textContent = text;
    messageBox.className = `message-box ${tone || ""}`.trim();
  }

  function clearMessage() {
    messageBox.hidden = true;
    messageBox.textContent = "";
    messageBox.className = "message-box";
  }

  function formatDate(value) {
    if (!value) {
      return "-";
    }
    return new Date(value).toLocaleString();
  }

  function formatBytes(bytes) {
    if (!bytes && bytes !== 0) {
      return "-";
    }
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let unit = units[0];
    for (let i = 0; i < units.length; i += 1) {
      unit = units[i];
      if (value < 1024 || i === units.length - 1) {
        break;
      }
      value /= 1024;
    }
    return `${value.toFixed(unit === "B" ? 0 : 2)} ${unit}`;
  }

  function authHeaders() {
    if (!apiKey) {
      return {};
    }
    return { "X-API-Key": apiKey };
  }

  function setProgress(overallPercent, label, meta) {
    const clamped = Math.max(0, Math.min(100, overallPercent || 0));
    progressFill.style.width = `${clamped}%`;
    progressPercent.textContent = `${Math.round(clamped)}%`;
    progressLabel.textContent = label || "Waiting for progress data";
    progressMeta.textContent = meta || "";
  }

  function renderArtifacts(artifacts) {
    artifactList.innerHTML = "";
    if (!artifacts || artifacts.length === 0) {
      artifactList.innerHTML = '<div class="artifact-row"><div class="artifact-meta"><strong>暂无产物</strong><span>任务成功后这里会出现可下载文件。</span></div></div>';
      return;
    }

    artifacts.forEach((artifact) => {
      const row = document.createElement("div");
      row.className = "artifact-row";

      const meta = document.createElement("div");
      meta.className = "artifact-meta";
      meta.innerHTML = `<strong>${artifact.filename}</strong><span>${artifact.name} · ${formatBytes(artifact.size_bytes)}</span>`;

      const button = document.createElement("button");
      button.type = "button";
      button.className = "artifact-button";
      button.textContent = "Download";
      button.addEventListener("click", async function () {
        const response = await fetch(artifact.url, { headers: authHeaders() });
        if (!response.ok) {
          showMessage(`下载 ${artifact.filename} 失败。`, "error");
          return;
        }
        const blob = await response.blob();
        const objectUrl = URL.createObjectURL(blob);
        const anchor = document.createElement("a");
        anchor.href = objectUrl;
        anchor.download = artifact.filename;
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
        URL.revokeObjectURL(objectUrl);
      });

      row.appendChild(meta);
      row.appendChild(button);
      artifactList.appendChild(row);
    });
  }

  async function loadGlbPreview(artifacts) {
    const glbArtifact = (artifacts || []).find((item) => item.name === "scene_glb");
    if (!glbArtifact) {
      return;
    }
    if (loadedGlbArtifactId === glbArtifact.artifact_id) {
      return;
    }
    previewPlaceholder.textContent = "正在加载 GLB 预览...";

    try {
      const response = await fetch(glbArtifact.url, { headers: authHeaders() });
      if (!response.ok) {
        throw new Error("artifact fetch failed");
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      glbViewer.src = objectUrl;
      glbViewer.hidden = false;
      previewPlaceholder.hidden = true;
      loadedGlbArtifactId = glbArtifact.artifact_id;
    } catch (error) {
      previewPlaceholder.hidden = false;
      previewPlaceholder.textContent = "GLB 预览加载失败。你仍然可以使用下方下载按钮获取 scene.glb。";
    }
  }

  function renderJob(job) {
    clearMessage();
    statusPill.textContent = job.status;
    statusPill.dataset.state = job.status;
    jobState.textContent = job.status;
    createdAt.textContent = formatDate(job.created_at);
    startedAt.textContent = formatDate(job.started_at);
    finishedAt.textContent = formatDate(job.finished_at);
    inputFile.textContent = job.input?.original_filename || "-";

    const video = job.input?.video;
    inputVideo.textContent = video
      ? `${video.width}x${video.height} · ${video.frame_count} frames · ${video.fps.toFixed(2)} fps`
      : "-";

    requestSummary.textContent = [
      `mode=${job.request?.mode || "-"}`,
      `fps=${job.request?.fps || "-"}`,
      `mask_sky=${job.request?.mask_sky ? "true" : "false"}`,
    ].join(" · ");

    runtimeSummary.textContent = [
      `pid=${job.runtime?.pid || "-"}`,
      `return_code=${job.runtime?.return_code ?? "-"}`,
      `offload_to_cpu=${job.runtime?.offload_to_cpu ? "true" : "false"}`,
    ].join(" · ");

    const progress = job.progress || {};
    let meta = "";
    if (job.status === "queued") {
      meta = progress.queue_position
        ? `当前排队位置：第 ${progress.queue_position} 个。`
        : "正在等待 GPU worker。";
    } else if (progress.total && progress.current !== null && progress.current !== undefined) {
      meta = `阶段进度：${progress.current} / ${progress.total}`;
    } else if (job.status === "running") {
      meta = "任务正在处理中。";
    } else if (job.status === "succeeded") {
      meta = "所有阶段已经完成。";
    } else if (job.status === "failed") {
      meta = "任务失败，请查看日志。";
    }
    setProgress(progress.overall_percent || 0, progress.label || job.status, meta);

    renderArtifacts(job.artifacts);

    if (job.error) {
      showMessage(job.error, "error");
    } else if (job.status === "succeeded") {
      showMessage("任务已完成，可以直接预览或下载产物。", "success");
    }

    if (job.status === "succeeded") {
      loadGlbPreview(job.artifacts);
    }

    if (job.status === "failed" || job.status === "succeeded") {
      if (pollTimer) {
        window.clearTimeout(pollTimer);
        pollTimer = null;
      }
      return;
    }

    pollTimer = window.setTimeout(fetchJob, 2000);
  }

  async function fetchJob() {
    if (!apiKey) {
      showMessage("浏览器里还没有 API key。请先回上传页输入 API key。", "error");
      return;
    }

    try {
      const response = await fetch(`/jobs/${jobId}`, { headers: authHeaders() });
      if (!response.ok) {
        const payload = await response.json();
        throw new Error(payload.detail || "请求失败");
      }
      const job = await response.json();
      renderJob(job);
    } catch (error) {
      showMessage(String(error.message || error), "error");
    }
  }

  refreshButton.addEventListener("click", function () {
    if (pollTimer) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
    fetchJob();
  });

  deleteButton.addEventListener("click", async function () {
    if (!apiKey) {
      showMessage("浏览器里还没有 API key。请先回上传页输入 API key。", "error");
      return;
    }
    const confirmed = window.confirm("确认删除这个 job 及其所有产物吗？");
    if (!confirmed) {
      return;
    }
    const response = await fetch(`/jobs/${jobId}`, {
      method: "DELETE",
      headers: authHeaders(),
    });
    if (!response.ok) {
      showMessage("删除 job 失败。", "error");
      return;
    }
    window.location.href = "/ui/upload";
  });

  fetchJob();
})();
