from flask import Flask, render_template, Response, request, jsonify
import cv2
import numpy as np
import pyrealsense2 as rs
import datetime
import os
import json
import time
import threading
import sys

app = Flask("RealSense Capture Toolkit")

# Load RealSense settings from JSON file
with open("config/rs_config.json", "r") as f:
    rs_config = json.load(f)


# Function to get connected RealSense devices
def get_connected_devices():
    context = rs.context()
    devices = []
    for device in context.devices:
        devices.append(
            {
                "name": device.get_info(rs.camera_info.name),
                "serial": device.get_info(rs.camera_info.serial_number),
                "product_line": device.get_info(rs.camera_info.product_line),
            }
        )
    return devices


# Global variables to manage pipeline and state
pipeline = None
align = None
streaming = False
stream_lock = threading.Lock()

# Create a black image with the same size as the color and depth images combined
black_image = np.zeros(
    (rs_config["image_height"], rs_config["image_width"] * 2, 3), dtype=np.uint8
)


@app.route("/devices")
def list_devices():
    devices = get_connected_devices()
    return jsonify(devices)


@app.route("/start_stream", methods=["POST"])
def start_stream():
    global pipeline, align, streaming

    with stream_lock:
        if streaming:
            return "", 204  # Already streaming

        device_serial = request.json["serial"]

        pipeline = rs.pipeline()
        config = rs.config()
        config.enable_device(device_serial)
        config.enable_stream(
            rs.stream.color,
            rs_config["image_width"],
            rs_config["image_height"],
            rs.format.bgr8,
            rs_config["fps"],
        )
        config.enable_stream(
            rs.stream.depth,
            rs_config["image_width"],
            rs_config["image_height"],
            rs.format.z16,
            rs_config["fps"],
        )
        pipeline.start(config)

        align_to = rs.stream.color
        align = rs.align(align_to)
        streaming = True

    return "", 204


@app.route("/stop_stream", methods=["POST"])
def stop_stream():
    global pipeline, streaming

    with stream_lock:
        if pipeline is not None:
            try:
                pipeline.stop()
            except Exception as e:
                print(f"Error stopping pipeline: {e}")
            finally:
                pipeline = None

        streaming = False
    return "", 204


@app.route("/capture", methods=["POST"])
def capture():
    global pipeline, align, streaming

    if not streaming or pipeline is None:
        return "Streaming is not active", 400

    data = request.json
    folder_name = data.get("folder_name", "default")

    with stream_lock:
        frames = pipeline.wait_for_frames()
        aligned_frames = align.process(frames)

        aligned_depth_frame = aligned_frames.get_depth_frame()
        color_frame = aligned_frames.get_color_frame()

        if not aligned_depth_frame or not color_frame:
            return "Failed to capture frames", 500

        color_image = np.asanyarray(color_frame.get_data())
        depth_image = np.asanyarray(aligned_depth_frame.get_data())

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = os.path.join("capture", folder_name)
        os.makedirs(save_path, exist_ok=True)

        color_filename = os.path.join(save_path, f"color_{timestamp}.jpg")
        depth_filename = os.path.join(save_path, f"depth_{timestamp}.png")

        cv2.imwrite(color_filename, color_image)
        cv2.imwrite(depth_filename, depth_image)

    return jsonify({"timestamp": timestamp}), 200


def get_frames():
    global pipeline, align, streaming

    while True:
        with stream_lock:
            if streaming and pipeline is not None:
                try:
                    frames = pipeline.wait_for_frames()
                    aligned_frames = align.process(frames)

                    aligned_depth_frame = aligned_frames.get_depth_frame()
                    color_frame = aligned_frames.get_color_frame()

                    if not aligned_depth_frame or not color_frame:
                        continue

                    color_image = np.asanyarray(color_frame.get_data())
                    depth_image = np.asanyarray(aligned_depth_frame.get_data())

                    # Normalize depth image for visualization
                    depth_colormap = cv2.applyColorMap(
                        cv2.convertScaleAbs(depth_image, alpha=0.03), cv2.COLORMAP_JET
                    )

                    # Combine the color and depth images side by side
                    combined_image = np.hstack((color_image, depth_colormap))

                    # Encode the combined image
                    combined_jpeg = cv2.imencode(".jpg", combined_image)[1]

                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + combined_jpeg.tobytes()
                        + b"\r\n\r\n"
                    )

                except RuntimeError as e:
                    print(f"Runtime error during frame retrieval: {e}")
                    fallback_image = cv2.imencode(".jpg", black_image)[1]
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + fallback_image.tobytes()
                        + b"\r\n\r\n"
                    )

                except Exception as e:
                    print(f"Unexpected error during frame retrieval: {e}")
                    fallback_image = cv2.imencode(".jpg", black_image)[1]
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n"
                        + fallback_image.tobytes()
                        + b"\r\n\r\n"
                    )
            else:
                # Fallback to black image if streaming is not active
                fallback_image = cv2.imencode(".jpg", black_image)[1]
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + fallback_image.tobytes()
                    + b"\r\n\r\n"
                )

        time.sleep(0.1)  # Add a slight delay to avoid hammering the CPU


@app.route("/video_feed")
def video_feed():
    return Response(get_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    try:
        app.run(host="0.0.0.0", port=5000)
    except Exception as e:
        print(f"Error running the Flask app: {e}")
        sys.exit(1)
