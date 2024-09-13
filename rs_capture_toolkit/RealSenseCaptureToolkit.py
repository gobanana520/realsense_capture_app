import time
from flask import Flask, render_template, Response, request, jsonify
import cv2
import numpy as np
import pyrealsense2 as rs
import datetime
import threading
import sys
from .Utils import get_logger, read_config, PROJ_ROOT, write_data_to_json


class RealSenseCaptureToolkit:
    """
    A toolkit to capture and stream video from multiple Intel RealSense cameras, with a web interface.
    """

    def __init__(self):
        self.app = Flask("RealSense Capture Toolkit")
        self.pipelines = {}  # Dictionary to hold pipelines for each device
        self.aligns = {}  # Dictionary to hold align objects for each device
        self.stream_locks = {}  # Dictionary to hold locks for each device

        # Load RealSense settings from JSON file
        self.rs_config = read_config()

        # Initialize the logger
        self.logger = get_logger("RealSenseCaptureToolkit")
        self.logger.info("RealSense Capture Toolkit initialized.")

        # Create a black image for fallback use when frames are not available
        self.black_image = np.zeros(
            (self.rs_config.image_height, self.rs_config.image_width, 3),
            dtype=np.uint8,
        )

        # Define routes
        self._define_routes()

    def _define_routes(self):
        """Define Flask routes for the web interface."""
        self.app.add_url_rule("/devices", "list_devices", self.list_devices)
        self.app.add_url_rule(
            "/start_stream", "start_stream", self.start_stream, methods=["POST"]
        )
        self.app.add_url_rule(
            "/stop_stream", "stop_stream", self.stop_stream, methods=["POST"]
        )
        self.app.add_url_rule("/capture", "capture", self.capture, methods=["POST"])
        self.app.add_url_rule("/video_feed", "video_feed", self.video_feed)
        self.app.add_url_rule(
            "/get_calibration_info",
            "get_calibration_info",
            self.get_calibration_info,
            methods=["POST"],
        )
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
        self.logger.info(f"Found {len(devices)} RealSense devices.")
        return devices

    def list_devices(self):
        """List all connected RealSense devices."""
        devices = self.get_connected_devices()
        return jsonify(devices)

    def start_stream(self):
        """Start the RealSense stream based on the device serial number provided."""
        device_serial = request.json.get("serial")
        if not device_serial:
            self.logger.error("Device serial number is required to start streaming.")
            return "Device serial number is required", 400

        if device_serial in self.pipelines:
            self.logger.warning(f"Stream already running for device {device_serial}.")
            return "", 204  # Already streaming

        pipeline = rs.pipeline()
        config = rs.config()
        config.enable_device(device_serial)
        config.enable_stream(
            rs.stream.color,
            self.rs_config.image_width,
            self.rs_config.image_height,
            rs.format.bgr8,
            self.rs_config.fps,
        )
        config.enable_stream(
            rs.stream.depth,
            self.rs_config.image_width,
            self.rs_config.image_height,
            rs.format.z16,
            self.rs_config.fps,
        )
        try:
            pipeline.start(config)
            self.logger.info(f"Started streaming from device: {device_serial}")
        except Exception as e:
            self.logger.error(f"Failed to start stream: {e}")
            return f"Failed to start stream: {e}", 500

        self.pipelines[device_serial] = pipeline
        self.aligns[device_serial] = rs.align(rs.stream.color)
        self.stream_locks[device_serial] = threading.Lock()

        return "", 204

    def stop_stream(self):
        """Stop the RealSense stream."""
        device_serial = request.json.get("serial")
        if device_serial in self.pipelines:
            with self.stream_locks[device_serial]:
                try:
                    self.pipelines[device_serial].stop()
                    self.logger.info(f"Stopped streaming from device: {device_serial}")
                except Exception as e:
                    self.logger.error(f"Error stopping pipeline: {e}")
                finally:
                    del self.pipelines[device_serial]
                    del self.aligns[device_serial]
                    del self.stream_locks[device_serial]

            return "", 204
        else:
            self.logger.error(f"No active stream found for device {device_serial}")
            return "Stream not found", 404

    def capture(self):
        """Capture and save both color and depth images for all active devices."""
        device_serial = request.json.get("serial")
        folder_name = request.json.get("folder_name", "default")

        if device_serial not in self.pipelines:
            self.logger.warning(
                f"Attempted capture while streaming is inactive for device {device_serial}."
            )
            return "Streaming is not active", 400

        save_path = PROJ_ROOT / "data" / "captures" / folder_name
        save_path.mkdir(parents=True, exist_ok=True)

        with self.stream_locks[device_serial]:
            frames = self.pipelines[device_serial].wait_for_frames()
            aligned_frames = self.aligns[device_serial].process(frames)

            aligned_depth_frame = aligned_frames.get_depth_frame()
            color_frame = aligned_frames.get_color_frame()

            if not aligned_depth_frame or not color_frame:
                self.logger.error(
                    f"Failed to capture frames for device {device_serial}."
                )
                return "Failed to capture frames", 500

            color_image = np.asanyarray(color_frame.get_data())
            depth_image = np.asanyarray(aligned_depth_frame.get_data())

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            color_filename = save_path / f"color_{device_serial}_{timestamp}.jpg"
            depth_filename = save_path / f"depth_{device_serial}_{timestamp}.png"

            cv2.imwrite(str(color_filename), color_image)
            cv2.imwrite(str(depth_filename), depth_image)

            self.logger.info(
                f"Captured images saved at {save_path} for device {device_serial}"
            )

        return jsonify({"timestamp": timestamp}), 200

    def get_calibration_info(self):
        """Retrieve and save the calibration info of the color and depth cameras for a specific device."""
        device_serial = request.json.get("serial")

        if device_serial not in self.pipelines:
            self.logger.warning(
                f"Calibration info requested while streaming is inactive for device {device_serial}."
            )
            return "Streaming is not active", 400

        try:
            profile = self.pipelines[device_serial].get_active_profile()
            device = profile.get_device()
            serial = device.get_info(rs.camera_info.serial_number)

            # Get intrinsics for color and depth streams
            color_stream = profile.get_stream(rs.stream.color)
            depth_stream = profile.get_stream(rs.stream.depth)

            color_intrinsics = color_stream.as_video_stream_profile().get_intrinsics()
            depth_intrinsics = depth_stream.as_video_stream_profile().get_intrinsics()

            # Get the extrinsics from depth to color
            depth_to_color_extrinsics = depth_stream.get_extrinsics_to(color_stream)

            calibration_info = {
                "color": {
                    "fx": color_intrinsics.fx,
                    "fy": color_intrinsics.fy,
                    "cx": color_intrinsics.ppx,
                    "cy": color_intrinsics.ppy,
                },
                "depth": {
                    "fx": depth_intrinsics.fx,
                    "fy": depth_intrinsics.fy,
                    "cx": depth_intrinsics.ppx,
                    "cy": depth_intrinsics.ppy,
                },
                "extrinsics": {
                    "rotation": depth_to_color_extrinsics.rotation,
                    "translation": depth_to_color_extrinsics.translation,
                },
                "width": color_intrinsics.width,
                "height": color_intrinsics.height,
            }

            save_path = PROJ_ROOT / "data" / "calibrations"
            save_path.mkdir(parents=True, exist_ok=True)
            filename = (
                save_path
                / f"{serial}_{color_intrinsics.width}x{color_intrinsics.height}.json"
            )
            write_data_to_json(filename, calibration_info)
            self.logger.info(f"Calibration info saved as {filename}")

            return jsonify({"filename": str(filename)}), 200

        except Exception as e:
            self.logger.error(f"Error retrieving calibration info: {e}")
            return str(e), 500

    def get_frames(self, serial):
        """Generator function to retrieve and yield color frames for streaming."""
        while True:
            if serial not in self.stream_locks:
                self.logger.info(
                    f"No active stream found for device {serial}. Returning fallback image."
                )
                yield from self.yield_fallback_image()
                break

            with self.stream_locks[serial]:
                if serial in self.pipelines:
                    try:
                        frames = self.pipelines[serial].wait_for_frames()
                        color_frame = frames.get_color_frame()

                        if not color_frame:
                            continue

                        color_image = np.asanyarray(color_frame.get_data())

                        # Encode the color image
                        color_jpeg = cv2.imencode(".jpg", color_image)[1]

                        yield (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n\r\n"
                            + color_jpeg.tobytes()
                            + b"\r\n\r\n"
                        )

                    except RuntimeError as e:
                        self.logger.error(
                            f"Runtime error during frame retrieval for device {serial}: {e}"
                        )
                        yield from self.yield_fallback_image()

                    except Exception as e:
                        self.logger.error(
                            f"Unexpected error during frame retrieval for device {serial}: {e}"
                        )
                        yield from self.yield_fallback_image()
                else:
                    yield from self.yield_fallback_image()

            time.sleep(0.1)  # Add a slight delay to avoid hammering the CPU

    def yield_fallback_image(self):
        """Yield a black fallback image when no frames are available."""
        fallback_image = cv2.imencode(".jpg", self.black_image)[1]
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + fallback_image.tobytes() + b"\r\n\r\n"
        )

    def video_feed(self):
        """Provide the video feed to the front-end."""
        serial = request.args.get("serial")
        return Response(
            self.get_frames(serial),
            mimetype="multipart/x-mixed-replace; boundary=frame",
        )

    def index(self):
        """Render the main index page."""
        return render_template("index.html")

    def run(self):
        """Run the Flask web server."""
        try:
            self.logger.info("Starting Flask server...")
            self.app.run(host="0.0.0.0", port=5000)
        except Exception as e:
            self.logger.error(f"Error running the Flask app: {e}")
            sys.exit(1)


if __name__ == "__main__":
    toolkit = RealSenseCaptureToolkit()
    toolkit.run()
