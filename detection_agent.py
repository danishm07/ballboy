import time
import cv2
import numpy as np
import mss
import requests
import json
from ultralytics import YOLO
from dotenv import load_dotenv
import os

load_dotenv()

# Broadcast pitch landmarks -> normalized pitch coords (0=left/top, 1=right/bottom)
SRC_POINTS = np.float32([[180, 580], [880, 580], [50, 150], [960, 150]])
DST_POINTS = np.float32([[0, 1], [1, 1], [0, 0], [1, 0]])
PITCH_HOMOGRAPHY = cv2.getPerspectiveTransform(SRC_POINTS, DST_POINTS)

model = YOLO("football-players-detection-3zvbc/2/yolov8s.pt")


sct = mss.mss()
monitor = sct.monitors[1]
region = {
    "top": monitor["top"],
    "left": monitor["left"],
    "width": int(monitor["width"] * 0.7),
    "height": monitor["height"],
}

last_time = 0


def pixel_to_pitch(cx, cy):
    pt = np.array([[[cx, cy]]], dtype=np.float32)
    out = cv2.perspectiveTransform(pt, PITCH_HOMOGRAPHY)[0][0]
    return float(out[0]), float(out[1])


def detect_players():
    global last_time

    shot = sct.grab(region)
    frame = np.array(shot)[:, :, :3]  # BGRA -> BGR
    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)

    # Optional: downscale for faster inference
    # frame = cv2.resize(frame, (1280, 720))

    results = model.track(
        frame,
        persist=True,
        tracker="bytetrack.yaml",
        conf=0.2,
        iou=0.3,
        verbose=False,
        classes=[0],
        imgsz=640,
    )[0]

    players = []
    if results.boxes is not None:
        boxes = results.boxes.xyxy.cpu().numpy()
        confs = results.boxes.conf.cpu().numpy()
        ids = results.boxes.id
        ids = ids.int().cpu().numpy().tolist() if ids is not None else [None] * len(boxes)

        for (x1, y1, x2, y2), conf, tid in zip(boxes, confs, ids):
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            pitch_x, pitch_y = pixel_to_pitch(cx, cy)
            players.append({
                "id": tid,
                "x1": float(x1),
                "y1": float(y1),
                "x2": float(x2),
                "y2": float(y2),
                "x": pitch_x,
                "y": pitch_y,
                "confidence": float(conf),
            })

    current_time = time.time()
    fps = 1.0 / (current_time - last_time) if last_time > 0 else 0
    last_time = current_time

    payload = {
        "players": players,
        "total": len(players),
        "timestamp": current_time,
        "width": region["width"],
        "height": region["height"],
        "fps": round(fps, 1),
    }

    print(f"[detection] {len(players)} players detected | FPS: {fps:.1f}")
    return payload

def run():
    print("[detection] starting with YOLOv8n + ByteTrack...")
    while True:
        try:
            payload = detect_players()
            # Send detections to server via REST API
            try:
                with open("detections.json", "w") as f:
                    json.dump(payload, f)
            except Exception:
                pass  # Server might not be ready, continue
        except Exception as e:
            print(f"[detection] error: {e}")
        # No sleep - run as fast as possible for real-time

if __name__ == "__main__":
    run()