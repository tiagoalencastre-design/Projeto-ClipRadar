"""
Detecta a posição horizontal de um rosto (webcam do criador, por exemplo)
dentro do trecho de vídeo, pra usar no corte vertical em vez de sempre
cortar no centro fixo da tela.
"""
from __future__ import annotations

import subprocess


def detect_face_offset_fraction(video_path: str, start_seconds: float, end_seconds: float, samples: int = 3) -> float | None:
    try:
        import cv2
    except ImportError:
        return None

    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if face_cascade.empty():
        return None

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    duration = max(end_seconds - start_seconds, 0.1)
    x_fractions = []

    try:
        for i in range(samples):
            timestamp = start_seconds + duration * (i + 1) / (samples + 1)
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
            if len(faces) == 0:
                continue

            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            frame_width = frame.shape[1]
            x_fractions.append((x + w / 2) / frame_width)
    finally:
        cap.release()

    if not x_fractions:
        return None

    return sum(x_fractions) / len(x_fractions)


def detect_face_bbox_fraction(
    video_path: str, start_seconds: float, end_seconds: float, samples: int = 3
) -> tuple[float, float, float, float] | None:
    """
    Detecta a REGIÃO (não só a posição horizontal) do maior rosto encontrado,
    como frações do quadro (x, y, largura, altura, todos de 0.0 a 1.0) —
    usado pro layout "gameplay + facecam", pra recortar só a webcam do
    criador em vez do quadro inteiro.

    Retorna None se nenhum rosto for detectado em nenhuma das amostras — quem
    chamar isso DEVE cair de volta pro layout sem facecam nesse caso (nunca
    inventar uma região de rosto que não existe).
    """
    try:
        import cv2
    except ImportError:
        return None

    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if face_cascade.empty():
        return None

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None

    duration = max(end_seconds - start_seconds, 0.1)
    boxes = []

    try:
        for i in range(samples):
            timestamp = start_seconds + duration * (i + 1) / (samples + 1)
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60))
            if len(faces) == 0:
                continue

            x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
            fh, fw = frame.shape[0], frame.shape[1]
            boxes.append((x / fw, y / fh, w / fw, h / fh))
    finally:
        cap.release()

    if not boxes:
        return None

    n = len(boxes)
    avg_x = sum(b[0] for b in boxes) / n
    avg_y = sum(b[1] for b in boxes) / n
    avg_w = sum(b[2] for b in boxes) / n
    avg_h = sum(b[3] for b in boxes) / n
    return (avg_x, avg_y, avg_w, avg_h)


def build_face_aware_crop_filter(face_x_fraction: float | None, target_width_ratio: float = 9 / 16) -> str:
    if face_x_fraction is None:
        x_expr = "(iw-ih*9/16)/2"
    else:
        # As vírgulas dentro de max()/min() precisam ser escapadas com \,
        # porque o FFmpeg usa vírgula pra separar filtros diferentes numa
        # cadeia — sem escapar, ele quebra com "No such filter".
        x_expr = f"max(0\\,min(iw-ih*9/16\\,iw*{face_x_fraction:.4f}-ih*9/16/2))"

    return f"crop=ih*9/16:ih:{x_expr}:0,scale=1080:1920"