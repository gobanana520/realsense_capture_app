document.addEventListener('DOMContentLoaded', function() {
    loadSelectedDevices();  // Load selected devices from localStorage
    loadDevices();
    loadLogs();
});

let enabledDevices = [];

function loadSelectedDevices() {
    const storedDevices = JSON.parse(localStorage.getItem('enabledDevices')) || [];
    enabledDevices = storedDevices;
}

function saveSelectedDevices() {
    localStorage.setItem('enabledDevices', JSON.stringify(enabledDevices));
}

async function loadDevices() {
    try {
        const response = await fetch("/devices");
        if (!response.ok) {
            throw new Error('Failed to fetch devices');
        }

        const devices = await response.json();
        const deviceList = document.getElementById("device-list");
        deviceList.innerHTML = '';

        if (devices.length === 0) {
            console.error('No devices found');
            return;
        }

        devices.forEach(device => {
            const listItem = document.createElement('li');
            listItem.className = 'list-group-item d-flex justify-content-between align-items-center';
            listItem.textContent = `${device.name} (${device.serial})`;

            const dot = document.createElement('span');
            dot.className = 'dot';
            dot.dataset.serial = device.serial;
            dot.style.cursor = 'pointer';
            dot.style.backgroundColor = enabledDevices.includes(device.serial) ? 'green' : 'red';

            dot.addEventListener('click', function() {
                toggleDevice(device.serial, dot);
            });

            listItem.appendChild(dot);
            deviceList.appendChild(listItem);
        });

        updateViewSelect(enabledDevices);
        updateStreamingInfo(enabledDevices);
        console.log('Devices loaded:', devices);
    } catch (error) {
        console.error('Error loading devices:', error);
    }
}

function toggleDevice(serial, dot) {
    if (enabledDevices.includes(serial)) {
        enabledDevices = enabledDevices.filter(s => s !== serial);
        dot.style.backgroundColor = 'red';
    } else {
        enabledDevices.push(serial);
        dot.style.backgroundColor = 'green';
    }

    saveSelectedDevices();  // Save the current state to localStorage
    updateViewSelect(enabledDevices);
    updateStreamingInfo(enabledDevices);
}

function updateViewSelect(enabledDevices) {
    const viewSelect = document.getElementById("view-select");
    viewSelect.innerHTML = ''; // Clear previous options

    enabledDevices.forEach(serial => {
        const option = new Option(`Device ${serial}`, serial);
        viewSelect.add(option);
    });

    if (viewSelect.options.length > 0) {
        viewSelect.value = viewSelect.options[0].value;
        viewSelect.dispatchEvent(new Event('change'));
    } else {
        document.getElementById("stream-frame").src = "/static/dummy.jpg"; // Show dummy image if no serial
        document.getElementById("device-info").textContent = "No streaming devices";
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
    enabledDevices.forEach(async serial => {
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

    updateStreamingInfo(enabledDevices);
});

document.getElementById("stop-stream-btn").addEventListener("click", async () => {
    enabledDevices.forEach(async serial => {
        await fetch("/stop_stream", { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({ serial }) });
        saveLog(`Stopped streaming device: ${serial}`, 'success');
    });

    updateViewSelect([]); // Clear the view-select dropdown
    enabledDevices = [];
    saveSelectedDevices();  // Update localStorage after clearing enabledDevices
    updateStreamingInfo([]);
});

document.getElementById("view-select").addEventListener("change", function() {
    const serial = this.value;
    const streamFrame = document.getElementById("stream-frame");
    if (serial) {
        streamFrame.src = `/video_feed?serial=${serial}`;
    } else {
        streamFrame.src = "/static/dummy.jpg"; // Show dummy image if no serial
    }
});

document.getElementById("capture-btn").addEventListener("click", async () => {
    const folderName = document.getElementById("folder-name").value || 'default';
    enabledDevices.forEach(async serial => {
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
    enabledDevices.forEach(async serial => {
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

function updateStreamingInfo(enabledDevices) {
    const deviceInfo = document.getElementById("device-info");
    if (enabledDevices.length > 0) {
        deviceInfo.textContent = `Streaming from devices: ${enabledDevices.join(', ')}`;
    } else {
        deviceInfo.textContent = "No streaming devices";
    }
}
