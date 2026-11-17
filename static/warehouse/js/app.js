(function () {
  "use strict";

  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));

  /* ------------------------------------------------------------------ */
  /* 移动端导航                                                          */
  /* ------------------------------------------------------------------ */
  const menuToggle = $("#menu-toggle");
  const sidebar = $("#sidebar");
  if (menuToggle && sidebar) {
    menuToggle.addEventListener("click", () => {
      sidebar.classList.toggle("is-open");
      document.body.classList.toggle("nav-open", sidebar.classList.contains("is-open"));
    });
    document.addEventListener("click", (event) => {
      if (
        document.body.classList.contains("nav-open") &&
        !sidebar.contains(event.target) &&
        !menuToggle.contains(event.target)
      ) {
        sidebar.classList.remove("is-open");
        document.body.classList.remove("nav-open");
      }
    });
  }

  /* ------------------------------------------------------------------ */
  /* 提示消息                                                            */
  /* ------------------------------------------------------------------ */
  const toastStack = $("#toast-stack");
  if (toastStack) {
    const closeToast = (toast) => {
      toast.classList.add("toast-out");
      window.setTimeout(() => toast.remove(), 220);
    };
    $$(".toast", toastStack).forEach((toast) => {
      const close = $(".toast-close", toast);
      if (close) close.addEventListener("click", () => closeToast(toast));
      window.setTimeout(() => closeToast(toast), 6500);
    });
  }

  /* ------------------------------------------------------------------ */
  /* 登录页演示账号                                                      */
  /* ------------------------------------------------------------------ */
  $$(".demo-account").forEach((button) => {
    button.addEventListener("click", () => {
      const form = $(".login-form");
      if (!form) return;
      form.querySelector('[name="username"]').value = button.dataset.user || "";
      form.querySelector('[name="password"]').value = button.dataset.pass || "";
      form.querySelector('[name="username"]').focus();
    });
  });

  /* ------------------------------------------------------------------ */
  /* 原生 dialog                                                         */
  /* ------------------------------------------------------------------ */
  $$("[data-dialog-open]").forEach((trigger) => {
    trigger.addEventListener("click", () => {
      const dialog = document.getElementById(trigger.dataset.dialogOpen);
      if (dialog && typeof dialog.showModal === "function") {
        dialog.showModal();
        const firstInput = dialog.querySelector("textarea, input");
        if (firstInput) window.setTimeout(() => firstInput.focus(), 80);
      }
    });
  });
  $$(".app-dialog").forEach((dialog) => {
    $$("[data-dialog-close]", dialog).forEach((button) => {
      button.addEventListener("click", () => dialog.close());
    });
    dialog.addEventListener("click", (event) => {
      if (event.target === dialog) dialog.close();
    });
  });

  /* ------------------------------------------------------------------ */
  /* 建单页库存预检                                                      */
  /* ------------------------------------------------------------------ */
  const orderForm = $("#order-form");
  if (orderForm) {
    const kind = orderForm.dataset.kind || window.ORDER_KIND || "transfer";
    const herbSelect = $("#id_herb");
    const locationSelect = kind === "transfer" ? $("#id_from_location") : $("#id_location");
    const batchInput = $("#id_batch_no");
    const quantityInput = $("#id_quantity");
    const preview = $("#stock-preview");
    const emptyBox = $("#stock-empty");
    const readyBox = $("#stock-ready");
    const totalEl = $("#stock-total");
    const unitEl = $("#stock-unit");
    const unitLabel = $("#unit-label");
    const listEl = $("#stock-batches");
    const warning = $("#stock-warning");
    const errorBox = $("#stock-error");
    const datalist = document.getElementById(
      kind === "transfer" ? "transfer-batch-options" : "outbound-batch-options"
    );
    const stockUrl = orderForm.dataset.stockUrl;
    let controller = null;
    let currentBatches = [];

    const fmt = (value) => {
      const number = Number(value);
      if (!Number.isFinite(number)) return String(value || "");
      return number.toLocaleString("zh-CN", { maximumFractionDigits: 3 });
    };

    const setEmpty = (title, subtitle) => {
      if (!emptyBox || !readyBox) return;
      emptyBox.hidden = false;
      readyBox.hidden = true;
      const titleEl = $("p", emptyBox);
      const subEl = $("small", emptyBox);
      if (titleEl && title) titleEl.textContent = title;
      if (subEl && subtitle) subEl.textContent = subtitle;
    };

    const setError = (message) => {
      if (!errorBox) return;
      errorBox.hidden = !message;
      errorBox.textContent = message || "";
    };

    const checkQuantity = () => {
      if (!quantityInput || !warning) return;
      const quantity = Number(quantityInput.value);
      const batchNo = batchInput ? batchInput.value.trim() : "";
      const batch = currentBatches.find((item) => item.batch_no === batchNo);
      let exceeded = false;
      if (quantity > 0) {
        if (batch && quantity > Number(batch.quantity)) exceeded = true;
        if (!batchNo) {
          const total = currentBatches.reduce((sum, item) => sum + Number(item.quantity), 0);
          exceeded = currentBatches.length > 0 && quantity > total;
        }
      }
      warning.hidden = !exceeded;
    };

    const render = (data) => {
      currentBatches = data.results || [];
      if (!currentBatches.length) {
        setEmpty("暂无可用库存", "该库位下没有这个药材的可出批次");
        if (datalist) datalist.innerHTML = "";
        if (batchInput) batchInput.value = "";
        if (warning) warning.hidden = true;
        return;
      }
      const unit = currentBatches[0].unit || "kg";
      if (totalEl) totalEl.textContent = fmt(data.total);
      if (unitEl) unitEl.textContent = unit;
      if (unitLabel) unitLabel.textContent = unit;

      if (datalist) {
        datalist.innerHTML = "";
        currentBatches.forEach((batch) => {
          const option = document.createElement("option");
          option.value = batch.batch_no;
          option.label = `${batch.batch_no} · 可用 ${fmt(batch.quantity)} ${unit}`;
          datalist.appendChild(option);
        });
      }

      if (listEl) {
        listEl.innerHTML = "";
        currentBatches.forEach((batch) => {
          const li = document.createElement("li");
          li.dataset.batch = batch.batch_no;
          const name = document.createElement("span");
          name.textContent = batch.batch_no;
          const amount = document.createElement("strong");
          amount.textContent = `${fmt(batch.quantity)} ${unit}`;
          li.append(name, amount);
          li.addEventListener("click", () => {
            if (batchInput) {
              batchInput.value = batch.batch_no;
              checkQuantity();
              highlightBatch();
            }
          });
          listEl.appendChild(li);
        });
      }

      if (batchInput && !batchInput.value.trim()) {
        batchInput.value = currentBatches[0].batch_no;
      }
      emptyBox.hidden = true;
      readyBox.hidden = false;
      highlightBatch();
      checkQuantity();
    };

    const highlightBatch = () => {
      if (!listEl) return;
      const selected = batchInput ? batchInput.value.trim() : "";
      $$("li", listEl).forEach((li) => {
        li.classList.toggle("selected", li.dataset.batch === selected);
      });
    };

    const loadStock = async () => {
      setError("");
      if (!herbSelect || !locationSelect || !herbSelect.value || !locationSelect.value) {
        setEmpty("尚未选择完整", "请先选择药材和库位");
        return;
      }
      if (!stockUrl) return;
      if (controller) controller.abort();
      controller = new AbortController();
      preview && preview.classList.add("is-loading");
      try {
        const url = new URL(stockUrl, window.location.origin);
        url.searchParams.set("herb", herbSelect.value);
        url.searchParams.set("location", locationSelect.value);
        const response = await fetch(url, {
          headers: { "X-Requested-With": "XMLHttpRequest" },
          signal: controller.signal,
        });
        if (!response.ok) throw new Error("库存读取失败");
        const data = await response.json();
        render(data);
      } catch (error) {
        if (error.name === "AbortError") return;
        setError("库存读取失败，请刷新页面后重试。");
      } finally {
        preview && preview.classList.remove("is-loading");
      }
    };

    [herbSelect, locationSelect].forEach((select) => {
      if (select) select.addEventListener("change", loadStock);
    });
    if (batchInput) {
      batchInput.addEventListener("change", () => {
        highlightBatch();
        checkQuantity();
      });
      batchInput.addEventListener("input", checkQuantity);
    }
    if (quantityInput) quantityInput.addEventListener("input", checkQuantity);

    loadStock();
  }

  /* ------------------------------------------------------------------ */
  /* 附件文件名提示                                                      */
  /* ------------------------------------------------------------------ */
  $$(".upload-file input[type=file]").forEach((input) => {
    input.addEventListener("change", () => {
      const hint = input.closest(".upload-file")?.querySelector(".upload-hint");
      if (hint && input.files && input.files.length) {
        hint.textContent = input.files[0].name;
        hint.classList.add("has-file");
      }
    });
  });
})();
