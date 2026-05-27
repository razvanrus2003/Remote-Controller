import io
import logging
import os
import threading
import time
import pathlib
import subprocess
import sys

import numpy as np
from PIL import Image, ImageFilter, ImageOps, ImageStat

# Make ROS imports optional so the module can run in a non-ROS (custom venv) environment.
HAS_RCLPY = True
try:
    import rclpy
    from rclpy.node import Node
    from sensor_msgs.msg import CompressedImage
    from std_msgs.msg import String
except Exception:
    HAS_RCLPY = False
    Node = object
    # Define lightweight placeholders for message types so importing the module
    # doesn't fail; these won't be used in non-ROS mode.
    class CompressedImage:
        def __init__(self):
            self.format = ''
            self.data = b''

    class String:
        def __init__(self):
            self.data = ''
import json


def ensure_venv_python_has_onnxruntime():
    try:
        import onnxruntime  # noqa: F401
        return
    except Exception:
        pass

    search_roots = [pathlib.Path.cwd(), *pathlib.Path(__file__).resolve().parents]
    venv_python = None
    for parent in search_roots:
        for venv_name in ('.venv', 'venv'):
            candidate = parent / venv_name / 'bin' / 'python'
            if not candidate.exists():
                continue

            try:
                subprocess.run(
                    [str(candidate), '-c', 'import onnxruntime'],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                continue

            venv_python = candidate
            break
        if venv_python is not None:
            break

    if venv_python is None:
        raise RuntimeError(
            'onnxruntime is not available in the current interpreter or any local venv. '
            'Install it into the project venv with `pip install onnxruntime` before launching.'
        )

    current_python = pathlib.Path(sys.executable).resolve()
    if current_python == venv_python.resolve():
        return

    os.execv(str(venv_python), [str(venv_python), *sys.argv])


try:
    from ament_index_python.packages import get_package_share_directory
except Exception:
    get_package_share_directory = None

try:
    ensure_venv_python_has_onnxruntime()
    import onnxruntime as ort
except Exception:
    ort = None

# If running as a script and ROS isn't available, provide a minimal local-mode
# entrypoint that verifies ONNX runtime and exits gracefully. This lets users
# execute the module inside a custom virtualenv without needing ROS installed.
def _run_local_mode():
    print('Running remote_control.video_ml in local (non-ROS) mode')
    if ort is None:
        print('onnxruntime not available. Call ensure_venv_python_has_onnxruntime() or install onnxruntime into the venv.')
        try:
            ensure_venv_python_has_onnxruntime()
        except Exception as e:
            print('Failed to locate onnxruntime in local venvs:', e)
            raise
    print('onnxruntime is available. Exiting (no ROS runtime requested).')


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

RESAMPLE_BILINEAR = getattr(getattr(Image, 'Resampling', Image), 'BILINEAR', Image.BILINEAR)


class VideoMlNode(Node):
    def __init__(self):
        super().__init__('remote_video_ml')
        self.obstacle_detection_interval_sec = 0.2
        # backend selection: 'midas' (default), 'fast', or 'heuristic'
        self.depth_backend = os.environ.get('DEPTH_BACKEND', 'fast').strip().lower()

        # configurable boxes via env vars: 'x1,y1,x2,y2' (normalized 0..1)
        def _parse_box_env(name, default):
            val = os.environ.get(name)
            if not val:
                return default
            try:
                parts = [float(x) for x in val.split(',')]
                if len(parts) == 4:
                    return tuple(parts)
            except Exception:
                pass
            return default

        # Default floor box: narrower vertical span (smaller height)
        self.floor_box = _parse_box_env('DEPTH_FLOOR_BOX', (0.45, 0.80, 0.55, 0.95))
        self.obstacle_box = _parse_box_env('DEPTH_OBSTACLE_BOX', (0.40, 0.45, 0.60, 0.65))
        # preview formats: comma separated list of 'png' and/or 'jpeg'
        self.depth_preview_formats = [s.strip().lower() for s in os.environ.get('DEPTH_PREVIEW_FORMAT', 'jpeg').split(',') if s.strip()]
        self.depth_preview_quality = int(os.environ.get('DEPTH_PREVIEW_QUALITY', '40'))
        self.depth_session = None
        self.camera_topic = os.environ.get('CAMERA_TOPIC', '/camera/image/compressed')

        self.image_subscription = self.create_subscription(
            CompressedImage,
            self.camera_topic,
            self.handle_image,
            1,
        )

        # Publisher for depth map previews (compressed)
        self.depth_publisher = self.create_publisher(
            CompressedImage,
            '/depth_map/image/compressed',
            1,
        )
        # Publisher for obstacle analysis results (JSON string)
        self.obstacle_publisher = self.create_publisher(
            String,
            '/obstacle',
            1,
        )

        self._init_depth_model()

        # runtime-local shared state (replaces previous shared_state module)
        self.frame_lock = threading.Lock()
        self.latest_frame = None
        self.latest_frame_seq = 0
        self.latest_frame_received_at = None

        self.endpoint_frame_lock = threading.Lock()
        self.latest_frame_endpoint = None
        self.latest_frame_endpoint_seq = 0
        self.latest_frame_endpoint_received_at = None

        self.frame_event = threading.Event()

        self.obstacle_lock = threading.Lock()
        self.latest_obstacle_state = None

        self.depth_map_lock = threading.Lock()
        self.latest_depth_map_png = None
        self.latest_depth_map_jpeg = None
        self.latest_depth_map_seq = 0
        self.latest_depth_map_updated_at = None
        self.latest_depth_map_backend = None
        self.depth_event = threading.Event()

        self.obstacle_detector_thread = threading.Thread(target=self._obstacle_detection_loop, daemon=True)
        self.obstacle_detector_thread.start()

    def _init_depth_model(self):
        if self.depth_backend == 'fast':
            # Attempt to load a fast pretrained depth ONNX if provided
            if ort is None:
                raise RuntimeError('onnxruntime not available for fast backend')

            env_path = os.environ.get('FAST_DEPTH_ONNX_PATH')
            share_path = None
            if get_package_share_directory is not None:
                try:
                    share_path = os.path.join(
                        get_package_share_directory('remote_control'),
                        'models',
                        'fast_depth.onnx',
                    )
                except Exception:
                    share_path = None

            source_root_path = os.path.abspath(
                os.path.join(os.path.dirname(__file__), '..', '..', 'models', 'fast_depth.onnx')
            )
            cwd_path = os.path.abspath(os.path.join(os.getcwd(), 'models', 'fast_depth.onnx'))

            candidates = []
            if env_path:
                candidates.append(os.path.abspath(env_path))
            if share_path:
                candidates.append(share_path)
            candidates.append(source_root_path)
            candidates.append(cwd_path)

            model_path = None
            for candidate in candidates:
                if os.path.exists(candidate):
                    model_path = candidate
                    break

            if model_path is None:
                self.get_logger().info('Fast depth ONNX not found; fast backend will use proxy algorithm')
                self.fast_session = None
                return

            sess_options = ort.SessionOptions()
            try:
                available_providers = ort.get_available_providers()
            except Exception:
                available_providers = []

            providers = []
            if 'CUDAExecutionProvider' in available_providers:
                providers.append('CUDAExecutionProvider')
            if 'TensorrtExecutionProvider' in available_providers:
                providers.append('TensorrtExecutionProvider')
            if 'CPUExecutionProvider' in available_providers:
                providers.append('CPUExecutionProvider')

            if providers:
                self.fast_session = ort.InferenceSession(model_path, sess_options, providers=providers)
            else:
                self.fast_session = ort.InferenceSession(model_path, sess_options)

            try:
                used = self.fast_session.get_providers()
            except Exception:
                used = available_providers

            self.get_logger().info(f'Loaded fast depth ONNX model from {model_path} using providers: {used}')
            return

        # default: midas
        if ort is None:
            raise RuntimeError('onnxruntime not available')

        env_path = os.environ.get('DEPTH_ONNX_PATH')
        share_path = None
        if get_package_share_directory is not None:
            try:
                share_path = os.path.join(
                    get_package_share_directory('remote_control'),
                    'models',
                    'midas_small.onnx',
                )
            except Exception as e:
                self.get_logger().warning(f'Could not resolve package share directory: {e}')

        source_root_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), '..', '..', 'models', 'midas_small.onnx')
        )
        cwd_path = os.path.abspath(os.path.join(os.getcwd(), 'models', 'midas_small.onnx'))

        candidates = []
        if env_path:
            candidates.append(os.path.abspath(env_path))
        if share_path:
            candidates.append(share_path)
        candidates.append(source_root_path)
        candidates.append(cwd_path)

        model_path = None
        for candidate in candidates:
            if os.path.exists(candidate):
                model_path = candidate
                break

        if model_path is None:
            raise FileNotFoundError(
                f"MiDaS ONNX model not found. Tried: {candidates}.\n"
                "Install the package, keep models/midas_small.onnx in the repo root, or set DEPTH_ONNX_PATH."
            )

        sess_options = ort.SessionOptions()
        try:
            available_providers = ort.get_available_providers()
        except Exception:
            available_providers = []

        providers = []
        # Prefer GPU providers if available: CUDA -> TensorRT -> CPU
        if 'CUDAExecutionProvider' in available_providers:
            providers.append('CUDAExecutionProvider')
        if 'TensorrtExecutionProvider' in available_providers:
            providers.append('TensorrtExecutionProvider')
        # Always keep CPU as a fallback
        if 'CPUExecutionProvider' in available_providers:
            providers.append('CPUExecutionProvider')

        if providers:
            self.depth_session = ort.InferenceSession(model_path, sess_options, providers=providers)
        else:
            # let onnxruntime pick defaults
            self.depth_session = ort.InferenceSession(model_path, sess_options)

        try:
            used = self.depth_session.get_providers()
        except Exception:
            used = available_providers

        self.get_logger().info(f'Loaded depth ONNX model from {model_path} using providers: {used}')

    def handle_image(self, msg: CompressedImage):
        try:
            frame_bytes = bytes(msg.data)
            now = time.monotonic()
            # Update processing buffer (seq increment happens here)
            with self.frame_lock:
                seq = self.latest_frame_seq + 1
                self.latest_frame = frame_bytes
                self.latest_frame_seq = seq
                self.latest_frame_received_at = now

            # Update endpoint buffer separately to avoid contention with processing
            with self.endpoint_frame_lock:
                # keep endpoint seq in sync with processing seq
                self.latest_frame_endpoint = frame_bytes
                self.latest_frame_endpoint_seq = seq
                self.latest_frame_endpoint_received_at = now
                # if paired with a command node in the same process, update its view too
                try:
                    cmd = getattr(self, 'command_node', None)
                    if cmd is not None:
                        try:
                            with cmd.endpoint_frame_lock:
                                cmd.latest_frame_endpoint_received_at = now
                        except Exception:
                            pass
                except Exception:
                    pass

            # Signal new frame (event is thread-safe)
            try:
                self.frame_event.set()
            except Exception:
                pass
        except Exception as e:
            self.get_logger().warning(f'Failed to handle incoming image: {e}')

    def _obstacle_detection_loop(self):
        last_processed_seq = -1

        while rclpy.ok():
            # Wait until a new frame arrives or timeout elapses. Using the event
            # reduces latency because we wake immediately when `handle_image` sets it.
            self.frame_event.wait(timeout=self.obstacle_detection_interval_sec)

            with self.frame_lock:
                frame_bytes = self.latest_frame
                frame_seq = self.latest_frame_seq
                frame_received_at = self.latest_frame_received_at
                # clear the event now that we've read the latest frame
                try:
                    self.frame_event.clear()
                except Exception:
                    pass

            if frame_bytes is None or frame_seq == last_processed_seq:
                continue

            last_processed_seq = frame_seq

            try:
                if self.depth_backend == 'midas' and self.depth_session is not None:
                    state, depth_preview_png, depth_preview_jpeg = self._analyze_frame_with_onnx(
                        frame_bytes,
                        frame_received_at,
                    )
                elif self.depth_backend == 'fast':
                    # prefer onnx fast session if available
                    if getattr(self, 'fast_session', None) is not None:
                        state, depth_preview_png, depth_preview_jpeg = self._analyze_frame_with_fast_onnx(
                            frame_bytes,
                            frame_received_at,
                        )
                    else:
                        state, depth_preview_png, depth_preview_jpeg = self._analyze_frame_with_fast(
                        frame_bytes,
                        frame_received_at,
                    )
                else:
                    state, depth_preview_png, depth_preview_jpeg = self._analyze_frame_for_obstacles(
                        frame_bytes,
                        frame_received_at,
                    )
            except Exception as e:
                state = {
                    'status': 'unknown',
                    'blocked': False,
                    'confidence': 0.0,
                    'reason': f'analysis failed: {e}',
                    'backend': 'unknown',
                    'updated_at': time.time(),
                    'frame_age_sec': None,
                    'stale': False,
                }
                depth_preview_png = None
                depth_preview_jpeg = None

            with self.obstacle_lock:
                self.latest_obstacle_state = state
            # Publish obstacle analysis as JSON on dedicated topic
            try:
                msg = String()
                # ensure JSON is serializable (state was built from primitives)
                msg.data = json.dumps(state)
                self.obstacle_publisher.publish(msg)
            except Exception as e:
                try:
                    self.get_logger().warning(f'Failed to publish obstacle state: {e}')
                except Exception:
                    pass

            if depth_preview_png is not None or depth_preview_jpeg is not None:
                with self.depth_map_lock:
                    self.latest_depth_map_png = depth_preview_png
                    self.latest_depth_map_jpeg = depth_preview_jpeg
                    self.latest_depth_map_seq = frame_seq
                    self.latest_depth_map_updated_at = time.time()
                    self.latest_depth_map_backend = state.get('backend', 'unknown')
                    self.depth_event.set()
                # Publish compressed depth preview on dedicated topic
                try:
                    img_bytes = depth_preview_jpeg if depth_preview_jpeg is not None else depth_preview_png
                    if img_bytes is not None:
                        comp = CompressedImage()
                        comp.format = 'jpeg' if depth_preview_jpeg is not None else 'png'
                        comp.data = bytearray(img_bytes)
                        try:
                            comp.header.stamp = self.get_clock().now().to_msg()
                        except Exception:
                            pass
                        self.depth_publisher.publish(comp)
                except Exception as e:
                    try:
                        self.get_logger().warning(f'Failed to publish depth map: {e}')
                    except Exception:
                        pass


    def _analyze_frame_for_obstacles(self, frame_bytes, frame_received_at):
        image = Image.open(io.BytesIO(frame_bytes)).convert('L')
        image = image.resize((160, 90), RESAMPLE_BILINEAR)

        width, height = image.size
        roi = image.crop((int(width * 0.2), int(height * 0.35), int(width * 0.8), int(height * 0.95)))
        roi_edges = roi.filter(ImageFilter.FIND_EDGES)

        roi_stats = ImageStat.Stat(roi)
        edge_stats = ImageStat.Stat(roi_edges)

        roi_mean = float(roi_stats.mean[0])
        roi_stddev = float(roi_stats.stddev[0])
        edge_mean = float(edge_stats.mean[0])

        edge_score = max(0.0, (14.0 - edge_mean) / 14.0)
        texture_score = max(0.0, (18.0 - roi_stddev) / 18.0)
        brightness_score = 0.0
        if roi_mean < 55.0:
            brightness_score = min(1.0, (55.0 - roi_mean) / 55.0)
        elif roi_mean > 205.0:
            brightness_score = min(1.0, (roi_mean - 205.0) / 50.0)

        confidence = min(1.0, (edge_score * 0.45) + (texture_score * 0.4) + (brightness_score * 0.15))
        blocked = confidence >= 0.55

        if blocked:
            reason = 'low-texture central view consistent with a wall or close obstacle'
            status = 'blocked'
        else:
            reason = 'visual texture in front of the robot is still sufficient for movement'
            status = 'clear'

        frame_age_sec = None
        if frame_received_at is not None:
            frame_age_sec = round(time.monotonic() - frame_received_at, 3)

        depth_preview_gray = ImageOps.autocontrast(image.filter(ImageFilter.GaussianBlur(radius=1.5)))
        depth_preview_rgb = ImageOps.colorize(depth_preview_gray, black='#081229', white='#f6f7fb')

        depth_preview_png = None
        depth_preview_jpeg = None
        if 'png' in self.depth_preview_formats:
            depth_preview_png_buffer = io.BytesIO()
            depth_preview_rgb.save(depth_preview_png_buffer, format='PNG')
            depth_preview_png = depth_preview_png_buffer.getvalue()
        if 'jpeg' in self.depth_preview_formats or 'jpg' in self.depth_preview_formats:
            depth_preview_jpeg_buffer = io.BytesIO()
            depth_preview_rgb.save(depth_preview_jpeg_buffer, format='JPEG', quality=self.depth_preview_quality)
            depth_preview_jpeg = depth_preview_jpeg_buffer.getvalue()

        return {
            'status': status,
            'blocked': blocked,
            'confidence': round(confidence, 3),
            'reason': reason,
            'backend': 'heuristic',
            'updated_at': time.time(),
            'frame_age_sec': frame_age_sec,
            'stale': False,
            'metrics': {
                'roi_mean': round(roi_mean, 3),
                'roi_stddev': round(roi_stddev, 3),
                'edge_mean': round(edge_mean, 3),
            },
        }, depth_preview_png, depth_preview_jpeg

    def _stats_for_box(self, arr, box):
        h, w = arr.shape[:2]
        x1, y1, x2, y2 = box
        # normalized coords (0..1) -> pixels
        if max(box) <= 1.0:
            x1 = int(x1 * w); x2 = int(x2 * w)
            y1 = int(y1 * h); y2 = int(y2 * h)
        else:
            x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
        # clamp
        x1 = max(0, min(w - 1, x1)); x2 = max(0, min(w, x2))
        y1 = max(0, min(h - 1, y1)); y2 = max(0, min(h, y2))
        if y2 <= y1 or x2 <= x1:
            return {'count': 0, 'median': None, 'mean': None, 'p25': None, 'p75': None}
        crop = arr[y1:y2, x1:x2]
        vals = crop[np.isfinite(crop)]
        if vals.size == 0:
            return {'count': 0, 'median': None, 'mean': None, 'p25': None, 'p75': None}
        return {
            'count': int(vals.size),
            'median': float(np.nanmedian(vals)),
            'mean': float(np.nanmean(vals)),
            'p25': float(np.percentile(vals, 25)),
            'p75': float(np.percentile(vals, 75)),
        }

    def _analyze_frame_with_onnx(self, frame_bytes, frame_received_at):
        img = Image.open(io.BytesIO(frame_bytes)).convert('RGB')
        input_shape = self.depth_session.get_inputs()[0].shape
        # input_shape may contain symbolic names like 'batch_size' which are
        # not convertible to int. Safely extract height/width from last two
        # dimensions with fallbacks.
        try:
            raw_h = input_shape[-2]
        except Exception:
            raw_h = None
        try:
            raw_w = input_shape[-1]
        except Exception:
            raw_w = None
        try:
            h = int(raw_h) if raw_h is not None else 256
        except Exception:
            h = 256
        try:
            w = int(raw_w) if raw_w is not None else 256
        except Exception:
            w = 256
        img_resized = img.resize((w, h), RESAMPLE_BILINEAR)

        img_np = np.asarray(img_resized, dtype=np.float32) / 255.0
        img_np = np.transpose(img_np, (2, 0, 1))[None, :, :, :]
        img_np = np.ascontiguousarray(img_np)

        ort_inputs = {self.depth_session.get_inputs()[0].name: img_np}
        t0 = time.monotonic()
        ort_outs = self.depth_session.run(None, ort_inputs)
        t_infer = time.monotonic() - t0
        try:
            # Use debug level to avoid blocking on INFO logs during fast loops
            self.get_logger().debug(f'ONNX inference time: {t_infer:.3f}s')
        except Exception:
            pass
        depth_map = np.asarray(ort_outs[0])
        depth_map = np.squeeze(depth_map)

        if depth_map.ndim != 2:
            raise ValueError(f'Unexpected depth output shape: {depth_map.shape}')

        valid_depth = depth_map[np.isfinite(depth_map)]
        if valid_depth.size == 0:
            raise ValueError('ONNX output contains no finite values')

        depth_low = float(np.percentile(valid_depth, 5.0))
        depth_high = float(np.percentile(valid_depth, 95.0))
        if depth_high <= depth_low:
            raise ValueError(
                f'Unable to normalize ONNX output: low={depth_low:.3f} high={depth_high:.3f}'
            )

        orientation = os.environ.get('DEPTH_ORIENTATION', 'higher_is_nearer').strip().lower()
        higher_is_nearer = orientation != 'lower_is_nearer'

        depth_img = Image.fromarray(depth_map).resize(img.size, Image.Resampling.BILINEAR)
        width, height = img.size
        roi_box = (int(width * 0.3), int(height * 0.45), int(width * 0.7), int(height * 0.95))
        depth_roi = np.array(depth_img.crop(roi_box)).astype(np.float32)

        depth_norm = np.clip((depth_map - depth_low) / (depth_high - depth_low), 0.0, 1.0)
        if not higher_is_nearer:
            depth_norm = 1.0 - depth_norm

        depth_norm_img = Image.fromarray(depth_norm.astype(np.float32)).resize(
            img.size,
            Image.Resampling.BILINEAR,
        )
        depth_norm_roi = np.array(depth_norm_img.crop(roi_box)).astype(np.float32)

        # Compare two center zones: lower (floor reference) and upper-center (possible obstacle)
        depth_norm_resized = np.array(depth_norm_img).astype(np.float32)
        # If image was converted to 8-bit, rescale back to 0..1
        try:
            if depth_norm_resized.max() > 1.1:
                depth_norm_resized = depth_norm_resized / 255.0
        except Exception:
            pass

        def _stats_for_box(arr, box):
            h, w = arr.shape[:2]
            x1, y1, x2, y2 = box
            # normalized coords (0..1) -> pixels
            if max(box) <= 1.0:
                x1 = int(x1 * w); x2 = int(x2 * w)
                y1 = int(y1 * h); y2 = int(y2 * h)
            else:
                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
            # clamp
            x1 = max(0, min(w - 1, x1)); x2 = max(0, min(w, x2))
            y1 = max(0, min(h - 1, y1)); y2 = max(0, min(h, y2))
            if y2 <= y1 or x2 <= x1:
                return {'count': 0, 'median': None, 'mean': None, 'p25': None, 'p75': None}
            crop = arr[y1:y2, x1:x2]
            vals = crop[np.isfinite(crop)]
            if vals.size == 0:
                return {'count': 0, 'median': None, 'mean': None, 'p25': None, 'p75': None}
            return {
                'count': int(vals.size),
                'median': float(np.nanmedian(vals)),
                'mean': float(np.nanmean(vals)),
                'p25': float(np.percentile(vals, 25)),
                'p75': float(np.percentile(vals, 75)),
            }

        # Tunable boxes (normalized): use env-configured boxes if present
        stats_floor = self._stats_for_box(depth_norm_resized, self.floor_box)
        stats_obstacle = self._stats_for_box(depth_norm_resized, self.obstacle_box)

        eps = 1e-6
        if stats_floor['median'] is None or stats_obstacle['median'] is None:
            median_diff = None
            median_ratio = None
        else:
            # positive diff means obstacle zone is nearer when higher_is_nearer
            median_diff = stats_obstacle['median'] - stats_floor['median']
            median_ratio = (stats_obstacle['median'] + eps) / (stats_floor['median'] + eps)

        depth_preview = Image.fromarray((depth_norm * 255.0).astype(np.uint8), mode='L')

        depth_preview_png = None
        depth_preview_jpeg = None
        if 'png' in self.depth_preview_formats:
            depth_preview_png_buffer = io.BytesIO()
            depth_preview.save(depth_preview_png_buffer, format='PNG')
            depth_preview_png = depth_preview_png_buffer.getvalue()
        if 'jpeg' in self.depth_preview_formats or 'jpg' in self.depth_preview_formats:
            depth_preview_jpeg_buffer = io.BytesIO()
            depth_preview.save(depth_preview_jpeg_buffer, format='JPEG', quality=self.depth_preview_quality)
            depth_preview_jpeg = depth_preview_jpeg_buffer.getvalue()

        median_depth_raw = float(np.nanmedian(depth_roi))
        median_near_score = float(np.nanmedian(depth_norm_roi))
        block_thresh = float(os.environ.get('DEPTH_BLOCK_SCORE_THRESHOLD', '0.65'))

        # Decide blocking using obstacle-zone median threshold (default 0.5)
        obs_med_thresh = float(os.environ.get('DEPTH_OBS_MEDIAN_THRESHOLD', '0.5'))

        if stats_obstacle.get('median') is not None:
            zone_median_obs = float(stats_obstacle['median'])
            zone_median_floor = None if stats_floor.get('median') is None else float(stats_floor['median'])

            if higher_is_nearer:
                blocked = zone_median_obs >= obs_med_thresh
                # confidence: how far above the threshold (0..1)
                if zone_median_obs <= obs_med_thresh:
                    conf = 0.0
                else:
                    conf = (zone_median_obs - obs_med_thresh) / (1.0 - obs_med_thresh)
            else:
                blocked = zone_median_obs <= obs_med_thresh
                if zone_median_obs >= obs_med_thresh:
                    conf = 0.0
                else:
                    conf = (obs_med_thresh - zone_median_obs) / max(1e-6, obs_med_thresh)

            confidence = max(0.0, min(1.0, conf))

            # Additional rule: if floor median is very low (no floor detected), treat as blocked
            floor_min_thresh = float(os.environ.get('DEPTH_FLOOR_MEDIAN_MIN', '0.70'))
            if zone_median_floor is not None and zone_median_floor < floor_min_thresh:
                # stronger blocking signal when floor missing
                floor_conf = min(1.0, (floor_min_thresh - zone_median_floor) / max(1e-6, floor_min_thresh))
                confidence = max(confidence, floor_conf)
                blocked = True
                reason = (
                    f'floor_missing: floor_median={zone_median_floor:.3f} '
                    f'floor_min_thresh={floor_min_thresh:.3f} '
                    f'obstacle_median={zone_median_obs:.3f} orientation={orientation}'
                )
            else:
                reason = (
                    f'obstacle_zone_median={zone_median_obs:.3f} '
                    f'floor_median={zone_median_floor} thresh={obs_med_thresh:.3f} '
                    f'orientation={orientation}'
                )

            status = 'blocked' if blocked else 'clear'
        else:
            # Fallback to original near-score behavior
            confidence = max(0.0, min(1.0, median_near_score))
            blocked = median_near_score >= block_thresh

            reason = (
                f'raw_median={median_depth_raw:.2f} '
                f'near_score={median_near_score:.3f} threshold={block_thresh:.3f} '
                f'orientation={orientation}'
            )
            status = 'blocked' if blocked else 'clear'

        frame_age_sec = None
        if frame_received_at is not None:
            frame_age_sec = round(time.monotonic() - frame_received_at, 3)

        return {
            'status': status,
            'blocked': bool(blocked),
            'confidence': round(confidence, 3),
            'reason': reason,
            'backend': 'midas_onnx',
            'updated_at': time.time(),
            'frame_age_sec': frame_age_sec,
            'stale': False,
            'metrics': {
                'median_depth_raw': round(median_depth_raw, 3),
                'near_score': round(median_near_score, 3),
                'depth_p5': round(depth_low, 3),
                'depth_p95': round(depth_high, 3),
                'floor_median': None if stats_floor.get('median') is None else round(stats_floor['median'], 3),
                'obstacle_median': None if stats_obstacle.get('median') is None else round(stats_obstacle['median'], 3),
                'floor_count': int(stats_floor.get('count', 0)),
                'obstacle_count': int(stats_obstacle.get('count', 0)),
                'floor_p25': None if stats_floor.get('p25') is None else round(stats_floor['p25'], 3),
                'floor_p75': None if stats_floor.get('p75') is None else round(stats_floor['p75'], 3),
                'obstacle_p25': None if stats_obstacle.get('p25') is None else round(stats_obstacle['p25'], 3),
                'obstacle_p75': None if stats_obstacle.get('p75') is None else round(stats_obstacle['p75'], 3),
                'median_diff': None if median_diff is None else round(median_diff, 3),
                'median_ratio': None if median_ratio is None else round(median_ratio, 3),
            },
        }, depth_preview_png, depth_preview_jpeg

    def _analyze_frame_with_fast(self, frame_bytes, frame_received_at):
        """
        Fast, approximate monocular depth proxy using local variance and blur.
        Returns the same shape of outputs as the MiDaS analyzer but computed quickly.
        """
        img = Image.open(io.BytesIO(frame_bytes)).convert('L')
        # operate at low resolution for speed
        # small = img.resize((64, 64), RESAMPLE_BILINEAR)

        arr = np.asarray(img).astype(np.float32)
        # local variance via gaussian blur subtraction
        blurred = np.asarray(Image.fromarray(arr).filter(ImageFilter.GaussianBlur(radius=2.0))).astype(np.float32)
        var = np.clip((arr - blurred), -255, 255)
        # map variance to 0..1 (higher variance -> nearer proxy)
        var_norm = (var - var.min()) / max(1e-6, (var.max() - var.min()))

        # resize back to original image size
        var_img = Image.fromarray((var_norm * 255.0).astype(np.uint8)).resize(img.size, Image.Resampling.BILINEAR)
        depth_norm = np.asarray(var_img).astype(np.float32) / 255.0

        # orientation handling same as depth config
        orientation = os.environ.get('DEPTH_ORIENTATION', 'higher_is_nearer').strip().lower()
        higher_is_nearer = orientation != 'lower_is_nearer'
        if not higher_is_nearer:
            depth_norm = 1.0 - depth_norm

        depth_norm_img = Image.fromarray((depth_norm * 255.0).astype(np.uint8), mode='L')

        width, height = img.size
        # compute ROIs using configured boxes
        roi_box = (int(width * 0.3), int(height * 0.45), int(width * 0.7), int(height * 0.95))
        depth_roi = np.array(depth_norm_img.crop(roi_box)).astype(np.float32)

        depth_preview = depth_norm_img

        depth_preview_png = None
        depth_preview_jpeg = None
        if 'png' in self.depth_preview_formats:
            buf = io.BytesIO()
            depth_preview.save(buf, format='PNG')
            depth_preview_png = buf.getvalue()
        if 'jpeg' in self.depth_preview_formats or 'jpg' in self.depth_preview_formats:
            buf = io.BytesIO()
            depth_preview.save(buf, format='JPEG', quality=self.depth_preview_quality)
            depth_preview_jpeg = buf.getvalue()

        median_depth_raw = float(np.nanmedian(depth_roi))
        median_near_score = float(np.nanmedian(depth_roi))

        # compute zone stats using configured boxes
        depth_norm_resized = depth_norm
        stats_floor = self._stats_for_box(depth_norm_resized, self.floor_box)
        stats_obstacle = self._stats_for_box(depth_norm_resized, self.obstacle_box)
        eps = 1e-6
        if stats_floor['median'] is None or stats_obstacle['median'] is None:
            median_diff = None
            median_ratio = None
        else:
            median_diff = stats_obstacle['median'] - stats_floor['median']
            median_ratio = (stats_obstacle['median'] + eps) / (stats_floor['median'] + eps)

        # thresholds and orientation handling (same defaults as MiDaS path)
        orientation = os.environ.get('DEPTH_ORIENTATION', 'higher_is_nearer').strip().lower()
        higher_is_nearer = orientation != 'lower_is_nearer'

        obs_med_thresh = float(os.environ.get('DEPTH_OBS_MEDIAN_THRESHOLD', '0.5'))

        if stats_obstacle.get('median') is not None:
            zone_median_obs = float(stats_obstacle['median'])
            zone_median_floor = None if stats_floor.get('median') is None else float(stats_floor['median'])

            if higher_is_nearer:
                blocked = zone_median_obs >= obs_med_thresh
                if zone_median_obs <= obs_med_thresh:
                    conf = 0.0
                else:
                    conf = (zone_median_obs - obs_med_thresh) / (1.0 - obs_med_thresh)
            else:
                blocked = zone_median_obs <= obs_med_thresh
                if zone_median_obs >= obs_med_thresh:
                    conf = 0.0
                else:
                    conf = (obs_med_thresh - zone_median_obs) / max(1e-6, obs_med_thresh)

            confidence = max(0.0, min(1.0, conf))

            # floor-missing rule
            floor_min_thresh = float(os.environ.get('DEPTH_FLOOR_MEDIAN_MIN', '0.70'))
            if zone_median_floor is not None and zone_median_floor < floor_min_thresh:
                floor_conf = min(1.0, (floor_min_thresh - zone_median_floor) / max(1e-6, floor_min_thresh))
                confidence = max(confidence, floor_conf)
                blocked = True
                reason = (
                    f'floor_missing: floor_median={zone_median_floor:.3f} '
                    f'floor_min_thresh={floor_min_thresh:.3f} '
                    f'obstacle_median={zone_median_obs:.3f} orientation={orientation}'
                )
            else:
                reason = (
                    f'obstacle_zone_median={zone_median_obs:.3f} '
                    f'floor_median={zone_median_floor} thresh={obs_med_thresh:.3f} '
                    f'orientation={orientation}'
                )

            status = 'blocked' if blocked else 'clear'
        else:
            # fallback to raw near score
            confidence = max(0.0, min(1.0, median_near_score))
            blocked = median_near_score >= float(os.environ.get('DEPTH_BLOCK_SCORE_THRESHOLD', '0.65'))
            reason = 'fast_depth_proxy'
            status = 'blocked' if blocked else 'clear'

        frame_age_sec = None
        if frame_received_at is not None:
            frame_age_sec = round(time.monotonic() - frame_received_at, 3)

        return {
            'status': status,
            'blocked': bool(blocked),
            'confidence': round(float(np.clip(confidence, 0.0, 1.0)), 3),
            'reason': reason,
            'backend': 'fast_proxy',
            'updated_at': time.time(),
            'frame_age_sec': frame_age_sec,
            'stale': False,
            'metrics': {
                'median_depth_raw': round(median_depth_raw, 3),
                'near_score': round(median_near_score, 3),
                'floor_median': None if stats_floor.get('median') is None else round(stats_floor['median'], 3),
                'obstacle_median': None if stats_obstacle.get('median') is None else round(stats_obstacle['median'], 3),
                'floor_count': int(stats_floor.get('count', 0)),
                'obstacle_count': int(stats_obstacle.get('count', 0)),
                'median_diff': None if median_diff is None else round(median_diff, 3),
                'median_ratio': None if median_ratio is None else round(median_ratio, 3),
            },
        }, depth_preview_png, depth_preview_jpeg

    def _analyze_frame_with_fast_onnx(self, frame_bytes, frame_received_at):
        # Run a pretrained fast-depth ONNX model (best-effort interface)
        img = Image.open(io.BytesIO(frame_bytes)).convert('RGB')
        input_shape = self.fast_session.get_inputs()[0].shape
        # See comment in _analyze_frame_with_onnx: handle symbolic dims safely
        try:
            raw_h = input_shape[-2]
        except Exception:
            raw_h = None
        try:
            raw_w = input_shape[-1]
        except Exception:
            raw_w = None
        try:
            h = int(raw_h) if raw_h is not None else 256
        except Exception:
            h = 256
        try:
            w = int(raw_w) if raw_w is not None else 256
        except Exception:
            w = 256
        img_resized = img.resize((w, h), RESAMPLE_BILINEAR)

        img_np = np.asarray(img_resized, dtype=np.float32) / 255.0
        img_np = np.transpose(img_np, (2, 0, 1))[None, :, :, :]
        img_np = np.ascontiguousarray(img_np)

        ort_inputs = {self.fast_session.get_inputs()[0].name: img_np}
        t0 = time.monotonic()
        ort_outs = self.fast_session.run(None, ort_inputs)
        t_infer = time.monotonic() - t0
        try:
            self.get_logger().debug(f'Fast-ONNX inference time: {t_infer:.3f}s')
        except Exception:
            pass

        depth_map = np.asarray(ort_outs[0])
        depth_map = np.squeeze(depth_map)

        if depth_map.ndim != 2:
            # try first channel if shape is HxWxC
            if depth_map.ndim == 3 and depth_map.shape[2] == 1:
                depth_map = depth_map[:, :, 0]
            else:
                raise ValueError(f'Unexpected fast-depth output shape: {depth_map.shape}')

        valid_depth = depth_map[np.isfinite(depth_map)]
        if valid_depth.size == 0:
            raise ValueError('fast-depth output contains no finite values')

        depth_low = float(np.percentile(valid_depth, 5.0))
        depth_high = float(np.percentile(valid_depth, 95.0))
        if depth_high <= depth_low:
            raise ValueError('Unable to normalize fast-depth output')

        orientation = os.environ.get('DEPTH_ORIENTATION', 'higher_is_nearer').strip().lower()
        higher_is_nearer = orientation != 'lower_is_nearer'

        depth_norm = np.clip((depth_map - depth_low) / (depth_high - depth_low), 0.0, 1.0)
        if not higher_is_nearer:
            depth_norm = 1.0 - depth_norm

        depth_norm_img = Image.fromarray((depth_norm * 255.0).astype(np.uint8)).resize(
            img.size,
            Image.Resampling.BILINEAR,
        )

        width, height = img.size
        roi_box = (int(width * 0.3), int(height * 0.45), int(width * 0.7), int(height * 0.95))
        depth_roi = np.array(depth_norm_img.crop(roi_box)).astype(np.float32)

        depth_preview = depth_norm_img

        depth_preview_png = None
        depth_preview_jpeg = None
        if 'png' in self.depth_preview_formats:
            buf = io.BytesIO()
            depth_preview.save(buf, format='PNG')
            depth_preview_png = buf.getvalue()
        if 'jpeg' in self.depth_preview_formats or 'jpg' in self.depth_preview_formats:
            buf = io.BytesIO()
            depth_preview.save(buf, format='JPEG', quality=self.depth_preview_quality)
            depth_preview_jpeg = buf.getvalue()

        median_depth_raw = float(np.nanmedian(depth_roi))
        median_near_score = float(np.nanmedian(depth_roi))

        depth_norm_resized = depth_norm
        stats_floor = self._stats_for_box(depth_norm_resized, self.floor_box)
        stats_obstacle = self._stats_for_box(depth_norm_resized, self.obstacle_box)

        eps = 1e-6
        if stats_floor['median'] is None or stats_obstacle['median'] is None:
            median_diff = None
            median_ratio = None
        else:
            median_diff = stats_obstacle['median'] - stats_floor['median']
            median_ratio = (stats_obstacle['median'] + eps) / (stats_floor['median'] + eps)

        orientation = os.environ.get('DEPTH_ORIENTATION', 'higher_is_nearer').strip().lower()
        higher_is_nearer = orientation != 'lower_is_nearer'

        obs_med_thresh = float(os.environ.get('DEPTH_OBS_MEDIAN_THRESHOLD', '0.5'))

        if stats_obstacle.get('median') is not None:
            zone_median_obs = float(stats_obstacle['median'])
            zone_median_floor = None if stats_floor.get('median') is None else float(stats_floor['median'])

            if higher_is_nearer:
                blocked = zone_median_obs >= obs_med_thresh
                if zone_median_obs <= obs_med_thresh:
                    conf = 0.0
                else:
                    conf = (zone_median_obs - obs_med_thresh) / (1.0 - obs_med_thresh)
            else:
                blocked = zone_median_obs <= obs_med_thresh
                if zone_median_obs >= obs_med_thresh:
                    conf = 0.0
                else:
                    conf = (obs_med_thresh - zone_median_obs) / max(1e-6, obs_med_thresh)

            confidence = max(0.0, min(1.0, conf))

            floor_min_thresh = float(os.environ.get('DEPTH_FLOOR_MEDIAN_MIN', '0.70'))
            if zone_median_floor is not None and zone_median_floor < floor_min_thresh:
                floor_conf = min(1.0, (floor_min_thresh - zone_median_floor) / max(1e-6, floor_min_thresh))
                confidence = max(confidence, floor_conf)
                blocked = True
                reason = (
                    f'floor_missing: floor_median={zone_median_floor:.3f} '
                    f'floor_min_thresh={floor_min_thresh:.3f} '
                    f'obstacle_median={zone_median_obs:.3f} orientation={orientation}'
                )
            else:
                reason = (
                    f'obstacle_zone_median={zone_median_obs:.3f} '
                    f'floor_median={zone_median_floor} thresh={obs_med_thresh:.3f} '
                    f'orientation={orientation}'
                )

            status = 'blocked' if blocked else 'clear'
        else:
            confidence = max(0.0, min(1.0, median_near_score))
            blocked = median_near_score >= float(os.environ.get('DEPTH_BLOCK_SCORE_THRESHOLD', '0.65'))
            reason = 'fast_depth_onnx'
            status = 'blocked' if blocked else 'clear'

        frame_age_sec = None
        if frame_received_at is not None:
            frame_age_sec = round(time.monotonic() - frame_received_at, 3)

        return {
            'status': status,
            'blocked': bool(blocked),
            'confidence': round(float(np.clip(confidence, 0.0, 1.0)), 3),
            'reason': reason,
            'backend': 'fast_onnx',
            'updated_at': time.time(),
            'frame_age_sec': frame_age_sec,
            'stale': False,
            'metrics': {
                'median_depth_raw': round(median_depth_raw, 3),
                'near_score': round(median_near_score, 3),
                'floor_median': None if stats_floor.get('median') is None else round(stats_floor['median'], 3),
                'obstacle_median': None if stats_obstacle.get('median') is None else round(stats_obstacle['median'], 3),
                'floor_count': int(stats_floor.get('count', 0)),
                'obstacle_count': int(stats_obstacle.get('count', 0)),
                'median_diff': None if median_diff is None else round(median_diff, 3),
                'median_ratio': None if median_ratio is None else round(median_ratio, 3),
            },
        }, depth_preview_png, depth_preview_jpeg


def main(args=None):
    rclpy.init(args=args)
    
    node = VideoMlNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
