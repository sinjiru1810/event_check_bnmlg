/* Shared frontend logic untuk halaman login & dashboard. */

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body.error) message = body.error;
    } catch (_) {}
    throw new Error(message);
  }
  return response.json();
}

/* ------------------------------------------------------------------ utils */
function humanDuration(totalSeconds) {
  const seconds = Math.max(0, Math.round(totalSeconds));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours >= 24) return `${Math.floor(hours / 24)} hari ${hours % 24} jam`;
  if (hours > 0) return `${hours} jam ${minutes} menit`;
  if (minutes > 0) return `${minutes} menit`;
  return `${seconds} detik`;
}

function clockTime(unixSeconds) {
  const date = new Date(unixSeconds * 1000);
  return date.toLocaleTimeString("id-ID", { hour: "2-digit", minute: "2-digit" });
}

function dateTime(unixSeconds) {
  const date = new Date(unixSeconds * 1000);
  return date.toLocaleString("id-ID", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

let toastTimer = null;
function toast(message, kind = "ok") {
  const box = $("#toast");
  if (!box) return;
  box.textContent = message;
  box.className = `toast toast--${kind} is-visible`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    box.className = `toast toast--${kind}`;
  }, 4200);
}

/* ------------------------------------------------------------------ login */
function initLogin() {
  const form = $("#login-form");
  const emailInput = $("#email");
  const button = $("#btn-login");
  const buttonLabel = $(".btn__label", button);
  const notice = $("#notice");
  const noticeText = $("#notice-text");
  const stepsBox = $("#steps");
  const logBox = $("#log");
  const logWrap = $("#log-wrap");
  const cancelButton = $("#btn-cancel");

  let poller = null;
  let finished = false;

  const steps = {
    open: $('[data-step="open"]', stepsBox),
    wait: $('[data-step="wait"]', stepsBox),
    done: $('[data-step="done"]', stepsBox),
  };

  function showNotice(kind, text) {
    notice.className = `notice notice--${kind} is-visible`;
    noticeText.textContent = text;
  }

  function hideNotice() {
    notice.className = "notice";
  }

  function setStep(name, state) {
    const element = steps[name];
    if (!element) return;
    element.classList.remove("is-active", "is-done", "is-error");
    if (state) element.classList.add(`is-${state}`);
  }

  function setBusy(busy) {
    button.disabled = busy;
    button.classList.toggle("is-loading", busy);
  }

  function setCancelVisible(visible) {
    cancelButton.style.display = visible ? "inline-flex" : "none";
  }

  function stopPolling() {
    if (poller) {
      clearInterval(poller);
      poller = null;
    }
  }

  function applyLog(text, running) {
    logBox.textContent = text || "";
    logBox.scrollTop = logBox.scrollHeight;

    if (text.includes("[1/4]")) {
      setStep("open", "done");
      setStep("wait", "active");
      stepsBox.classList.add("is-visible");
      logWrap.classList.add("is-visible");
    }
    if (text.includes("[4/4]")) {
      setStep("open", "done");
      setStep("wait", "active");
    }
    if (text.includes("[OK] Masuk")) {
      setStep("wait", "done");
      setStep("done", "done");
    }
    if (text.includes("[GAGAL]")) {
      setStep("wait", "error");
      setStep("done", "error");
    }

    if (!running && !finished) {
      finished = true;
      stopPolling();
      setBusy(false);
      setCancelVisible(false);

      if (text.includes("[OK] Masuk")) {
        showNotice("ok", "Berhasil masuk. Session tersimpan — mengalihkan ke dashboard…");
        buttonLabel.textContent = "Buka Dashboard";
        button.disabled = false;
        button.onclick = (event) => {
          event.preventDefault();
          window.location.href = "/";
        };
        button.type = "button";
        setTimeout(() => {
          window.location.href = "/";
        }, 2200);
      } else if (text.includes("[GAGAL]")) {
        showNotice(
          "err",
          "Login belum selesai. Jendela browser mungkin tertutup atau waktu habis — coba lagi."
        );
        buttonLabel.textContent = "Coba Lagi";
        stepsBox.classList.add("is-visible");
      } else {
        showNotice("warn", "Proses berhenti tanpa hasil. Coba jalankan lagi.");
        buttonLabel.textContent = "Coba Lagi";
      }
    }
  }

  async function poll() {
    try {
      const data = await api("/api/login/log");
      applyLog(data.log, data.running);

      if (data.running) {
        setCancelVisible(true);
        const idle = data.log_updated_at
          ? Date.now() / 1000 - data.log_updated_at
          : 0;
        if (idle > 120) {
          showNotice(
            "warn",
            "Proses login sudah lama nggak aktif (tab mungkin ditutup). Klik Batalkan lalu coba lagi."
          );
        }
      }
    } catch (error) {
      stopPolling();
      setBusy(false);
      showNotice("err", `Gagal membaca log: ${error.message}`);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    hideNotice();
    finished = false;
    setBusy(true);
    buttonLabel.textContent = "Membuka browser…";
    stepsBox.classList.add("is-visible");
    setStep("open", "active");
    setStep("wait", null);
    setStep("done", null);

    try {
      const result = await api("/api/login/start", {
        method: "POST",
        body: JSON.stringify({ email: emailInput.value.trim() }),
      });

      if (!result.started) {
        setBusy(false);
        buttonLabel.textContent = "Masuk dengan Microsoft";
        showNotice("warn", result.reason || "Login sudah berjalan.");
        return;
      }

      buttonLabel.textContent = "Menunggu autentikasi…";
      setCancelVisible(true);
      logWrap.classList.add("is-visible");
      poller = setInterval(poll, 1200);
      poll();
    } catch (error) {
      setBusy(false);
      buttonLabel.textContent = "Masuk dengan Microsoft";
      showNotice("err", `Tidak bisa memulai login: ${error.message}`);
    }
  });

  cancelButton.addEventListener("click", async () => {
    cancelButton.disabled = true;
    try {
      const result = await api("/api/login/cancel", { method: "POST" });
      stopPolling();
      finished = true;
      setBusy(false);
      setCancelVisible(false);
      buttonLabel.textContent = "Masuk dengan Microsoft";
      showNotice(
        "warn",
        result.cancelled
          ? "Proses login dibatalkan. Session lama tetap tersimpan."
          : "Nggak ada proses login yang berjalan."
      );
    } catch (error) {
      showNotice("err", `Gagal membatalkan: ${error.message}`);
    } finally {
      cancelButton.disabled = false;
    }
  });

  // Info awal: session sudah ada atau belum
  api("/api/status")
    .then((status) => {
      if (status.running) {
        setBusy(true);
        buttonLabel.textContent = "Menunggu autentikasi…";
        setCancelVisible(true);
        stepsBox.classList.add("is-visible");
        logWrap.classList.add("is-visible");
        finished = false;
        poller = setInterval(poll, 1200);
        poll();
      } else if (status.has_state) {
        showNotice(
          "warn",
          `Session sudah ada (${status.cookie_count} cookie). Login ulang akan menimpanya.`
        );
      }
    })
    .catch(() => {});
}

/* -------------------------------------------------------------- dashboard */
function initDashboard() {
  const badge = $("#badge");
  const badgeText = $("#badge-text");
  const statCookies = $("#stat-cookies");
  const statExpiry = $("#stat-expiry");
  const statUpdated = $("#stat-updated");
  const refreshButton = $("#btn-refresh");
  const refreshLabel = $(".btn__label", refreshButton);
  const logoutButton = $("#btn-logout");
  const openBimayButton = $("#btn-open-bimay");

  let latest = null;

  function render(status) {
    latest = status;
    badge.className = "badge";

    if (status.running) {
      badge.classList.add("badge--warn");
      badgeText.textContent = "Login berjalan";
    } else if (!status.has_state) {
      badge.classList.add("badge--err");
      badgeText.textContent = "Belum login";
    } else if (status.expires_at && status.expires_at < status.now) {
      badge.classList.add("badge--err");
      badgeText.textContent = "Session expired";
    } else {
      badge.classList.add("badge--ok");
      badgeText.textContent = "Session aktif";
    }

    statCookies.textContent = status.has_state ? `${status.cookie_count} cookie` : "—";

    if (!status.has_state) {
      statExpiry.textContent = "—";
    } else if (!status.expires_at) {
      statExpiry.innerHTML = 'Sesi browser <small>(tanpa expiry)</small>';
    } else if (status.expires_at < status.now) {
      statExpiry.textContent = "Sudah lewat";
    } else {
      const left = status.expires_at - status.now;
      statExpiry.innerHTML = `${humanDuration(left)} <small>lagi</small>`;
      statExpiry.title = `Berakhir ${dateTime(status.expires_at)} (${clockTime(status.expires_at)})`;
    }

    statUpdated.textContent = status.updated_at ? dateTime(status.updated_at) : "—";
  }

  async function loadStatus() {
    try {
      render(await api("/api/status"));
    } catch (error) {
      toast(`Gagal memuat status: ${error.message}`, "err");
    }
  }

  refreshButton.addEventListener("click", async () => {
    refreshButton.disabled = true;
    refreshButton.classList.add("is-loading");
    refreshLabel.textContent = "Memeriksa…";

    try {
      const result = await api("/api/session/refresh", { method: "POST" });
      render(result.status);
      if (result.ok) {
        toast("Session masih hidup dan sudah diperbarui.", "ok");
      } else {
        toast("Session mati. Jalankan login ulang.", "err");
      }
    } catch (error) {
      toast(`Refresh gagal: ${error.message}`, "err");
    } finally {
      refreshButton.disabled = false;
      refreshButton.classList.remove("is-loading");
      refreshLabel.textContent = "Cek & Refresh Session";
    }
  });

  logoutButton.addEventListener("click", async () => {
    if (!confirm("Hapus session tersimpan? Kamu perlu login ulang setelah ini.")) {
      return;
    }
    try {
      const result = await api("/api/logout", { method: "POST" });
      render(result.status);
      toast("Session dihapus.", "ok");
    } catch (error) {
      toast(`Gagal menghapus: ${error.message}`, "err");
    }
  });

  openBimayButton.addEventListener("click", async () => {
    openBimayButton.disabled = true;
    try {
      const result = await api("/api/login/start", {
        method: "POST",
        body: JSON.stringify({}),
      });
      if (result.started) {
        toast(
          "Jendela BINUS Maya dibuka pakai session tersimpan. Cek taskbar ya.",
          "ok"
        );
      } else {
        toast(result.reason || "Ada proses login yang masih berjalan.", "err");
      }
    } catch (error) {
      toast(`Gagal membuka: ${error.message}`, "err");
    } finally {
      openBimayButton.disabled = false;
    }
  });

  loadStatus();
  setInterval(() => {
    if (latest) render({ ...latest, now: Date.now() / 1000 });
  }, 30000);
}

/* ------------------------------------------------------------------ rooms */
function initRooms() {
  const dateInput = $("#f-date");
  const locationSelect = $("#f-location");
  const labCheck = $("#f-lab");
  const button = $("#btn-load");
  const buttonLabel = $(".btn__label", button);
  const tbody = $("#r-body");
  const meta = $("#r-meta");

  const now = new Date();
  dateInput.value = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, "0"),
    String(now.getDate()).padStart(2, "0"),
  ].join("-");

  const escapeHtml = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[char]);

  const timeOnly = (value) => String(value ?? "").substring(0, 5);

  function render(data) {
    $("#r-shown").textContent = data.counts.shown;
    $("#r-total").textContent = data.counts.peminjaman;
    $("#r-lab").textContent = data.counts.lab_peminjaman;
    $("#r-rooms").textContent = data.counts.lab_rooms;

    meta.textContent =
      `${data.date} · ${data.location} · diambil ${data.scraped_at}` +
      (data.fresh ? "" : " (cache 5 menit)");

    if (!data.rows.length) {
      tbody.innerHTML =
        '<tr><td colspan="7" class="empty">Tidak ada peminjaman untuk tanggal dan filter ini.</td></tr>';
      return;
    }

    tbody.innerHTML = data.rows
      .map((row) => {
        const statusClass = String(row.Status).toLowerCase() === "approved"
          ? "tag--approved"
          : "tag--requested";
        const shift =
          row.ShiftStart != null && row.ShiftEnd != null
            ? `${row.ShiftStart}–${row.ShiftEnd}`
            : "—";
        return `<tr>
          <td><span class="room-code">${escapeHtml(row.Facility_ID)}</span>
              <span class="muted">${escapeHtml(row.Room)}</span></td>
          <td><span class="tag ${statusClass}">${escapeHtml(row.Status)}</span></td>
          <td>${escapeHtml(timeOnly(row.StartTime))}–${escapeHtml(timeOnly(row.EndTime))}</td>
          <td>${escapeHtml(shift)}</td>
          <td>${escapeHtml(row.Name)}<span class="muted">${escapeHtml(row.BinusianID)}</span></td>
          <td>${escapeHtml(row.Description)}<span class="muted">${escapeHtml(row.Notes)}</span></td>
          <td>${escapeHtml(row.Telephone)}</td>
        </tr>`;
      })
      .join("");
  }

  async function load() {
    button.disabled = true;
    button.classList.add("is-loading");
    buttonLabel.textContent = "Memuat…";

    try {
      const params = new URLSearchParams({
        day: dateInput.value,
        location: locationSelect.value,
        lab_only: String(labCheck.checked),
      });
      const data = await api(`/api/rooms?${params.toString()}`);
      render(data);
      toast(`${data.counts.shown} peminjaman ditampilkan.`, "ok");
    } catch (error) {
      tbody.innerHTML =
        `<tr><td colspan="7" class="empty">Gagal memuat: ${escapeHtml(error.message)}</td></tr>`;
      toast(error.message, "err");
    } finally {
      button.disabled = false;
      button.classList.remove("is-loading");
      buttonLabel.textContent = "Muat Data";
    }
  }

  button.addEventListener("click", load);
  load();
}

/* ------------------------------------------------------------------- boot */
const page = document.body.dataset.page;
if (page === "login") initLogin();
if (page === "dashboard") initDashboard();
if (page === "rooms") initRooms();
