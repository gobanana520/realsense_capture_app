from flask import Flask, render_template, Response, request, jsonify
import cv2
import numpy as np
import pyrealsense2 as rs
import datetime
from pathlib import Path
import json
import time
import threading
import sys

class RealSenseCaptureToolkit:
    def __init__(self, config_file):
        self.app = Flask("RealSense Capture Toolkit")
        self.pipeline = None
        self.align = None
        self.streaming = False
        self.stream_lock = threading.Lock()

        # Load RealSense settings from JSON file
        with Path(config_file).open("r") as f:
            self.rs_config = json.load(f)

        # Create a black image for fallback use when frames are not available
        self.black_image = np.zeros(
            (self.rs_config["image_height"], self.rs_config["image_width"] * 2, 3),
            dtype=np.uint8
        )

        # Define routes
        self._define_routes()

    def _define_routes(self):
        """Define Flask routes for the web interface."""
        self.app.add_url_rule("/devices", "list_devices", self.list_devices)
        self.app.add_url_rule("/start_stream", "start_stream", self.start_stream, methods=["POST"])
        self.app.add_url_rule("/stop_stream", "stop_stream", self.stop_stream, methods=["POST"])
        self.app.add_url_rule("/capture", "capture", self.capture, methods=["POST"])
        self.app.add_url_rule("/video_feed", "video_feed", self.video_feed)
        self.app.add_url_rule("/", "index", self.index)

    def get_connected_devices(self):
        """Retrieve information about connected RealSense devices."""
        context = rs.context()
        devices = [
            {
                "name": device.get_info(rs.camera_info.name),
                "serial": device.get_info(rs.camera_info.serial_number),
                "product_line": device.get_info(rs.camera_info.product_line),
            }
            for device in context.devices
        ]
        return devices

    def list_devices(self):
        """List all connected RealSense devices."""
        devices = self.get_connected_devices()
        return jsonify(devices)

    def start_stream(self):
        """Start the RealSense stream based on the device serial number provided."""
        with self.stream_lock:
            if self.streaming:
                return "", 204  # Already streaming

            device_serial = request.json.get("serial")
            if not device_serial:
                return "Device serial number is required", 400

            self.pipeline = rs.pipeline()
            config = rs.config()
            config.enable_device(device_serial)
            config.enable_stream(
                rs.stream.color, self.rs_config["image_width"], self.rs_config["image_height"],
                rs.format.bgr8, self.rs_config["fps"]
            )
            config.enable_stream(
                rs.stream.depth, self.rs_config["image_width"], self.rs_config["image_height"],
                rs.format.z16, self.rs_config["fps"]
            )
            try:
                self.pipeline.start(config)
            except Exception as e:
                self.pipeline = None
                return f"Failed to start stream: {e}", 500

            align_to = rs.stream.color
            self.align = rs.align(align_to)
            self.streaming = True

        return "", 204

    def stop_stream(self):
        """Stop the RealSense stream."""
        with self.stream_lock:
            if self.pipeline is not None:
                try:
                    self.pipeline.stop()
                except Exception as e:
                    print(f"Error stopping pipeline: {e}")
                finally:
                    self.pipeline = None

            self.streaming = False
        return "", 204

    def capture(self):
        """Capture and save color and depth images."""
        if not self.streaming or self.pipeline is None:
            return "Streaming is not active", 400

        data = request.json
        folder_name = data.get("folder_name", "default")

        with self.stream_lock:
            frames = self.pipeline.wait_for_frames()
            aligned_frames = self.align.process(frames)

            aligned_depth_frame = aligned_frames.get_depth_frame()
            color_frame = aligned_frames.get_color_frame()

            if not aligned_depth_frame or not color_frame:
                return "Failed to capture frames", 500

            color_image = np.asanyarray(color_frame.get_data())
            depth_image = np.asanyarray(aligned_depth_frame.get_data())

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = Path("captures") / folder_name
            save_path.mkdir(parents=True, exist_ok=True)

            color_filename = save_path / f"color_{timestamp}.jpg"
            depth_filename = save_path / f"depth_{timestamp}.png"

            cv2.imwrite(str(color_filename), color_image)
            cv2.imwrite(str(depth_filename), depth_image)

        return jsonify({"timestamp": timestamp}), 200

    def get_frames(self):
        """Generator function to retrieve and yield frames for streaming."""
        while True:
            with self.stream_lock:
                if self.streaming and self.pipeline is not None:
                    try:
                        frames = self.pipeline.wait_for_frames()
                        aligned_frames = self.align.process(frames)

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
                        yield from self.yield_fallback_image()

                    except Exception as e:
                        print(f"Unexpected error during frame retrieval: {e}")
                        yield from self.yield_fallback_image()
                else:
                    yield from self.yield_fallback_image()

            time.sleep(0.1)  # Add a slight delay to avoid hammering the CPU

    def yield_fallback_image(self):
        """Yield a black fallback image when no frames are available."""
        fallback_image = cv2.imencode(".jpg", self.black_image)[1]
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + fallback_image.tobytes()
            + b"\r\n\r\n"
        )

    def video_feed(self):
        """Provide the video feed to the front-end."""
        return Response(self.get_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

    def index(self):
        """Render the main index page."""
        return render_template("index.html")

    def run(self):
        """Run the Flask web server."""
        try:
            self.app.run(host="0.0.0.0", port=5000)
        except Exception as e:
            print(f"Error running the Flask app: {e}")
            sys.exit(1)


if __name__ == "__main__":
    toolkit = RealSenseCaptureToolkit("config/rs_config.json")
    toolkit.run()
