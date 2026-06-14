const $ = (selector) => document.querySelector(selector);
const curveElement = $("#curve");
const controls = ["#i2c", "#spi", "#serial", "#fanEnabled", "#unitToggle", "#psi"];
let mounted = false;
let loading = false;
let displayedUnit = "C";

const defaultCurve = [
  { temp_c: 35, speed_pct: 30 },
  { temp_c: 50, speed_pct: 50 },
  { temp_c: 60, speed_pct: 70 },
  { temp_c: 65, speed_pct: 100 },
];

function apiPath(name) {
  return `api/${name}`;
}

async function request(name, options = {}) {
  const response = await fetch(apiPath(name), {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok || data.error) {
    throw new Error(data.error || `Request failed (${response.status})`);
  }
  return data;
}

function toast(message, kind = "success") {
  const element = $("#toast");
  element.textContent = message;
  element.dataset.kind = kind;
  element.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => {
    element.hidden = true;
  }, 5000);
}

function backupMessage(data, savedLabel) {
  const names = [data.backup, data.cmdline_backup].filter(Boolean);
  return names.length ? `${savedLabel} Backup created: ${names.join("; ")}` : "No changes to save.";
}

function formatBytes(value) {
  if (value < 1024) return `${value} B`;
  return `${(value / 1024).toFixed(1)} KB`;
}

function renderBackups(backups) {
  const list = $("#backupList");
  list.replaceChildren();
  if (!backups.length) {
    const empty = document.createElement("p");
    empty.className = "backup-empty";
    empty.textContent = "No Pi Hardware Studio backups found.";
    list.appendChild(empty);
    $("#deleteBackupsButton").disabled = true;
    return;
  }

  backups.forEach((backup) => {
    const label = document.createElement("label");
    label.className = "backup-row";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = backup.name;
    checkbox.addEventListener("change", updateDeleteBackupsButton);
    const details = document.createElement("span");
    details.className = "backup-details";
    const name = document.createElement("strong");
    name.textContent = backup.name;
    const metadata = document.createElement("small");
    metadata.textContent = `${backup.source} · ${new Date(backup.modified).toLocaleString()}`;
    details.append(name, metadata);
    const size = document.createElement("span");
    size.className = "backup-size";
    size.textContent = formatBytes(backup.size);
    label.append(checkbox, details, size);
    list.appendChild(label);
  });
  updateDeleteBackupsButton();
}

function updateDeleteBackupsButton() {
  $("#deleteBackupsButton").disabled = !document.querySelector("#backupList input:checked");
}

function cToF(value) {
  return value * 9 / 5 + 32;
}

function fToC(value) {
  return (value - 32) * 5 / 9;
}

function currentUnit() {
  return $("#unitToggle").checked ? "F" : "C";
}

function renderCurve(curve = defaultCurve) {
  const unit = currentUnit();
  displayedUnit = unit;
  curveElement.innerHTML = "";
  curve.forEach((point, index) => {
    const row = document.createElement("div");
    row.className = "curve-row";
    const shownTemp = unit === "F" ? cToF(point.temp_c) : point.temp_c;
    row.innerHTML = `
      <span class="point-number">${index + 1}</span>
      <label>Temperature
        <span class="input-with-unit">
          <input class="temp" type="number" step="1" min="${unit === "F" ? 68 : 20}"
            max="${unit === "F" ? 212 : 100}" value="${Math.round(shownTemp)}">
          <span>°${unit}</span>
        </span>
      </label>
      <label>Fan speed
        <span class="input-with-unit">
          <input class="speed" type="number" step="1" min="0" max="100"
            value="${Math.round(point.speed_pct)}">
          <span>%</span>
        </span>
      </label>`;
    curveElement.appendChild(row);
  });
  curveElement.querySelectorAll("input").forEach((input) => input.addEventListener("input", markDirty));
  setFanInputsEnabled();
}

function readCurve() {
  const unit = displayedUnit;
  return [...document.querySelectorAll(".curve-row")].map((row) => {
    const shownTemp = Number(row.querySelector(".temp").value);
    return {
      temp_c: unit === "F" ? fToC(shownTemp) : shownTemp,
      speed_pct: Number(row.querySelector(".speed").value),
    };
  });
}

function setFanInputsEnabled() {
  const enabled = mounted && $("#fanEnabled").checked;
  curveElement.querySelectorAll("input").forEach((input) => {
    input.disabled = !enabled;
  });
}

function markDirty() {
  if (!loading) {
    $("#dirtyBadge").hidden = false;
  }
}

function updateFanDisplay(fan) {
  $("#fanTelemetry").textContent = fan.detected
    ? `${fan.rpm.toLocaleString()} RPM${fan.speed_pct === null ? "" : ` · ${fan.speed_pct}% PWM`}`
    : "Fan telemetry unavailable until the driver is active";
  const yamlAvailable = mounted && Boolean(fan.sensor_yaml);
  $("#fanSensorConfig").hidden = !yamlAvailable;
  $("#fanSensorYaml").value = yamlAvailable ? fan.sensor_yaml : "";
}

function setMountedState(value, target = null) {
  mounted = value;
  $("#mountStatus").textContent = value ? "Boot mounted" : "Not mounted";
  $("#mountStatus").classList.toggle("online", value);
  $("#targetText").textContent = value ? `Editing ${target}` : "Mount the boot partition to read and change host settings.";
  $("#mountButton").disabled = value;
  $("#mountButton").textContent = value ? "Mounted" : "Mount boot partition";
  document.querySelectorAll("input, textarea, button").forEach((element) => {
    if (!["mountButton"].includes(element.id)) {
      element.disabled = !value;
    }
  });
  setFanInputsEnabled();
}

function applyStatus(data) {
  loading = true;
  setMountedState(data.mounted, data.target);
  const settings = data.settings;
  $("#i2c").checked = data.mounted && settings.i2c;
  $("#spi").checked = data.mounted && settings.spi;
  $("#serial").checked = data.mounted && settings.serial;
  $("#psi").checked = data.mounted && settings.psi;
  $("#fanEnabled").checked = data.mounted && settings.fan_enabled;
  $("#unitToggle").checked = settings.temperature_unit === "F";
  renderCurve(settings.fan_curve);
  updateFanDisplay(data.fan);
  $("#dirtyBadge").hidden = true;
  loading = false;
}

async function refresh() {
  try {
    applyStatus(await request("status"));
  } catch (error) {
    toast(error.message, "error");
  }
}

$("#mountButton").addEventListener("click", async () => {
  try {
    $("#mountButton").disabled = true;
    $("#mountButton").textContent = "Scanning…";
    await request("mount", { method: "POST", body: "{}" });
    await refresh();
    toast("Boot partition mounted.");
  } catch (error) {
    setMountedState(false);
    toast(error.message, "error");
  }
});

controls.forEach((selector) => $(selector).addEventListener("change", markDirty));
$("#fanEnabled").addEventListener("change", setFanInputsEnabled);
$("#unitToggle").addEventListener("change", () => {
  const canonical = readCurve();
  renderCurve(canonical);
  markDirty();
});

$("#copyFanYamlButton").addEventListener("click", async () => {
  const yaml = $("#fanSensorYaml").value;
  if (!yaml) return;
  try {
    await navigator.clipboard.writeText(yaml);
    toast("Fan sensor YAML copied.");
  } catch {
    $("#fanSensorYaml").select();
    document.execCommand("copy");
    toast("Fan sensor YAML copied.");
  }
});

$("#saveButton").addEventListener("click", async () => {
  try {
    const data = await request("settings", {
      method: "PUT",
      body: JSON.stringify({
        i2c: $("#i2c").checked,
        spi: $("#spi").checked,
        serial: $("#serial").checked,
        psi: $("#psi").checked,
        fan_enabled: $("#fanEnabled").checked,
        fan_curve: readCurve(),
        temperature_unit: currentUnit(),
      }),
    });
    $("#dirtyBadge").hidden = true;
    toast(backupMessage(data, "Settings applied."));
  } catch (error) {
    toast(error.message, "error");
  }
});

$("#sshButton").addEventListener("click", async () => {
  try {
    const data = await request("ssh", {
      method: "PUT",
      body: JSON.stringify({ public_key: $("#sshKey").value }),
    });
    $("#sshKey").value = "";
    toast(data.already_present ? "That key is already installed." : `Key installed on: ${data.added_to.join(", ")}`);
  } catch (error) {
    toast(error.message, "error");
  }
});

$("#editorButton").addEventListener("click", async () => {
  try {
    const data = await request("config");
    $("#configEditor").value = data.content;
    $("#editorDialog").showModal();
  } catch (error) {
    toast(error.message, "error");
  }
});

$("#configSaveButton").addEventListener("click", async () => {
  if (!confirm("Save the raw boot configuration? Invalid settings can prevent the host from booting.")) {
    return;
  }
  try {
    const data = await request("config", {
      method: "PUT",
      body: JSON.stringify({ content: $("#configEditor").value }),
    });
    $("#editorDialog").close();
    toast(backupMessage(data, "Configuration saved."));
    await refresh();
  } catch (error) {
    toast(error.message, "error");
  }
});

$("#cmdlineEditorButton").addEventListener("click", async () => {
  try {
    const data = await request("cmdline");
    $("#cmdlineEditor").value = data.content;
    $("#cmdlineDialog").showModal();
  } catch (error) {
    toast(error.message, "error");
  }
});

$("#cmdlineSaveButton").addEventListener("click", async () => {
  if (!confirm("Save cmdline.txt? Invalid kernel arguments can prevent the host from booting.")) {
    return;
  }
  try {
    const data = await request("cmdline", {
      method: "PUT",
      body: JSON.stringify({ content: $("#cmdlineEditor").value }),
    });
    $("#cmdlineDialog").close();
    toast(backupMessage(data, "Kernel command line saved."));
    await refresh();
  } catch (error) {
    toast(error.message, "error");
  }
});

$("#backupManagerButton").addEventListener("click", async () => {
  try {
    const data = await request("backups");
    renderBackups(data.backups);
    $("#backupDialog").showModal();
  } catch (error) {
    toast(error.message, "error");
  }
});

$("#deleteBackupsButton").addEventListener("click", async () => {
  const names = [...document.querySelectorAll("#backupList input:checked")]
    .map((input) => input.value);
  if (!names.length) return;
  if (!confirm(`Permanently delete ${names.length} selected backup${names.length === 1 ? "" : "s"}?`)) {
    return;
  }
  try {
    const data = await request("backups", {
      method: "DELETE",
      body: JSON.stringify({ names }),
    });
    renderBackups((await request("backups")).backups);
    toast(`Deleted ${data.deleted.length} backup${data.deleted.length === 1 ? "" : "s"}.`);
  } catch (error) {
    toast(error.message, "error");
  }
});

$("#rebootButton").addEventListener("click", async () => {
  if (!confirm("Reboot the Home Assistant host now?")) {
    return;
  }
  try {
    await request("reboot", { method: "POST", body: "{}" });
    toast("Host reboot requested.");
  } catch (error) {
    toast(error.message, "error");
  }
});

refresh();
setInterval(async () => {
  if (!mounted || document.hidden) return;
  try {
    const data = await request("status");
    updateFanDisplay(data.fan);
  } catch {
    // Keep the last telemetry value during a transient refresh failure.
  }
}, 10000);
