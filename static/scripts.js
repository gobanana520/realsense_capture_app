document.addEventListener('DOMContentLoaded', function() {
    clearLogs();
    loadDevices();
    loadLogs();
});

async function loadDevices() {
    const response = await fetch("/devices");
    const devices = await response.json();
    const deviceSelect = document.getElementById("device-select");
    deviceSelect.innerHTML = '';

    devices.forEach(device => {
        const option = new Option(`${device.name} (${device.serial})`, device.serial);
        deviceSelect.add(option);
    });
}

function clearLogs() {
    localStorage.removeItem("logs");
}

function loadLogs() {
    const logInfo = document.getElementById("log-info");
    logInfo.innerHTML = '';
    const logs = JSON.parse(localStorage.getItem("logs")) || [];

    logs.forEach(log => {
        const p = document.createElement("p");
        p.textContent = `[${log.timestamp}] ${log.text}`;
        p.className = log.type === 'error' ? 'text-danger' : 'text-success';
        logInfo.appendChild(p);
    });

    scrollToBottom(logInfo);
}

function saveLog(text, type) {
    const now = new Date();
    const timestamp = now.toLocaleString();
    const logs = JSON.parse(localStorage.getItem("logs")) || [];
    logs.push({ text, type, timestamp });
    localStorage.setItem("logs", JSON.stringify(logs));
    loadLogs();
}

function scrollToBottom(element) {
    element.scrollTop = element.scrollHeight;
}

document.getElementById("start-stream-btn").addEventListener("click", async () => {
    const serial = document.getElementById("device-select").value;
    const selectedDevice = document.getElementById("device-select").selectedOptions[0].text;
    await fetch("/start_stream", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ serial })
    });
    document.getElementById("device-info").textContent = `Streaming from device: ${selectedDevice}`;
    saveLog(`Started streaming from device: ${serial}`, 'success');
});

document.getElementById("stop-stream-btn").addEventListener("click", async () => {
    await fetch("/stop_stream", { method: "POST" });
    document.getElementById("device-info").textContent = "Streaming stopped.";
    saveLog("Streaming stopped.", 'success');
});

document.getElementById("capture-btn").addEventListener("click", async () => {
    const folderName = document.getElementById("folder-name").value || 'default';
    const serial = document.getElementById("device-select").value;
    const response = await fetch("/capture", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ folder_name: folderName })
    });
    if (response.ok) {
        const { timestamp } = await response.json();
        saveLog(`Capture saved: ${serial}_${timestamp}`, 'success');
    } else {
        saveLog("Capture failed.", 'error');
    }
});

document.getElementById("get-calibration-btn").addEventListener("click", async () => {
    const serial = document.getElementById("device-select").value;
    const response = await fetch("/get_calibration_info", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ serial })
    });
    if (response.ok) {
        const { filename } = await response.json();
        saveLog(`Calibration info saved: ${filename}`, 'success');
    } else {
        saveLog("Failed to save calibration info.", 'error');
    }
});
