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

  document.addEventListener("click", function (event) {
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

    if (event.target.matches("[data-modal-root]")) {
      hideModal(event.target);
      return;
    }

    const sidebarToggle = event.target.closest("[data-sidebar-toggle]");
    if (sidebarToggle) {
      toggleSidebar();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    document.querySelectorAll("[data-modal-root].flex").forEach(hideModal);
  });
})();
