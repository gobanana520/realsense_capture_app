import argparse
import pyrealsense2 as rs
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Device:
    serial: str
    pipeline: rs.pipeline
    pipeline_profile: rs.pipeline_profile
    product_line: str


class RealsenseDeviceManager:
    def __init__(self, context, pipeline_configuration) -> None:
        if not isinstance(context, rs.context):
            raise TypeError("context must be an instance of rs.context")
        if not isinstance(pipeline_configuration, rs.config):
            raise TypeError("pipeline_configuration must be an instance of rs.config")

        self._context = context
        self._available_devices = self._enumerate_connected_devices(context)
        self._enabled_devices = {}
        self._config = pipeline_configuration
        self._frame_counter = 0

    def _enumerate_connected_devices(self, context):
        connected_devices = []

        for d in context.devices:
            if d.get_info(rs.camera_info.name).lower() != "platform camera":
                serial = d.get_info(rs.camera_info.serial_number)
                product_line = d.get_info(rs.camera_info.product_line)
                device_info = (serial, product_line)  # (serial_number, product_line)
                connected_devices.append(device_info)
        return connected_devices

    def enable_device(self, device_info, enable_ir_emitter=False):
        try:
            pip = rs.pipeline()
            device_serial = device_info[0]
            product_line = device_info[1]
            self._config.enable_device(device_serial)
            pip_profile = pip.start(self._config)
            # set the acquisition parameters
            sensor = pip_profile.get_device().first_depth_sensor()
            if sensor.supports(rs.option.emitter_enabled):
                sensor.set_option(
                    rs.option.emitter_enabled, 1 if enable_ir_emitter else 0
                )
            self._enabled_devices[device_serial] = Device(
                device_serial, pip, pip_profile, product_line
            )
        except Exception as e:
            print(f"Failed to enable device {device_info}: {e}")

    def enable_all_devices(self, enable_ir_emitter=False):
        print(f"- {len(self._available_devices)} devices have been found")

        for device_info in self._available_devices:
            print(f"  - launching {device_info[1]} {device_info[0]}")
            self.enable_device(device_info, enable_ir_emitter)

    def enable_emitter(self):
        for serial, device in self._enabled_devices.items():
            sensor = device.pipeline_profile.get_device().first_depth_sensor()
            if sensor.supports(rs.option.emitter_enabled):
                sensor.set_option(rs.option.emitter_enabled, 1)
                sensor.set_option(rs.option.laser_power, 330)

    def load_settings_json(self, file_path):
        with open(file_path, "r") as file:
            json_text = file.read().strip()
        for serial, device in self._enabled_devices.items():
            device = device.pipeline_profile.get_device()
            advanced_mode = rs.rs400_advanced_mode(device)
            advanced_mode.load_json(json_text)

    def poll_frames(self):
        frames = {}
        while len(frames) < len(self._enabled_devices):
            for serial, device in self._enabled_devices.items():
                streams = device.pipeline_profile.get_streams()
                frameset = device.pipeline.wait_for_frames()
                if frameset.size() == len(streams):
                    dev_info = (serial, device.product_line)
                    frames[dev_info] = {}
                    for stream in streams:
                        if stream.stream_type() == rs.stream.infrared:
                            frame = frameset.get_infrared_frame(stream.stream_index())
                            key_ = (stream.stream_type(), stream.stream_index())
                        else:
                            frame = frameset.first_or_default(stream.stream_type())
                            key_ = stream.stream_type()
                        frames[dev_info][key_] = frame
        return frames

    def get_depth_shape(self):
        width = -1
        height = -1
        for serial, device in self._enabled_devices.items():
            for stream in device.pipeline_profile.get_streams():
                if rs.stream.depth == stream.stream_type():
                    width = stream.as_video_stream_profile().width()
                    height = stream.as_video_stream_profile().height()
        return width, height

    def get_device_intrinsics(self, frames):
        device_intrinsics = {}
        for dev_info, frameset in frames.items():
            serial = dev_info[0]
            device_intrinsics[serial] = {}
            for key, value in frameset.items():
                device_intrinsics[serial][key] = (
                    value.get_profile().as_video_stream_profile().get_intrinsics()
                )
        return device_intrinsics

    def get_depth_to_color_extrinsics(self, frames):
        device_extrinsics = {}
        for dev_info, frameset in frames.items():
            serial = dev_info[0]
            depth_frame = frameset[rs.stream.depth]
            color_frame = frameset[rs.stream.color]
            extrinsics = (
                depth_frame.get_profile()
                .as_video_stream_profile()
                .get_extrinsics_to(color_frame.get_profile())
            )
            device_extrinsics[serial] = extrinsics
        return device_extrinsics

    def disable_streams(self):
        self._config.disable_all_streams()


def save_intrinsics_json(serial, intr_color, intr_depth, extr, output_file):
    """Save intrinsics and extrinsics data to a JSON file."""
    data = {
        "serial": serial,
        "width": intr_color.width,  # Shared width
        "height": intr_color.height,  # Shared height
        "color_intrinsics": {
            "fx": intr_color.fx,
            "fy": intr_color.fy,
            "cx": intr_color.ppx,  # ppx corresponds to cx
            "cy": intr_color.ppy,  # ppy corresponds to cy
        },
        "depth_intrinsics": {
            "fx": intr_depth.fx,
            "fy": intr_depth.fy,
            "cx": intr_depth.ppx,  # ppx corresponds to cx
            "cy": intr_depth.ppy,  # ppy corresponds to cy
        },
        "extrinsics": extr.rotation + extr.translation,
    }

    with open(output_file, "w") as outfile:
        json.dump(data, outfile, indent=4)

    print(f"Saved intrinsics and extrinsics to {output_file}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate intrinsics info for all connected cameras."
    )
    parser.add_argument("--width", help="stream width", default=1280, type=int)
    parser.add_argument("--height", help="stream height", default=720, type=int)
    parser.add_argument("--fps", help="stream fps", default=30, type=int)
    args = parser.parse_args()
    return args


if __name__ == "__main__":
    args = parse_args()
    width = args.width
    height = args.height
    fps = args.fps

    PROJ_ROOT = Path(__file__).resolve().parents[1]

    try:
        c = rs.config()
        c.enable_stream(rs.stream.depth, width, height, rs.format.z16, fps)
        c.enable_stream(rs.stream.color, width, height, rs.format.rgb8, fps)
        device_manager = RealsenseDeviceManager(rs.context(), c)
        device_manager.enable_all_devices()
        for k in range(150):
            frames = device_manager.poll_frames()

        device_intrinsics = device_manager.get_device_intrinsics(frames)
        device_extrinsics = device_manager.get_depth_to_color_extrinsics(frames)

        for key, value in device_intrinsics.items():
            print(f"- camera: {key}...")
            serial = key
            intr_color = value[rs.stream.color]
            intr_depth = value[rs.stream.depth]
            extr = device_extrinsics[key]

            # Save to JSON
            output_file = PROJ_ROOT / f"camera_{serial}_calibration_info.json"
            save_intrinsics_json(serial, intr_color, intr_depth, extr, output_file)

    finally:
        device_manager.disable_streams()
