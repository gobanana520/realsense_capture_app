document.addEventListener('DOMContentLoaded', function() {
    clearLogs();
    loadDevices();
    loadLogs();
});

async function loadDevices() {
    const response = await fetch("/devices");
    const devices = await response.json();
    const deviceSelect = document.getElementById("device-select");
    const viewSelect = document.getElementById("view-select");
    deviceSelect.innerHTML = '';
    viewSelect.innerHTML = '';

    devices.forEach(device => {
        const option = new Option(`${device.name} (${device.serial})`, device.serial);
        deviceSelect.add(option);
        viewSelect.add(option.cloneNode(true)); // Populate view-select with the same options
    });

    viewSelect.addEventListener('change', function() {
        const serial = this.value;
        const streamFrame = document.getElementById("stream-frame");
        streamFrame.src = `/video_feed?serial=${serial}`;
    });

    // Trigger the video feed update for the first device in the list
    if (viewSelect.options.length > 0) {
        viewSelect.value = viewSelect.options[0].value;
        viewSelect.dispatchEvent(new Event('change'));
    }
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
    const selectedDevices = Array.from(document.getElementById("device-select").selectedOptions).map(opt => opt.value);
    selectedDevices.forEach(async serial => {
        const response = await fetch("/start_stream", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ serial })
        });
        if (response.ok) {
            saveLog(`Started streaming from device: ${serial}`, 'success');
        } else {
            saveLog(`Failed to start streaming from device: ${serial}`, 'error');
        }
    });
    updateStreamingInfo(selectedDevices);
});

document.getElementById("stop-stream-btn").addEventListener("click", async () => {
    const selectedDevices = Array.from(document.getElementById("device-select").selectedOptions).map(opt => opt.value);
    selectedDevices.forEach(async serial => {
        await fetch("/stop_stream", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({ serial }) });
        saveLog(`Stopped streaming device: ${serial}`, 'success');
    });

    const viewSelect = document.getElementById("view-select");
    if (viewSelect.options.length > 0) {
        // Switch to another active stream or clear the image source
        const remainingDevices = Array.from(viewSelect.options).map(opt => opt.value).filter(serial => selectedDevices.indexOf(serial) === -1);
        if (remainingDevices.length > 0) {
            viewSelect.value = remainingDevices[0];
            document.getElementById("stream-frame").src = `/video_feed?serial=${remainingDevices[0]}`;
        } else {
            document.getElementById("stream-frame").src = ""; // Clear the image source
            document.getElementById("device-info").textContent = "No streaming devices";
        }
    }

    updateStreamingInfo([]);
});


document.getElementById("capture-btn").addEventListener("click", async () => {
    const folderName = document.getElementById("folder-name").value || 'default';
    const selectedDevices = Array.from(document.getElementById("device-select").selectedOptions).map(opt => opt.value);
    selectedDevices.forEach(async serial => {
        const response = await fetch("/capture", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ serial, folder_name: folderName })
        });
        if (response.ok) {
            const { timestamp } = await response.json();
            saveLog(`Capture saved: ${serial}_${timestamp} in folder ${folderName}`, 'success');
        } else {
            saveLog(`Capture failed for device ${serial}.`, 'error');
        }
    });
});

document.getElementById("get-calibration-btn").addEventListener("click", async () => {
    const selectedDevices = Array.from(document.getElementById("device-select").selectedOptions).map(opt => opt.value);
    selectedDevices.forEach(async serial => {
        const response = await fetch("/get_calibration_info", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ serial })
        });
        if (response.ok) {
            const { filename } = await response.json();
            saveLog(`Calibration info saved: ${filename} for device ${serial}`, 'success');
        } else {
            saveLog(`Failed to save calibration info for device ${serial}.`, 'error');
        }
    });
});

function updateStreamingInfo(selectedDevices) {
    const deviceInfo = document.getElementById("device-info");
    if (selectedDevices.length > 0) {
        deviceInfo.textContent = `Streaming from devices: ${selectedDevices.join(', ')}`;
    } else {
        deviceInfo.textContent = "No streaming devices";
    }
}
