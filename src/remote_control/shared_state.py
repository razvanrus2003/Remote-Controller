from dataclasses import dataclass, field
import threading


@dataclass
class SharedRuntimeState:
    frame_lock: threading.Lock = field(default_factory=threading.Lock)
    frame_event: threading.Event = field(default_factory=threading.Event)
    latest_frame: bytes | None = None
    latest_frame_seq: int = 0
    latest_frame_received_at: float | None = None

    telemetry_lock: threading.Lock = field(default_factory=threading.Lock)
    latest_telemetry: str | None = None

    obstacle_lock: threading.Lock = field(default_factory=threading.Lock)
    latest_obstacle_state: dict = field(default_factory=lambda: {
        'status': 'unknown',
        'blocked': False,
        'confidence': 0.0,
        'reason': 'waiting for camera frames',
        'backend': 'unknown',
        'updated_at': None,
        'frame_age_sec': None,
        'stale': True,
    })

    depth_map_lock: threading.Lock = field(default_factory=threading.Lock)
    depth_event: threading.Event = field(default_factory=threading.Event)
    latest_depth_map_png: bytes | None = None
    latest_depth_map_jpeg: bytes | None = None
    latest_depth_map_seq: int = -1
    latest_depth_map_updated_at: float | None = None
    latest_depth_map_backend: str = 'unknown'

    health_lock: threading.Lock = field(default_factory=threading.Lock)
    last_health: str = 'health topic not published yet'
    last_health_received_at: float | None = None
