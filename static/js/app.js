(function () {
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

  function toggleSidebar() {
    const sidebar = document.querySelector("[data-sidebar-panel]");
    if (!sidebar) return;
    sidebar.classList.toggle("-translate-x-full");
  }

  function populateUserDetail(row) {
    const modal = document.getElementById("user-detail-modal");
    if (!modal) return;

    const setValue = function (selector, value) {
      const field = modal.querySelector(selector);
      if (field) field.value = value ?? "";
    };

    setValue("#user-detail-id", row.dataset.userId);
    setValue("#user-detail-name", row.dataset.userName);
    setValue("#user-detail-department", row.dataset.userDepartment);
    setValue("#user-detail-position", row.dataset.userPosition);
    setValue("#user-detail-active", row.dataset.userUseYn);
  }

  function getProjectCreateModal() {
    return document.getElementById("project-create-modal");
  }

  function getProjectSearchModal() {
    return document.getElementById("project-user-search-modal");
  }

  function getProjectRoleList(role) {
    return document.querySelector(`[data-project-role-list="${role}"]`);
  }

  function getProjectRoleInput(role) {
    return document.querySelector(`[data-project-role-input="${role}"]`);
  }

  function getRoleLabel(role) {
    return role === "manager" ? "프로젝트 관리자" : "담당";
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
      metaField.textContent = metaParts.join(" · ") || getRoleLabel(role);
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
          : "아직 추가된 담당자가 없습니다.";
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

  function addSelectedUsersFromSearch() {
    const modal = getProjectSearchModal();
    if (!modal) return;

    const targetRole = modal.dataset.projectTargetRole || "manager";
    const selectedRows = Array.from(modal.querySelectorAll("[data-project-user-checkbox]:checked"))
      .map((checkbox) => checkbox.closest("[data-project-user-row]"))
      .filter(Boolean);

    if (selectedRows.length === 0) {
      window.alert("추가할 사용자를 선택하세요.");
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
      window.alert("이미 추가된 사용자가 포함되어 있습니다.");
    }

    if (addedCount > 0) {
      modal.querySelectorAll("[data-project-user-checkbox]").forEach((checkbox) => {
        checkbox.checked = false;
      });
      hideModal(modal);
    }
  }

  document.addEventListener("click", function (event) {
    const projectSearchTrigger = event.target.closest("[data-project-open-search]");
    if (projectSearchTrigger) {
      openProjectUserSearch(projectSearchTrigger.dataset.projectOpenSearch);
      return;
    }

    const userDetailRow = event.target.closest("[data-user-id]");
    if (userDetailRow && userDetailRow.dataset.modalTarget === "user-detail-modal") {
      populateUserDetail(userDetailRow);
    }

    const openTrigger = event.target.closest("[data-modal-target]");
    if (openTrigger) {
      showModal(document.getElementById(openTrigger.dataset.modalTarget));
      return;
    }

    const closeTrigger = event.target.closest("[data-modal-hide]");
    if (closeTrigger) {
      hideModal(document.getElementById(closeTrigger.dataset.modalHide));
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
      hideModal(event.target);
      return;
    }

    const sidebarToggle = event.target.closest("[data-sidebar-toggle]");
    if (sidebarToggle) {
      toggleSidebar();
    }
  });

  document.addEventListener("submit", function (event) {
    const form = event.target.closest("[data-project-create-form]");
    if (!form) return;

    syncAllProjectRoles();

    const projectNameField = form.querySelector("#project-name");
    const projectName = projectNameField ? projectNameField.value.trim() : "";
    if (!projectName) {
      window.alert("프로젝트명을 입력하세요.");
      event.preventDefault();
      return;
    }

    const managerIds = getProjectRoleInput("manager")?.value.trim() || "";
    const memberIds = getProjectRoleInput("member")?.value.trim() || "";
    if (!managerIds && !memberIds) {
      window.alert("최소 1명의 사용자를 추가해야 합니다.");
      event.preventDefault();
      return;
    }

    if (!window.confirm("프로젝트를 등록하시겠습니까?")) {
      event.preventDefault();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    document.querySelectorAll("[data-modal-root].flex").forEach(hideModal);
  });

  const projectPageState = document.getElementById("project-page-state");
  if (projectPageState?.dataset.openProjectUserSearch === "true") {
    openProjectUserSearch(projectPageState.dataset.openProjectUserSearchRole || "manager");
  }

  syncAllProjectRoles();
})();
