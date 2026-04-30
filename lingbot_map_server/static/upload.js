(function () {
  const apiKeyInput = document.getElementById("api-key");
  const fileInput = document.getElementById("video-file");
  const modeInput = document.getElementById("mode");
  const uploadForm = document.getElementById("upload-form");
  const progressFill = document.getElementById("progress-fill");
  const progressText = document.getElementById("progress-text");
  const messageBox = document.getElementById("message-box");
  const submitButton = document.getElementById("submit-button");

  const storageKey = "lingbot_map_server_api_key";
  apiKeyInput.value = window.localStorage.getItem(storageKey) || "";

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

  function setProgress(percent) {
    const clamped = Math.max(0, Math.min(100, percent));
    progressFill.style.width = `${clamped}%`;
    progressText.textContent = `${Math.round(clamped)}%`;
  }

  function toggleWindowFields() {
    const isWindowed = modeInput.value === "windowed";
    document.getElementById("window-size").disabled = !isWindowed;
    document.getElementById("overlap-size").disabled = !isWindowed;
  }

  modeInput.addEventListener("change", toggleWindowFields);
  toggleWindowFields();

  uploadForm.addEventListener("submit", function (event) {
    event.preventDefault();
    clearMessage();

    const apiKey = apiKeyInput.value.trim();
    const file = fileInput.files[0];
    if (!apiKey) {
      showMessage("请先输入 API key。", "error");
      return;
    }
    if (!file) {
      showMessage("请选择一个 mp4 文件。", "error");
      return;
    }
    if (!file.name.toLowerCase().endsWith(".mp4")) {
      showMessage("当前版本只支持 .mp4 文件。", "error");
      return;
    }
    if (file.size > window.LINGBOT_UI.maxUploadBytes) {
      showMessage("文件超过服务端当前限制。", "error");
      return;
    }

    window.localStorage.setItem(storageKey, apiKey);

    const formData = new FormData();
    formData.append("file", file);
    formData.append("fps", document.getElementById("fps").value);
    formData.append("mode", modeInput.value);
    formData.append("window_size", document.getElementById("window-size").value);
    formData.append("overlap_size", document.getElementById("overlap-size").value);
    formData.append("num_scale_frames", document.getElementById("num-scale-frames").value);
    const keyframeInterval = document.getElementById("keyframe-interval").value.trim();
    if (keyframeInterval) {
      formData.append("keyframe_interval", keyframeInterval);
    }
    formData.append("mask_sky", document.getElementById("mask-sky").checked ? "true" : "false");
    formData.append("mask_humans", document.getElementById("mask-humans").checked ? "true" : "false");

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/jobs");
    xhr.setRequestHeader("X-API-Key", apiKey);

    submitButton.disabled = true;
    submitButton.textContent = "Uploading...";
    setProgress(0);

    xhr.upload.addEventListener("progress", function (e) {
      if (e.lengthComputable) {
        setProgress((e.loaded / e.total) * 100);
      }
    });

    xhr.onreadystatechange = function () {
      if (xhr.readyState !== XMLHttpRequest.DONE) {
        return;
      }
      submitButton.disabled = false;
      submitButton.textContent = "Start Job";

      if (xhr.status >= 200 && xhr.status < 300) {
        setProgress(100);
        const response = JSON.parse(xhr.responseText);
        showMessage(`Job ${response.job_id} 已创建，正在跳转结果页。`, "success");
        window.setTimeout(function () {
          window.location.href = `/ui/workspace?job_id=${response.job_id}`;
        }, 350);
        return;
      }

      let detail = "上传失败，请检查服务日志。";
      try {
        const payload = JSON.parse(xhr.responseText);
        detail = payload.detail || detail;
      } catch (err) {
        // Keep the fallback message.
      }
      showMessage(detail, "error");
    };

    xhr.send(formData);
  });
})();
