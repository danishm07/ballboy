"""
Ballboy Soccer Tracker - calibrated detection overlay
pip install ultralytics opencv-python numpy pillow PyQt5
python3 soccer_tracker.py
"""

import sys
import queue
import threading
import json
import time

import cv2
import numpy as np
from ultralytics import YOLO
from PyQt5.QtWidgets import QApplication, QWidget, QPushButton, QHBoxLayout
from PyQt5.QtCore import Qt, QTimer, QRect, QEvent
from PyQt5.QtGui import QPainter, QPen, QColor, QFont, QFontMetrics

CALIBRATION_FILE = "calibration.json"
DETECTIONS_FILE = "detections.json"
MODEL_PATH = "yolov8s.pt"


def grab_screen():
    from PIL import ImageGrab
    img = ImageGrab.grab()
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


def calibrate(frame):
    pts = []
    drag_pos = [None]
    win = "CALIBRATE | Click TOP-LEFT then BOTTOM-RIGHT of video | R=reset Enter=confirm"

    def on_mouse(event, x, y, flags, _):
        if event == cv2.EVENT_LBUTTONDOWN and len(pts) < 2:
            pts.append((x, y))
        elif event == cv2.EVENT_MOUSEMOVE:
            drag_pos[0] = (x, y)

    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, min(frame.shape[1], 1280), min(frame.shape[0], 720))
    cv2.setMouseCallback(win, on_mouse)

    while True:
        disp = frame.copy()
        if pts:
            cv2.circle(disp, pts[0], 8, (0, 255, 0), -1)
        if len(pts) == 1 and drag_pos[0]:
            cv2.rectangle(disp, pts[0], drag_pos[0], (0, 255, 0), 2)
        if len(pts) == 2:
            cv2.rectangle(disp, pts[0], pts[1], (0, 255, 0), 3)
            msg = "Press ENTER to confirm (R to reset)"
        else:
            step = "TOP-LEFT of the video player" if not pts else "BOTTOM-RIGHT of the video player"
            msg = f"Click the {step}"
        cv2.putText(disp, msg, (10, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 220, 255), 2)
        cv2.imshow(win, disp)

        key = cv2.waitKey(20) & 0xFF
        if key == ord('r'):
            pts.clear()
        elif key in (13, 10) and len(pts) == 2:
            break
        elif key == 27:
            cv2.destroyWindow(win)
            return None

    cv2.destroyWindow(win)
    x1 = min(pts[0][0], pts[1][0])
    y1 = min(pts[0][1], pts[1][1])
    x2 = max(pts[0][0], pts[1][0])
    y2 = max(pts[0][1], pts[1][1])
    return (x1, y1, x2, y2)


def get_calibration(force=False):
    if not force:
        try:
            with open(CALIBRATION_FILE) as f:
                d = json.load(f)
                box = (d["x1"], d["y1"], d["x2"], d["y2"])
                print(f"[tracker] Using saved calibration: {box}")
                return box
        except Exception:
            pass
    print("[tracker] Taking screenshot for calibration...")
    frame = grab_screen()
    box = calibrate(frame)
    if box:
        with open(CALIBRATION_FILE, "w") as f:
            json.dump({"x1": box[0], "y1": box[1], "x2": box[2], "y2": box[3]}, f)
    return box


class Overlay(QWidget):
    def __init__(self, x, y, w, h):
        super().__init__()
        self.setGeometry(x, y, w, h)
        # KEY FIX: BypassWindowManagerHint prevents macOS from hiding on focus change
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.BypassWindowManagerHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)
        self._boxes = []
        self.show()

    def event(self, e):
        # Block all activation events
        if e.type() in (QEvent.WindowActivate, QEvent.FocusIn, QEvent.Enter):
            return True
        return super().event(e)

    def update_boxes(self, boxes):
        self._boxes = boxes
        self.update()

    def reposition(self, x, y, w, h):
        self.setGeometry(x, y, w, h)

    def paintEvent(self, event):
        if not self._boxes:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        font = QFont('Arial', 9, QFont.Bold)
        painter.setFont(font)
        fm = QFontMetrics(font)

        for (x1, y1, x2, y2, label, rgb) in self._boxes:
            r, g, b = rgb
            qcol = QColor(r, g, b)
            painter.setPen(QPen(qcol, 2))
            painter.drawRect(x1, y1, x2 - x1, y2 - y1)

            tw = fm.boundingRect(label).width() + 6
            th = fm.height() + 2
            painter.fillRect(QRect(x1, max(y1 - th, 0), tw, th), qcol)
            painter.setPen(QPen(QColor(0, 0, 0)))
            painter.drawText(x1 + 3, max(y1 - 3, th - 2), label)


class ControlWindow(QWidget):
    def __init__(self, on_recalibrate, on_quit):
        super().__init__()
        self.setWindowTitle("Ballboy Tracker")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setFixedSize(240, 40)

        layout = QHBoxLayout()
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        recal_btn = QPushButton("Recalibrate (C)")
        quit_btn = QPushButton("Quit (Q)")
        recal_btn.clicked.connect(on_recalibrate)
        quit_btn.clicked.connect(on_quit)
        layout.addWidget(recal_btn)
        layout.addWidget(quit_btn)
        self.setLayout(layout)
        self.show()


class DetectionWorker(threading.Thread):
    def __init__(self, box_queue):
        super().__init__(daemon=True)
        self._q = box_queue
        self._stop = threading.Event()
        self._vbox = None
        self._vbox_lock = threading.Lock()
        self.model = None
        self._last_fps_time = time.time()
        self._frame_count = 0

    def set_video_box(self, vbox):
        with self._vbox_lock:
            self._vbox = vbox

    def stop(self):
        self._stop.set()

    def run(self):
        print("[tracker] Loading YOLO model...")
        self.model = YOLO(MODEL_PATH)
        print("[tracker] Model loaded.")

        from PIL import ImageGrab

        while not self._stop.is_set():
            with self._vbox_lock:
                vbox = self._vbox
            if vbox is None:
                continue

            vx1, vy1, vx2, vy2 = vbox
            img = ImageGrab.grab()
            frame = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
            crop = frame[vy1:vy2, vx1:vx2]

            if crop.size == 0:
                continue

            results = self.model(
                crop,
                classes=[0, 32],
                verbose=False,
                conf=0.25,
                imgsz=480
            )[0]

            boxes = []
            pipeline_players = []

            for i, det in enumerate(results.boxes):
                cls = int(det.cls)
                conf = float(det.conf)
                x1, y1, x2, y2 = map(int, det.xyxy[0])
                cx = (x1 + x2) / 2
                video_width = vx2 - vx1

                if cls == 0:
                    is_home = cx < video_width * 0.5
                    label = f"{conf:.2f}"
                    color = (255, 165, 0)
                    boxes.append((x1, y1, x2, y2, label, color))
                    pipeline_players.append({
                        "id": i,
                        "x1": float(x1), "y1": float(y1),
                        "x2": float(x2), "y2": float(y2),
                        "x": cx / video_width,
                        "y": (y1 + y2) / 2 / (vy2 - vy1),
                        "confidence": conf,
                        "team": "home" if is_home else "away"
                    })
                elif cls == 32:
                    boxes.append((x1, y1, x2, y2, "Ball", (0, 230, 230)))

            self._frame_count += 1
            now = time.time()
            elapsed = now - self._last_fps_time
            if elapsed >= 1.0:
                fps = self._frame_count / elapsed
                self._frame_count = 0
                self._last_fps_time = now
                print(f"[tracker] {len(pipeline_players)} players | FPS: {fps:.1f}")

            payload = {
                "players": pipeline_players,
                "total": len(pipeline_players),
                "timestamp": time.time(),
                "width": vx2 - vx1,
                "height": vy2 - vy1
            }
            try:
                with open(DETECTIONS_FILE, "w") as f:
                    json.dump(payload, f)
            except Exception:
                pass

            try:
                self._q.put_nowait(boxes)
            except queue.Full:
                pass


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--recalibrate", action="store_true")
    args = parser.parse_args()

    app = QApplication(sys.argv)
    ratio = app.primaryScreen().devicePixelRatio()

    box = get_calibration(force=args.recalibrate)
    if not box:
        print("[tracker] Cancelled.")
        return

    vx1, vy1, vx2, vy2 = box
    qx = int(vx1 / ratio)
    qy = int(vy1 / ratio)
    qw = int((vx2 - vx1) / ratio)
    qh = int((vy2 - vy1) / ratio)

    overlay = Overlay(qx, qy, qw, qh)

    box_queue = queue.Queue(maxsize=2)
    worker = DetectionWorker(box_queue)
    worker.set_video_box(box)
    worker.start()

    def do_recalibrate():
        worker.set_video_box(None)
        frame2 = grab_screen()
        new_box = calibrate(frame2)
        if new_box:
            with open(CALIBRATION_FILE, "w") as f:
                json.dump({"x1": new_box[0], "y1": new_box[1],
                          "x2": new_box[2], "y2": new_box[3]}, f)
            vx1, vy1, vx2, vy2 = new_box
            qx = int(vx1 / ratio)
            qy = int(vy1 / ratio)
            qw = int((vx2 - vx1) / ratio)
            qh = int((vy2 - vy1) / ratio)
            overlay.reposition(qx, qy, qw, qh)
            overlay.update_boxes([])
            worker.set_video_box(new_box)

    ctrl = ControlWindow(
        on_recalibrate=do_recalibrate,
        on_quit=QApplication.quit
    )

    def poll():
        try:
            boxes = box_queue.get_nowait()
            scaled = [
                (int(x1/ratio), int(y1/ratio),
                 int(x2/ratio), int(y2/ratio),
                 label, rgb)
                for (x1, y1, x2, y2, label, rgb) in boxes
            ]
            overlay.update_boxes(scaled)
        except queue.Empty:
            pass

    timer = QTimer()
    timer.timeout.connect(poll)
    timer.start(16)

    app.exec_()
    worker.stop()


if __name__ == "__main__":
    main()