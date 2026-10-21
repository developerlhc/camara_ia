"""Interfaz de un solo clic para iniciar V380, YOLO y la grabación."""

from __future__ import annotations

import os
import socket
import subprocess
import time
import tkinter as tk
from pathlib import Path
from threading import Event, Thread
from tkinter import messagebox, ttk

from tools.v380_motion_recorder.recorder import MotionRecorder, RecorderConfig

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "grabaciones_v380"


def port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


class RecorderApp:
    def __init__(self, window: tk.Tk):
        self.window = window
        self.stop_event: Event | None = None
        self.worker: Thread | None = None
        self.bridge_process = None
        self.selected_confidence = 0.45
        self.status = tk.StringVar(value="Detenido")
        self.clip_count = tk.StringVar(value="0 clips guardados")
        self.confidence = tk.DoubleVar(value=0.45)

        window.title("Grabador V380 con YOLO")
        window.geometry("520x310")
        window.minsize(520, 310)
        window.protocol("WM_DELETE_WINDOW", self.close)
        frame = ttk.Frame(window, padding=24)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Grabador V380", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(
            frame,
            text="YOLO detecta personas y guarda automáticamente partes de 20 segundos.",
            wraplength=460,
        ).pack(anchor="w", pady=(4, 18))
        ttk.Label(frame, textvariable=self.status, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        ttk.Label(frame, textvariable=self.clip_count).pack(anchor="w", pady=(3, 15))
        options = ttk.Frame(frame)
        options.pack(fill="x")
        ttk.Label(options, text="Confianza YOLO").pack(side="left")
        ttk.Scale(options, from_=0.2, to=0.8, variable=self.confidence).pack(
            side="left", fill="x", expand=True, padx=12
        )
        buttons = ttk.Frame(frame)
        buttons.pack(fill="x", pady=(22, 0))
        self.start_button = ttk.Button(buttons, text="Iniciar grabación", command=self.start)
        self.start_button.pack(side="left")
        self.stop_button = ttk.Button(buttons, text="Detener", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=8)
        ttk.Button(buttons, text="Abrir grabaciones", command=self.open_output).pack(side="right")
        self.window.after(1000, self.refresh)

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status.set("Preparando cámara y modelo YOLO…")
        self.selected_confidence = float(self.confidence.get())
        self.stop_event = Event()
        self.worker = Thread(target=self._run, daemon=True)
        self.worker.start()

    def _run(self):
        try:
            if not port_open(8556):
                self._set_status("Iniciando automáticamente el puente V380…")
                flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                self.bridge_process = subprocess.Popen(
                    [
                        "powershell.exe",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        str(ROOT / "iniciar.ps1"),
                    ],
                    cwd=ROOT,
                    creationflags=flags,
                )
                deadline = time.monotonic() + 90
                while time.monotonic() < deadline and not self.stop_event.is_set():
                    if port_open(8556):
                        break
                    if self.bridge_process.poll() is not None:
                        raise RuntimeError("Vigilay Local terminó antes de publicar la cámara")
                    self.stop_event.wait(1)
                if not port_open(8556):
                    raise RuntimeError("El puente V380 no respondió en 90 segundos")
            if self.stop_event.is_set():
                return
            self._set_status("Grabando automáticamente · YOLO activo")
            config = RecorderConfig(
                source="rtsp://127.0.0.1:8556/live",
                output=OUTPUT,
                detector="yolo",
                model=ROOT / "yolo11n.pt",
                confidence=self.selected_confidence,
                max_clip=20,
                pre_roll=0,
                post_roll=2,
                fps=15,
            )
            MotionRecorder(config, self.stop_event).run()
        except Exception as exc:
            self._set_status("Error")
            message = str(exc)
            self.window.after(
                0, lambda detail=message: messagebox.showerror("Grabador V380", detail)
            )
        finally:
            self.window.after(0, self._stopped)

    def _set_status(self, value: str):
        self.window.after(0, self.status.set, value)

    def stop(self):
        self.status.set("Deteniendo…")
        if self.stop_event:
            self.stop_event.set()

    def _stopped(self):
        self.status.set("Detenido")
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def refresh(self):
        count = sum(1 for _ in OUTPUT.rglob("*.mp4")) if OUTPUT.exists() else 0
        self.clip_count.set(f"{count} clips guardados")
        self.window.after(1000, self.refresh)

    def open_output(self):
        OUTPUT.mkdir(parents=True, exist_ok=True)
        os.startfile(OUTPUT)

    def close(self):
        if self.stop_event:
            self.stop_event.set()
        self.window.destroy()


def main():
    window = tk.Tk()
    try:
        ttk.Style().theme_use("vista")
    except tk.TclError:
        pass
    RecorderApp(window)
    window.mainloop()


if __name__ == "__main__":
    main()
