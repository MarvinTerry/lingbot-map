import * as THREE from "/ui-static/vendor/three/three.module.js";
import { OrbitControls } from "/ui-static/vendor/three/examples/jsm/controls/OrbitControls.js";
import { GLTFLoader } from "/ui-static/vendor/three/examples/jsm/loaders/GLTFLoader.js";

const storageKey = "lingbot_map_server_api_key";
let apiKey = window.localStorage.getItem(storageKey) || "";
const initialJobId = window.LINGBOT_WORKSPACE.selectedJobId || null;

const jobsList = document.getElementById("jobs-list");
const refreshButton = document.getElementById("workspace-refresh");
const fitViewButton = document.getElementById("fit-view-button");
const deleteJobButton = document.getElementById("delete-job-button");
const filtersRoot = document.getElementById("workspace-filters");
const selectedJobTitle = document.getElementById("selected-job-title");
const detailStatusPill = document.getElementById("detail-status-pill");
const detailProgressLabel = document.getElementById("detail-progress-label");
const detailProgressPercent = document.getElementById("detail-progress-percent");
const detailProgressFill = document.getElementById("detail-progress-fill");
const detailProgressMeta = document.getElementById("detail-progress-meta");
const detailMessageBox = document.getElementById("detail-message-box");
const detailJobId = document.getElementById("detail-job-id");
const detailCreatedAt = document.getElementById("detail-created-at");
const detailStartedAt = document.getElementById("detail-started-at");
const detailFinishedAt = document.getElementById("detail-finished-at");
const detailInputFile = document.getElementById("detail-input-file");
const detailVideoMeta = document.getElementById("detail-video-meta");
const detailRequestMeta = document.getElementById("detail-request-meta");
const detailRuntimeMeta = document.getElementById("detail-runtime-meta");
const detailArtifacts = document.getElementById("detail-artifacts");
const viewerStage = document.getElementById("viewer-stage");
const viewerEmpty = document.getElementById("viewer-empty");
const viewerStatus = document.getElementById("viewer-status");
const viewerStats = document.getElementById("viewer-stats");
const authModal = document.getElementById("auth-modal");
const authModalForm = document.getElementById("auth-modal-form");
const authModalInput = document.getElementById("auth-modal-input");
const authModalSubmit = document.getElementById("auth-modal-submit");
const authModalMessage = document.getElementById("auth-modal-message");
const authModalCopy = document.getElementById("auth-modal-copy");

let currentFilter = "all";
let selectedJobId = initialJobId;
let allJobs = [];
let selectedJob = null;
let listPollTimer = null;
let jobPollTimer = null;
let currentArtifactId = null;
let currentObjectUrl = null;
let currentSceneObject = null;
let renderer = null;
let scene = null;
let camera = null;
let controls = null;
let loader = null;
let viewerAvailable = false;
let renderScheduled = false;
let previewFrame = null;
let currentPreviewUrl = null;
let authRequired = false;

if (viewerStage) {
  previewFrame = document.createElement("iframe");
  previewFrame.hidden = true;
  previewFrame.title = "LingBot-Map Preview";
  previewFrame.referrerPolicy = "strict-origin-when-cross-origin";
  Object.assign(previewFrame.style, {
    position: "absolute",
    inset: "0",
    width: "100%",
    height: "100%",
    border: "0",
    background: "#f6efe5",
    zIndex: "2",
  });
  viewerStage.appendChild(previewFrame);
}

function initializeViewer() {
  if (!viewerStage) {
    return;
  }

  try {
    renderer = new THREE.WebGLRenderer({
      antialias: false,
      alpha: false,
      powerPreference: "low-power",
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.25));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.0;
    renderer.setClearColor(0xf1e7d7, 1);
    viewerStage.appendChild(renderer.domElement);

    scene = new THREE.Scene();
    scene.fog = new THREE.Fog(0xf1e7d7, 12, 48);

    camera = new THREE.PerspectiveCamera(50, 1, 0.01, 2000);
    camera.position.set(2.2, 1.6, 3.4);

    controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.07;
    controls.target.set(0, 0.2, 0);
    controls.addEventListener("change", requestRender);

    const hemiLight = new THREE.HemisphereLight(0xfff4d8, 0x7b6248, 1.35);
    scene.add(hemiLight);

    const dirLight = new THREE.DirectionalLight(0xffffff, 1.25);
    dirLight.position.set(3, 5, 4);
    scene.add(dirLight);

    loader = new GLTFLoader();
    viewerAvailable = true;
    requestRender();
  } catch (error) {
    viewerAvailable = false;
    viewerStatus.textContent = "Viewer unavailable";
    viewerStats.textContent = "-";
    viewerEmpty.hidden = false;
    viewerEmpty.textContent = "当前浏览器无法初始化 WebGL viewer，但 job 列表和产物下载仍可正常使用。";
  }
}

function authHeaders() {
  return apiKey ? { "X-API-Key": apiKey } : {};
}

function showAuthModal(message) {
  authRequired = true;
  authModal.hidden = false;
  authModalCopy.textContent = message || "访问 workspace 前需要先提供 API key。";
  authModalInput.value = apiKey || "";
  authModalMessage.hidden = true;
  authModalMessage.textContent = "";
  authModalSubmit.disabled = false;
  authModalSubmit.textContent = "Login";
  window.setTimeout(() => authModalInput.focus(), 0);
}

function hideAuthModal() {
  authRequired = false;
  authModal.hidden = true;
  authModalMessage.hidden = true;
  authModalMessage.textContent = "";
}

function showAuthError(message) {
  authModalMessage.hidden = false;
  authModalMessage.textContent = message;
  authModalMessage.className = "message-box error";
}

function handleUnauthorized(message) {
  apiKey = "";
  window.localStorage.removeItem(storageKey);
  if (listPollTimer) {
    window.clearTimeout(listPollTimer);
    listPollTimer = null;
  }
  if (jobPollTimer) {
    window.clearTimeout(jobPollTimer);
    jobPollTimer = null;
  }
  resetWorkspaceState();
  showAuthModal(message || "API key 无效，请重新输入。");
}

function showMessage(text, tone) {
  detailMessageBox.hidden = false;
  detailMessageBox.textContent = text;
  detailMessageBox.className = `message-box ${tone || ""}`.trim();
}

function clearMessage() {
  detailMessageBox.hidden = true;
  detailMessageBox.textContent = "";
  detailMessageBox.className = "message-box";
}

function formatDate(value) {
  return value ? new Date(value).toLocaleString() : "-";
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

function setProgress(progress, status) {
  const overall = Math.max(0, Math.min(100, progress?.overall_percent || 0));
  detailProgressFill.style.width = `${overall}%`;
  detailProgressPercent.textContent = `${Math.round(overall)}%`;
  detailProgressLabel.textContent = progress?.label || status || "Waiting";

  let meta = "";
  if (status === "queued") {
    meta = progress?.queue_position
      ? `当前排队位置：第 ${progress.queue_position} 个`
      : "等待 GPU worker 分配";
  } else if (progress?.total && progress?.current !== null && progress?.current !== undefined) {
    meta = `阶段进度：${progress.current} / ${progress.total}`;
  } else if (status === "running") {
    meta = "任务正在处理";
  } else if (status === "succeeded") {
    meta = "任务已完成";
  } else if (status === "failed") {
    meta = "任务失败";
  }
  detailProgressMeta.textContent = meta || "当前暂无额外进度信息。";
}

function filteredJobs() {
  if (currentFilter === "all") {
    return allJobs;
  }
  return allJobs.filter((job) => job.status === currentFilter);
}

function updateUrl(jobId) {
  const url = new URL(window.location.href);
  if (jobId) {
    url.searchParams.set("job_id", jobId);
  } else {
    url.searchParams.delete("job_id");
  }
  window.history.replaceState({}, "", url);
}

function setSelectedJob(jobId, { shouldFetch = true } = {}) {
  selectedJobId = jobId;
  updateUrl(jobId);
  renderJobList();
  if (jobId && shouldFetch) {
    fetchSelectedJob();
  }
}

function renderJobList() {
  const jobs = filteredJobs();
  jobsList.innerHTML = "";

  if (jobs.length === 0) {
    jobsList.innerHTML = '<div class="jobs-empty">当前筛选条件下没有 job。</div>';
    return;
  }

  jobs.forEach((job) => {
    const item = document.createElement("button");
    item.type = "button";
    item.className = "job-list-item";
    if (job.job_id === selectedJobId) {
      item.classList.add("is-active");
    }

    const progress = job.progress || {};
    const percent = Math.round(progress.overall_percent || 0);
    item.innerHTML = `
      <div class="job-list-head">
        <strong>${job.input?.original_filename || job.job_id}</strong>
        <span class="job-list-state" data-state="${job.status}">${job.status}</span>
      </div>
      <div class="job-list-sub">${formatDate(job.created_at)}</div>
      <div class="job-list-progress-row">
        <span>${progress.label || "-"}</span>
        <span>${percent}%</span>
      </div>
      <div class="job-list-progress-track"><div class="job-list-progress-fill" style="width:${percent}%"></div></div>
    `;
    item.addEventListener("click", () => setSelectedJob(job.job_id));
    jobsList.appendChild(item);
  });
}

function clearViewer() {
  if (!viewerAvailable || !scene) {
    return;
  }
  if (currentSceneObject) {
    scene.remove(currentSceneObject);
    currentSceneObject.traverse?.((child) => {
      if (child.geometry) {
        child.geometry.dispose?.();
      }
      if (child.material) {
        if (Array.isArray(child.material)) {
          child.material.forEach((material) => material.dispose?.());
        } else {
          child.material.dispose?.();
        }
      }
    });
    currentSceneObject = null;
  }
  if (currentObjectUrl) {
    URL.revokeObjectURL(currentObjectUrl);
    currentObjectUrl = null;
  }
  currentArtifactId = null;
  requestRender();
}

function clearEmbeddedPreview() {
  if (!previewFrame) {
    currentPreviewUrl = null;
    return;
  }
  previewFrame.hidden = true;
  if (previewFrame.src) {
    previewFrame.src = "about:blank";
  }
  currentPreviewUrl = null;
}

function loadEmbeddedPreview(job) {
  const preview = job?.preview || {};
  if (!previewFrame || preview.status !== "ready" || !preview.url) {
    return false;
  }
  clearViewer();
  if (currentPreviewUrl !== preview.url) {
    previewFrame.src = preview.url;
    currentPreviewUrl = preview.url;
  }
  previewFrame.hidden = false;
  viewerEmpty.hidden = true;
  viewerStatus.textContent = "Interactive preview";
  viewerStats.textContent = preview.port ? `Viser :${preview.port}` : "Viser";
  fitViewButton.textContent = "Open Preview";
  return true;
}

function renderScene() {
  renderScheduled = false;
  if (!viewerAvailable || !renderer || !scene || !camera || !controls) {
    return;
  }
  controls.update();
  renderer.render(scene, camera);
}

function requestRender() {
  if (renderScheduled) {
    return;
  }
  renderScheduled = true;
  window.requestAnimationFrame(renderScene);
}

function resetWorkspaceState() {
  selectedJob = null;
  selectedJobTitle.textContent = "No job selected";
  detailStatusPill.textContent = "idle";
  detailStatusPill.dataset.state = "idle";
  detailJobId.textContent = "-";
  detailCreatedAt.textContent = "-";
  detailStartedAt.textContent = "-";
  detailFinishedAt.textContent = "-";
  detailInputFile.textContent = "-";
  detailVideoMeta.textContent = "-";
  detailRequestMeta.textContent = "-";
  detailRuntimeMeta.textContent = "-";
  detailArtifacts.innerHTML = '<div class="artifact-row"><div class="artifact-meta"><strong>暂无选中 job</strong><span>请从左侧列表选择一个 job。</span></div></div>';
  setProgress({ overall_percent: 0, label: "Waiting for job" }, "idle");
  clearEmbeddedPreview();
  clearViewer();
  viewerEmpty.hidden = false;
  viewerEmpty.textContent = "左侧选择一个 job。成功完成的 job 会在这里以 Three.js 方式加载并展示 scene.glb。";
  viewerStatus.textContent = "Idle";
  viewerStats.textContent = "-";
  fitViewButton.textContent = "Fit View";
}

function fitObjectInView(object) {
  if (!viewerAvailable || !camera || !controls || !object) {
    return;
  }
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) {
    return;
  }

  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const maxDim = Math.max(size.x, size.y, size.z, 0.1);
  const distance = maxDim * 1.6;

  camera.near = Math.max(0.01, distance / 1000);
  camera.far = distance * 100;
  camera.updateProjectionMatrix();

  camera.position.set(center.x + distance, center.y + distance * 0.6, center.z + distance);
  controls.target.copy(center);
  controls.update();

  viewerStats.textContent = `Bounds: ${size.x.toFixed(2)} × ${size.y.toFixed(2)} × ${size.z.toFixed(2)}`;

  object.traverse((child) => {
    if (child.isPoints && child.material && "size" in child.material) {
      child.material.size = Math.min(Math.max(maxDim * 0.04, 0.01), 0.12);
      child.material.sizeAttenuation = false;
      child.material.needsUpdate = true;
    }
  });
  requestRender();
}

async function loadGlb(job) {
  if (!viewerAvailable || !loader) {
    viewerEmpty.hidden = false;
    viewerEmpty.textContent = "当前浏览器无法加载 GLB 预览，请直接下载产物查看。";
    viewerStatus.textContent = "Viewer unavailable";
    viewerStats.textContent = "-";
    return;
  }

  const artifact = (job.artifacts || []).find((item) => item.name === "scene_glb");
  if (!artifact) {
    clearViewer();
    viewerEmpty.hidden = false;
    viewerEmpty.textContent = "这个 job 还没有 scene.glb。";
    viewerStatus.textContent = "No GLB artifact";
    viewerStats.textContent = "-";
    return;
  }

  if (currentArtifactId === artifact.artifact_id) {
    return;
  }

  viewerStatus.textContent = "Loading GLB...";
  viewerEmpty.hidden = false;
  viewerEmpty.textContent = "正在下载并加载 GLB。";

  const response = await fetch(artifact.url, { headers: authHeaders() });
  if (response.status === 401) {
    handleUnauthorized("GLB 预览请求被拒绝，请重新输入 API key。");
    return;
  }
  if (!response.ok) {
    viewerStatus.textContent = "GLB load failed";
    viewerEmpty.textContent = "GLB 下载失败，请稍后重试。";
    return;
  }

  const blob = await response.blob();
  const objectUrl = URL.createObjectURL(blob);

  try {
    const gltf = await loader.loadAsync(objectUrl);
    clearViewer();
    currentObjectUrl = objectUrl;
    currentArtifactId = artifact.artifact_id;
    currentSceneObject = gltf.scene;
    scene.add(gltf.scene);
    fitObjectInView(gltf.scene);
    viewerEmpty.hidden = true;
    viewerStatus.textContent = "GLB loaded";
    requestRender();
  } catch (error) {
    URL.revokeObjectURL(objectUrl);
    viewerStatus.textContent = "GLB load failed";
    viewerEmpty.hidden = false;
    viewerEmpty.textContent = "GLB 解析失败。";
  }
}

function renderArtifacts(job) {
  detailArtifacts.innerHTML = "";
  const artifacts = job?.artifacts || [];
  if (artifacts.length === 0) {
    detailArtifacts.innerHTML = '<div class="artifact-row"><div class="artifact-meta"><strong>暂无产物</strong><span>任务成功后可下载 scene.glb、metadata.json 和 log.txt。</span></div></div>';
    return;
  }

  artifacts.forEach((artifact) => {
    const row = document.createElement("div");
    row.className = "artifact-row";
    row.innerHTML = `
      <div class="artifact-meta">
        <strong>${artifact.filename}</strong>
        <span>${artifact.name} · ${formatBytes(artifact.size_bytes)}</span>
      </div>
    `;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "artifact-button";
    button.textContent = "Download";
    button.addEventListener("click", async () => {
      const response = await fetch(artifact.url, { headers: authHeaders() });
      if (response.status === 401) {
        handleUnauthorized("下载产物前需要重新输入有效的 API key。");
        return;
      }
      if (!response.ok) {
        showMessage(`下载 ${artifact.filename} 失败。`, "error");
        return;
      }
      const blob = await response.blob();
      const objectUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = artifact.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(objectUrl);
    });
    row.appendChild(button);
    detailArtifacts.appendChild(row);
  });
}

function renderSelectedJob(job) {
  selectedJob = job;
  clearMessage();
  selectedJobTitle.textContent = job.input?.original_filename || job.job_id;
  detailStatusPill.textContent = job.status;
  detailStatusPill.dataset.state = job.status;
  detailJobId.textContent = job.job_id;
  detailCreatedAt.textContent = formatDate(job.created_at);
  detailStartedAt.textContent = formatDate(job.started_at);
  detailFinishedAt.textContent = formatDate(job.finished_at);
  detailInputFile.textContent = job.input?.original_filename || "-";

  const video = job.input?.video;
  detailVideoMeta.textContent = video
    ? `${video.width}x${video.height} · ${video.frame_count} frames · ${video.fps.toFixed(2)} fps`
    : "-";
  detailRequestMeta.textContent = [
    `mode=${job.request?.mode || "-"}`,
    `fps=${job.request?.fps || "-"}`,
    `mask_sky=${job.request?.mask_sky ? "true" : "false"}`,
  ].join(" · ");
  detailRuntimeMeta.textContent = [
    `pid=${job.runtime?.pid || "-"}`,
    `return_code=${job.runtime?.return_code ?? "-"}`,
    `offload_to_cpu=${job.runtime?.offload_to_cpu ? "true" : "false"}`,
  ].join(" · ");

  setProgress(job.progress, job.status);
  renderArtifacts(job);

  if (job.error) {
    showMessage(job.error, "error");
  } else if (job.status === "succeeded") {
    showMessage("任务已完成，可以直接预览或下载产物。", "success");
  }

  if (job.status === "succeeded") {
    if (loadEmbeddedPreview(job)) {
      return;
    }

    const preview = job.preview || {};
    if (preview.status === "starting" || preview.status === "pending") {
      clearViewer();
      viewerEmpty.hidden = false;
      viewerEmpty.textContent = "正在启动交互式预览，请稍候...";
      viewerStatus.textContent = "Starting preview";
      viewerStats.textContent = "-";
      fitViewButton.textContent = "Fit View";
      return;
    }

    clearEmbeddedPreview();
    fitViewButton.textContent = "Fit View";
    loadGlb(job);
  } else {
    clearEmbeddedPreview();
    clearViewer();
    viewerEmpty.hidden = false;
    viewerEmpty.textContent = job.status === "failed"
      ? "任务失败，无法展示 GLB。"
      : "等待任务完成后显示 GLB。";
    viewerStatus.textContent = job.progress?.label || job.status;
    viewerStats.textContent = "-";
    fitViewButton.textContent = "Fit View";
  }
}

async function fetchJobs() {
  if (!apiKey) {
    resetWorkspaceState();
    showAuthModal("访问 workspace 前需要先提供 API key。");
    return;
  }

  try {
    const response = await fetch("/jobs", { headers: authHeaders() });
    if (response.status === 401) {
      handleUnauthorized("API key 无效，请重新输入。");
      return;
    }
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail || "Failed to fetch jobs");
    }
    const payload = await response.json();
    allJobs = payload.jobs || [];

    if (!selectedJobId && allJobs.length > 0) {
      selectedJobId = allJobs[0].job_id;
    }
    if (selectedJobId && !allJobs.some((job) => job.job_id === selectedJobId)) {
      selectedJobId = allJobs.length > 0 ? allJobs[0].job_id : null;
    }

    renderJobList();
    if (selectedJobId) {
      fetchSelectedJob();
    } else {
      resetWorkspaceState();
    }
  } catch (error) {
    showMessage(String(error.message || error), "error");
  } finally {
    if (listPollTimer) {
      window.clearTimeout(listPollTimer);
    }
    if (!authRequired && apiKey) {
      listPollTimer = window.setTimeout(fetchJobs, 2500);
    } else {
      listPollTimer = null;
    }
  }
}

async function fetchSelectedJob() {
  if (!selectedJobId) {
    return;
  }
  try {
    const response = await fetch(`/jobs/${selectedJobId}`, { headers: authHeaders() });
    if (response.status === 401) {
      handleUnauthorized("API key 无效，请重新输入。");
      return;
    }
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail || "Failed to fetch job");
    }
    const job = await response.json();
    renderSelectedJob(job);
  } catch (error) {
    showMessage(String(error.message || error), "error");
  } finally {
    if (jobPollTimer) {
      window.clearTimeout(jobPollTimer);
    }
    if (!authRequired && apiKey && selectedJobId) {
      jobPollTimer = window.setTimeout(fetchSelectedJob, 2000);
    } else {
      jobPollTimer = null;
    }
  }
}

function resizeRenderer() {
  if (!viewerAvailable || !renderer || !camera) {
    return;
  }
  const rect = viewerStage.getBoundingClientRect();
  if (rect.width === 0 || rect.height === 0) {
    return;
  }
  camera.aspect = rect.width / rect.height;
  camera.updateProjectionMatrix();
  renderer.setSize(rect.width, rect.height, false);
  requestRender();
}

fitViewButton.addEventListener("click", () => {
  if (currentPreviewUrl) {
    window.open(currentPreviewUrl, "_blank", "noopener");
    return;
  }
  if (currentSceneObject) {
    fitObjectInView(currentSceneObject);
  }
});

deleteJobButton.addEventListener("click", async () => {
  if (!selectedJobId) {
    return;
  }
  const confirmed = window.confirm("确认删除当前 job 及其所有产物吗？");
  if (!confirmed) {
    return;
  }
  const response = await fetch(`/jobs/${selectedJobId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  if (response.status === 401) {
    handleUnauthorized("删除 job 前需要重新输入有效的 API key。");
    return;
  }
  if (!response.ok) {
    showMessage("删除 job 失败。", "error");
    return;
  }

  const remaining = allJobs.filter((job) => job.job_id !== selectedJobId);
  setSelectedJob(remaining.length > 0 ? remaining[0].job_id : null, { shouldFetch: false });
  await fetchJobs();
});

refreshButton.addEventListener("click", async () => {
  if (authRequired) {
    return;
  }
  if (listPollTimer) {
    window.clearTimeout(listPollTimer);
    listPollTimer = null;
  }
  if (jobPollTimer) {
    window.clearTimeout(jobPollTimer);
    jobPollTimer = null;
  }
  await fetchJobs();
});

filtersRoot.addEventListener("click", (event) => {
  if (authRequired) {
    return;
  }
  const button = event.target.closest("[data-filter]");
  if (!button) {
    return;
  }
  currentFilter = button.dataset.filter;
  [...filtersRoot.querySelectorAll("[data-filter]")].forEach((node) => {
    node.classList.toggle("is-active", node === button);
  });
  renderJobList();
});

window.addEventListener("resize", resizeRenderer);

authModalForm.addEventListener("submit", async (event) => {
  event.preventDefault();

  const nextApiKey = authModalInput.value.trim();
  if (!nextApiKey) {
    showAuthError("请输入 API key。");
    return;
  }

  authModalSubmit.disabled = true;
  authModalSubmit.textContent = "Checking...";
  authModalMessage.hidden = true;

  try {
    const response = await fetch("/jobs", {
      headers: { "X-API-Key": nextApiKey },
    });
    if (response.status === 401) {
      showAuthError("API key 无效。");
      return;
    }
    if (!response.ok) {
      const payload = await response.json();
      throw new Error(payload.detail || "登录校验失败");
    }

    apiKey = nextApiKey;
    window.localStorage.setItem(storageKey, apiKey);
    hideAuthModal();
    await fetchJobs();
  } catch (error) {
    showAuthError(String(error.message || error));
  } finally {
    authModalSubmit.disabled = false;
    authModalSubmit.textContent = "Login";
  }
});

initializeViewer();
resizeRenderer();
if (apiKey) {
  fetchJobs();
} else {
  resetWorkspaceState();
  showAuthModal("访问 workspace 前需要先提供 API key。");
}
