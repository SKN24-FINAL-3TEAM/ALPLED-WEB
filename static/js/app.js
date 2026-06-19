(function () {
  const DOC_ALLOWED_EXTENSIONS = new Set(["docx", "hwp", "pdf"]);
  const DOC_MAX_FILE_SIZE = 10 * 1024 * 1024;
  const DOC_MAX_FILES_PER_UPLOAD = 5;
  const onlyOfficeEditors = new Map();

  function showModal(modal) {
    if (!modal) return;
    modal.classList.remove("hidden");
    modal.classList.add("flex");
    document.body.classList.add("overflow-hidden");
  }

  function hideModal(modal) {
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
    document.body.classList.remove("overflow-hidden");
  }

  function getAlertRoot() {
    return document.getElementById("app-alert-root");
  }

  function getAlertTemplate() {
    return document.getElementById("app-alert-template");
  }

  function getConfirmRoot() {
    return document.getElementById("app-confirm-root");
  }

  function getNoticeRoot() {
    return document.getElementById("app-notice-root");
  }

  function getConfirmTitle() {
    return document.querySelector("[data-confirm-title]");
  }

  function getConfirmMessage() {
    return document.querySelector("[data-confirm-message]");
  }

  function getConfirmSubmitButton() {
    return document.querySelector("[data-confirm-submit]");
  }

  function getNoticeTitle() {
    return document.querySelector("[data-notice-title]");
  }

  function getNoticeMessage() {
    return document.querySelector("[data-notice-message]");
  }

  function getNoticeSubmitButton() {
    return document.querySelector("[data-notice-submit]");
  }

  function applyAlertStyles(alertNode, iconNode, level) {
    const levelMap = {
      success: {
        alert: ["border-emerald-200", "bg-emerald-50", "text-emerald-800"],
        icon: ["bg-emerald-100", "text-emerald-700"],
      },
      error: {
        alert: ["border-red-200", "bg-red-50", "text-red-800"],
        icon: ["bg-red-100", "text-red-700"],
      },
      warning: {
        alert: ["border-amber-200", "bg-amber-50", "text-amber-800"],
        icon: ["bg-amber-100", "text-amber-700"],
      },
      info: {
        alert: ["border-blue-200", "bg-blue-50", "text-blue-800"],
        icon: ["bg-blue-100", "text-blue-700"],
      },
    };
    const resolvedLevel = levelMap[level] ? level : "info";
    alertNode.classList.add(...levelMap[resolvedLevel].alert);
    iconNode.classList.add(...levelMap[resolvedLevel].icon);
  }

  function dismissAppAlert(alertNode) {
    if (!alertNode) return;
    alertNode.remove();
  }

  function showAppAlert(message, level = "info") {
    const root = getAlertRoot();
    const template = getAlertTemplate();
    if (!root || !template) {
      const fallback = document.createElement("div");
      fallback.className = "fixed right-4 top-4 z-[60] rounded-lg border border-slate-200 bg-white px-4 py-3 text-sm text-slate-700 shadow-lg";
      fallback.textContent = message;
      document.body.appendChild(fallback);
      window.setTimeout(() => fallback.remove(), 4000);
      return;
    }

    const alertNode = template.content.firstElementChild.cloneNode(true);
    const messageNode = alertNode.querySelector("[data-alert-message]");
    const iconNode = alertNode.querySelector("[data-alert-icon]");
    if (messageNode) {
      messageNode.textContent = message;
    }
    if (iconNode) {
      applyAlertStyles(alertNode, iconNode, level);
    }

    root.appendChild(alertNode);
    window.setTimeout(() => dismissAppAlert(alertNode), 4000);
  }

  let confirmResolver = null;
  let noticeResolver = null;
  let docJobPollTimer = null;
  let docJobElapsedTimer = null;
  let docJobElapsedSeconds = 0;

  function setConfirmTone(button, tone) {
    if (!button) return;
    button.className = "rounded-lg px-4 py-2 text-sm font-semibold text-white shadow-sm transition";
    if (tone === "danger") {
      button.classList.add("bg-rose-600", "hover:bg-rose-700");
      return;
    }
    button.classList.add("bg-blue-600", "hover:bg-blue-700");
  }

  function resolveConfirm(result) {
    if (!confirmResolver) return;
    const resolver = confirmResolver;
    confirmResolver = null;
    hideModal(getConfirmRoot());
    resolver(result);
  }

  function resolveNotice() {
    if (!noticeResolver) return;
    const resolver = noticeResolver;
    noticeResolver = null;
    hideModal(getNoticeRoot());
    resolver();
  }

  function showConfirmDialog({
    title = "확인",
    message = "",
    confirmText = "확인",
    cancelText = "취소",
    tone = "primary",
  }) {
    const root = getConfirmRoot();
    const titleNode = getConfirmTitle();
    const messageNode = getConfirmMessage();
    const submitButton = getConfirmSubmitButton();
    const cancelButton = root?.querySelector("[data-confirm-cancel]");
    if (!root || !titleNode || !messageNode || !submitButton || !cancelButton) {
      return Promise.resolve(true);
    }

    titleNode.textContent = title;
    messageNode.textContent = message;
    submitButton.textContent = confirmText;
    cancelButton.textContent = cancelText;
    setConfirmTone(submitButton, tone);
    showModal(root);

    return new Promise((resolve) => {
      confirmResolver = resolve;
      submitButton.focus();
    });
  }

  function showNoticeDialog({
    title = "안내",
    message = "",
    buttonText = "확인",
  }) {
    const root = getNoticeRoot();
    const titleNode = getNoticeTitle();
    const messageNode = getNoticeMessage();
    const submitButton = getNoticeSubmitButton();
    if (!root || !titleNode || !messageNode || !submitButton) {
      showAppAlert(message || title, "info");
      return Promise.resolve();
    }

    titleNode.textContent = title;
    messageNode.textContent = message;
    submitButton.textContent = buttonText;
    showModal(root);

    return new Promise((resolve) => {
      noticeResolver = resolve;
      submitButton.focus();
    });
  }

  function getJobProgressRoot() {
    return document.getElementById("doc-job-progress-root");
  }

  function getJobProgressTitle() {
    return document.querySelector("[data-job-progress-title]");
  }

  function getJobProgressMessage() {
    return document.querySelector("[data-job-progress-message]");
  }

  function getJobProgressElapsed() {
    return document.querySelector("[data-job-progress-elapsed]");
  }

  function clearDocJobPollTimer() {
    if (!docJobPollTimer) return;
    window.clearTimeout(docJobPollTimer);
    docJobPollTimer = null;
  }

  function clearDocJobElapsedTimer() {
    if (!docJobElapsedTimer) return;
    window.clearInterval(docJobElapsedTimer);
    docJobElapsedTimer = null;
  }

  function formatElapsedTime(totalSeconds) {
    const normalized = Math.max(Number.parseInt(totalSeconds || 0, 10) || 0, 0);
    const hours = Math.floor(normalized / 3600);
    const minutes = Math.floor((normalized % 3600) / 60);
    const seconds = normalized % 60;
    if (hours > 0) {
      return [hours, minutes, seconds].map((value) => String(value).padStart(2, "0")).join(":");
    }
    return [minutes, seconds].map((value) => String(value).padStart(2, "0")).join(":");
  }

  function renderElapsedTime(totalSeconds) {
    const elapsedNode = getJobProgressElapsed();
    if (!elapsedNode) return;
    elapsedNode.textContent = formatElapsedTime(totalSeconds);
  }

  function startElapsedTimer(initialSeconds = 0) {
    clearDocJobElapsedTimer();
    docJobElapsedSeconds = Math.max(Number.parseInt(initialSeconds || 0, 10) || 0, 0);
    renderElapsedTime(docJobElapsedSeconds);
    docJobElapsedTimer = window.setInterval(() => {
      docJobElapsedSeconds += 1;
      renderElapsedTime(docJobElapsedSeconds);
    }, 1000);
  }

  function updateJobProgress({ title, message }) {
    const titleNode = getJobProgressTitle();
    const messageNode = getJobProgressMessage();
    if (titleNode && title) {
      titleNode.textContent = title;
    }
    if (messageNode && message) {
      messageNode.textContent = message;
    }
  }

  function showJobProgress({ title, message }) {
    const root = getJobProgressRoot();
    if (!root) return;
    updateJobProgress({ title, message });
    showModal(root);
  }

  function hideJobProgress() {
    clearDocJobPollTimer();
    clearDocJobElapsedTimer();
    hideModal(getJobProgressRoot());
  }

  function hideOpenModalsExceptJobProgress() {
    const jobProgressRoot = getJobProgressRoot();
    document.querySelectorAll("[data-modal-root].flex").forEach((modal) => {
      if (modal === jobProgressRoot) return;
      hideModal(modal);
    });
  }

  function resolveFormSubmitUrl(form, fallbackUrl = window.location.href) {
    if (!form) return fallbackUrl;

    const dataUrl = form.dataset.submitUrl?.trim();
    if (dataUrl) {
      return dataUrl;
    }

    // Avoid named form controls like <input name="action"> shadowing DOM properties.
    const attributeUrl = form.getAttribute("action");
    if (typeof attributeUrl === "string" && attributeUrl.trim()) {
      return attributeUrl.trim();
    }

    return fallbackUrl;
  }

  async function pollDocJob(pollUrl, options = {}) {
    const {
      title = "문서 작업 진행 중",
      pollIntervalMs = 10000,
      fallbackRedirectUrl = "",
      fallbackElapsedSeconds = 0,
    } = options;

    if (!pollUrl) {
      hideJobProgress();
      showAppAlert("작업 상태 조회 경로를 확인할 수 없습니다.", "error");
      return;
    }

    try {
      const response = await window.fetch(pollUrl, {
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
        },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.message || "작업 상태를 확인하지 못했습니다.");
      }

      updateJobProgress({
        title: payload.title || title,
        message: payload.message || "작업을 처리하고 있습니다.",
      });
      startElapsedTimer(payload.elapsed_seconds ?? fallbackElapsedSeconds);

      if (payload.status === "running") {
        clearDocJobPollTimer();
        docJobPollTimer = window.setTimeout(() => {
          pollDocJob(pollUrl, {
            title: payload.title || title,
            pollIntervalMs: payload.poll_interval_ms || pollIntervalMs,
            fallbackRedirectUrl,
            fallbackElapsedSeconds: payload.elapsed_seconds ?? fallbackElapsedSeconds,
          });
        }, payload.poll_interval_ms || pollIntervalMs);
        return;
      }

      if (payload.status === "completed") {
        const redirectUrl = payload.redirect_url || fallbackRedirectUrl || window.location.href;
        window.location.assign(redirectUrl);
        return;
      }

      hideJobProgress();
      showAppAlert(payload.message || "문서 작업을 완료하지 못했습니다.", payload.status === "failed" ? "error" : "warning");
    } catch (error) {
      hideJobProgress();
      showAppAlert(error.message || "작업 상태를 확인하지 못했습니다.", "error");
    }
  }

  async function startDocJob(form) {
    if (!form || form.dataset.submitting === "true") return;

    const csrfToken = form.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
    const formData = new FormData(form);
    const fallbackTitle = form.dataset.jobTitle || "문서 작업 진행 중";
    const requestUrl = resolveFormSubmitUrl(form);
    startElapsedTimer(0);

    form.dataset.submitting = "true";
    hideOpenModalsExceptJobProgress();
    showJobProgress({
      title: fallbackTitle,
      message: "요청을 전송하고 있습니다.",
    });

    try {
      const response = await window.fetch(requestUrl, {
        method: (form.method || "POST").toUpperCase(),
        body: formData,
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": csrfToken,
        },
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.message || "문서 작업 요청을 처리하지 못했습니다.");
      }

      showJobProgress({
        title: payload.title || fallbackTitle,
        message: payload.message || "요청을 처리하고 있습니다.",
      });

      if (payload.status === "completed" && payload.redirect_url) {
        window.location.assign(payload.redirect_url);
        return;
      }

      await pollDocJob(payload.poll_url, {
        title: payload.title || fallbackTitle,
        pollIntervalMs: payload.poll_interval_ms || 10000,
        fallbackRedirectUrl: payload.redirect_url || "",
        fallbackElapsedSeconds: payload.elapsed_seconds || 0,
      });
    } catch (error) {
      hideJobProgress();
      showAppAlert(error.message || "문서 작업 요청 중 오류가 발생했습니다.", "error");
    } finally {
      delete form.dataset.submitting;
    }
  }

  function initDocJobPageStates() {
    const pageState = document.querySelector("[data-doc-job-page-state]");
    if (!pageState || pageState.dataset.initialized === "true") return;

    pageState.dataset.initialized = "true";
    showJobProgress({
      title: pageState.dataset.jobTitle || "문서 작업 진행 중",
      message: pageState.dataset.jobMessage || "작업을 처리하고 있습니다.",
    });
    startElapsedTimer(Number.parseInt(pageState.dataset.jobElapsedSeconds || "0", 10) || 0);
    pollDocJob(pageState.dataset.pollUrl, {
      title: pageState.dataset.jobTitle || "문서 작업 진행 중",
      pollIntervalMs: Number.parseInt(pageState.dataset.pollIntervalMs || "10000", 10) || 10000,
      fallbackElapsedSeconds: Number.parseInt(pageState.dataset.jobElapsedSeconds || "0", 10) || 0,
    });
  }

  function resubmitForm(form, submitter) {
    if (!form) return;
    form.dataset.skipConfirm = "true";
    if (submitter && typeof form.requestSubmit === "function") {
      form.requestSubmit(submitter);
      return;
    }
    if (typeof form.requestSubmit === "function") {
      form.requestSubmit();
      return;
    }
    form.submit();
  }

  function toggleSidebar() {
    const sidebar = document.querySelector("[data-sidebar-panel]");
    if (!sidebar) return;
    sidebar.classList.toggle("-translate-x-full");
  }

  function openItfFileDialog() {
    const input = document.querySelector("[data-itf-file-input]");
    if (!input) return;
    input.click();
  }

  function submitItfUpload(fileList) {
    const form = document.querySelector("[data-itf-upload-form]");
    const input = document.querySelector("[data-itf-file-input]");
    if (!form || !input || !fileList || fileList.length === 0) return;
    input.files = fileList;
    if (typeof form.requestSubmit === "function") {
      form.requestSubmit();
      return;
    }
    form.submit();
  }

  function openProfilePage(trigger) {
    const profileUrl = trigger?.dataset.profileUrl;
    if (!profileUrl) return;
    window.location.assign(profileUrl);
  }

  function populateUserDetail(row) {
    const modal = document.getElementById("user-detail-modal");
    if (!modal) return;

    const setValue = function (selector, value) {
      const field = modal.querySelector(selector);
      if (field) field.value = value ?? "";
    };

    setValue("#user-detail-sn", row.dataset.userSn);
    setValue("#user-detail-id", row.dataset.userId);
    setValue("#user-detail-name", row.dataset.userName);
    setValue("#user-detail-department", row.dataset.userDepartment);
    setValue("#user-detail-position", row.dataset.userPosition);
    setValue("#user-detail-active", row.dataset.userUseYn);
    setValue("#user-detail-temp-password-yn", row.dataset.userTempPasswordYn);
  }

  function getProjectSearchModal() {
    return document.getElementById("project-user-search-modal");
  }

  function getProjectFormModal() {
    return document.getElementById("project-form-modal");
  }

  function getProjectRoleList(role) {
    return document.querySelector(`[data-project-role-list="${role}"]`);
  }

  function getProjectRoleInput(role) {
    return document.querySelector(`[data-project-role-input="${role}"]`);
  }

  function getRoleLabel(role) {
    return role === "manager" ? "프로젝트 관리자" : "멤버";
  }

  function getProjectUserItemTemplate() {
    return document.getElementById("project-user-item-template");
  }

  function readProjectUserFromRow(row) {
    return {
      userId: row.dataset.userId ?? "",
      userName: row.dataset.userName ?? "",
      userPosition: row.dataset.userPosition ?? "",
      userDepartment: row.dataset.userDepartment ?? "",
    };
  }

  function isProjectUserAlreadyAdded(userId) {
    if (!userId) return false;
    const allItems = document.querySelectorAll("[data-project-user-item]");
    for (const item of allItems) {
      if (item.dataset.userId === userId) {
        return true;
      }
    }
    return false;
  }

  function syncProjectRole(role) {
    const list = getProjectRoleList(role);
    const input = getProjectRoleInput(role);
    if (!list || !input) return;

    const items = Array.from(list.querySelectorAll("[data-project-user-item]"));
    const ids = items.map((item) => item.dataset.userId).filter(Boolean);
    input.value = ids.join(",");

    const emptyState = list.querySelector("[data-project-empty]");
    if (emptyState) {
      emptyState.classList.toggle("hidden", items.length > 0);
    }
  }

  function syncAllProjectRoles() {
    syncProjectRole("manager");
    syncProjectRole("member");
  }

  function appendProjectUser(role, user) {
    const list = getProjectRoleList(role);
    const template = getProjectUserItemTemplate();
    if (!list || !template) return false;

    const fragment = template.content.firstElementChild.cloneNode(true);
    fragment.dataset.userId = user.userId;

    const nameField = fragment.querySelector("[data-project-user-name]");
    if (nameField) {
      nameField.textContent = user.userName;
    }

    const metaField = fragment.querySelector("[data-project-user-meta]");
    if (metaField) {
      const metaParts = [];
      if (user.userPosition) metaParts.push(user.userPosition);
      if (user.userDepartment) metaParts.push(user.userDepartment);
      metaField.textContent = metaParts.join(" / ") || getRoleLabel(role);
    }

    const emptyState = list.querySelector("[data-project-empty]");
    if (emptyState) {
      emptyState.remove();
    }

    list.appendChild(fragment);
    syncProjectRole(role);
    return true;
  }

  function removeProjectUser(button) {
    const item = button.closest("[data-project-user-item]");
    if (!item) return;
    const roleList = item.closest("[data-project-role-list]");
    const role = roleList?.dataset.projectRoleList;
    item.remove();

    if (role) {
      const list = getProjectRoleList(role);
      if (list && !list.querySelector("[data-project-user-item]")) {
        const emptyMessage = document.createElement("div");
        emptyMessage.dataset.projectEmpty = "true";
        emptyMessage.className = "rounded-xl bg-slate-100 px-4 py-5 text-center text-sm text-slate-500";
        emptyMessage.textContent = role === "manager"
          ? "아직 추가된 관리자가 없습니다."
          : "아직 추가된 멤버가 없습니다.";
        list.appendChild(emptyMessage);
      }
      syncProjectRole(role);
    }
  }

  function openProjectUserSearch(role) {
    const modal = getProjectSearchModal();
    if (!modal) return;

    modal.dataset.projectTargetRole = role;

    const form = modal.querySelector("[data-project-user-search-form]");
    if (form) {
      const roleInput = form.querySelector('[name="project_target_role"]');
      if (roleInput) {
        roleInput.value = role;
      }
    }

    const title = modal.querySelector("[data-project-search-target-label]");
    if (title) {
      title.textContent = getRoleLabel(role);
    }

    showModal(modal);
  }

  function openProjectFormFromRow(row) {
    const openUrl = row?.dataset?.projectOpenUrl;
    if (!openUrl) return;
    window.location.assign(openUrl);
  }

  function addSelectedUsersFromSearch() {
    const modal = getProjectSearchModal();
    if (!modal) return;

    const targetRole = modal.dataset.projectTargetRole || "manager";
    const selectedRows = Array.from(modal.querySelectorAll("[data-project-user-checkbox]:checked"))
      .map((checkbox) => checkbox.closest("[data-project-user-row]"))
      .filter(Boolean);

    if (selectedRows.length === 0) {
      showAppAlert("추가할 사용자를 선택해 주세요.", "warning");
      return;
    }

    let addedCount = 0;
    let duplicated = false;

    selectedRows.forEach((row) => {
      const user = readProjectUserFromRow(row);
      if (!user.userId) return;

      if (isProjectUserAlreadyAdded(user.userId)) {
        duplicated = true;
        return;
      }

      if (appendProjectUser(targetRole, user)) {
        addedCount += 1;
      }
    });

    if (duplicated) {
      showAppAlert("이미 추가된 사용자가 포함되어 있습니다.", "warning");
    }

    if (addedCount > 0) {
      modal.querySelectorAll("[data-project-user-checkbox]").forEach((checkbox) => {
        checkbox.checked = false;
      });
      hideModal(modal);
    }
  }

  function createDocStore() {
    return {
      rfp: new DataTransfer(),
      meeting: new DataTransfer(),
    };
  }

  const docStore = createDocStore();

  function getDocInput(section) {
    return document.querySelector(`[data-doc-file-input="${section}"]`);
  }

  function getDocList(section) {
    return document.querySelector(`[data-doc-file-list="${section}"]`);
  }

  function getTotalDocFileCount(nextSection = null, nextLength = null) {
    const sections = ["rfp", "meeting"];
    return sections.reduce((total, section) => {
      if (section === nextSection && nextLength !== null) {
        return total + nextLength;
      }
      return total + docStore[section].files.length;
    }, 0);
  }

  function fileKey(file) {
    return [file.name, file.size, file.lastModified].join(":");
  }

  function renderDocFiles(section) {
    const list = getDocList(section);
    if (!list) return;

    const files = Array.from(docStore[section].files);
    list.innerHTML = "";

    if (files.length === 0) {
      const empty = document.createElement("div");
      empty.className = "rounded-xl border border-slate-200 bg-slate-50 px-4 py-4 text-sm text-slate-500";
      empty.textContent = "선택한 파일이 없습니다.";
      list.appendChild(empty);
      return;
    }

    files.forEach((file, index) => {
      const row = document.createElement("div");
      row.className = "flex items-center justify-between rounded-xl border border-slate-200 bg-white px-4 py-3 shadow-sm";

      const meta = document.createElement("div");
      meta.className = "min-w-0";

      const name = document.createElement("p");
      name.className = "truncate text-sm font-medium text-slate-900";
      name.textContent = file.name;
      meta.appendChild(name);

      const size = document.createElement("p");
      size.className = "mt-1 text-xs text-slate-500";
      size.textContent = `${(file.size / (1024 * 1024)).toFixed(2)} MB`;
      meta.appendChild(size);

      const removeButton = document.createElement("button");
      removeButton.type = "button";
      removeButton.className = "rounded-lg px-3 py-2 text-sm font-semibold text-slate-500 transition hover:bg-slate-100 hover:text-slate-900";
      removeButton.dataset.docRemoveFile = section;
      removeButton.dataset.docFileIndex = String(index);
      removeButton.textContent = "삭제";

      row.appendChild(meta);
      row.appendChild(removeButton);
      list.appendChild(row);
    });
  }

  function syncDocInput(section) {
    const input = getDocInput(section);
    if (!input) return;
    input.files = docStore[section].files;
  }

  function addDocFiles(section, fileList) {
    if (!fileList || fileList.length === 0) return;

    const currentFiles = Array.from(docStore[section].files);
    const seen = new Set(currentFiles.map(fileKey));
    const nextFiles = [...currentFiles];

    for (const file of Array.from(fileList)) {
      const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
      if (!DOC_ALLOWED_EXTENSIONS.has(extension)) {
        showAppAlert("docx, hwp, pdf 파일만 업로드할 수 있습니다.", "error");
        continue;
      }
      if (file.size > DOC_MAX_FILE_SIZE) {
        showAppAlert("각 파일은 10MB 이하만 업로드할 수 있습니다.", "error");
        continue;
      }
      if (seen.has(fileKey(file))) {
        continue;
      }
      if (getTotalDocFileCount(section, nextFiles.length) >= DOC_MAX_FILES_PER_UPLOAD) {
        showAppAlert(`한 번에 최대 ${DOC_MAX_FILES_PER_UPLOAD}개 파일까지만 등록할 수 있습니다.`, "warning");
        break;
      }

      seen.add(fileKey(file));
      nextFiles.push(file);
    }

    const transfer = new DataTransfer();
    nextFiles.forEach((file) => transfer.items.add(file));
    docStore[section] = transfer;
    syncDocInput(section);
    renderDocFiles(section);
  }

  function removeDocFile(section, index) {
    const files = Array.from(docStore[section].files);
    const transfer = new DataTransfer();
    files.forEach((file, currentIndex) => {
      if (currentIndex !== index) {
        transfer.items.add(file);
      }
    });
    docStore[section] = transfer;
    syncDocInput(section);
    renderDocFiles(section);
  }

  function openDocFileDialog(section) {
    const input = getDocInput(section);
    if (!input) return;
    input.click();
  }

  function prepareDocUploadUI() {
    renderDocFiles("rfp");
    renderDocFiles("meeting");
  }

  function handleDocAction(button) {
    const form = button.closest("form");
    if (!form) return false;

    const checked = form.querySelectorAll('[data-docs-item-checkbox]:checked');
    if (checked.length === 0) {
      showAppAlert("파일을 하나 이상 선택해 주세요.", "warning");
      return false;
    }

    return true;
  }

  function syncDocsSelectAll(trigger) {
    const form = trigger.closest("form");
    if (!form) return;
    form.querySelectorAll("[data-docs-item-checkbox]").forEach((checkbox) => {
      checkbox.checked = trigger.checked;
    });
  }

  let onlyOfficeScriptPromise = null;

  function loadScriptOnce(src) {
    if (onlyOfficeScriptPromise) return onlyOfficeScriptPromise;

    onlyOfficeScriptPromise = new Promise((resolve, reject) => {
      const existing = document.querySelector(`script[src="${src}"]`);
      if (existing) {
        existing.addEventListener("load", () => resolve(), { once: true });
        existing.addEventListener("error", () => reject(new Error("failed to load script")), { once: true });
        if (existing.dataset.loaded === "true") {
          resolve();
        }
        return;
      }

      const script = document.createElement("script");
      script.src = src;
      script.async = true;
      script.addEventListener("load", function () {
        script.dataset.loaded = "true";
        resolve();
      }, { once: true });
      script.addEventListener("error", function () {
        reject(new Error("failed to load script"));
      }, { once: true });
      document.head.appendChild(script);
    });

    return onlyOfficeScriptPromise;
  }

  async function initOnlyOfficeEditor(root) {
    const configUrl = root.dataset.configUrl;
    const documentServerUrl = root.dataset.documentServerUrl;
    if (!configUrl) return;
    const editorHeight = Math.max(720, Math.floor(window.innerHeight * 0.8));
    const editorHeightPx = `${editorHeight}px`;
    root.style.height = editorHeightPx;

    if (!documentServerUrl) {
      root.innerHTML = `<div class="flex h-full items-center justify-center text-sm text-slate-500" style="height:${editorHeightPx};">OnlyOffice 서버 주소가 설정되지 않았습니다.</div>`;
      return;
    }

    try {
      const response = await window.fetch(configUrl, { credentials: "same-origin" });
      if (!response.ok) {
        throw new Error(`config request failed: ${response.status}`);
      }
      const config = await response.json();
      config.width = config.width || "100%";
      config.height = editorHeight;

      await loadScriptOnce(`${documentServerUrl}/web-apps/apps/api/documents/api.js`);
      if (!(window.DocsAPI && window.DocsAPI.DocEditor)) {
        throw new Error("DocsAPI unavailable");
      }

      const holder = document.createElement("div");
      holder.id = `onlyoffice-${Math.random().toString(36).slice(2)}`;
      holder.className = "h-full w-full";
      holder.style.height = editorHeightPx;
      root.innerHTML = "";
      root.appendChild(holder);
      const editor = new window.DocsAPI.DocEditor(holder.id, config);
      onlyOfficeEditors.set(root, editor);
    } catch (error) {
      root.innerHTML = `<div class="flex h-full items-center justify-center px-6 text-center text-sm text-slate-500" style="height:${editorHeightPx};">OnlyOffice 편집기를 불러오지 못했습니다. 환경 변수와 Docker 상태를 확인해 주세요.</div>`;
    }
  }

  function initOnlyOfficeEditors() {
    document.querySelectorAll("[data-onlyoffice-root]").forEach((root) => {
      initOnlyOfficeEditor(root);
    });
  }

  function setInlineStatus(node, message, tone = "info") {
    if (!node) return;

    const toneClasses = {
      success: ["border-emerald-200", "bg-emerald-50", "text-emerald-800"],
      error: ["border-red-200", "bg-red-50", "text-red-800"],
      warning: ["border-amber-200", "bg-amber-50", "text-amber-800"],
      info: ["border-blue-200", "bg-blue-50", "text-blue-800"],
    };
    const resolvedTone = toneClasses[tone] ? tone : "info";

    node.className = "rounded-2xl border px-4 py-3 text-sm";
    node.classList.add(...toneClasses[resolvedTone]);
    node.textContent = message;
    node.classList.remove("hidden");
  }

  async function submitOnlyOfficeSave(form, submitter) {
    if (!form || form.dataset.submitting === "true") return;

    const editRoot = form.closest("[data-onlyoffice-edit-root]");
    const statusNode = editRoot?.querySelector("[data-doc-save-status]");
    const saveButton = submitter || form.querySelector("[data-doc-save-submit]");
    const csrfToken = form.querySelector('input[name="csrfmiddlewaretoken"]')?.value || "";
    const formData = new FormData(form);
    const requestUrl = resolveFormSubmitUrl(form);

    form.dataset.submitting = "true";
    if (saveButton) {
      saveButton.disabled = true;
    }
    setInlineStatus(statusNode, "OnlyOffice 저장 완료를 확인하는 중입니다.", "info");

    try {
      const response = await window.fetch(requestUrl, {
        method: "POST",
        body: formData,
        credentials: "same-origin",
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          "X-CSRFToken": csrfToken,
        },
      });

      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        setInlineStatus(statusNode, payload.message || "문서 저장을 완료하지 못했습니다.", "error");
        return;
      }

      setInlineStatus(statusNode, payload.message || "문서 수정 내용을 저장했습니다.", "success");

      const editorRoot = document.querySelector("[data-onlyoffice-root]");
      const editor = editorRoot ? onlyOfficeEditors.get(editorRoot) : null;
      if (editor && typeof editor.destroyEditor === "function") {
        try {
          editor.destroyEditor();
        } catch (error) {
          // Ignore editor cleanup failures and continue with navigation.
        }
      }

      if (payload.redirect_url) {
        window.location.assign(payload.redirect_url);
      }
    } catch (error) {
      setInlineStatus(statusNode, "문서 저장 중 오류가 발생했습니다. 다시 시도해 주세요.", "error");
    } finally {
      delete form.dataset.submitting;
      if (saveButton) {
        saveButton.disabled = false;
      }
    }
  }

  async function loadHistoryPreview(previewUrl, trigger) {
    if (!previewUrl) return;

    const modal = trigger?.closest?.("#history-modal") || document.getElementById("history-modal");
    const previewContent = modal?.querySelector("[data-history-preview-content]");
    const previewMeta = modal?.querySelector("[data-history-preview-meta]");
    if (!modal || !previewContent || !previewMeta) return;

    modal.querySelectorAll("[data-history-preview-row]").forEach((row) => {
      row.classList.remove("border-blue-300", "bg-blue-50");
    });
    trigger?.closest("[data-history-preview-row]")?.classList.add("border-blue-300", "bg-blue-50");

    previewMeta.textContent = "미리보기를 불러오는 중입니다.";
    previewContent.textContent = "선택한 수정 이력을 불러오는 중입니다.";

    try {
      const response = await window.fetch(previewUrl, { credentials: "same-origin" });
      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.message || `preview request failed: ${response.status}`);
      }

      const payload = await response.json();
      previewContent.textContent = payload.preview_text || "문서 내용이 없습니다.";
      previewMeta.textContent = payload.created_at && payload.creator_name
        ? `${payload.created_at} · ${payload.creator_name}`
        : "미리보기";
    } catch (error) {
      previewMeta.textContent = "미리보기를 불러오지 못했습니다.";
      previewContent.textContent = error.message || "수정 이력 미리보기를 불러오지 못했습니다.";
      showAppAlert("수정 이력 미리보기를 불러오지 못했습니다.", "error");
    }
  }

  document.addEventListener("click", function (event) {
    const profileTrigger = event.target.closest("[data-profile-url]");
    if (profileTrigger && !event.target.closest("form, button, a, input, select, textarea, label")) {
      openProfilePage(profileTrigger);
      return;
    }

    const projectSearchTrigger = event.target.closest("[data-project-open-search]");
    if (projectSearchTrigger) {
      openProjectUserSearch(projectSearchTrigger.dataset.projectOpenSearch);
      return;
    }

    const projectOpenRow = event.target.closest("[data-project-open-url]");
    if (projectOpenRow && !event.target.closest("a, button, input, select, textarea, form, label")) {
      openProjectFormFromRow(projectOpenRow);
      return;
    }

    const docSelectTrigger = event.target.closest("[data-doc-upload-select]");
    if (docSelectTrigger) {
      openDocFileDialog(docSelectTrigger.dataset.docUploadSelect);
      return;
    }

    const itfSelectTrigger = event.target.closest("[data-itf-upload-select]");
    if (itfSelectTrigger) {
      openItfFileDialog();
      return;
    }

    const docRemoveButton = event.target.closest("[data-doc-remove-file]");
    if (docRemoveButton) {
      removeDocFile(
        docRemoveButton.dataset.docRemoveFile,
        Number.parseInt(docRemoveButton.dataset.docFileIndex || "-1", 10),
      );
      return;
    }

    const userDetailRow = event.target.closest("[data-user-id]");
    if (userDetailRow && userDetailRow.dataset.modalTarget === "user-detail-modal") {
      populateUserDetail(userDetailRow);
    }

    const alertDismissButton = event.target.closest("[data-alert-dismiss]");
    if (alertDismissButton) {
      dismissAppAlert(alertDismissButton.closest("[data-app-alert]"));
      return;
    }

    const confirmSubmit = event.target.closest("[data-confirm-submit]");
    if (confirmSubmit) {
      resolveConfirm(true);
      return;
    }

    const noticeSubmit = event.target.closest("[data-notice-submit]");
    if (noticeSubmit) {
      resolveNotice();
      return;
    }

    const confirmCancel = event.target.closest("[data-confirm-cancel]");
    if (confirmCancel) {
      resolveConfirm(false);
      return;
    }

    const openTrigger = event.target.closest("[data-modal-target]");
    if (openTrigger) {
      showModal(document.getElementById(openTrigger.dataset.modalTarget));
      return;
    }

    const historyPreviewTrigger = event.target.closest("[data-history-preview-url]");
    if (historyPreviewTrigger) {
      loadHistoryPreview(historyPreviewTrigger.dataset.historyPreviewUrl, historyPreviewTrigger);
      return;
    }

    const closeTrigger = event.target.closest("[data-modal-hide]");
    if (closeTrigger) {
      const modal = document.getElementById(closeTrigger.dataset.modalHide);
      if (modal?.dataset.confirmRoot !== undefined) {
        resolveConfirm(false);
        return;
      }
      if (modal?.dataset.noticeRoot !== undefined) {
        resolveNotice();
        return;
      }
      if (modal?.dataset.jobProgressRoot !== undefined) {
        return;
      }
      hideModal(modal);
      return;
    }

    const projectRemoveButton = event.target.closest("[data-project-remove-user]");
    if (projectRemoveButton) {
      removeProjectUser(projectRemoveButton);
      return;
    }

    const projectSearchAddButton = event.target.closest("[data-project-search-add]");
    if (projectSearchAddButton) {
      addSelectedUsersFromSearch();
      return;
    }

    if (event.target.matches("[data-modal-root]")) {
      if (event.target.dataset.jobProgressRoot !== undefined) {
        return;
      }
      if (event.target.dataset.confirmRoot !== undefined) {
        resolveConfirm(false);
        return;
      }
      if (event.target.dataset.noticeRoot !== undefined) {
        resolveNotice();
        return;
      }
      hideModal(event.target);
      return;
    }

    const sidebarToggle = event.target.closest("[data-sidebar-toggle]");
    if (sidebarToggle) {
      toggleSidebar();
    }
  });

  document.addEventListener("change", function (event) {
    const currentProjectSelect = event.target.closest("[data-current-project-select]");
    if (currentProjectSelect) {
      currentProjectSelect.form?.submit();
      return;
    }

    const docInput = event.target.closest("[data-doc-file-input]");
    if (docInput) {
      addDocFiles(docInput.dataset.docFileInput, docInput.files);
      return;
    }

    const itfInput = event.target.closest("[data-itf-file-input]");
    if (itfInput) {
      submitItfUpload(itfInput.files);
      return;
    }

    const selectAll = event.target.closest("[data-docs-select-all]");
    if (selectAll) {
      syncDocsSelectAll(selectAll);
    }
  });

  document.addEventListener("dragover", function (event) {
    const zone = event.target.closest("[data-doc-drop-zone]");
    if (zone) {
      event.preventDefault();
      zone.classList.add("border-blue-300", "bg-blue-50");
      return;
    }

    const itfZone = event.target.closest("[data-itf-drop-zone]");
    if (!itfZone) return;
    event.preventDefault();
    itfZone.classList.add("border-blue-300", "bg-blue-50");
  });

  document.addEventListener("dragleave", function (event) {
    const zone = event.target.closest("[data-doc-drop-zone]");
    if (zone) {
      if (zone.contains(event.relatedTarget)) return;
      zone.classList.remove("border-blue-300", "bg-blue-50");
      return;
    }

    const itfZone = event.target.closest("[data-itf-drop-zone]");
    if (!itfZone) return;
    if (itfZone.contains(event.relatedTarget)) return;
    itfZone.classList.remove("border-blue-300", "bg-blue-50");
  });

  document.addEventListener("drop", function (event) {
    const zone = event.target.closest("[data-doc-drop-zone]");
    if (zone) {
      event.preventDefault();
      zone.classList.remove("border-blue-300", "bg-blue-50");
      addDocFiles(zone.dataset.docDropZone, event.dataTransfer?.files);
      return;
    }

    const itfZone = event.target.closest("[data-itf-drop-zone]");
    if (!itfZone) return;
    event.preventDefault();
    itfZone.classList.remove("border-blue-300", "bg-blue-50");
    submitItfUpload(event.dataTransfer?.files);
  });

  document.addEventListener("submit", async function (event) {
    const form = event.target;
    if (form?.dataset?.skipConfirm === "true") {
      delete form.dataset.skipConfirm;
      return;
    }

    const docUploadForm = event.target.closest("[data-doc-upload-form]");
    if (docUploadForm) {
      syncDocInput("rfp");
      syncDocInput("meeting");

      const totalFiles = getTotalDocFileCount();
      if (totalFiles === 0) {
        showAppAlert("업로드할 파일을 선택해 주세요.", "warning");
        event.preventDefault();
        return;
      }

      if (totalFiles > DOC_MAX_FILES_PER_UPLOAD) {
        showAppAlert(`한 번에 최대 ${DOC_MAX_FILES_PER_UPLOAD}개 파일까지만 등록할 수 있습니다.`, "warning");
        event.preventDefault();
      }
      return;
    }

    const docActionButton = event.submitter?.closest?.("[data-docs-action]");
    if (docActionButton) {
      if (!handleDocAction(docActionButton)) {
        event.preventDefault();
        return;
      }

      event.preventDefault();
      const confirmed = await showConfirmDialog({
        title: docActionButton.dataset.docsAction === "delete" ? "삭제 확인" : "다운로드 확인",
        message: docActionButton.dataset.docsAction === "delete"
          ? "선택한 파일을 삭제하시겠습니까?"
          : "선택한 파일을 다운로드하시겠습니까?",
        confirmText: docActionButton.dataset.docsAction === "delete" ? "삭제" : "다운로드",
        tone: docActionButton.dataset.docsAction === "delete" ? "danger" : "primary",
      });
      if (confirmed) {
        resubmitForm(docActionButton.closest("form"), event.submitter);
      }
      return;
    }

    const docSaveForm = event.target.closest("[data-doc-save-form]");
    if (docSaveForm) {
      event.preventDefault();
      await submitOnlyOfficeSave(docSaveForm, event.submitter);
      return;
    }

    const docJobForm = event.target.closest("[data-doc-job-form]");
    if (docJobForm) {
      event.preventDefault();
      await startDocJob(docJobForm);
      return;
    }

    const confirmForm = event.target.closest("[data-confirm-form]");
    if (confirmForm) {
      event.preventDefault();
      const confirmed = await showConfirmDialog({
        title: confirmForm.dataset.confirmTitle || "확인",
        message: confirmForm.dataset.confirmMessage || "",
        confirmText: confirmForm.dataset.confirmText || "확인",
        cancelText: confirmForm.dataset.cancelText || "취소",
        tone: confirmForm.dataset.confirmTone || "primary",
      });
      if (confirmed) {
        resubmitForm(confirmForm, event.submitter);
      }
      return;
    }

    const projectForm = event.target.closest("[data-project-create-form]");
    if (!projectForm) return;

    syncAllProjectRoles();

    const projectNameField = projectForm.querySelector("#project-name");
    const projectName = projectNameField ? projectNameField.value.trim() : "";
    if (!projectName) {
      showAppAlert("프로젝트명을 입력해 주세요.", "warning");
      event.preventDefault();
      return;
    }

    const managerIds = getProjectRoleInput("manager")?.value.trim() || "";
    const memberIds = getProjectRoleInput("member")?.value.trim() || "";
    if (!managerIds && !memberIds) {
      showAppAlert("최소 1명의 사용자를 추가해야 합니다.", "warning");
      event.preventDefault();
      return;
    }

    event.preventDefault();
    const confirmed = await showConfirmDialog({
      title: "프로젝트 등록",
      message: "프로젝트를 등록하시겠습니까?",
      confirmText: "등록",
      tone: "primary",
    });
    if (confirmed) {
      resubmitForm(projectForm, event.submitter);
    }
  });

  document.addEventListener("keydown", function (event) {
    const projectOpenRow = event.target.closest("[data-project-open-url]");
    if (projectOpenRow && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      openProjectFormFromRow(projectOpenRow);
      return;
    }

    const profileTrigger = event.target.closest("[data-profile-url]");
    if (profileTrigger && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      openProfilePage(profileTrigger);
      return;
    }

    if (event.key !== "Escape") return;
    const jobProgressRoot = getJobProgressRoot();
    if (jobProgressRoot?.classList.contains("flex")) {
      return;
    }
    const confirmRoot = getConfirmRoot();
    if (confirmRoot?.classList.contains("flex")) {
      resolveConfirm(false);
      return;
    }
    const noticeRoot = getNoticeRoot();
    if (noticeRoot?.classList.contains("flex")) {
      resolveNotice();
      return;
    }
    document.querySelectorAll("[data-modal-root].flex").forEach(hideModal);
  });

  const projectPageState = document.getElementById("project-page-state");
  if (projectPageState?.dataset.openProjectForm === "true") {
    showModal(getProjectFormModal());
  }
  if (projectPageState?.dataset.openProjectUserSearch === "true") {
    openProjectUserSearch(projectPageState.dataset.openProjectUserSearchRole || "manager");
  }

  const userPageState = document.getElementById("user-page-state");
  if (userPageState?.dataset.openUserCreateModal === "true") {
    showModal(document.getElementById("user-create-modal"));
  }

  if (document.querySelector("[data-modal-root].flex")) {
    document.body.classList.add("overflow-hidden");
  }

  const autoNoticeTrigger = document.querySelector("[data-auto-notice]");
  if (autoNoticeTrigger) {
    showNoticeDialog({
      title: autoNoticeTrigger.dataset.noticeTitle || "안내",
      message: autoNoticeTrigger.dataset.noticeMessage || "",
      buttonText: autoNoticeTrigger.dataset.noticeButtonText || "확인",
    }).then(() => {
      const redirectUrl = autoNoticeTrigger.dataset.noticeRedirectUrl;
      if (redirectUrl) {
        window.location.replace(redirectUrl);
      }
    });
  }

  syncAllProjectRoles();
  prepareDocUploadUI();
  initDocJobPageStates();
  initOnlyOfficeEditors();
})();
