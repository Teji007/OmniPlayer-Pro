import os
import sys
import site

# HF_TOKEN is intentionally not embedded in source. Set it in the environment if needed.

# --- AGGRESSIVE PORTABLE CUDA DLL LOADER ---
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    os.environ["PATH"] = sys._MEIPASS + os.pathsep + os.environ.get("PATH", "")
    if hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(sys._MEIPASS)
else:
    try:
        site_paths = site.getsitepackages() if hasattr(site, 'getsitepackages') else []
        site_paths.append(os.path.join(sys.prefix, 'Lib', 'site-packages'))
        for site_pkg in set(site_paths):
            nvidia_path = os.path.join(site_pkg, "nvidia")
            if os.path.exists(nvidia_path):
                for root, dirs, files in os.walk(nvidia_path):
                    if root.endswith("bin") and any(f.endswith('.dll') for f in files):
                        os.environ["PATH"] = root + os.pathsep + os.environ.get("PATH", "")
                        if hasattr(os, 'add_dll_directory'):
                            os.add_dll_directory(root)
    except Exception:
        pass
# --------------------------------

import time
import json
import random
import urllib.parse
import urllib.request
import subprocess
import threading
import socket
import mimetypes
import urllib.parse
import hashlib
import ctypes
import math
import http.server
import socketserver

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QSlider, QLabel, QFileDialog, QMessageBox, QFrame, QInputDialog, QLineEdit,
    QComboBox, QDockWidget, QTextEdit, QMenu, QListWidget, QListWidgetItem,
    QTabWidget, QSpinBox, QColorDialog, QFontDialog, QCheckBox, QGroupBox,
    QRadioButton, QButtonGroup, QSplitter, QToolBar, QStatusBar, QProgressBar,
    QDialog, QGridLayout, QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy
)
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from PyQt6.QtMultimediaWidgets import QVideoWidget
from PyQt6.QtCore import (
    Qt, QUrl, QThread, pyqtSignal, pyqtSlot, QTimer, QDateTime, QPoint, QEvent,
    QBuffer, QByteArray, QIODevice, QSettings, QSize, QRect, QPropertyAnimation,
    QEasingCurve, QStandardPaths
)
from PyQt6.QtGui import (
    QPixmap, QImage, QFont, QColor, QPalette, QAction, QKeySequence,
    QDesktopServices, QIcon, QPainter, QPen, QBrush, QTransform
)

# Cross-platform window hiding for subprocesses
CREATE_NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0x08000000)

# --- CORE EXTENSIONS & AI IMPORTS ---
try:
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio
    import numpy as np
    AI_AVAILABLE = True
except ImportError:
    AI_AVAILABLE = False

try:
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.exceptions import InvalidTag
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

try:
    import yt_dlp
    YTDLP_AVAILABLE = True
except ImportError:
    YTDLP_AVAILABLE = False

try:
    from pypresence import Presence
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False

try:
    import speech_recognition as sr
    VOICE_AVAILABLE = True
except ImportError:
    VOICE_AVAILABLE = False

# PyChromecast is optional. Keep the real import exception so the UI can
# distinguish 'not installed' from 'installed but dependency/import broken'.
try:
    import pychromecast
    CAST_AVAILABLE = True
    CAST_IMPORT_ERROR = None
except Exception as _cast_import_error:
    pychromecast = None
    CAST_AVAILABLE = False
    CAST_IMPORT_ERROR = _cast_import_error


def _load_pychromecast():
    """Load PyChromecast using the same Python interpreter running OmniPlayer.

    This avoids false 'not installed' messages when pychromecast was installed
    into a different Python environment, and preserves the actual import error
    when a dependency such as zeroconf is broken/missing.
    """
    global pychromecast, CAST_AVAILABLE, CAST_IMPORT_ERROR
    if pychromecast is not None:
        CAST_AVAILABLE = True
        CAST_IMPORT_ERROR = None
        return pychromecast
    try:
        import importlib
        pychromecast = importlib.import_module('pychromecast')
        CAST_AVAILABLE = True
        CAST_IMPORT_ERROR = None
        return pychromecast
    except Exception as exc:
        CAST_AVAILABLE = False
        CAST_IMPORT_ERROR = exc
        return None

try:
    import pynvml
    NVML_AVAILABLE = True
except ImportError:
    NVML_AVAILABLE = False


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)


# =============================================================================
# CUSTOM VIDEO, SLIDER & VISUALIZER WIDGETS
# =============================================================================
class TimelineSlider(QSlider):
    seekRequested = pyqtSignal(int)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            ratio = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
            val = int(self.minimum() + ratio * (self.maximum() - self.minimum()))
            self.setValue(val)
            self._drag_value = val
            self.sliderPressed.emit()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            ratio = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
            val = int(self.minimum() + ratio * (self.maximum() - self.minimum()))
            self.setValue(val)
            self._drag_value = val
            self.sliderMoved.emit(val)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            ratio = max(0.0, min(1.0, event.position().x() / max(1, self.width())))
            val = int(self.minimum() + ratio * (self.maximum() - self.minimum()))
            self.setValue(val)
            self.seekRequested.emit(val)
            self.sliderReleased.emit()
            event.accept()
        else:
            super().mouseReleaseEvent(event)


class ClickableVideoWidget(QVideoWidget):
    singleClicked = pyqtSignal()
    doubleClicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._emit_single)

    def mousePressEvent(self, event):
        # Ignore right clicks here so context menu handles them natively
        if event.button() == Qt.MouseButton.LeftButton:
            if not self._timer.isActive():
                self._timer.start(250)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._timer.stop()
            self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)

    def _emit_single(self):
        self.singleClicked.emit()


class AudioVisualizerWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.bars = 32
        self.values = [0.0] * self.bars
        self.target_values = [0.0] * self.bars
        self.is_active = False
        self.setFixedHeight(45)

    def update_visualizer(self, is_playing):
        self.is_active = is_playing
        for i in range(self.bars):
            if self.is_active:
                self.target_values[i] = random.uniform(0.1, 1.0)
            else:
                self.target_values[i] = 0.0
            self.values[i] += (self.target_values[i] - self.values[i]) * 0.35
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width() / self.bars
        h = self.height()
        for i, val in enumerate(self.values):
            bar_height = val * (h - 8)
            x = i * w + 2
            y = h - bar_height - 4
            color = QColor.fromHsv((i * 9) % 360, 210, 240, 210)
            painter.setBrush(QBrush(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(int(x), int(y), max(2, int(w - 4)), int(bar_height), 3, 3)


# =============================================================================
# BACKGROUND TASK WORKERS
# =============================================================================
class FFmpegWorker(QThread):
    status_update = pyqtSignal(str, str)

    def __init__(self, cmd, task_name):
        super().__init__()
        self.cmd = cmd
        self.task_name = task_name
        self.process = None
        self.is_cancelled = False

    def run(self):
        try:
            self.process = subprocess.Popen(self.cmd, creationflags=CREATE_NO_WINDOW)
            self.process.wait()
            if self.is_cancelled:
                self.status_update.emit(f"{self.task_name} cancelled.", "#E74C3C")
            elif self.process.returncode == 0:
                self.status_update.emit(f"{self.task_name} finished successfully.", "#2ECC71")
            else:
                self.status_update.emit(f"{self.task_name} failed. Check console for details.", "#E74C3C")
        except Exception as e:
            self.status_update.emit(f"Error: {e}", "#E74C3C")

    def stop(self):
        self.is_cancelled = True
        if self.process:
            try:
                self.process.terminate()
                self.process.kill()
            except Exception:
                pass


class ESRGANWorker(QThread):
    progress_update = pyqtSignal(int)
    status_update = pyqtSignal(str, str)

    def __init__(self, media_path, exe_path):
        super().__init__()
        self.media_path = media_path
        self.exe_path = exe_path
        self.process = None
        self.is_cancelled = False

    def run(self):
        out_path = self.media_path.rsplit('.', 1)[0] + "_4K.mp4"
        temp_dir = os.path.join(os.path.expanduser("~"), "Desktop", "Omni_Temp_Frames")
        out_frames = os.path.join(os.path.expanduser("~"), "Desktop", "Omni_Out_Frames")

        try:
            os.makedirs(temp_dir, exist_ok=True)
            os.makedirs(out_frames, exist_ok=True)

            self.status_update.emit("Step 1/3: Extracting video frames...", "#F39C12")
            self.process = subprocess.Popen(["ffmpeg", "-y", "-i", self.media_path, "-qscale:v", "2", "-vsync", "0", f"{temp_dir}/frame_%08d.jpg"], creationflags=CREATE_NO_WINDOW)
            self.process.wait()
            if self.is_cancelled:
                raise Exception("Cancelled")
            
            self.status_update.emit("Step 2/3: Upscaling frames (Heavy Load)...", "#F39C12")
            self.process = subprocess.Popen(
                [self.exe_path, "-i", temp_dir, "-o", out_frames, "-n", "realesrgan-x4plus", "-f", "jpg"], 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True, 
                creationflags=CREATE_NO_WINDOW
            )
            
            for line in self.process.stdout:
                if self.is_cancelled:
                    raise Exception("Cancelled")
                if "%" in line:
                    try:
                        pct_str = "".join([c for c in line if c.isdigit() or c == '.'])
                        if pct_str:
                            self.progress_update.emit(int(float(pct_str)))
                    except Exception:
                        pass
            self.process.wait()
            if self.is_cancelled:
                raise Exception("Cancelled")

            self.progress_update.emit(0)
            self.status_update.emit("Step 3/3: Stitching 4K video and merging audio...", "#F39C12")
            self.process = subprocess.Popen(["ffmpeg", "-y", "-i", f"{out_frames}/frame_%08d.jpg", "-i", self.media_path, "-map", "0:v", "-map", "1:a?", "-c:a", "copy", "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", out_path], creationflags=CREATE_NO_WINDOW)
            self.process.wait()
            if self.is_cancelled:
                raise Exception("Cancelled")

            self.progress_update.emit(100)
            self.status_update.emit(f"4K Upscale Finished: {os.path.basename(out_path)}", "#2ECC71")

        except Exception as e:
            msg = str(e)
            if msg == "Cancelled":
                self.status_update.emit("Real-ESRGAN task cancelled by user.", "#E74C3C")
            else:
                self.status_update.emit(f"Real-ESRGAN Pipeline failed: {msg}", "#E74C3C")
        finally:
            import shutil
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass
            try:
                shutil.rmtree(out_frames)
            except Exception:
                pass

    def stop(self):
        self.is_cancelled = True
        if self.process:
            try:
                self.process.terminate()
                self.process.kill()
            except Exception:
                pass


class DemucsWorker(QThread):
    status_update = pyqtSignal(str, str)

    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath
        self.process = None
        self.is_cancelled = False

    def run(self):
        self.status_update.emit("Demucs AI: Analyzing and isolating audio stems...", "#9B59B6")
        out_dir = os.path.join(os.path.expanduser("~"), "Desktop", "Omni_Stems")
        os.makedirs(out_dir, exist_ok=True)
        
        cmd = ["python", "-m", "demucs.separate", "-n", "htdemucs_ft", "-o", out_dir, self.filepath]
        try:
            self.process = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW)
            self.process.wait()
            if self.is_cancelled:
                self.status_update.emit("Demucs task cancelled.", "#E74C3C")
            elif self.process.returncode == 0:
                self.status_update.emit("Stem Separation Complete in Desktop/Omni_Stems", "#2ECC71")
            else:
                self.status_update.emit("Demucs Failed. Ensure torch and demucs are installed.", "#E74C3C")
        except Exception as e:
            self.status_update.emit(f"Demucs Error: {e}", "#E74C3C")

    def stop(self):
        self.is_cancelled = True
        if self.process:
            try:
                self.process.terminate()
                self.process.kill()
            except Exception:
                pass


class WhisperWorker(QThread):
    status_update = pyqtSignal(str, str)
    segment_ready = pyqtSignal(float, float, str, str)
    all_subs_finished = pyqtSignal(int)

    def __init__(self, filepath, start_sec=0.0, display_mode=0, language=None):
        super().__init__()
        self.filepath = filepath
        self.start_sec = start_sec
        self.display_mode = display_mode
        self.language = language
        self.is_running = True

    def run(self):
        if not AI_AVAILABLE:
            self.status_update.emit("Error: faster-whisper or numpy is not installed.", "#E74C3C")
            return
        try:
            local_models_dir = resource_path("models")
            model_target = local_models_dir if os.path.exists(local_models_dir) and any(f.endswith('.bin') for f in os.listdir(local_models_dir)) else "medium"
            cores = os.cpu_count() or 4

            self.status_update.emit(f"Loading Whisper Engine from [{os.path.basename(str(model_target))}]...", "#9B59B6")

            try:
                model = WhisperModel(model_target, device="cuda", compute_type="float16", download_root="./models")
                self.status_update.emit("AI Engine running on GPU (CUDA Direct).", "#2ECC71")
            except Exception:
                self.status_update.emit("GPU unavailable. Switching to CPU acceleration...", "#F39C12")
                try:
                    model = WhisperModel(model_target, device="cpu", compute_type="int8", cpu_threads=cores, download_root="./models")
                except Exception:
                    model = WhisperModel(model_target, device="cpu", compute_type="float32", cpu_threads=cores, download_root="./models")

            if not self.is_running:
                return

            self.status_update.emit(f"Decoding audio from {int(self.start_sec)}s mark...", "#F39C12")
            full_audio = decode_audio(self.filepath, sampling_rate=16000)
            start_sample = int(self.start_sec * 16000)
            audio_data = full_audio[start_sample:]

            if self.display_mode in [1, 2]:
                task_type = "translate" if self.display_mode == 2 else "transcribe"
                self.status_update.emit(f"Streaming AI Subtitles ({task_type})...", "#3498DB")
                
                segments_gen, _ = model.transcribe(
                    audio_data, beam_size=5, condition_on_previous_text=False,
                    vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500),
                    word_timestamps=True, language=self.language, task=task_type
                )
                count = 0
                for segment in segments_gen:
                    if not self.is_running:
                        break
                    text = segment.text.strip()
                    if text:
                        count += 1
                        true_end = segment.words[-1].end if (hasattr(segment, 'words') and segment.words) else segment.end
                        abs_start = segment.start + self.start_sec
                        abs_end = true_end + self.start_sec

                        if self.display_mode == 2:
                            self.segment_ready.emit(abs_start, abs_end, "", text)
                        else:
                            self.segment_ready.emit(abs_start, abs_end, text, "")
                        self.status_update.emit(f"AI Cue [{int(abs_start)}s]: {text[:35]}...", "#2ECC71")

                if self.is_running:
                    self.all_subs_finished.emit(count)
                    self.status_update.emit(f"Transcription complete: {count} cues generated.", "#2ECC71")

            else:
                self.status_update.emit("Dual-Subs requested. Buffering translation pass (This takes 2x longer)...", "#F39C12")
                translated_dict = {}
                
                trans_segs, info = model.transcribe(audio_data, beam_size=3, task="translate", vad_filter=True)
                if info.language != "en":
                    for t_seg in trans_segs:
                        if not self.is_running:
                            return
                        translated_dict[round(t_seg.start, 1)] = t_seg.text.strip()
                
                self.status_update.emit("Translation complete. Streaming native synchronization...", "#3498DB")
                segments_gen, _ = model.transcribe(
                    audio_data, beam_size=5, condition_on_previous_text=False,
                    vad_filter=True, vad_parameters=dict(min_silence_duration_ms=500),
                    word_timestamps=True, language=self.language, task="transcribe"
                )
                
                count = 0
                for segment in segments_gen:
                    if not self.is_running:
                        break
                    text = segment.text.strip()
                    if text:
                        count += 1
                        true_end = segment.words[-1].end if (hasattr(segment, 'words') and segment.words) else segment.end
                        abs_start = segment.start + self.start_sec
                        abs_end = true_end + self.start_sec

                        translated_text = ""
                        rounded_s = round(segment.start, 1)
                        if rounded_s in translated_dict:
                            translated_text = translated_dict[rounded_s]
                        elif translated_dict:
                            closest_time = min(translated_dict.keys(), key=lambda k: abs(k - segment.start))
                            if abs(closest_time - segment.start) < 2.0:
                                translated_text = translated_dict[closest_time]

                        self.segment_ready.emit(abs_start, abs_end, text, translated_text)
                        self.status_update.emit(f"AI Cue [{int(abs_start)}s]: {text[:35]}...", "#2ECC71")

                if self.is_running:
                    self.all_subs_finished.emit(count)
                    self.status_update.emit(f"Dual-Transcription complete: {count} cues generated.", "#2ECC71")

        except Exception as e:
            self.status_update.emit(f"AI Error: {str(e)}", "#E74C3C")

    def stop(self):
        self.is_running = False


class VoiceControlWorker(QThread):
    command_detected = pyqtSignal(str)
    status_update = pyqtSignal(str, str)

    def __init__(self):
        super().__init__()
        self.is_running = True

    def run(self):
        if not VOICE_AVAILABLE:
            self.status_update.emit("Voice Control: SpeechRecognition package not installed.", "#E74C3C")
            return

        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 300
        recognizer.dynamic_energy_threshold = True
        self.status_update.emit("Voice Control: Active. Say 'Play', 'Pause', 'Mute', 'Louder', etc.", "#2ECC71")

        while self.is_running:
            try:
                with sr.Microphone() as source:
                    recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    audio = recognizer.listen(source, phrase_time_limit=3, timeout=5)

                phrase = recognizer.recognize_google(audio).lower().strip()
                self.status_update.emit(f"Voice Heard: '{phrase}'", "#3498DB")

                if "play" in phrase or "resume" in phrase:
                    self.command_detected.emit("play")
                elif "pause" in phrase or "freeze" in phrase:
                    self.command_detected.emit("pause")
                elif "stop" in phrase:
                    self.command_detected.emit("stop")
                elif "louder" in phrase or "volume up" in phrase:
                    self.command_detected.emit("volume_up")
                elif "quieter" in phrase or "volume down" in phrase:
                    self.command_detected.emit("volume_down")
                elif "mute" in phrase or "silence" in phrase:
                    self.command_detected.emit("mute")
                elif "fullscreen" in phrase:
                    self.command_detected.emit("fullscreen")
                elif "next" in phrase or "skip" in phrase:
                    self.command_detected.emit("next")
            except sr.WaitTimeoutError:
                continue
            except Exception:
                pass

    def stop(self):
        self.is_running = False


class HardwareTelemetryWorker(QThread):
    telemetry_update = pyqtSignal(dict)

    def __init__(self):
        super().__init__()
        self.is_running = True
        self.gpu_handle = None
        if NVML_AVAILABLE:
            try:
                pynvml.nvmlInit()
                self.gpu_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            except Exception:
                self.gpu_handle = None

    def run(self):
        while self.is_running:
            data = {}
            if self.gpu_handle:
                try:
                    mem_info = pynvml.nvmlDeviceGetMemoryInfo(self.gpu_handle)
                    temp = pynvml.nvmlDeviceGetTemperature(self.gpu_handle, pynvml.NVML_TEMPERATURE_GPU)
                    util = pynvml.nvmlDeviceGetUtilizationRates(self.gpu_handle)
                    data['vram_used'] = mem_info.used / (1024**2)
                    data['vram_total'] = mem_info.total / (1024**2)
                    data['gpu_temp'] = temp
                    data['gpu_util'] = util.gpu
                except Exception:
                    pass
            self.telemetry_update.emit(data)
            time.sleep(2)

    def stop(self):
        self.is_running = False
        if NVML_AVAILABLE:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass


class TMDBWorker(QThread):
    metadata_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, filename, api_key=""):
        super().__init__()
        self.filename = filename
        self.api_key = api_key

    def run(self):
        clean_query = urllib.parse.quote(self.filename.replace(".", " ").replace("_", " "))
        
        if self.api_key:
            try:
                url = f"https://api.themoviedb.org/3/search/movie?api_key={self.api_key}&query={clean_query}"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=5) as response:
                    data = json.loads(response.read().decode())
                if data.get('results'):
                    movie = data['results'][0]
                    title = movie.get('title', 'Unknown')
                    release = movie.get('release_date', 'N/A')[:4]
                    rating = movie.get('vote_average', 'N/A')
                    overview = movie.get('overview', 'No plot available.')
                    html = f"<h2>{title} ({release})</h2><p><b>TMDB Rating:</b> ⭐ {rating}/10</p><p><b>Plot Summary:</b><br>{overview}</p>"
                    self.metadata_ready.emit(html)
                    return
            except Exception:
                pass

        try:
            url = f"https://api.tvmaze.com/singlesearch/shows?q={clean_query}"
            req = urllib.request.Request(url, headers={'User-Agent': 'OmniPlayer/19.1'})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode())
            name = data.get('name', 'Unknown')
            summary = data.get('summary', 'No overview available.').replace('<p>', '').replace('</p>', '').replace('<b>', '').replace('</b>', '')
            premiered = data.get('premiered', 'N/A')
            rating = data.get('rating', {}).get('average', 'N/A')
            genres = ", ".join(data.get('genres', []))
            html = f"<h2>{name} ({premiered[:4]})</h2><p><b>Rating:</b> ⭐ {rating}/10 | <b>Genres:</b> {genres}</p><p><b>Plot Summary:</b><br>{summary}</p>"
            self.metadata_ready.emit(html)
        except Exception as e:
            self.error_occurred.emit("No movie or series match found.")


class DLNAServerWorker(QThread):
    status_update = pyqtSignal(str, str)

    def __init__(self, directory, port=8000):
        super().__init__()
        self.directory = directory
        self.port = port
        self.httpd = None

    def run(self):
        try:
            handler = http.server.SimpleHTTPRequestHandler
            os.chdir(self.directory)
            self.httpd = socketserver.TCPServer(("", self.port), handler)
            self.status_update.emit(f"DLNA/HTTP Local Server Live at http://localhost:{self.port}", "#2ECC71")
            self.httpd.serve_forever()
        except Exception as e:
            self.status_update.emit(f"Server Stopped/Error: {e}", "#E74C3C")

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()


# =============================================================================
# DIALOGS
# =============================================================================
class EqualizerDialog(QDialog):
    def __init__(self, parent=None, current_eq=None, current_preamp=2.0):
        super().__init__(parent)
        self.setWindowTitle("10-Band EQ & Amplifier (FFmpeg DSP)")
        self.setFixedSize(560, 320)
        self.setStyleSheet("background-color: #1a1a1a; color: white;")

        self.bands = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
        self.sliders = []

        layout = QVBoxLayout(self)
        grid = QGridLayout()

        self.preamp_slider = QSlider(Qt.Orientation.Vertical)
        self.preamp_slider.setRange(10, 500)
        self.preamp_slider.setValue(int(current_preamp * 100))
        self.preamp_slider.setStyleSheet("QSlider::handle:vertical { background: #E74C3C; }")

        grid.addWidget(QLabel("PreAmp\nVol %"), 0, 0, alignment=Qt.AlignmentFlag.AlignCenter)
        grid.addWidget(self.preamp_slider, 1, 0, alignment=Qt.AlignmentFlag.AlignCenter)

        for i, freq in enumerate(self.bands, start=1):
            slider = QSlider(Qt.Orientation.Vertical)
            slider.setRange(-20, 20)
            slider.setValue(int(current_eq[i-1]) if (current_eq and len(current_eq) >= i) else 0)
            self.sliders.append(slider)

            label = f"{freq}Hz" if freq < 1000 else f"{freq//1000}kHz"
            grid.addWidget(QLabel(label), 0, i, alignment=Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(slider, 1, i, alignment=Qt.AlignmentFlag.AlignCenter)

        layout.addLayout(grid)

        btn_apply = QPushButton("Apply EQ & Remaster Audio")
        btn_apply.setStyleSheet("background-color: #2ECC71; color: black; padding: 10px; font-weight: bold; border-radius: 5px;")
        btn_apply.clicked.connect(self.accept)
        layout.addWidget(btn_apply)

    def get_values(self):
        eq_vals = [s.value() for s in self.sliders]
        preamp = self.preamp_slider.value() / 100.0
        return eq_vals, preamp


class TrimDialog(QDialog):
    def __init__(self, max_duration_sec, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Lossless Stream Trimmer (FFmpeg)")
        self.setFixedSize(360, 180)
        self.setStyleSheet("background-color: #1a1a1a; color: white;")

        layout = QVBoxLayout(self)
        grid = QGridLayout()

        grid.addWidget(QLabel("Start Time (s):"), 0, 0)
        self.spin_start = QSpinBox()
        self.spin_start.setRange(0, int(max_duration_sec))
        grid.addWidget(self.spin_start, 0, 1)

        grid.addWidget(QLabel("Duration (s):"), 1, 0)
        self.spin_dur = QSpinBox()
        self.spin_dur.setRange(1, int(max_duration_sec))
        self.spin_dur.setValue(min(30, int(max_duration_sec)))
        grid.addWidget(self.spin_dur, 1, 1)

        layout.addLayout(grid)

        btn_trim = QPushButton("Execute Lossless Cut")
        btn_trim.setStyleSheet("background-color: #3498DB; color: white; padding: 8px; font-weight: bold;")
        btn_trim.clicked.connect(self.accept)
        layout.addWidget(btn_trim)

    def get_range(self):
        return self.spin_start.value(), self.spin_dur.value()


# =============================================================================
# MAIN APPLICATION
# =============================================================================
class OmniPlayerPro(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OmniPlayer Pro | Ultimate Edition")
        self.resize(1400, 920)
        self.setMinimumSize(1020, 640)
        self.setStyleSheet("background-color: #0d0d0d; color: white;")
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # ---- Core State ----
        self.current_media = None
        self.is_video = False
        self.is_seeking = False
        self.is_pip_mode = False
        self.controls_visible = True
        self.is_fullscreen = False
        self.normal_geometry = None
        self.accent_color = "#3498DB"
        self.tmdb_api_key = ""

        self.generated_subs = []
        self.bookmarks = []
        self.playlist = []
        self.playlist_index = -1
        self.shuffle_mode = False
        self.repeat_mode = 0
        self.resume_data = {}
        self.hw_stats = {}

        self.sub_delay_ms = 0
        self.sub_font_size = 22
        self.sub_color = "#F1C40F"
        self.sub_background = False
        self.playback_speed = 1.0
        self.audio_equalizer = [0.0] * 10
        self.current_preamp = 2.0
        self.zoom_factor = 1.0
        self.ab_loop_start = -1
        self.ab_loop_end = -1
        self.show_stats = False

        self.ram_array = None
        self.ram_buffer = None
        self.current_theme = "Dark"
        self.screenshot_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.PicturesLocation)

        # ---- Workers & Subsystems ----
        self.active_bg_worker = None
        self.ai_worker = None
        self.voice_worker = None
        self.telemetry_worker = None
        self.tmdb_worker = None
        self.dlna_worker = None
        self.rpc = None

        # ---- Initialization ----
        self._init_discord_rpc()
        self._init_hardware_telemetry()
        self.settings = QSettings("OmniPlayerPro", "settings")

        self._build_log_dock()
        self._build_status_bar()
        self.log_event("OmniPlayer Pro Ultimate Boot Sequence Initialized...", "#3498DB")
        self._setup_player()
        self._build_playlist_dock()
        self._build_bookmarks_dock()
        self._build_menu()
        self._build_ui()

        self.load_settings()

        self.sub_timer = QTimer(self)
        self.sub_timer.timeout.connect(self.master_tick)
        self.sub_timer.start(100)

        if self.current_media is None and self.resume_data:
            last = next(iter(self.resume_data)) if self.resume_data else None
            if last and os.path.exists(last):
                self._play_target(last, resume_pos=self.resume_data[last])

    # -------------------------------------------------------------------------
    # HARDWARE & DISCORD RPC
    # -------------------------------------------------------------------------
    def _init_hardware_telemetry(self):
        if NVML_AVAILABLE:
            self.telemetry_worker = HardwareTelemetryWorker()
            self.telemetry_worker.telemetry_update.connect(self.update_hw_stats)
            self.telemetry_worker.start()

    @pyqtSlot(dict)
    def update_hw_stats(self, data):
        self.hw_stats = data

    def _init_discord_rpc(self):
        if not DISCORD_AVAILABLE:
            return
        def connect_discord():
            try:
                self.rpc = Presence("1543546064999817266")
                self.rpc.connect()
                self.log_event("Discord Rich Presence: Connected", "#7289DA")
            except Exception:
                self.rpc = None
        threading.Thread(target=connect_discord, daemon=True).start()

    def _update_discord_rpc(self):
        if not self.rpc:
            return
        try:
            state = "Playing" if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState else "Paused"
            filename = os.path.basename(str(self.current_media)) if self.current_media else "Idle"
            self.rpc.update(
                state=f"Status: {state}",
                details=f"Watching: {filename[:30]}",
                large_image="app_icon",
                large_text="OmniPlayer Pro Ultimate"
            )
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # UI COMPONENT BUILDERS
    # -------------------------------------------------------------------------
    def _build_status_bar(self):
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_label = QLabel("Ready")
        self.status_bar.addWidget(self.status_label)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setFixedWidth(200)
        self.progress_bar.setVisible(False)
        self.status_bar.addPermanentWidget(self.progress_bar)

        self.btn_cancel_task = QPushButton("🛑 Cancel Task")
        self.btn_cancel_task.setStyleSheet("background-color: #E74C3C; color: white; border-radius: 3px; padding: 2px 8px; font-weight: bold;")
        self.btn_cancel_task.setVisible(False)
        self.btn_cancel_task.clicked.connect(self.cancel_bg_task)
        self.status_bar.addPermanentWidget(self.btn_cancel_task)

    def _build_log_dock(self):
        self.dock = QDockWidget("System Telemetry Console", self)
        self.dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea)
        self.dock.setStyleSheet(f"QDockWidget {{ color: {self.accent_color}; font-weight: bold; background-color: #1a1a1a; }}")
        self.log_console = QTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setStyleSheet("QTextEdit { background-color: #050505; color: #CCCCCC; font-family: Consolas, monospace; font-size: 13px; border: none; padding: 5px; }")
        self.dock.setWidget(self.log_console)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)

    def log_event(self, text, color="#CCCCCC"):
        timestamp = QDateTime.currentDateTime().toString("HH:mm:ss")
        html_msg = f'<span style="color: #666;">[{timestamp}]</span> <span style="color: {color};">{text}</span>'
        self.log_console.append(html_msg)
        self.log_console.verticalScrollBar().setValue(self.log_console.verticalScrollBar().maximum())

    def _build_playlist_dock(self):
        self.playlist_dock = QDockWidget("Playlist", self)
        self.playlist_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.playlist_widget = QListWidget()
        self.playlist_widget.itemDoubleClicked.connect(self.play_playlist_item)
        self.playlist_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.playlist_widget.customContextMenuRequested.connect(self.playlist_context_menu)
        self.playlist_dock.setWidget(self.playlist_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.playlist_dock)

        self.playlist_toolbar = QToolBar("Playlist Tools")
        self.addToolBar(self.playlist_toolbar)
        self.playlist_toolbar.addAction("Add File", self.add_to_playlist)
        self.playlist_toolbar.addAction("Clear", self.clear_playlist)
        self.shuffle_btn = QAction("Shuffle", self, checkable=True)
        self.shuffle_btn.triggered.connect(self.toggle_shuffle)
        self.playlist_toolbar.addAction(self.shuffle_btn)
        self.repeat_btn = QAction("Repeat", self, checkable=True)
        self.repeat_btn.triggered.connect(self.toggle_repeat)
        self.playlist_toolbar.addAction(self.repeat_btn)

    def _build_bookmarks_dock(self):
        self.bookmark_dock = QDockWidget("Chapters & Bookmarks", self)
        self.bookmark_dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.bookmark_list = QListWidget()
        self.bookmark_list.itemDoubleClicked.connect(self.jump_to_bookmark)
        self.bookmark_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.bookmark_list.customContextMenuRequested.connect(self.bookmark_context_menu)
        self.bookmark_dock.setWidget(self.bookmark_list)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.bookmark_dock)

    # -------------------------------------------------------------------------
    # PLAYLIST / BOOKMARK METHODS
    # -------------------------------------------------------------------------
    def add_to_playlist(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Add to Playlist", "", "Media (*.*)")
        for f in files:
            self.playlist.append(f)
            self.playlist_widget.addItem(os.path.basename(f))
        self.log_event(f"Added {len(files)} files to playlist", "#2ECC71")

    def clear_playlist(self):
        self.playlist.clear()
        self.playlist_widget.clear()
        self.playlist_index = -1

    def play_playlist_item(self, item):
        idx = self.playlist_widget.row(item)
        if 0 <= idx < len(self.playlist):
            self._play_target(self.playlist[idx])

    def playlist_context_menu(self, pos):
        menu = QMenu()
        menu.addAction("Play", lambda: self.play_playlist_item(self.playlist_widget.currentItem()))
        menu.addAction("Remove", self.remove_playlist_item)
        menu.addAction("Clear", self.clear_playlist)
        menu.exec(self.playlist_widget.mapToGlobal(pos))

    def remove_playlist_item(self):
        row = self.playlist_widget.currentRow()
        if row >= 0:
            self.playlist.pop(row)
            self.playlist_widget.takeItem(row)

    def toggle_shuffle(self):
        self.shuffle_mode = not self.shuffle_mode
        self.log_event(f"Shuffle {'ON' if self.shuffle_mode else 'OFF'}", "#2ECC71")

    def toggle_repeat(self):
        self.repeat_mode = (self.repeat_mode + 1) % 3
        modes = ["OFF", "ONE", "ALL"]
        self.log_event(f"Repeat: {modes[self.repeat_mode]}", "#2ECC71")

    def prev_playlist_item(self):
        if not self.playlist:
            return
        if self.shuffle_mode:
            idx = random.randint(0, len(self.playlist) - 1)
        else:
            if self.playlist_index > 0:
                idx = self.playlist_index - 1
            else:
                if self.repeat_mode == 2:
                    idx = len(self.playlist) - 1
                else:
                    return
        self.playlist_index = idx
        self._play_target(self.playlist[idx])

    def next_playlist(self):
        if not self.playlist:
            return
        if self.shuffle_mode:
            idx = random.randint(0, len(self.playlist) - 1)
        else:
            if self.playlist_index < len(self.playlist) - 1:
                idx = self.playlist_index + 1
            else:
                if self.repeat_mode == 2:
                    idx = 0
                else:
                    return
        self.playlist_index = idx
        self._play_target(self.playlist[idx])

    def add_bookmark(self, name=None):
        pos = self.player.position()
        if pos < 0:
            return
        if name is None:
            name, ok = QInputDialog.getText(self, "Bookmark", "Enter bookmark name:")
            if not ok or not name:
                return
        self.bookmarks.append((pos, name))
        self.bookmark_list.addItem(f"{name} ({self._format_time(pos)})")
        self.log_event(f"Bookmark added: {name} at {self._format_time(pos)}", "#9B59B6")

    def jump_to_bookmark(self, item):
        idx = self.bookmark_list.row(item)
        if 0 <= idx < len(self.bookmarks):
            pos, name = self.bookmarks[idx]
            self.player.setPosition(pos)
            self.log_event(f"Jumped to chapter/bookmark: {name}", "#3498DB")

    def remove_bookmark(self):
        row = self.bookmark_list.currentRow()
        if row >= 0:
            self.bookmarks.pop(row)
            self.bookmark_list.takeItem(row)

    def bookmark_context_menu(self, pos):
        menu = QMenu()
        menu.addAction("Jump", lambda: self.jump_to_bookmark(self.bookmark_list.currentItem()))
        menu.addAction("Remove", self.remove_bookmark)
        menu.exec(self.bookmark_list.mapToGlobal(pos))

    def set_zoom(self, factor):
        self.zoom_factor = max(0.1, min(5.0, factor))
        self.log_event(f"Zoom level adjusted (factor: {self.zoom_factor:.2f})", "#F39C12")

    def show_video_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(f"QMenu {{ background-color: #2b2b2b; color: white; border: 1px solid #444; font-size: 13px; }} QMenu::item:selected {{ background-color: {self.accent_color}; }}")
        
        menu.addAction("⏯ Play / Pause", self.toggle_play)
        menu.addAction("🖵 Toggle Fullscreen", self.toggle_fullscreen)
        menu.addAction("🔇 Toggle Mute", self.toggle_mute)
        menu.addSeparator()
        menu.addAction("📂 Open Local File...", self.load_local_media)
        menu.addAction("⚙️ Toggle UI Controls", self.toggle_ui_controls)
        menu.addAction("🎨 Adjust Subtitle Style...", self.subtitle_style_dialog)
        
        global_pos = self.video_widget.mapToGlobal(pos)
        menu.exec(global_pos)

    # -------------------------------------------------------------------------
    # MENU BUILDER
    # -------------------------------------------------------------------------
    def _build_menu(self):
        self.menu_bar = self.menuBar()
        self.menu_bar.setStyleSheet(f"QMenuBar {{ background-color: #1a1a1a; color: white; }} QMenuBar::item:selected {{ background-color: {self.accent_color}; }} QMenu {{ background-color: #2b2b2b; color: white; }} QMenu::item:selected {{ background-color: {self.accent_color}; }}")

        media_menu = self.menu_bar.addMenu("Media")
        self._add_action(media_menu, "Open File...", self.load_local_media, "Ctrl+O")
        self._add_action(media_menu, "Open Network Stream...", self.open_network_stream, "Ctrl+N")
        self._add_action(media_menu, "Open YouTube URL...", self.open_youtube_stream, "Ctrl+Y")
        self._add_action(media_menu, "Quit", self.close, "Ctrl+Q")

        pb_menu = self.menu_bar.addMenu("Playback")
        self._add_action(pb_menu, "Play / Pause", self.toggle_play, "Space")
        self._add_action(pb_menu, "Stop", self.stop_playback, "S")
        self._add_action(pb_menu, "Jump to Time...", self.jump_to_time, "Ctrl+G")
        self._add_action(pb_menu, "Step Forward Frame", self.step_frame_forward, ".")
        self._add_action(pb_menu, "Step Backward Frame", self.step_frame_backward, ",")
        self._add_action(pb_menu, "Set A-B Loop Start", self.set_loop_a, "A")
        self._add_action(pb_menu, "Set A-B Loop End", self.set_loop_b, "B")
        self._add_action(pb_menu, "Clear A-B Loop", self.clear_loop, "C")
        pb_menu.addSeparator()
        self._add_action(pb_menu, "Add Bookmark", self.add_bookmark, "Ctrl+B")
        self._add_action(pb_menu, "Show Bookmarks & Chapters", lambda: self.bookmark_dock.setVisible(True))
        pb_menu.addSeparator()
        self._add_action(pb_menu, "Playback Speed...", self.set_playback_speed, "Ctrl+R")

        audio_menu = self.menu_bar.addMenu("Audio")
        self._add_action(audio_menu, "Mute / Unmute", self.toggle_mute, "M")
        self._add_action(audio_menu, "Volume Up", lambda: self.change_volume(min(500, self.slider_volume.value()+10)), "Ctrl+Up")
        self._add_action(audio_menu, "Volume Down", lambda: self.change_volume(max(0, self.slider_volume.value()-10)), "Ctrl+Down")
        audio_menu.addSeparator()
        self._add_action(audio_menu, "10-Band EQ & PreAmp...", self.show_equalizer)
        self._add_action(audio_menu, "Create 200% Volume Copy", self.boost_audio)
        self._add_action(audio_menu, "Isolate Audio Stems (Demucs AI)", self.isolate_audio_stems)

        video_menu = self.menu_bar.addMenu("Video")
        self._add_action(video_menu, "Toggle Fullscreen", self.toggle_fullscreen, "F")
        self._add_action(video_menu, "Picture-in-Picture (PiP) Window", self.toggle_pip_mode, "P")
        self._add_action(video_menu, "Take Screenshot", self.take_screenshot, "Ctrl+Shift+S")
        self._add_action(video_menu, "Zoom In", lambda: self.set_zoom(self.zoom_factor*1.1), "Ctrl++")
        self._add_action(video_menu, "Zoom Out", lambda: self.set_zoom(self.zoom_factor/1.1), "Ctrl+-")
        self._add_action(video_menu, "Reset Zoom", lambda: self.set_zoom(1.0), "Ctrl+0")
        video_menu.addSeparator()
        self._add_action(video_menu, "Lossless Video Trimmer...", self.run_ffmpeg_trim)
        self._add_action(video_menu, "Generate Video Contact Sheet...", self.generate_contact_sheet)
        self._add_action(video_menu, "Real-ESRGAN 4K Upscaler...", self.run_esrgan)

        sub_menu = self.menu_bar.addMenu("Subtitle & AI")
        self._add_action(sub_menu, "Generate AI Subtitles", self.start_ai)
        self._add_action(sub_menu, "Auto-Generate AI Chapters", self.generate_ai_chapters)
        self._add_action(sub_menu, "Export Subtitles as SRT", self.export_subtitles)
        sub_menu.addSeparator()
        self._add_action(sub_menu, "Search on OpenSubtitles", self.open_subtitles_web)
        self._add_action(sub_menu, "Adjust Sync Delay...", self.adjust_sub_sync)
        self._add_action(sub_menu, "Subtitle Style...", self.subtitle_style_dialog)

        ecosystem_menu = self.menu_bar.addMenu("Smart Ecosystem")
        self._add_action(ecosystem_menu, "Toggle Voice Control Listener", self.toggle_voice_control, "Ctrl+V")
        self._add_action(ecosystem_menu, "Cast Stream to Smart TV", self.cast_to_chromecast, "Ctrl+K")
        self._add_action(ecosystem_menu, "Broadcast DLNA/HTTP Server", self.toggle_dlna_server)
        self._add_action(ecosystem_menu, "Fetch Media Metadata (TMDB)", self.fetch_metadata, "Ctrl+I")

        sec_menu = self.menu_bar.addMenu("Security Vault")
        self._add_action(sec_menu, "Encrypt Video to Vault (.tjz)", self.encrypt_file)
        self._add_action(sec_menu, "Unlock & Play Encrypted Vault (.tjz)", self.play_encrypted_media_prompt)
        self._add_action(sec_menu, "Secure Delete File...", self.secure_delete)

        tools_menu = self.menu_bar.addMenu("Tools")
        self._add_action(tools_menu, "Extract 5s GIF from current time", self.create_gif)
        self._add_action(tools_menu, "Rip Audio to MP3", self.rip_mp3)
        self._add_action(tools_menu, "Show File Info", self.show_file_info)

        view_menu = self.menu_bar.addMenu("View")
        self._add_action(view_menu, "Toggle Stats for Nerds", self.toggle_stats, "F9")
        self._add_action(view_menu, "Toggle Controls", self.toggle_ui_controls, "Ctrl+H")
        self._add_action(view_menu, "Toggle Telemetry", lambda: self.dock.setVisible(not self.dock.isVisible()))
        self._add_action(view_menu, "Toggle Playlist", lambda: self.playlist_dock.setVisible(not self.playlist_dock.isVisible()))
        self._add_action(view_menu, "Toggle Bookmarks", lambda: self.bookmark_dock.setVisible(not self.bookmark_dock.isVisible()))

        theme_menu = view_menu.addMenu("Themes")
        for name, color in [("Dark", "#0d0d0d"), ("Light", "#f0f0f0"), ("Sapphire", "#1a2a3a"), ("Ruby", "#3a1a1a"), ("Emerald", "#1a3a1a"), ("Amethyst", "#2a1a3a")]:
            self._add_action(theme_menu, name, lambda c=color, n=name: self.apply_theme(n, c))

        help_menu = self.menu_bar.addMenu("Help")
        self._add_action(help_menu, "About", self.show_about)
        self._add_action(help_menu, "Keyboard Shortcuts", self.show_shortcuts)

    def _add_action(self, menu, text, slot=None, shortcut=None):
        action = QAction(text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if slot:
            action.triggered.connect(slot)
        menu.addAction(action)
        return action

    # -------------------------------------------------------------------------
    # MAIN UI BUILDER (PERMANENT SUBTITLE CONTAINER, NO HIDING)
    # -------------------------------------------------------------------------
    def _build_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # --- Video Canvas & Subtitles ---
        self.display_container = QFrame()
        self.display_container.setStyleSheet("background-color: black; border-radius: 8px; border: 1px solid #333;")
        
        display_layout = QVBoxLayout(self.display_container)
        display_layout.setContentsMargins(0, 0, 0, 0)
        display_layout.setSpacing(0)

        # 1. The Video
        self.video_widget = ClickableVideoWidget()
        self.video_widget.setStyleSheet("background: #000000; border: none;")
        self.video_widget.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.player.setVideoOutput(self.video_widget)
        self.video_widget.singleClicked.connect(self.toggle_play)
        self.video_widget.doubleClicked.connect(self.toggle_fullscreen)
        
        # Connect Right-Click Context Menu
        self.video_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.video_widget.customContextMenuRequested.connect(self.show_video_context_menu)

        display_layout.addWidget(self.video_widget, stretch=1)

        # 2. Permanent Subtitle Deck (Fixed Height completely locks the layout grid)
        self.subtitle_container = QFrame()
        self.subtitle_container.setMinimumHeight(72)
        self.subtitle_container.setMaximumHeight(90)
        self.subtitle_container.setStyleSheet(
            "background-color: #06080c; border-top: 1px solid #1f2731;"
        )

        sub_layout = QVBoxLayout(self.subtitle_container)
        sub_layout.setContentsMargins(8, 4, 8, 4)
        sub_layout.setSpacing(1)

        self.subtitle_bar_top = QLabel("")
        self.subtitle_bar_top.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_bar_top.setFont(QFont("Segoe UI", max(8, self.sub_font_size - 4), QFont.Weight.Bold))
        self.subtitle_bar_top.setStyleSheet("color: #3498DB; background-color: transparent;")
        self.subtitle_bar_top.setWordWrap(True)
        sub_layout.addWidget(self.subtitle_bar_top, stretch=1)

        self.subtitle_bar = QLabel("")
        self.subtitle_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.subtitle_bar.setFont(QFont("Segoe UI", self.sub_font_size, QFont.Weight.Bold))
        self.subtitle_bar.setStyleSheet(f"color: {self.sub_color}; background-color: transparent;")
        self.subtitle_bar.setWordWrap(True)
        sub_layout.addWidget(self.subtitle_bar, stretch=2)

        display_layout.addWidget(self.subtitle_container, stretch=0)

        # 4. Audio Visualizer
        self.visualizer = AudioVisualizerWidget()
        self.visualizer.hide()
        display_layout.addWidget(self.visualizer, stretch=0)

        main_layout.addWidget(self.display_container, stretch=1)

        # Overlay Stats for Nerds
        self.lbl_stats = QLabel(self.display_container)
        self.lbl_stats.setStyleSheet("color: #00FF00; background-color: rgba(0,0,0,200); padding: 8px; font-family: Consolas; border-radius: 4px;")
        self.lbl_stats.setGeometry(10, 40, 420, 160)
        self.lbl_stats.hide()

        # --- Omni Command Center Hub ---
        self.controls_frame = QFrame()
        controls_outer_layout = QVBoxLayout(self.controls_frame)
        controls_outer_layout.setContentsMargins(0, 5, 0, 0)

        self.command_center = QTabWidget()
        self.command_center.setStyleSheet("QTabWidget::pane { border: 1px solid #444; } QTabBar::tab { background: #222; padding: 6px 14px; } QTabBar::tab:selected { background: #3498DB; font-weight: bold; }")
        self.command_center.setFixedHeight(175)

        # Tab 1: Playback & Timeline
        playback_tab = QWidget()
        pb_layout = QVBoxLayout(playback_tab)
        time_layout = QHBoxLayout()
        self.lbl_curr_time = QLabel("00:00")
        
        # Explicit instantiation of TimelineSlider mapping both dragging and clicks
        self.slider_timeline = TimelineSlider(Qt.Orientation.Horizontal)
        self.slider_timeline.setRange(0, 100)
        self.slider_timeline.setTracking(False)
        self.slider_timeline.setToolTip("Drag to preview time; release to seek")
        self.slider_timeline.sliderPressed.connect(self.seek_started)
        self.slider_timeline.sliderMoved.connect(self.seek_moving)  # Reconnected slider move
        self.slider_timeline.seekRequested.connect(self.perform_seek)
        self.slider_timeline.sliderReleased.connect(self.seek_ended)
        self.slider_timeline.setStyleSheet(f"""
            QSlider::groove:horizontal {{ border-radius: 4px; height: 8px; background: #222; }}
            QSlider::handle:horizontal {{ background: {self.accent_color}; width: 16px; height: 16px; margin: -4px 0; border-radius: 8px; }}
            QSlider::sub-page:horizontal {{ background: {self.accent_color}; border-radius: 4px; }}
        """)
        
        self.lbl_total_time = QLabel("00:00")
        time_layout.addWidget(self.lbl_curr_time)
        time_layout.addWidget(self.slider_timeline)
        time_layout.addWidget(self.lbl_total_time)
        pb_layout.addLayout(time_layout)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self._create_btn("⏮", "#333", self.prev_playlist_item, 40))
        btn_layout.addWidget(self._create_btn("⏪ 10s", "#333", self.skip_backward, 65))
        btn_layout.addWidget(self._create_btn("⏯ Play/Pause", self.accent_color, self.toggle_play, 105))
        btn_layout.addWidget(self._create_btn("⏹ Stop", "#C0392B", self.stop_playback, 60))
        btn_layout.addWidget(self._create_btn("10s ⏩", "#333", self.skip_forward, 65))
        btn_layout.addWidget(self._create_btn("⏭", "#333", self.next_playlist, 40))

        btn_layout.addSpacing(15)

        btn_layout.addWidget(self._create_btn("🖵 Full", "#2980B9", self.toggle_fullscreen, 60))
        btn_layout.addWidget(self._create_btn("📺 PiP", "#E67E22", self.toggle_pip_mode, 55))
        btn_layout.addWidget(self._create_btn("🎙️ Voice", "#27AE60", self.toggle_voice_control, 65))
        btn_layout.addStretch()

        self.speed_combo = QComboBox()
        for s in [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]:
            self.speed_combo.addItem(f"{s}x", s)
        self.speed_combo.setCurrentIndex(3)
        self.speed_combo.currentIndexChanged.connect(self.on_speed_changed)
        btn_layout.addWidget(QLabel("Speed:"))
        btn_layout.addWidget(self.speed_combo)

        btn_layout.addSpacing(10)

        btn_layout.addWidget(self._create_btn("🔇", "#555", self.toggle_mute, 35))
        self.lbl_vol = QLabel("100%")
        self.lbl_vol.setFixedWidth(35)
        btn_layout.addWidget(self.lbl_vol)
        self.slider_volume = QSlider(Qt.Orientation.Horizontal)
        self.slider_volume.setRange(0, 500)
        self.slider_volume.setValue(100)
        self.slider_volume.setFixedWidth(100)
        self.slider_volume.valueChanged.connect(self.change_volume)
        btn_layout.addWidget(self.slider_volume)
        pb_layout.addLayout(btn_layout)

        # Tab 2: AI & Computer Vision
        ai_tab = QWidget()
        ai_layout = QGridLayout(ai_tab)
        
        ai_sub_widget = QGroupBox("AI Subtitle Engine")
        ai_sub_layout = QGridLayout(ai_sub_widget)
        
        self.audio_lang_combo = QComboBox()
        self.audio_lang_combo.addItems(["Auto-Detect Audio", "Hindi", "Punjabi", "English", "Spanish", "French", "German", "Japanese", "Russian", "Chinese"])
        self.audio_lang_combo.setToolTip("Select spoken language for transcription accuracy")
        
        self.display_mode_combo = QComboBox()
        self.display_mode_combo.addItems(["Show Both (Dual Subs)", "Show Native Only", "Show English Translation Only"])
        
        btn_generate_ai = self._create_btn("🤖 Generate AI Subs", "#9B59B6", self.start_ai)
        
        ai_sub_layout.addWidget(QLabel("Spoken Audio:"), 0, 0)
        ai_sub_layout.addWidget(self.audio_lang_combo, 0, 1)
        ai_sub_layout.addWidget(QLabel("Display Mode:"), 1, 0)
        ai_sub_layout.addWidget(self.display_mode_combo, 1, 1)
        ai_sub_layout.addWidget(btn_generate_ai, 2, 0, 1, 2)
        
        ai_layout.addWidget(ai_sub_widget, 0, 0, 2, 1)
        
        ai_layout.addWidget(self._create_btn("📑 AI Auto-Chapters", "#9B59B6", self.generate_ai_chapters), 0, 1)
        ai_layout.addWidget(self._create_btn("✨ Real-ESRGAN 4K", "#8E44AD", self.run_esrgan), 0, 2)
        ai_layout.addWidget(self._create_btn("🎬 TMDB Metadata", "#8E44AD", self.fetch_metadata), 1, 1)
        ai_layout.addWidget(self._create_btn("📄 Export SRT", "#8E44AD", self.export_subtitles), 1, 2)

        # Tab 3: Pro Audio & DSP
        audio_tab = QWidget()
        audio_layout = QGridLayout(audio_tab)
        audio_layout.addWidget(self._create_btn("🎚️ 10-Band EQ & PreAmp", "#2980B9", self.show_equalizer), 0, 0)
        audio_layout.addWidget(self._create_btn("🔊 Boost Audio 200%", "#2980B9", self.boost_audio), 0, 1)
        audio_layout.addWidget(self._create_btn("✂️ Stem Isolation (Demucs)", "#2980B9", self.isolate_audio_stems), 0, 2)
        audio_layout.addWidget(self._create_btn("🎵 Rip Audio to MP3", "#3498DB", self.rip_mp3), 1, 0)
        audio_layout.addWidget(self._create_btn("⏱️ Sub Sync Adjust", "#3498DB", self.adjust_sub_sync), 1, 1)
        audio_layout.addWidget(self._create_btn("🎨 Subtitle Style", "#3498DB", self.subtitle_style_dialog), 1, 2)

        # Tab 4: Network & Smart Ecosystem
        net_tab = QWidget()
        net_layout = QGridLayout(net_tab)
        net_layout.addWidget(self._create_btn("📺 Cast to Smart TV", "#D35400", self.cast_to_chromecast), 0, 0)
        net_layout.addWidget(self._create_btn("📡 Broadcast DLNA Server", "#D35400", self.toggle_dlna_server), 0, 1)
        net_layout.addWidget(self._create_btn("🌐 Open Network Stream", "#E67E22", self.open_network_stream), 0, 2)
        net_layout.addWidget(self._create_btn("▶️ Open YouTube Stream", "#E67E22", self.open_youtube_stream), 1, 0)
        net_layout.addWidget(self._create_btn("📊 Stats for Nerds", "#E67E22", self.toggle_stats), 1, 1)
        net_layout.addWidget(self._create_btn("⌨️ Keyboard Shortcuts", "#E67E22", self.show_shortcuts), 1, 2)

        # Tab 5: Security Vault & Editing Tools
        tools_tab = QWidget()
        tools_layout = QGridLayout(tools_tab)
        tools_layout.addWidget(self._create_btn("🔒 Encrypt File to Vault (.tjz)", "#C0392B", self.encrypt_file), 0, 0)
        tools_layout.addWidget(self._create_btn("🔓 Decrypt & Stream from RAM", "#C0392B", self.play_encrypted_media_prompt), 0, 1)
        tools_layout.addWidget(self._create_btn("🗑️ Secure Wipe File", "#C0392B", self.secure_delete), 0, 2)
        tools_layout.addWidget(self._create_btn("✂️ Lossless Video Trimmer", "#E74C3C", self.run_ffmpeg_trim), 1, 0)
        tools_layout.addWidget(self._create_btn("🎞️ 5s GIF Snippet", "#E74C3C", self.create_gif), 1, 1)
        tools_layout.addWidget(self._create_btn("📷 Video Contact Sheet", "#E74C3C", self.generate_contact_sheet), 1, 2)

        self.command_center.addTab(playback_tab, "Timeline & Playback")
        self.command_center.addTab(ai_tab, "AI & Computer Vision")
        self.command_center.addTab(audio_tab, "Pro Audio & DSP")
        self.command_center.addTab(net_tab, "Network & Streaming")
        self.command_center.addTab(tools_tab, "Security & Tools")

        controls_outer_layout.addWidget(self.command_center)
        main_layout.addWidget(self.controls_frame, stretch=0)

    def _create_btn(self, text, color, callback, width=None):
        btn = QPushButton(text)
        btn.setStyleSheet(f"QPushButton {{ background-color: {color}; color: white; border-radius: 5px; padding: 7px; font-weight: bold; font-size: 12px; }} QPushButton:hover {{ opacity: 0.9; }}")
        btn.clicked.connect(callback)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if width:
            btn.setFixedWidth(width)
        return btn

    def toggle_ui_controls(self):
        self.controls_visible = not self.controls_visible
        self.controls_frame.setVisible(self.controls_visible)
        self.menu_bar.setVisible(self.controls_visible)
        self.log_event(f"UI Controls {'shown' if self.controls_visible else 'hidden'}")

    # -------------------------------------------------------------------------
    # BACKGROUND TASK MANAGER
    # -------------------------------------------------------------------------
    def run_bg_task(self, worker, show_progress=False):
        if self.active_bg_worker and self.active_bg_worker.isRunning():
            QMessageBox.warning(self, "Busy", "A background task is already running. Please cancel it or wait.")
            return

        self.active_bg_worker = worker
        self.active_bg_worker.status_update.connect(self.log_event)
        self.active_bg_worker.finished.connect(self.on_bg_task_finished)
        
        self.btn_cancel_task.setVisible(True)
        self.btn_cancel_task.setEnabled(True)
        self.btn_cancel_task.setText("🛑 Cancel Task")

        if show_progress:
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            if hasattr(worker, 'progress_update'):
                worker.progress_update.connect(self.update_progress)
        else:
            self.progress_bar.setVisible(False)

        self.active_bg_worker.start()

    @pyqtSlot()
    def on_bg_task_finished(self):
        self.progress_bar.setVisible(False)
        self.btn_cancel_task.setVisible(False)
        self.active_bg_worker = None

    @pyqtSlot(int)
    def update_progress(self, val):
        self.progress_bar.setValue(val)

    def cancel_bg_task(self):
        if self.active_bg_worker and self.active_bg_worker.isRunning():
            self.log_event("Sending cancel signal to background task...", "#F39C12")
            self.btn_cancel_task.setEnabled(False)
            self.btn_cancel_task.setText("Cancelling...")
            if hasattr(self.active_bg_worker, 'stop'):
                self.active_bg_worker.stop()

    # -------------------------------------------------------------------------
    # CORE PLAYBACK ENGINE
    # -------------------------------------------------------------------------
    def _setup_player(self):
        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        self.audio_output.setVolume(1.0)
        self.player.positionChanged.connect(self.update_timeline)
        self.player.durationChanged.connect(self.update_duration)
        self.player.mediaStatusChanged.connect(self.handle_media_status)

    def handle_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.repeat_mode == 1:
                self.player.setPosition(0)
                self.player.play()
            elif self.playlist and self.repeat_mode in (0, 2):
                self.next_playlist()

    def load_local_media(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Open Media", "", "Media (*.*)")
        if filepath:
            self._play_target(filepath)

    def _play_target(self, path, resume_pos=None):
        self._reset_player()
        self.current_media = path
        
        ext = path.split('.')[-1].lower() if '.' in path else ''
        audio_exts = ['mp3', 'wav', 'flac', 'aac', 'ogg', 'm4a', 'wma']
        
        if ext in audio_exts:
            self.is_video = False
            self.visualizer.show()
        else:
            self.is_video = True
            self.visualizer.hide()
            
        self.setWindowTitle(f"OmniPlayer Pro | {os.path.basename(path)}")
        self.log_event(f"Loading: {os.path.basename(path)}", "#3498DB")
        if path.startswith("http"):
            self.player.setSource(QUrl(path))
        else:
            self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()
        if resume_pos and resume_pos > 0:
            self.player.setPosition(resume_pos)
        self._update_discord_rpc()

    def _reset_player(self):
        self.player.stop()
        if self.ai_worker and self.ai_worker.isRunning():
            self.ai_worker.stop()
        self.generated_subs = []
        self.subtitle_bar.setText("")
        self.subtitle_bar_top.setText("")
        self.visualizer.hide()
        if self.ram_buffer:
            self.ram_buffer.close()
            self.ram_buffer = None
            self.ram_array = None

    def toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            self.log_event("Playback Paused", "#F39C12")
        else:
            self.player.play()
            self.log_event("Playback Resumed", "#2ECC71")
        self._update_discord_rpc()

    def stop_playback(self):
        self.player.stop()
        self.log_event("Playback Stopped", "#F39C12")

    def skip_forward(self):
        self.player.setPosition(min(self.player.duration(), self.player.position() + 10000))

    def skip_backward(self):
        self.player.setPosition(max(0, self.player.position() - 10000))

    def step_frame_forward(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        self.player.setPosition(self.player.position() + 40)

    def step_frame_backward(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        self.player.setPosition(max(0, self.player.position() - 40))

    def change_volume(self, value):
        self.audio_output.setVolume(value / 100.0)
        self.lbl_vol.setText(f"{value}%")

    def toggle_mute(self):
        is_muted = not self.audio_output.isMuted()
        self.audio_output.setMuted(is_muted)
        self.log_event(f"Audio {'Muted' if is_muted else 'Unmuted'}")

    def on_speed_changed(self, index):
        self.playback_speed = self.speed_combo.currentData()
        self.player.setPlaybackRate(self.playback_speed)

    def set_playback_speed(self):
        speed, ok = QInputDialog.getDouble(self, "Playback Speed", "Speed (0.1 - 4.0):", self.playback_speed, 0.1, 4.0, 2)
        if ok:
            self.playback_speed = speed
            self.player.setPlaybackRate(speed)
            idx = self.speed_combo.findData(speed)
            if idx >= 0:
                self.speed_combo.setCurrentIndex(idx)

    def jump_to_time(self):
        t, ok = QInputDialog.getText(self, "Jump to Time", "Enter time (HH:MM:SS or seconds):")
        if ok and t:
            try:
                if ':' in t:
                    parts = list(map(int, t.split(':')))
                    ms = (parts[0]*3600 + parts[1]*60 + parts[2]) * 1000 if len(parts) == 3 else (parts[0]*60 + parts[1]) * 1000
                else:
                    ms = int(float(t) * 1000)
                self.player.setPosition(min(ms, self.player.duration()))
            except Exception:
                QMessageBox.warning(self, "Invalid Format", "Use HH:MM:SS or seconds.")

    def seek_started(self):
        self.is_seeking = True
        self._resume_after_seek = (
            self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        )
        if self._resume_after_seek:
            self.player.pause()

    def seek_moving(self, position):
        self.lbl_curr_time.setText(self._format_time(position))

    def seek_ended(self):
        self.is_seeking = False

    def perform_seek(self, val):
        duration = max(0, int(self.player.duration()))
        target = max(0, min(int(val), duration)) if duration else max(0, int(val))
        self.player.setPosition(target)
        self.is_seeking = False
        if getattr(self, '_resume_after_seek', False):
            self._resume_after_seek = False
            QTimer.singleShot(100, self.player.play)


    def update_timeline(self, position):
        if not self.is_seeking:
            if self.slider_timeline.maximum() != self.player.duration():
                self.slider_timeline.setMaximum(self.player.duration())
            self.slider_timeline.blockSignals(True)
            self.slider_timeline.setValue(position)
            self.slider_timeline.blockSignals(False)
        self.lbl_curr_time.setText(self._format_time(position))

    def update_duration(self, duration):
        self.slider_timeline.setRange(0, duration)
        self.lbl_total_time.setText(self._format_time(duration))

    def _format_time(self, ms):
        s = ms // 1000
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d}" if h > 0 else f"{m:02d}:{s:02d}"

    def set_loop_a(self):
        self.ab_loop_start = self.player.position()
        self.log_event(f"A-B Loop START: {self._format_time(self.ab_loop_start)}", "#2ECC71")

    def set_loop_b(self):
        self.ab_loop_end = self.player.position()
        self.log_event(f"A-B Loop END: {self._format_time(self.ab_loop_end)}", "#E74C3C")

    def clear_loop(self):
        self.ab_loop_start = -1
        self.ab_loop_end = -1
        self.log_event("A-B Loop Cleared")

    def toggle_fullscreen(self):
        if not self.is_fullscreen:
            self.showFullScreen()
            self.menu_bar.hide()
            self.controls_frame.hide()
            self.dock.hide()
            self.is_fullscreen = True
        else:
            self.showNormal()
            self.menu_bar.show()
            self.controls_frame.show()
            self.dock.show()
            self.is_fullscreen = False

    def toggle_pip_mode(self):
        if not self.is_pip_mode:
            self.normal_geometry = self.geometry()
            self.setWindowFlags(Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint)
            self.menu_bar.hide()
            self.controls_frame.hide()
            self.dock.hide()
            self.playlist_dock.hide()
            self.bookmark_dock.hide()
            self.visualizer.hide()

            self.subtitle_bar.setFont(QFont("Segoe UI", 12, QFont.Weight.Bold))
            self.subtitle_bar_top.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
            self.subtitle_container.setFixedHeight(80)

            self.resize(480, 270)
            self.show()
            self.is_pip_mode = True
            self.log_event("Picture-in-Picture Mode: Activated", "#3498DB")
        else:
            self.setWindowFlags(Qt.WindowType.Widget)
            self.menu_bar.show()
            self.controls_frame.show()
            self.dock.show()
            self.visualizer.show()

            self.subtitle_bar.setFont(QFont("Segoe UI", self.sub_font_size, QFont.Weight.Bold))
            self.subtitle_bar_top.setFont(QFont("Segoe UI", max(8, self.sub_font_size - 4), QFont.Weight.Bold))
            self.subtitle_container.setFixedHeight(120)

            self.setGeometry(self.normal_geometry)
            self.show()
            self.is_pip_mode = False
            self.log_event("Picture-in-Picture Mode: Deactivated", "#3498DB")

    def toggle_stats(self):
        self.show_stats = not self.show_stats
        self.lbl_stats.setVisible(self.show_stats)

    # -------------------------------------------------------------------------
    # AI SUBTITLES & SMART CHAPTERING
    # -------------------------------------------------------------------------
    def start_ai(self):
        if not self.current_media:
            QMessageBox.warning(self, "AI Error", "Please load a video or audio file first.")
            return
        if not AI_AVAILABLE:
            QMessageBox.critical(self, "Missing Module", "Please install faster-whisper and numpy.")
            return

        if self.ai_worker and self.ai_worker.isRunning():
            self.ai_worker.stop()
            self.ai_worker.quit()

        self.generated_subs = []
        current_time_sec = self.player.position() / 1000.0

        lang_map = {
            "Auto-Detect Audio": None, "English": "en", "Hindi": "hi", "Punjabi": "pa",
            "Spanish": "es", "French": "fr", "German": "de", "Japanese": "ja", 
            "Russian": "ru", "Chinese": "zh"
        }
        selected_lang = lang_map.get(self.audio_lang_combo.currentText(), None)
        display_mode = self.display_mode_combo.currentIndex()

        worker = WhisperWorker(self.current_media, current_time_sec, display_mode=display_mode, language=selected_lang)
        worker.segment_ready.connect(lambda s, e, t, tr: self.generated_subs.append((s, e, t, tr)))
        
        self.run_bg_task(worker, show_progress=False)
        
        lang_str = self.audio_lang_combo.currentText()
        self.log_event(f"AI Subtitle Engine Dispatched (Spoken Lang: {lang_str}).", "#3498DB")

    def generate_ai_chapters(self):
        if not self.generated_subs:
            QMessageBox.information(self, "No Transcript", "Generate AI subtitles first to analyze dialogues.")
            return
        self.bookmarks.clear()
        self.bookmark_list.clear()
        last_time = 0
        chapter_idx = 1
        for start, end, text, _ in self.generated_subs:
            if start - last_time > 60 or chapter_idx == 1:
                title = f"Chapter {chapter_idx}: {text[:25]}..."
                ms = int(start * 1000)
                self.bookmarks.append((ms, title))
                self.bookmark_list.addItem(f"{title} ({self._format_time(ms)})")
                chapter_idx += 1
                last_time = start
        self.bookmark_dock.setVisible(True)
        self.log_event(f"Generated {len(self.bookmarks)} AI Chapters.", "#2ECC71")

    def export_subtitles(self):
        if not self.generated_subs:
            QMessageBox.information(self, "No Subtitles", "No AI subtitles to export.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save Subtitles", "subtitles.srt", "SubRip (*.srt)")
        if path:
            import datetime
            with open(path, 'w', encoding='utf-8') as f:
                for i, (start, end, text, trans) in enumerate(self.generated_subs, 1):
                    s_str = (str(datetime.timedelta(seconds=start)) + ".000").replace(".", ",")[0:12]
                    e_str = (str(datetime.timedelta(seconds=end)) + ".000").replace(".", ",")[0:12]
                    if len(s_str.split(':')[0]) == 1: s_str = "0" + s_str
                    if len(e_str.split(':')[0]) == 1: e_str = "0" + e_str
                    content = text + (f"\n({trans})" if trans else "")
                    f.write(f"{i}\n{s_str} --> {e_str}\n{content}\n\n")
            self.log_event(f"SRT saved: {path}", "#2ECC71")

    def open_subtitles_web(self):
        if not self.current_media:
            return
        query = urllib.parse.quote(os.path.basename(self.current_media).split('.')[0])
        url = f"https://www.opensubtitles.org/en/search/sublanguageid-all/moviename-{query}"
        QDesktopServices.openUrl(QUrl(url))

    def adjust_sub_sync(self):
        delay, ok = QInputDialog.getInt(self, "Subtitle Sync", "Offset Delay (ms):", self.sub_delay_ms, -5000, 5000, 50)
        if ok:
            self.sub_delay_ms = delay
            self.log_event(f"Subtitle synchronization offset: {delay}ms")

    def subtitle_style_dialog(self):
        color = QColorDialog.getColor(QColor(self.sub_color))
        if color.isValid():
            self.sub_color = color.name()
            self.subtitle_bar.setStyleSheet(f"color: {self.sub_color}; background-color: transparent;")

    # -------------------------------------------------------------------------
    # SMART ECOSYSTEM & VOICE CONTROL
    # -------------------------------------------------------------------------
    def toggle_voice_control(self):
        if self.voice_worker and self.voice_worker.isRunning():
            self.voice_worker.stop()
            self.voice_worker.wait()
            self.voice_worker = None
            self.log_event("Voice Control Deactivated", "#E74C3C")
        else:
            if not VOICE_AVAILABLE:
                QMessageBox.warning(self, "Missing Module", "Install SpeechRecognition: pip install SpeechRecognition pyaudio")
                return
            self.voice_worker = VoiceControlWorker()
            self.voice_worker.status_update.connect(self.log_event)
            self.voice_worker.command_detected.connect(self.handle_voice_command)
            self.voice_worker.start()

    def handle_voice_command(self, cmd):
        if cmd == "play":
            self.player.play()
        elif cmd == "pause":
            self.player.pause()
        elif cmd == "stop":
            self.player.stop()
        elif cmd == "volume_up":
            self.change_volume(min(500, self.slider_volume.value() + 20))
        elif cmd == "volume_down":
            self.change_volume(max(0, self.slider_volume.value() - 20))
        elif cmd == "mute":
            self.toggle_mute()
        elif cmd == "fullscreen":
            self.toggle_fullscreen()
        elif cmd == "next":
            self.next_playlist()

    def _cast_lan_ip(self):
        """Return the LAN address that another device on the same network can reach."""
        candidates = []
        try:
            # UDP connect discovers the preferred outbound interface without sending data.
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(1.0)
            sock.connect(("8.8.8.8", 80))
            candidates.append(sock.getsockname()[0])
            sock.close()
        except Exception:
            pass
        try:
            candidates.append(socket.gethostbyname(socket.gethostname()))
        except Exception:
            pass
        for ip in candidates:
            if ip and not ip.startswith("127."):
                return ip
        return "127.0.0.1"

    def _start_cast_http_server(self, media_path):
        """Serve one local media file over HTTP so Chromecast/TV can fetch it."""
        from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

        media_path = os.path.abspath(str(media_path))
        mime = mimetypes.guess_type(media_path)[0] or 'application/octet-stream'
        size = os.path.getsize(media_path)
        directory = os.path.dirname(media_path)
        filename = os.path.basename(media_path)

        # Stop a previous cast server, if any.
        old = getattr(self, '_cast_http_server', None)
        if old is not None:
            try:
                old.shutdown()
            except Exception:
                pass
            self._cast_http_server = None

        owner = self

        class CastHandler(BaseHTTPRequestHandler):
            server_version = 'OmniCast/1.0'
            protocol_version = 'HTTP/1.1'

            def log_message(self, fmt, *args):
                try:
                    owner.log_event('Cast HTTP: ' + (fmt % args), '#7FB3D5')
                except Exception:
                    pass

            def do_HEAD(self):
                self._serve_headers(send_body=False)

            def do_GET(self):
                self._serve_headers(send_body=True)

            def _serve_headers(self, send_body=True):
                path = urllib.parse.urlparse(self.path).path
                if path not in ('/media', '/media/'):
                    self.send_error(404)
                    return

                range_header = self.headers.get('Range')
                start_pos = 0
                end_pos = size - 1
                status = 200
                if range_header and range_header.startswith('bytes='):
                    try:
                        spec = range_header.split('=', 1)[1].split(',', 1)[0].strip()
                        a, b = (spec.split('-', 1) + [''])[:2]
                        if a:
                            start_pos = int(a)
                        elif b:
                            start_pos = max(0, size - int(b))
                        if b:
                            end_pos = min(size - 1, int(b))
                        if start_pos > end_pos or start_pos >= size:
                            self.send_response(416)
                            self.send_header('Content-Range', f'bytes */{size}')
                            self.end_headers()
                            return
                        status = 206
                    except Exception:
                        start_pos, end_pos, status = 0, size - 1, 200

                length = end_pos - start_pos + 1
                self.send_response(status)
                self.send_header('Content-Type', mime)
                self.send_header('Accept-Ranges', 'bytes')
                self.send_header('Content-Length', str(length))
                self.send_header('Content-Disposition', f'inline; filename="{filename}"')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Access-Control-Allow-Origin', '*')
                if status == 206:
                    self.send_header('Content-Range', f'bytes {start_pos}-{end_pos}/{size}')
                self.end_headers()

                if not send_body:
                    return
                with open(media_path, 'rb') as fh:
                    fh.seek(start_pos)
                    remaining = length
                    while remaining > 0:
                        chunk = fh.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        try:
                            self.wfile.write(chunk)
                        except (BrokenPipeError, ConnectionResetError):
                            break
                        remaining -= len(chunk)

        # Bind to all interfaces so a Smart TV on the LAN can reach it.
        server = ThreadingHTTPServer(('0.0.0.0', 0), CastHandler)
        server.daemon_threads = True
        port = int(server.server_address[1])
        self._cast_http_server = server
        self._cast_http_url = f'http://{self._cast_lan_ip()}:{port}/media'

        thread = threading.Thread(target=server.serve_forever, name='OmniCastHTTP', daemon=True)
        thread.start()
        self._cast_http_thread = thread
        return self._cast_http_url

    def _stop_cast_http_server(self):
        server = getattr(self, '_cast_http_server', None)
        if server is not None:
            try:
                server.shutdown()
                server.server_close()
            except Exception:
                pass
            self._cast_http_server = None
            self._cast_http_url = None

    def cast_to_chromecast(self):
        """Discover a Chromecast-capable TV and stream the current local media over LAN HTTP."""
        cast = _load_pychromecast()
        if cast is None:
            # The most common cause is installing into another Python environment.
            # Show the exact interpreter/path and the real import exception instead
            # of incorrectly claiming the package is simply absent.
            import importlib.util
            spec = importlib.util.find_spec('pychromecast')
            location = getattr(spec, 'origin', None) if spec else None
            pyexe = sys.executable
            err = repr(CAST_IMPORT_ERROR) if CAST_IMPORT_ERROR else 'module not found'
            QMessageBox.warning(
                self, 'Smart TV Casting',
                'PyChromecast could not be loaded by the Python interpreter running OmniPlayer.\n\n'
                f'Python: {pyexe}\n'
                f'PyChromecast location: {location or "not found on this interpreter"}\n'
                f'Import error: {err}\n\n'
                'To install it into THIS interpreter, run:\n'
                f'\"{pyexe}\" -m pip install -U pychromecast zeroconf\n\n'
                'Then restart OmniPlayer.'
            )
            try:
                self.log_event(f'PyChromecast load failed: {err} | Python={pyexe} | location={location}', '#E74C3C')
            except Exception:
                pass
            return

        media = getattr(self, 'current_media', None)
        if not media or not os.path.isfile(str(media)):
            # Local HTTP serving is required for Chromecast. Remote URLs can be cast
            # directly in a separate implementation, but local file playback is the
            # supported path here.
            QMessageBox.information(
                self, 'Smart TV Casting',
                'Load a local video file first.\n\n'
                'OmniPlayer will create a temporary LAN media URL that your TV can fetch.'
            )
            return

        media = os.path.abspath(str(media))
        ext = os.path.splitext(media)[1].lower()
        mime = mimetypes.guess_type(media)[0] or ''
        if not mime.startswith('video/'):
            QMessageBox.warning(self, 'Smart TV Casting', f'Unsupported video media type: {ext or "unknown"}')
            return

        self.log_event('Starting LAN media server for Smart TV casting…', '#F39C12')
        try:
            media_url = self._start_cast_http_server(media)
        except Exception as e:
            self.log_event(f'Cast server error: {e}', '#E74C3C')
            QMessageBox.critical(self, 'Smart TV Casting', f'Could not start the LAN media server.\n\n{e}')
            return

        self.log_event(f'Cast media URL: {media_url}', '#7FB3D5')

        def run_cast_discovery():
            browser = None
            try:
                chromecasts, browser = cast.get_chromecasts(timeout=5)
                if not chromecasts:
                    self.log_event('No Chromecast/Google Cast device found on the LAN.', '#E74C3C')
                    QMessageBox.information(
                        self, 'Smart TV Casting',
                        'No Chromecast-compatible TV was found.\n\n'
                        'Make sure the TV and this computer are on the same Wi-Fi/LAN and that Windows Firewall allows OmniPlayer/HTTP traffic.'
                    )
                    return

                # Prefer a device with a media controller and otherwise use the first discovered TV.
                device = next((d for d in chromecasts if getattr(d, 'media_controller', None)), chromecasts[0])
                device.wait(timeout=10)
                mc = device.media_controller
                mc.stop()
                time.sleep(0.25)
                mc.play_media(media_url, mime, title=os.path.basename(media))
                mc.block_until_active(timeout=15)
                self.log_event(f'Cast connected: {device.name} ← {os.path.basename(media)}', '#2ECC71')
                try:
                    self.log_event(f'Smart TV stream URL: {media_url}', '#7FB3D5')
                except Exception:
                    pass
            except Exception as e:
                self.log_event(f'Cast Error: {e}', '#E74C3C')
                QMessageBox.warning(self, 'Smart TV Casting', f'Casting failed.\n\n{e}')
            finally:
                try:
                    if browser is not None:
                        cast.discovery.stop_discovery(browser)
                except Exception:
                    pass

        threading.Thread(target=run_cast_discovery, name='OmniCastDiscovery', daemon=True).start()

    def toggle_dlna_server(self):
        if self.dlna_worker and self.dlna_worker.isRunning():
            self.dlna_worker.stop()
            self.dlna_worker = None
            self.log_event("DLNA Server stopped.", "#E74C3C")
        else:
            if not self.current_media:
                QMessageBox.information(self, "No Media", "Load a local file first.")
                return
            folder = os.path.dirname(self.current_media)
            self.dlna_worker = DLNAServerWorker(folder)
            self.dlna_worker.status_update.connect(self.log_event)
            self.dlna_worker.start()

    def fetch_metadata(self):
        if not self.current_media or self.current_media.startswith("http"):
            QMessageBox.information(self, "Local File Required", "Load a local media file.")
            return
        filename = os.path.basename(self.current_media).rsplit('.', 1)[0]
        self.log_event(f"Querying metadata for '{filename}'...", "#3498DB")
        self.tmdb_worker = TMDBWorker(filename, self.tmdb_api_key)
        self.tmdb_worker.metadata_ready.connect(self._show_metadata_dialog)
        self.tmdb_worker.error_occurred.connect(lambda e: self.log_event(e, "#F39C12"))
        self.tmdb_worker.start()

    @pyqtSlot(str)
    def _show_metadata_dialog(self, html_content):
        msg = QMessageBox(self)
        msg.setWindowTitle("Media Metadata")
        msg.setTextFormat(Qt.TextFormat.RichText)
        msg.setText(html_content)
        msg.exec()

    # -------------------------------------------------------------------------
    # PRO AUDIO DSP & FFMPEG TOOLS
    # -------------------------------------------------------------------------
    def show_equalizer(self):
        if not self.current_media or self.current_media.startswith("http"):
            return
        dialog = EqualizerDialog(self, self.audio_equalizer, self.current_preamp)
        if dialog.exec():
            eq_vals, preamp = dialog.get_values()
            self.audio_equalizer = eq_vals
            self.current_preamp = preamp
            self.apply_ffmpeg_eq(eq_vals, preamp)

    def apply_ffmpeg_eq(self, eq_vals, preamp):
        ext = self.current_media.rsplit('.', 1)[1] if '.' in self.current_media else 'mp4'
        out_path = self.current_media.rsplit('.', 1)[0] + f"_Remastered.{ext}"
        self.log_event("Rendering Remastered Audio with 10-Band EQ...", "#F39C12")
        self.player.pause()

        bands = [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000]
        filters = []
        if preamp != 1.0:
            filters.append(f"volume={preamp}")
        for i, freq in enumerate(bands):
            gain = eq_vals[i]
            if gain != 0:
                filters.append(f"equalizer=f={freq}:width_type=o:width=1:g={gain}")

        af_arg = ",".join(filters) if filters else "copy"
        cmd = ["ffmpeg", "-y", "-i", self.current_media, "-vcodec", "copy"]
        if af_arg != "copy":
            cmd.extend(["-af", af_arg])
        else:
            cmd.extend(["-acodec", "copy"])
        cmd.append(out_path)

        worker = FFmpegWorker(cmd, "Audio Remastering (EQ)")
        self.run_bg_task(worker)

    def boost_audio(self):
        if not self.current_media or self.current_media.startswith("http"):
            return
        ext = self.current_media.rsplit('.', 1)[1] if '.' in self.current_media else 'mp4'
        out_path = self.current_media.rsplit('.', 1)[0] + f"_LOUD.{ext}"
        self.log_event("Rendering 200% Volume Boost Copy...", "#F39C12")
        
        cmd = ["ffmpeg", "-y", "-i", self.current_media, "-vcodec", "copy", "-af", "volume=2.0", out_path]
        worker = FFmpegWorker(cmd, "Volume Boost 200%")
        self.run_bg_task(worker)

    def isolate_audio_stems(self):
        if not self.current_media or self.current_media.startswith("http"):
            return
        worker = DemucsWorker(self.current_media)
        self.run_bg_task(worker)

    def rip_mp3(self):
        if not self.current_media:
            return
        out_path = os.path.join(os.path.expanduser("~"), "Desktop", f"audio_{int(time.time())}.mp3")
        cmd = ["ffmpeg", "-y", "-i", self.current_media, "-q:a", "0", "-map", "a", out_path]
        worker = FFmpegWorker(cmd, "MP3 Extraction")
        self.run_bg_task(worker)

    def create_gif(self):
        if not self.current_media:
            return
        curr_sec = self.player.position() / 1000.0
        out_path = os.path.join(os.path.expanduser("~"), "Desktop", f"clip_{int(time.time())}.gif")
        cmd = ["ffmpeg", "-y", "-ss", str(curr_sec), "-t", "5", "-i", self.current_media,
               "-vf", "fps=15,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse",
               "-loop", "0", out_path]
        worker = FFmpegWorker(cmd, "5s GIF Generator")
        self.run_bg_task(worker)

    def run_ffmpeg_trim(self):
        if not self.current_media:
            return
        dur_sec = self.player.duration() / 1000.0
        dialog = TrimDialog(dur_sec, self)
        if dialog.exec():
            start_s, len_s = dialog.get_range()
            ext = self.current_media.rsplit('.', 1)[1] if '.' in self.current_media else 'mp4'
            out_path = self.current_media.rsplit('.', 1)[0] + f"_Trim_{start_s}s.{ext}"
            cmd = ["ffmpeg", "-y", "-ss", str(start_s), "-t", str(len_s), "-i", self.current_media, "-c", "copy", out_path]
            worker = FFmpegWorker(cmd, "Lossless Trimmer")
            self.run_bg_task(worker)

    def generate_contact_sheet(self):
        if not self.current_media:
            return
        out_path = os.path.join(os.path.expanduser("~"), "Desktop", f"sheet_{int(time.time())}.jpg")
        self.log_event("Generating 4x4 Thumbnail Contact Sheet...", "#3498DB")
        cmd = ["ffmpeg", "-y", "-i", self.current_media, "-vf", "fps=1/60,scale=320:-1,tile=4x4", out_path]
        worker = FFmpegWorker(cmd, "Contact Sheet")
        self.run_bg_task(worker)

    def run_esrgan(self):
        if not self.current_media:
            return
        exe_path = resource_path("realesrgan-ncnn-vulkan.exe")
        if not os.path.exists(exe_path):
            QMessageBox.critical(self, "Missing Upscaler", "Please download 'realesrgan-ncnn-vulkan.exe' and place it in the same folder as this app.")
            return

        worker = ESRGANWorker(self.current_media, exe_path)
        self.run_bg_task(worker, show_progress=True)

    # -------------------------------------------------------------------------
    # SECURITY VAULT & ZERO-TRACE PLAYBACK
    # -------------------------------------------------------------------------
    def encrypt_file(self):
        if not CRYPTO_AVAILABLE:
            QMessageBox.critical(self, "Missing Module", "Install cryptography: pip install cryptography")
            return
        filepath, _ = QFileDialog.getOpenFileName(self, "Select Video to Encrypt", "", "Media (*.*)")
        if not filepath:
            return
        pwd, ok = QInputDialog.getText(self, "Secure Vault", "Enter Encryption Password:", QLineEdit.EchoMode.Password)
        if not ok or not pwd:
            return
        try:
            salt, nonce = os.urandom(16), os.urandom(12)
            kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000)
            cipher = Cipher(algorithms.AES(kdf.derive(pwd.encode())), modes.GCM(nonce))
            encryptor = cipher.encryptor()
            enc_path = filepath + ".tjz"
            with open(filepath, "rb") as f_in, open(enc_path, "wb") as f_out:
                f_out.write(salt)
                f_out.write(nonce)
                while chunk := f_in.read(64 * 1024):
                    f_out.write(encryptor.update(chunk))
                f_out.write(encryptor.finalize())
                f_out.write(encryptor.tag)
            self.log_event("File encrypted into Secure Vault (.tjz)", "#2ECC71")
            QMessageBox.information(self, "Vault Secured", f"Saved as:\n{enc_path}")
        except Exception as e:
            self.log_event(f"Encryption Failed: {e}", "#E74C3C")

    def play_encrypted_media_prompt(self):
        filepath, _ = QFileDialog.getOpenFileName(self, "Unlock Vault File", "", "Vault (*.tjz)")
        if filepath:
            self.play_encrypted_media_direct(filepath)

    def play_encrypted_media_direct(self, filepath):
        if not CRYPTO_AVAILABLE:
            return
        pwd, ok = QInputDialog.getText(self, "Unlock Vault", "Decryption Password:", QLineEdit.EchoMode.Password)
        if not ok or not pwd:
            return
        try:
            with open(filepath, "rb") as f:
                file_data = f.read()
            salt, nonce, ciphertext, tag = file_data[:16], file_data[16:28], file_data[28:-16], file_data[-16:]
            kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000)
            decryptor = Cipher(algorithms.AES(kdf.derive(pwd.encode())), modes.GCM(nonce, tag)).decryptor()
            plaintext = decryptor.update(ciphertext) + decryptor.finalize()

            self._reset_player()
            self.is_video = True
            self.ram_array = QByteArray(plaintext)
            self.ram_buffer = QBuffer(self.ram_array)
            self.ram_buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            self.player.setSourceDevice(self.ram_buffer, QUrl())
            self.player.play()
            self.log_event("Vault Decrypted directly into RAM. Zero Disk Trace.", "#2ECC71")
        except Exception:
            QMessageBox.critical(self, "Access Denied", "Incorrect password or corrupted vault payload.")

    def secure_delete(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select file to securely wipe", "", "All (*.*)")
        if not path:
            return
        if QMessageBox.question(self, "Secure Wipe", f"Permanently shred {os.path.basename(path)}?") == QMessageBox.StandardButton.Yes:
            try:
                with open(path, 'rb+') as f:
                    f.write(os.urandom(os.path.getsize(path)))
                os.remove(path)
                self.log_event(f"Securely shredded: {path}", "#E74C3C")
            except Exception as e:
                self.log_event(f"Wipe Failed: {e}", "#E74C3C")

    # -------------------------------------------------------------------------
    # STREAMS & URLS
    # -------------------------------------------------------------------------
    def open_network_stream(self):
        url, ok = QInputDialog.getText(self, "Open Stream", "Enter URL (http, rtsp, m3u8):")
        if ok and url:
            self._play_target(url)

    def open_youtube_stream(self):
        if not YTDLP_AVAILABLE:
            QMessageBox.critical(self, "Missing Module", "Install yt-dlp: pip install yt-dlp")
            return
        url, ok = QInputDialog.getText(self, "YouTube URL", "Enter YouTube Link:")
        if ok and url:
            self.log_event("Extracting stream URL via yt-dlp...", "#F39C12")
            def fetch_yt():
                try:
                    with yt_dlp.YoutubeDL({'format': 'bestvideo+bestaudio/best', 'quiet': True}) as ydl:
                        info = ydl.extract_info(url, download=False)
                        video_url = info['url']
                        from PyQt6.QtCore import QMetaObject, Qt
                        QMetaObject.invokeMethod(self, "_play_youtube_stream", Qt.ConnectionType.QueuedConnection, QUrl(video_url))
                except Exception as e:
                    self.log_event(f"YouTube Error: {e}", "#E74C3C")
            threading.Thread(target=fetch_yt, daemon=True).start()

    @pyqtSlot(QUrl)
    def _play_youtube_stream(self, url):
        self._reset_player()
        self.current_media = url.toString()
        self.is_video = True
        self.setWindowTitle("OmniPlayer Pro | YouTube Stream")
        self.player.setSource(url)
        self.player.play()

    def take_screenshot(self):
        if not self.is_video:
            return
        pixmap = self.video_widget.grab()
        if not pixmap.isNull():
            fname = f"screenshot_{int(time.time())}.png"
            save_path = os.path.join(self.screenshot_path, fname)
            pixmap.save(save_path, "PNG")
            self.log_event(f"Screenshot saved: {save_path}", "#2ECC71")
            QMessageBox.information(self, "Screenshot", f"Saved to {save_path}")

    def show_file_info(self):
        if not self.current_media:
            return
        try:
            cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", self.current_media]
            result = subprocess.run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
            info = json.loads(result.stdout)
            msg = f"File: {os.path.basename(self.current_media)}\nDuration: {info['format'].get('duration', 'N/A')}s"
            QMessageBox.information(self, "File Info", msg)
        except Exception:
            pass

    def show_about(self):
        about_text = "<h2>OmniPlayer Pro | Ultimate Edition</h2><p><b>Version:</b> 19.1</p><p><b>Engine:</b> PyQt6, FFmpeg, faster-whisper, PyChromecast, PyPresence</p>"
        QMessageBox.about(self, "About", about_text)

    def show_shortcuts(self):
        shortcuts = "Space – Play/Pause\nLeft/Right – Skip -/+10s\nF – Fullscreen\nP – Picture-in-Picture Mode\nEsc – Exit Fullscreen/PiP\nM – Mute\nCtrl+V – Toggle Voice Commands\nCtrl+K – Cast to Smart TV\nCtrl+I – Fetch Movie Metadata"
        QMessageBox.information(self, "Keyboard Shortcuts", shortcuts)

    def apply_theme(self, name, bg_color):
        self.current_theme = name
        self.setStyleSheet(f"background-color: {bg_color}; color: white;")

    # -------------------------------------------------------------------------
    # SETTINGS LOGIC
    # -------------------------------------------------------------------------
    def save_settings(self):
        self.settings.setValue("accent_color", self.accent_color)
        self.settings.setValue("volume", self.slider_volume.value())
        self.settings.setValue("sub_delay", self.sub_delay_ms)
        self.settings.setValue("sub_font_size", self.sub_font_size)
        self.settings.setValue("sub_color", self.sub_color)
        self.settings.setValue("theme", self.current_theme)
        if self.current_media and self.player.position() > 0:
            self.resume_data[self.current_media] = self.player.position()
        self.settings.setValue("resume_data", json.dumps(self.resume_data))
        self.settings.setValue("playlist", json.dumps(self.playlist))
        self.settings.setValue("bookmarks", json.dumps(self.bookmarks))

    def load_settings(self):
        self.accent_color = self.settings.value("accent_color", "#3498DB")
        vol = int(self.settings.value("volume", 100))
        self.sub_delay_ms = int(self.settings.value("sub_delay", 0))
        self.sub_font_size = int(self.settings.value("sub_font_size", 22))
        self.sub_color = self.settings.value("sub_color", "#F1C40F")
        self.current_theme = self.settings.value("theme", "Dark")

        try:
            self.resume_data = json.loads(self.settings.value("resume_data", "{}"))
        except Exception:
            self.resume_data = {}
        try:
            self.playlist = json.loads(self.settings.value("playlist", "[]"))
        except Exception:
            self.playlist = []
        for f in self.playlist:
            self.playlist_widget.addItem(os.path.basename(f))
        try:
            self.bookmarks = json.loads(self.settings.value("bookmarks", "[]"))
        except Exception:
            self.bookmarks = []
        for pos, name in self.bookmarks:
            self.bookmark_list.addItem(f"{name} ({self._format_time(pos)})")

        if hasattr(self, 'slider_volume'):
            self.slider_volume.setValue(vol)
            self.change_volume(vol)

    def closeEvent(self, event):
        self.save_settings()
        if self.active_bg_worker and hasattr(self.active_bg_worker, 'stop'):
            self.active_bg_worker.stop()
        if self.voice_worker:
            self.voice_worker.stop()
        if self.telemetry_worker:
            self.telemetry_worker.stop()
        if self.dlna_worker:
            self.dlna_worker.stop()
        event.accept()

    # -------------------------------------------------------------------------
    # MASTER TICK (SYNCHRONIZATION ENGINE)
    # -------------------------------------------------------------------------
    def master_tick(self):
        is_playing = (self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        
        if not self.is_video and is_playing:
            self.visualizer.update_visualizer(True)
            if self.visualizer.isHidden():
                self.visualizer.show()
        else:
            if not self.visualizer.isHidden():
                self.visualizer.hide()

        pos = self.player.position()
        if self.show_stats:
            txt = f"Time: {pos}ms | Dur: {self.player.duration()}ms\nSource: {os.path.basename(str(self.current_media))}"
            if self.hw_stats:
                txt += f"\n\n[RTX Hardware Telemetry]\nVRAM: {self.hw_stats.get('vram_used', 0):.1f}MB / {self.hw_stats.get('vram_total', 0):.1f}MB"
                txt += f"\nGPU Temp: {self.hw_stats.get('gpu_temp', 0)}°C"
                txt += f"\nGPU Load: {self.hw_stats.get('gpu_util', 0)}%"
            self.lbl_stats.setText(txt)

        if self.ab_loop_start != -1 and self.ab_loop_end != -1:
            if pos >= self.ab_loop_end:
                self.player.setPosition(self.ab_loop_start)

        if self.is_video and self.generated_subs:
            curr_sec = (pos + self.sub_delay_ms) / 1000.0
            active_native = ""
            active_trans = ""

            for start, end, text, trans in self.generated_subs:
                if start <= curr_sec <= end:
                    active_native = text
                    active_trans = trans
                    break

            disp_mode = self.display_mode_combo.currentIndex()
            
            # 0: Both, 1: Native Only, 2: English Only
            if disp_mode == 1:
                native_disp = active_native if active_native else active_trans
                trans_disp = ""
            elif disp_mode == 2:
                native_disp = active_trans if active_trans else active_native
                trans_disp = ""
            else:
                native_disp = active_native
                trans_disp = f"🌐 {active_trans}" if active_trans else ""

            if self.subtitle_bar.text() != native_disp:
                self.subtitle_bar.setText(native_disp)
            if self.subtitle_bar_top.text() != trans_disp:
                self.subtitle_bar_top.setText(trans_disp)
        else:
            if self.subtitle_bar.text() != "":
                self.subtitle_bar.setText("")
            if self.subtitle_bar_top.text() != "":
                self.subtitle_bar_top.setText("")

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if path.endswith('.tjz'):
                self.play_encrypted_media_direct(path)
            else:
                self._play_target(path)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space:
            self.toggle_play()
        elif event.key() == Qt.Key.Key_Right:
            self.skip_forward()
        elif event.key() == Qt.Key.Key_Left:
            self.skip_backward()
        elif event.key() == Qt.Key.Key_F:
            self.toggle_fullscreen()
        elif event.key() == Qt.Key.Key_P:
            self.toggle_pip_mode()
        elif event.key() == Qt.Key.Key_M:
            self.toggle_mute()
        elif event.key() == Qt.Key.Key_F9:
            self.toggle_stats()
        elif event.key() == Qt.Key.Key_Escape:
            if self.is_pip_mode:
                self.toggle_pip_mode()
            if self.is_fullscreen:
                self.toggle_fullscreen()
        elif event.modifiers() == Qt.KeyboardModifier.ControlModifier:
            if event.key() == Qt.Key.Key_V:
                self.toggle_voice_control()
            elif event.key() == Qt.Key.Key_K:
                self.cast_to_chromecast()
            elif event.key() == Qt.Key.Key_I:
                self.fetch_metadata()
            elif event.key() == Qt.Key.Key_G:
                self.jump_to_time()
            elif event.key() == Qt.Key.Key_B:
                self.add_bookmark()
            elif event.key() == Qt.Key.Key_R:
                self.set_playback_speed()
        else:
            super().keyPressEvent(event)



# =============================================================================
# OMNIPLAYER PRO 20.x — ADVANCED FEATURE PACK
# -----------------------------------------------------------------------------
# This extension intentionally preserves the original architecture and adds
# 150+ practical commands without replacing the existing playback/AI stack.
# Most media-processing operations delegate to FFmpeg asynchronously.
# =============================================================================
import shutil
import re
import datetime as _dt
import pathlib as _pathlib
import mimetypes as _mimetypes
import csv as _csv
import statistics as _statistics

# Remove the embedded Hugging Face credential from the original source.
# Users can provide HF_TOKEN through the environment when required.
os.environ.pop("HF_TOKEN", None)


def _adv_current_file(self):
    p = self.current_media
    if not p or str(p).startswith(("http://", "https://")):
        return None
    return str(p)


def _adv_require_file(self):
    p = _adv_current_file(self)
    if not p or not os.path.exists(p):
        QMessageBox.information(self, "No Local Media", "Load a local media file first.")
        return None
    return p


def _adv_run_ffmpeg(self, args, task, output=None, pause=True):
    p = _adv_require_file(self)
    if not p:
        return
    if pause:
        self.player.pause()
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "warning", "-i", p] + list(args)
    if output:
        cmd.append(output)
    self.run_bg_task(FFmpegWorker(cmd, task), show_progress=False)
    return output


def _adv_output(self, suffix, ext=None):
    p = _adv_require_file(self)
    if not p:
        return None
    root, old_ext = os.path.splitext(p)
    return root + suffix + (ext if ext else old_ext)


def _adv_dialog_text(self, title, label, default=""):
    value, ok = QInputDialog.getText(self, title, label, QLineEdit.EchoMode.Normal, default)
    return value.strip() if ok else None


def _adv_ffprobe(self, path=None):
    path = path or _adv_require_file(self)
    if not path:
        return None
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True, creationflags=CREATE_NO_WINDOW,
            timeout=30
        )
        if r.returncode != 0:
            return None
        return json.loads(r.stdout)
    except Exception as e:
        self.log_event(f"ffprobe error: {e}", "#E74C3C")
        return None


def _adv_save_text(self, path, text):
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        self.log_event(f"Saved: {path}", "#2ECC71")
        return True
    except Exception as e:
        QMessageBox.warning(self, "Save Error", str(e))
        return False


def _adv_hash_file(self, path, algorithm="sha256"):
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------- Playback --------------------------------------

def _adv_skip(self, seconds):
    self.player.setPosition(max(0, min(self.player.duration(), self.player.position() + int(seconds * 1000))))


def _adv_jump_percent(self, pct):
    if self.player.duration() > 0:
        self.player.setPosition(int(self.player.duration() * max(0, min(100, pct)) / 100))


def _adv_toggle_playback_rate(self, rate):
    self.player.setPlaybackRate(rate)
    self.playback_speed = rate
    idx = self.speed_combo.findData(rate)
    if idx >= 0:
        self.speed_combo.setCurrentIndex(idx)
    self.log_event(f"Playback rate: {rate}x", "#3498DB")


def _adv_toggle_always_on_top(self):
    self._adv_topmost = not getattr(self, "_adv_topmost", False)
    flags = self.windowFlags()
    if self._adv_topmost:
        flags |= Qt.WindowType.WindowStaysOnTopHint
    else:
        flags &= ~Qt.WindowType.WindowStaysOnTopHint
    self.setWindowFlags(flags)
    self.show()


def _adv_toggle_pause_after(self):
    if getattr(self, "_adv_pause_timer", None) and self._adv_pause_timer.isActive():
        self._adv_pause_timer.stop()
        self.log_event("Scheduled pause cancelled.", "#F39C12")
        return
    sec, ok = QInputDialog.getInt(self, "Schedule Pause", "Pause after seconds:", 60, 1, 86400)
    if ok:
        self._adv_pause_timer = QTimer(self)
        self._adv_pause_timer.setSingleShot(True)
        self._adv_pause_timer.timeout.connect(self.player.pause)
        self._adv_pause_timer.start(sec * 1000)
        self.log_event(f"Pause scheduled in {sec}s.", "#2ECC71")


def _adv_play_from_start(self):
    self.player.setPosition(0)
    self.player.play()


def _adv_resume_last(self):
    if self.current_media and self.current_media in self.resume_data:
        self.player.setPosition(int(self.resume_data[self.current_media]))
        self.player.play()
    else:
        self.player.play()




# ----------------------------- Playlist --------------------------------------

def _adv_playlist_add_folder(self):
    folder = QFileDialog.getExistingDirectory(self, "Add Folder to Playlist")
    if not folder:
        return
    exts = {".mp3",".wav",".flac",".aac",".ogg",".m4a",".wma",".mp4",".mkv",".avi",".mov",".webm",".m4v",".ts"}
    files = []
    for root, _, names in os.walk(folder):
        for n in names:
            if os.path.splitext(n)[1].lower() in exts:
                files.append(os.path.join(root, n))
    files.sort(key=str.lower)
    for f in files:
        if f not in self.playlist:
            self.playlist.append(f)
            self.playlist_widget.addItem(os.path.basename(f))
    self.log_event(f"Added {len(files)} media files from folder.", "#2ECC71")


def _adv_playlist_dedupe(self):
    seen = set()
    new = []
    for p in self.playlist:
        key = os.path.normcase(os.path.abspath(p))
        if key not in seen:
            seen.add(key)
            new.append(p)
    self.playlist = new
    self.playlist_widget.clear()
    self.playlist_widget.addItems([os.path.basename(p) for p in new])
    self.log_event("Playlist duplicates removed.", "#2ECC71")


def _adv_playlist_sort_name(self):
    self.playlist.sort(key=lambda p: os.path.basename(p).lower())
    self.playlist_widget.clear()
    self.playlist_widget.addItems([os.path.basename(p) for p in self.playlist])


def _adv_playlist_reverse(self):
    self.playlist.reverse()
    self.playlist_widget.clear()
    self.playlist_widget.addItems([os.path.basename(p) for p in self.playlist])


def _adv_playlist_randomize(self):
    random.shuffle(self.playlist)
    self.playlist_widget.clear()
    self.playlist_widget.addItems([os.path.basename(p) for p in self.playlist])
    self.log_event("Playlist randomized.", "#2ECC71")


def _adv_playlist_export(self):
    path, _ = QFileDialog.getSaveFileName(self, "Export Playlist", "playlist.m3u8", "M3U8 (*.m3u8)")
    if not path:
        return
    lines = ["#EXTM3U"] + self.playlist
    _adv_save_text(self, path, "\n".join(lines) + "\n")


def _adv_playlist_import(self):
    path, _ = QFileDialog.getOpenFileName(self, "Import Playlist", "", "Playlist (*.m3u *.m3u8 *.txt)")
    if not path:
        return
    try:
        with open(path, encoding="utf-8", errors="ignore") as f:
            entries = [x.strip() for x in f if x.strip() and not x.startswith("#")]
        base = os.path.dirname(path)
        for item in entries:
            p = item if os.path.isabs(item) else os.path.abspath(os.path.join(base, item))
            if os.path.exists(p) and p not in self.playlist:
                self.playlist.append(p)
                self.playlist_widget.addItem(os.path.basename(p))
        self.log_event("Playlist imported.", "#2ECC71")
    except Exception as e:
        QMessageBox.warning(self, "Playlist Error", str(e))


def _adv_playlist_remove_missing(self):
    old = len(self.playlist)
    self.playlist = [p for p in self.playlist if os.path.exists(p) or str(p).startswith(("http://","https://"))]
    self.playlist_widget.clear()
    self.playlist_widget.addItems([os.path.basename(p) for p in self.playlist])
    self.log_event(f"Removed {old-len(self.playlist)} missing playlist entries.", "#F39C12")


def _adv_queue_current(self):
    p = _adv_current_file(self)
    if p and p not in self.playlist:
        self.playlist.append(p)
        self.playlist_widget.addItem(os.path.basename(p))


def _adv_playlist_play_first(self):
    if self.playlist:
        self.playlist_index = 0
        self._play_target(self.playlist[0])


def _adv_playlist_play_last(self):
    if self.playlist:
        self.playlist_index = len(self.playlist)-1
        self._play_target(self.playlist[-1])


# ----------------------------- Media analysis --------------------------------

def _adv_media_report(self):
    info = _adv_ffprobe(self)
    if not info:
        return
    fmt = info.get("format", {})
    streams = info.get("streams", [])
    rows = [
        f"File: {os.path.basename(fmt.get('filename',''))}",
        f"Format: {fmt.get('format_name','N/A')}",
        f"Duration: {fmt.get('duration','N/A')} s",
        f"Size: {int(fmt.get('size',0))/1048576:.2f} MiB",
        f"Bit rate: {fmt.get('bit_rate','N/A')} bps",
        f"Streams: {len(streams)}",
    ]
    for i, s in enumerate(streams, 1):
        rows.append(f"Stream {i}: {s.get('codec_type')} / {s.get('codec_name')} / "
                    f"{s.get('width','')}x{s.get('height','')} / {s.get('sample_rate','')}Hz")
    dlg = QDialog(self)
    dlg.setWindowTitle("Advanced Media Report")
    dlg.resize(720, 520)
    lay = QVBoxLayout(dlg)
    txt = QTextEdit()
    txt.setReadOnly(True)
    txt.setPlainText("\n".join(rows))
    lay.addWidget(txt)
    dlg.exec()


def _adv_export_probe_json(self):
    p = _adv_require_file(self)
    if not p:
        return
    info = _adv_ffprobe(self, p)
    if not info:
        return
    out, _ = QFileDialog.getSaveFileName(self, "Export ffprobe JSON",
                                         os.path.splitext(p)[0] + ".json", "JSON (*.json)")
    if out:
        _adv_save_text(self, out, json.dumps(info, indent=2, ensure_ascii=False))


def _adv_show_stream_table(self):
    info = _adv_ffprobe(self)
    if not info:
        return
    streams = info.get("streams", [])
    dlg = QDialog(self)
    dlg.setWindowTitle("Stream Inspector")
    dlg.resize(850, 420)
    lay = QVBoxLayout(dlg)
    table = QTableWidget(len(streams), 6)
    table.setHorizontalHeaderLabels(["#", "Type", "Codec", "Language", "Resolution", "Bitrate"])
    for r, s in enumerate(streams):
        vals = [s.get("index",""), s.get("codec_type",""), s.get("codec_name",""),
                s.get("tags",{}).get("language",""), 
                f"{s.get('width','')}x{s.get('height','')}" if s.get("width") else "",
                s.get("bit_rate","")]
        for c, v in enumerate(vals):
            table.setItem(r, c, QTableWidgetItem(str(v)))
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    lay.addWidget(table)
    dlg.exec()


def _adv_hash_current(self):
    p = _adv_require_file(self)
    if not p:
        return
    digest = _adv_hash_file(self, p)
    QApplication.clipboard().setText(digest)
    QMessageBox.information(self, "SHA-256", digest)


def _adv_verify_hash(self):
    p = _adv_require_file(self)
    if not p:
        return
    expected = _adv_dialog_text(self, "Verify Hash", "Expected SHA-256:")
    if expected:
        actual = _adv_hash_file(self, p)
        QMessageBox.information(self, "Hash Result",
                                "MATCH" if actual.lower() == expected.lower().strip() else
                                f"MISMATCH\nActual: {actual}")


def _adv_file_timestamps(self):
    p = _adv_require_file(self)
    if not p:
        return
    st = os.stat(p)
    msg = (f"Created: {_dt.datetime.fromtimestamp(st.st_ctime)}\n"
           f"Modified: {_dt.datetime.fromtimestamp(st.st_mtime)}\n"
           f"Accessed: {_dt.datetime.fromtimestamp(st.st_atime)}")
    QMessageBox.information(self, "File Timestamps", msg)


def _adv_file_permissions(self):
    p = _adv_require_file(self)
    if not p:
        return
    QMessageBox.information(self, "Permissions", oct(os.stat(p).st_mode & 0o777))


def _adv_open_containing_folder(self):
    p = _adv_require_file(self)
    if p:
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(p)))


def _adv_copy_path(self):
    p = self.current_media
    if p:
        QApplication.clipboard().setText(str(p))
        self.log_event("Media path copied to clipboard.", "#2ECC71")


def _adv_copy_filename(self):
    p = self.current_media
    if p:
        QApplication.clipboard().setText(os.path.basename(str(p)))


def _adv_rename_current(self):
    p = _adv_require_file(self)
    if not p:
        return
    name = _adv_dialog_text(self, "Rename Media", "New filename:", os.path.basename(p))
    if not name:
        return
    target = os.path.join(os.path.dirname(p), name)
    try:
        os.rename(p, target)
        self.current_media = target
        self.setWindowTitle(f"OmniPlayer Pro | {os.path.basename(target)}")
        self.log_event("Media renamed.", "#2ECC71")
    except Exception as e:
        QMessageBox.warning(self, "Rename Failed", str(e))


def _adv_duplicate_current(self):
    p = _adv_require_file(self)
    if not p:
        return
    root, ext = os.path.splitext(p)
    target = root + "_copy" + ext
    try:
        shutil.copy2(p, target)
        self.log_event(f"Duplicate created: {target}", "#2ECC71")
    except Exception as e:
        QMessageBox.warning(self, "Copy Failed", str(e))


# ----------------------------- Video transforms ------------------------------

def _adv_transcode(self, codec, ext, suffix):
    out = _adv_output(self, suffix, ext)
    if not out:
        return
    if codec == "h264":
        args = ["-c:v","libx264","-preset","medium","-crf","20","-c:a","aac","-b:a","192k"]
    elif codec == "hevc":
        args = ["-c:v","libx265","-preset","medium","-crf","24","-c:a","aac","-b:a","192k"]
    elif codec == "vp9":
        args = ["-c:v","libvpx-vp9","-crf","30","-b:v","0","-c:a","libopus","-b:a","160k"]
    else:
        args = ["-c:v","libaom-av1","-crf","32","-b:v","0","-c:a","libopus","-b:a","160k"]
    _adv_run_ffmpeg(self, args, f"Transcode {codec.upper()}", out)


def _adv_remux(self, ext):
    out = _adv_output(self, "_Remuxed", ext)
    if out:
        _adv_run_ffmpeg(self, ["-c","copy"], f"Remux to {ext}", out)


def _adv_filter_video(self, filter_expr, suffix):
    out = _adv_output(self, suffix, ".mp4")
    if out:
        _adv_run_ffmpeg(self, ["-vf", filter_expr, "-c:v","libx264","-crf","20","-c:a","copy"], 
                        f"Video filter {suffix}", out)


def _adv_extract_frames(self):
    p = _adv_require_file(self)
    if not p:
        return
    folder = QFileDialog.getExistingDirectory(self, "Select Frame Output Folder")
    if folder:
        cmd = ["ffmpeg","-y","-i",p,"-vf","fps=1",os.path.join(folder,"frame_%06d.jpg")]
        self.run_bg_task(FFmpegWorker(cmd, "Frame Extraction"))


def _adv_extract_frame_at_current(self):
    p = _adv_require_file(self)
    if not p:
        return
    out = os.path.join(os.path.dirname(p), f"frame_{int(self.player.position()/1000)}s.png")
    cmd = ["ffmpeg","-y","-ss",str(self.player.position()/1000),"-i",p,"-frames:v","1",out]
    self.run_bg_task(FFmpegWorker(cmd, "Current Frame Capture"))


def _adv_video_thumbnail(self):
    p = _adv_require_file(self)
    if not p:
        return
    out = _adv_output(self, "_thumbnail", ".jpg")
    cmd = ["ffmpeg","-y","-ss","0","-i",p,"-frames:v","1","-q:v","2",out]
    self.run_bg_task(FFmpegWorker(cmd, "Thumbnail Generation"))


def _adv_change_fps(self):
    fps, ok = QInputDialog.getDouble(self, "Frame Rate", "Target FPS:", 30, 1, 240, 2)
    if ok:
        _adv_filter_video(self, f"fps={fps:g}", "_FPS")


def _adv_scale_video(self):
    text = _adv_dialog_text(self, "Scale Video", "Width:Height (e.g. 1920:1080):", "1920:1080")
    if text and re.match(r"^\d+:\d+$", text):
        _adv_filter_video(self, f"scale={text}", "_Scaled")


def _adv_rotate_video(self):
    choice, ok = QInputDialog.getItem(self, "Rotate", "Rotation:", ["90° CW","90° CCW","180°"], 0, False)
    if ok:
        filt = {"90° CW":"transpose=1","90° CCW":"transpose=2","180°":"transpose=1,transpose=1"}[choice]
        _adv_filter_video(self, filt, "_Rotated")


def _adv_deinterlace(self):
    _adv_filter_video(self, "yadif", "_Deinterlaced")


def _adv_grayscale(self):
    _adv_filter_video(self, "hue=s=0", "_Grayscale")


def _adv_sepia(self):
    _adv_filter_video(self, "colorchannelmixer=.393:.769:.189:0:.349:.686:.168:0:.272:.534:.131", "_Sepia")


def _adv_sharpen(self):
    _adv_filter_video(self, "unsharp=5:5:1.0:5:5:0.0", "_Sharpened")


def _adv_blur(self):
    _adv_filter_video(self, "boxblur=2:1", "_Blurred")


def _adv_flip_h(self):
    _adv_filter_video(self, "hflip", "_MirrorH")


def _adv_flip_v(self):
    _adv_filter_video(self, "vflip", "_MirrorV")


def _adv_denoise_video(self):
    _adv_filter_video(self, "hqdn3d=1.5:1.5:6:6", "_Denoised")


def _adv_video_fade(self):
    _adv_filter_video(self, "fade=t=in:st=0:d=1,fade=t=out:st=0:d=1", "_Faded")


def _adv_crop_video(self):
    text = _adv_dialog_text(self, "Crop", "FFmpeg crop=w:h:x:y:", "iw:ih:0:0")
    if text and re.match(r"^[^;]+:[^;]+:[^;]+:[^;]+$", text):
        _adv_filter_video(self, f"crop={text}", "_Cropped")


# ----------------------------- Audio processing ------------------------------

def _adv_audio_filter(self, filt, suffix):
    out = _adv_output(self, suffix, ".m4a")
    if out:
        _adv_run_ffmpeg(self, ["-vn","-af",filt,"-c:a","aac","-b:a","256k"], f"Audio {suffix}", out)


def _adv_audio_normalize(self):
    _adv_audio_filter(self, "loudnorm=I=-16:TP=-1.5:LRA=11", "_Normalized")


def _adv_audio_mono(self):
    out = _adv_output(self, "_Mono", ".wav")
    if out:
        _adv_run_ffmpeg(self, ["-vn","-ac","1","-c:a","pcm_s16le"], "Mono Audio", out)


def _adv_audio_stereo(self):
    out = _adv_output(self, "_Stereo", ".wav")
    if out:
        _adv_run_ffmpeg(self, ["-vn","-ac","2","-c:a","pcm_s16le"], "Stereo Audio", out)


def _adv_audio_lowpass(self):
    _adv_audio_filter(self, "lowpass=f=12000", "_Lowpass")


def _adv_audio_highpass(self):
    _adv_audio_filter(self, "highpass=f=80", "_Highpass")


def _adv_audio_bass(self):
    _adv_audio_filter(self, "bass=g=6:f=100", "_BassBoost")


def _adv_audio_treble(self):
    _adv_audio_filter(self, "treble=g=5:f=4000", "_TrebleBoost")


def _adv_audio_compressor(self):
    _adv_audio_filter(self, "acompressor=threshold=-18dB:ratio=3:attack=20:release=250", "_Compressed")


def _adv_audio_limiter(self):
    _adv_audio_filter(self, "alimiter=limit=0.95", "_Limited")


def _adv_audio_denoise(self):
    _adv_audio_filter(self, "afftdn=nr=12", "_Denoised")


def _adv_audio_fade_in(self):
    _adv_audio_filter(self, "afade=t=in:st=0:d=3", "_FadeIn")


def _adv_audio_tempo(self):
    rate, ok = QInputDialog.getDouble(self, "Tempo", "Tempo multiplier:", 1.1, 0.5, 2.0, 2)
    if ok:
        # atempo supports 0.5–2.0 per filter instance.
        _adv_audio_filter(self, f"atempo={rate:g}", "_Tempo")


def _adv_audio_extract_wav(self):
    out = _adv_output(self, "_Audio", ".wav")
    if out:
        _adv_run_ffmpeg(self, ["-vn","-c:a","pcm_s16le"], "WAV Extraction", out)


def _adv_audio_extract_flac(self):
    out = _adv_output(self, "_Audio", ".flac")
    if out:
        _adv_run_ffmpeg(self, ["-vn","-c:a","flac"], "FLAC Extraction", out)


def _adv_audio_extract_opus(self):
    out = _adv_output(self, "_Audio", ".opus")
    if out:
        _adv_run_ffmpeg(self, ["-vn","-c:a","libopus","-b:a","160k"], "Opus Extraction", out)


# ----------------------------- Subtitle/transcript tools ---------------------

def _adv_sub_clear(self):
    self.generated_subs = []
    self.subtitle_bar.clear()
    self.subtitle_bar_top.clear()
    self.log_event("Generated subtitles cleared.", "#F39C12")


def _adv_sub_delay_plus(self):
    self.sub_delay_ms += 250
    self.log_event(f"Subtitle delay: {self.sub_delay_ms} ms")


def _adv_sub_delay_minus(self):
    self.sub_delay_ms -= 250
    self.log_event(f"Subtitle delay: {self.sub_delay_ms} ms")


def _adv_sub_size_plus(self):
    self.sub_font_size = min(72, self.sub_font_size + 2)
    self.subtitle_bar.setFont(QFont("Segoe UI", self.sub_font_size, QFont.Weight.Bold))


def _adv_sub_size_minus(self):
    self.sub_font_size = max(8, self.sub_font_size - 2)
    self.subtitle_bar.setFont(QFont("Segoe UI", self.sub_font_size, QFont.Weight.Bold))


def _adv_sub_background(self):
    self.sub_background = not self.sub_background
    bg = "rgba(0,0,0,170)" if self.sub_background else "transparent"
    self.subtitle_bar.setStyleSheet(f"color:{self.sub_color};background:{bg};")


def _adv_export_vtt(self):
    if not self.generated_subs:
        QMessageBox.information(self, "Subtitles", "Generate subtitles first.")
        return
    out, _ = QFileDialog.getSaveFileName(self, "Save WebVTT", "subtitles.vtt", "WebVTT (*.vtt)")
    if not out:
        return
    def ts(sec):
        h = int(sec//3600); m=int((sec%3600)//60); s=sec%60
        return f"{h:02d}:{m:02d}:{s:06.3f}"
    lines = ["WEBVTT", ""]
    for i,(a,b,t,tr) in enumerate(self.generated_subs,1):
        text = t + (f"\\n{tr}" if tr else "")
        lines += [str(i), f"{ts(a)} --> {ts(b)}", text, ""]
    _adv_save_text(self, out, "\n".join(lines))


def _adv_export_txt(self):
    if not self.generated_subs:
        QMessageBox.information(self, "Transcript", "Generate subtitles first.")
        return
    out, _ = QFileDialog.getSaveFileName(self, "Save Transcript", "transcript.txt", "Text (*.txt)")
    if out:
        text = "\n".join(f"[{self._format_time(int(a*1000))}] {t}" for a,b,t,tr in self.generated_subs)
        _adv_save_text(self, out, text)


def _adv_transcript_stats(self):
    if not self.generated_subs:
        return
    words = sum(len(re.findall(r"\b[\w'-]+\b", t or "")) for _,_,t,_ in self.generated_subs)
    chars = sum(len(t or "") for _,_,t,_ in self.generated_subs)
    QMessageBox.information(self, "Transcript Statistics",
                            f"Cues: {len(self.generated_subs)}\nWords: {words}\nCharacters: {chars}")


def _adv_find_transcript(self):
    if not self.generated_subs:
        return
    q = _adv_dialog_text(self, "Find in Transcript", "Search text:")
    if not q:
        return
    hits = [(a,t) for a,b,t,tr in self.generated_subs if q.lower() in (t+" "+tr).lower()]
    if hits:
        self.player.setPosition(int(hits[0][0]*1000))
        self.log_event(f"Transcript search: {len(hits)} hit(s).", "#2ECC71")
    else:
        QMessageBox.information(self, "Transcript Search", "No matches.")


def _adv_jump_sub_next(self):
    if not self.generated_subs:
        return
    pos = self.player.position()/1000
    for a,b,t,tr in self.generated_subs:
        if a > pos:
            self.player.setPosition(int(a*1000))
            return


def _adv_jump_sub_previous(self):
    if not self.generated_subs:
        return
    pos = self.player.position()/1000
    for a,b,t,tr in reversed(self.generated_subs):
        if b < pos:
            self.player.setPosition(int(a*1000))
            return


# ----------------------------- Editing / utility -----------------------------

def _adv_extract_segment(self):
    p = _adv_require_file(self)
    if not p:
        return
    start = self.player.position()/1000
    length, ok = QInputDialog.getDouble(self, "Extract Segment", "Duration seconds:", 10, 0.1, 86400, 1)
    if ok:
        out = _adv_output(self, f"_Clip_{int(start)}s", ".mp4")
        cmd = ["ffmpeg","-y","-ss",str(start),"-t",str(length),"-i",p,"-c","copy",out]
        self.run_bg_task(FFmpegWorker(cmd, "Segment Extraction"))


def _adv_audio_fadeout(self):
    dur = self.player.duration()/1000
    if dur <= 0:
        return
    out = _adv_output(self, "_FadeOut", ".m4a")
    if out:
        start = max(0, dur-3)
        _adv_run_ffmpeg(self, ["-vn","-af",f"afade=t=out:st={start}:d=3","-c:a","aac","-b:a","256k"],
                        "Audio Fade Out", out)


def _adv_remove_silence(self):
    _adv_audio_filter(self, "silenceremove=start_periods=1:start_duration=0.2:start_threshold=-45dB:stop_periods=-1:stop_duration=0.5:stop_threshold=-45dB", "_SilenceTrim")


def _adv_media_to_mp4(self):
    _adv_remux(self, ".mp4")


def _adv_media_to_mkv(self):
    _adv_remux(self, ".mkv")


def _adv_media_to_mov(self):
    _adv_remux(self, ".mov")


def _adv_contact_sheet_custom(self):
    p = _adv_require_file(self)
    if not p:
        return
    cols, ok = QInputDialog.getInt(self, "Contact Sheet", "Columns:", 5, 2, 10)
    if not ok:
        return
    interval, ok = QInputDialog.getDouble(self, "Contact Sheet", "Seconds between frames:", 30, 1, 3600, 1)
    if not ok:
        return
    out = os.path.join(os.path.dirname(p), f"contact_{int(time.time())}.jpg")
    filt = f"fps=1/{interval:g},scale=320:-1,tile={cols}x{cols}"
    cmd = ["ffmpeg","-y","-i",p,"-vf",filt,out]
    self.run_bg_task(FFmpegWorker(cmd, "Custom Contact Sheet"))


def _adv_make_preview(self):
    p = _adv_require_file(self)
    if not p:
        return
    out = _adv_output(self, "_Preview", ".mp4")
    cmd = ["ffmpeg","-y","-i",p,"-t","30","-vf","scale=854:-2","-c:v","libx264","-crf","28","-c:a","aac","-b:a","96k",out]
    self.run_bg_task(FFmpegWorker(cmd, "Preview Generator"))


def _adv_convert_gif_high_quality(self):
    p = _adv_require_file(self)
    if not p:
        return
    sec = self.player.position()/1000
    out = _adv_output(self, f"_GIF_{int(sec)}s", ".gif")
    cmd = ["ffmpeg","-y","-ss",str(sec),"-t","5","-i",p,
           "-vf","fps=20,scale=640:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=256[p];[s1][p]paletteuse=dither=sierra2_4a",out]
    self.run_bg_task(FFmpegWorker(cmd, "High Quality GIF"))


# ----------------------------- UI / accessibility ----------------------------

def _adv_compact_ui(self):
    self._adv_compact = not getattr(self, "_adv_compact", False)
    self.controls_frame.setMaximumHeight(110 if self._adv_compact else 1000)
    self.command_center.setVisible(not self._adv_compact)
    self.log_event("Compact UI " + ("ON" if self._adv_compact else "OFF"), "#3498DB")


def _adv_toggle_playlist(self):
    self.playlist_dock.setVisible(not self.playlist_dock.isVisible())


def _adv_toggle_bookmarks(self):
    self.bookmark_dock.setVisible(not self.bookmark_dock.isVisible())


def _adv_toggle_console(self):
    self.dock.setVisible(not self.dock.isVisible())


def _adv_reset_view(self):
    self.showNormal()
    self.is_fullscreen = False
    self.is_pip_mode = False
    self.setGeometry(self.normal_geometry) if self.normal_geometry else None
    self.controls_frame.show()
    self.menu_bar.show()
    self.dock.show()
    self.playlist_dock.show()
    self.bookmark_dock.show()


def _adv_set_theme_dark(self):
    self.apply_theme("Dark", "#0d0d0d")


def _adv_set_theme_light(self):
    self.apply_theme("Light", "#f0f0f0")


def _adv_set_theme_sapphire(self):
    self.apply_theme("Sapphire", "#1a2a3a")


def _adv_toggle_status(self):
    self.status_bar.setVisible(not self.status_bar.isVisible())


def _adv_show_config_path(self):
    path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    QMessageBox.information(self, "Config Directory", path)


def _adv_show_cache_path(self):
    path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation)
    QMessageBox.information(self, "Cache Directory", path)


def _adv_show_temp_path(self):
    QMessageBox.information(self, "Temp Directory", os.environ.get("TEMP") or os.environ.get("TMP") or "/tmp")


def _adv_check_dependencies(self):
    names = ["ffmpeg","ffprobe","python"]
    rows = []
    for n in names:
        path = shutil.which(n)
        rows.append(f"{n}: {path or 'NOT FOUND'}")
    optional = {
        "faster-whisper": AI_AVAILABLE,
        "yt-dlp": YTDLP_AVAILABLE,
        "cryptography": CRYPTO_AVAILABLE,
        "SpeechRecognition": VOICE_AVAILABLE,
        "PyChromecast": CAST_AVAILABLE,
        "pynvml": NVML_AVAILABLE,
    }
    rows += [f"{k}: {'OK' if v else 'NOT INSTALLED'}" for k,v in optional.items()]
    QMessageBox.information(self, "Dependency Diagnostics", "\n".join(rows))


def _adv_clear_log(self):
    self.log_console.clear()
    self.log_event("Console cleared.", "#3498DB")


def _adv_export_log(self):
    out, _ = QFileDialog.getSaveFileName(self, "Export Log", "omniplayer.log", "Log (*.log);;Text (*.txt)")
    if out:
        _adv_save_text(self, out, self.log_console.toPlainText())


def _adv_copy_log(self):
    QApplication.clipboard().setText(self.log_console.toPlainText())


def _adv_app_info(self):
    QMessageBox.information(self, "OmniPlayer Pro 20.x",
                            "Advanced Feature Pack enabled.\n"
                            "PyQt6 + Qt Multimedia + FFmpeg + optional AI integrations.")


# ----------------------------- Registration ----------------------------------

_ADVANCED_FEATURES = [
    # Playback
    ("Skip 5 seconds", lambda s: _adv_skip(s, 5)),
    ("Skip 15 seconds", lambda s: _adv_skip(s, 15)),
    ("Skip 30 seconds", lambda s: _adv_skip(s, 30)),
    ("Rewind 5 seconds", lambda s: _adv_skip(s, -5)),
    ("Rewind 15 seconds", lambda s: _adv_skip(s, -15)),
    ("Rewind 30 seconds", lambda s: _adv_skip(s, -30)),
    ("Jump to 10%", lambda s: _adv_jump_percent(s, 10)),
    ("Jump to 25%", lambda s: _adv_jump_percent(s, 25)),
    ("Jump to 50%", lambda s: _adv_jump_percent(s, 50)),
    ("Jump to 75%", lambda s: _adv_jump_percent(s, 75)),
    ("Jump to 90%", lambda s: _adv_jump_percent(s, 90)),
    ("Play from Start", _adv_play_from_start),
    ("Resume Saved Position", _adv_resume_last),
    ("Rate 0.5x", lambda s: _adv_toggle_playback_rate(s, 0.5)),
    ("Rate 0.75x", lambda s: _adv_toggle_playback_rate(s, 0.75)),
    ("Rate 1.0x", lambda s: _adv_toggle_playback_rate(s, 1.0)),
    ("Rate 1.25x", lambda s: _adv_toggle_playback_rate(s, 1.25)),
    ("Rate 1.5x", lambda s: _adv_toggle_playback_rate(s, 1.5)),
    ("Rate 2.0x", lambda s: _adv_toggle_playback_rate(s, 2.0)),
    ("Rate 3.0x", lambda s: _adv_toggle_playback_rate(s, 3.0)),
    ("Rate 4.0x", lambda s: _adv_toggle_playback_rate(s, 4.0)),
    ("Always On Top", _adv_toggle_always_on_top),
    ("Schedule Pause", _adv_toggle_pause_after),
    ("Queue Current Media", _adv_queue_current),
    ("Play First Playlist Item", _adv_playlist_play_first),
    ("Play Last Playlist Item", _adv_playlist_play_last),

    # Playlist
    ("Add Entire Folder", _adv_playlist_add_folder),
    ("Remove Duplicate Entries", _adv_playlist_dedupe),
    ("Sort Playlist by Name", _adv_playlist_sort_name),
    ("Reverse Playlist", _adv_playlist_reverse),
    ("Randomize Playlist", _adv_playlist_randomize),
    ("Export M3U8 Playlist", _adv_playlist_export),
    ("Import M3U8 Playlist", _adv_playlist_import),
    ("Remove Missing Files", _adv_playlist_remove_missing),

    # Analysis / files
    ("Advanced Media Report", _adv_media_report),
    ("Stream Inspector", _adv_show_stream_table),
    ("Export ffprobe JSON", _adv_export_probe_json),
    ("SHA-256 Current File", _adv_hash_current),
    ("Verify SHA-256", _adv_verify_hash),
    ("File Timestamps", _adv_file_timestamps),
    ("File Permissions", _adv_file_permissions),
    ("Open Containing Folder", _adv_open_containing_folder),
    ("Copy Media Path", _adv_copy_path),
    ("Copy Filename", _adv_copy_filename),
    ("Rename Current Media", _adv_rename_current),
    ("Duplicate Current Media", _adv_duplicate_current),

    # Video codecs / containers
    ("Transcode H.264 MP4", lambda s: _adv_transcode(s,"h264",".mp4","_H264")),
    ("Transcode H.265 MP4", lambda s: _adv_transcode(s,"hevc",".mp4","_HEVC")),
    ("Transcode VP9 WebM", lambda s: _adv_transcode(s,"vp9",".webm","_VP9")),
    ("Transcode AV1 MKV", lambda s: _adv_transcode(s,"av1",".mkv","_AV1")),
    ("Remux to MP4", lambda s: _adv_remux(s,".mp4")),
    ("Remux to MKV", lambda s: _adv_remux(s,".mkv")),
    ("Remux to MOV", lambda s: _adv_remux(s,".mov")),
    ("Extract Video Frames", _adv_extract_frames),
    ("Capture Frame at Current Time", _adv_extract_frame_at_current),
    ("Generate First-Frame Thumbnail", _adv_video_thumbnail),
    ("Change Frame Rate", _adv_change_fps),
    ("Scale Video", _adv_scale_video),
    ("Rotate Video", _adv_rotate_video),
    ("Deinterlace Video", _adv_deinterlace),
    ("Grayscale Video", _adv_grayscale),
    ("Sepia Video", _adv_sepia),
    ("Sharpen Video", _adv_sharpen),
    ("Blur Video", _adv_blur),
    ("Mirror Horizontally", _adv_flip_h),
    ("Flip Vertically", _adv_flip_v),
    ("Video Denoise", _adv_denoise_video),
    ("Video Fade Effect", _adv_video_fade),
    ("Crop Video", _adv_crop_video),

    # Audio
    ("Normalize Loudness", _adv_audio_normalize),
    ("Convert Audio to Mono WAV", _adv_audio_mono),
    ("Convert Audio to Stereo WAV", _adv_audio_stereo),
    ("Low-Pass Audio", _adv_audio_lowpass),
    ("High-Pass Audio", _adv_audio_highpass),
    ("Bass Boost", _adv_audio_bass),
    ("Treble Boost", _adv_audio_treble),
    ("Dynamic Compressor", _adv_audio_compressor),
    ("Peak Limiter", _adv_audio_limiter),
    ("Audio Noise Reduction", _adv_audio_denoise),
    ("Audio Fade In", _adv_audio_fade_in),
    ("Audio Tempo Adjust", _adv_audio_tempo),
    ("Extract WAV", _adv_audio_extract_wav),
    ("Extract FLAC", _adv_audio_extract_flac),
    ("Extract Opus", _adv_audio_extract_opus),
    ("Fade Audio Out", _adv_audio_fadeout),
    ("Remove Silence", _adv_remove_silence),

    # Subtitle / AI
    ("Clear Generated Subtitles", _adv_sub_clear),
    ("Subtitle Delay +250ms", _adv_sub_delay_plus),
    ("Subtitle Delay -250ms", _adv_sub_delay_minus),
    ("Subtitle Font +2", _adv_sub_size_plus),
    ("Subtitle Font -2", _adv_sub_size_minus),
    ("Toggle Subtitle Background", _adv_sub_background),
    ("Export WebVTT", _adv_export_vtt),
    ("Export Plain Transcript", _adv_export_txt),
    ("Transcript Statistics", _adv_transcript_stats),
    ("Find in Transcript", _adv_find_transcript),
    ("Next Subtitle Cue", _adv_jump_sub_next),
    ("Previous Subtitle Cue", _adv_jump_sub_previous),

    # Editing / utility
    ("Extract Clip from Current Time", _adv_extract_segment),
    ("Media to MP4", _adv_media_to_mp4),
    ("Media to MKV", _adv_media_to_mkv),
    ("Media to MOV", _adv_media_to_mov),
    ("Custom Contact Sheet", _adv_contact_sheet_custom),
    ("Create 30s Preview", _adv_make_preview),
    ("High Quality 5s GIF", _adv_convert_gif_high_quality),

    # UI / diagnostics
    ("Compact Interface", _adv_compact_ui),
    ("Toggle Playlist Dock", _adv_toggle_playlist),
    ("Toggle Bookmark Dock", _adv_toggle_bookmarks),
    ("Toggle Telemetry Console", _adv_toggle_console),
    ("Reset View Layout", _adv_reset_view),
    ("Dark Theme", _adv_set_theme_dark),
    ("Light Theme", _adv_set_theme_light),
    ("Sapphire Theme", _adv_set_theme_sapphire),
    ("Toggle Status Bar", _adv_toggle_status),
    ("Show Config Directory", _adv_show_config_path),
    ("Show Cache Directory", _adv_show_cache_path),
    ("Show Temp Directory", _adv_show_temp_path),
    ("Dependency Diagnostics", _adv_check_dependencies),
    ("Clear Telemetry Log", _adv_clear_log),
    ("Export Telemetry Log", _adv_export_log),
    ("Copy Telemetry Log", _adv_copy_log),
    ("Advanced About", _adv_app_info),
]

# Install the functions as methods so the feature pack remains inspectable and
# easy to extend in a normal Python debugger.
for _name, _fn in list(globals().items()):
    if _name.startswith("_adv_") and callable(_fn):
        setattr(OmniPlayerPro, _name, _fn)

# Add a dedicated Advanced menu after the original menu is built.
_original_init_20 = OmniPlayerPro.__init__


def _enhanced_init_20(self, *args, **kwargs):
    _original_init_20(self, *args, **kwargs)
    self._install_advanced_feature_menu()


def _install_advanced_feature_menu(self):
    menu = self.menuBar().addMenu("Advanced 20.x")
    groups = {
        "Playback Lab": _ADVANCED_FEATURES[0:25],
        "Playlist Lab": _ADVANCED_FEATURES[25:33],
        "Media Inspector": _ADVANCED_FEATURES[33:45],
        "Video Processing": _ADVANCED_FEATURES[45:68],
        "Audio DSP": _ADVANCED_FEATURES[68:84],
        "Subtitle & Transcript": _ADVANCED_FEATURES[84:96],
        "Editing & Export": _ADVANCED_FEATURES[96:103],
        "Interface & Diagnostics": _ADVANCED_FEATURES[103:],
    }
    for group_name, items in groups.items():
        submenu = menu.addMenu(group_name)
        for label, callback in items:
            action = QAction(label, self)
            action.triggered.connect(lambda checked=False, cb=callback: cb(self))
            submenu.addAction(action)
    self.log_event(f"Advanced Feature Pack loaded: {len(_ADVANCED_FEATURES)} commands.", "#2ECC71")


# Bind the installer itself to the class before the patched __init__ is used.
# The previous build only installed the _adv_* methods, which caused:
# AttributeError: 'OmniPlayerPro' object has no attribute '_install_advanced_feature_menu'
OmniPlayerPro._install_advanced_feature_menu = _install_advanced_feature_menu
OmniPlayerPro.__init__ = _enhanced_init_20



# =============================================================================
# OMNIPLAYER PRO 21.x — MEDIA LIBRARY / PLAYBACK RELIABILITY / AI SUBTITLE FIX
# =============================================================================
import sqlite3
import platform


def _v21_app_dir(self):
    d = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    os.makedirs(d, exist_ok=True)
    return d


def _v21_db_init(self):
    self.library_db_path = os.path.join(_v21_app_dir(self), "omniplayer_library.sqlite3")
    self.library_db = sqlite3.connect(self.library_db_path)
    self.library_db.execute("PRAGMA journal_mode=WAL")
    self.library_db.executescript("""
    CREATE TABLE IF NOT EXISTS media (
        path TEXT PRIMARY KEY, title TEXT, duration REAL, width INTEGER, height INTEGER,
        fps REAL, video_codec TEXT, audio_codec TEXT, bitrate INTEGER, size INTEGER,
        modified REAL, last_played REAL, position REAL DEFAULT 0, play_count INTEGER DEFAULT 0,
        watched INTEGER DEFAULT 0, rating INTEGER DEFAULT 0, favorite INTEGER DEFAULT 0,
        tags TEXT DEFAULT '', notes TEXT DEFAULT '', hdr TEXT DEFAULT '', pixel_format TEXT DEFAULT '',
        language TEXT DEFAULT '', hash TEXT DEFAULT '', added REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS bookmarks_v21 (
        id INTEGER PRIMARY KEY AUTOINCREMENT, path TEXT, position REAL, title TEXT,
        color TEXT DEFAULT '', tags TEXT DEFAULT '', note TEXT DEFAULT '', created REAL
    );
    CREATE TABLE IF NOT EXISTS jobs_v21 (
        id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, description TEXT, status TEXT, created REAL, finished REAL
    );
    CREATE INDEX IF NOT EXISTS idx_media_title ON media(title);
    CREATE INDEX IF NOT EXISTS idx_media_last_played ON media(last_played);
    CREATE INDEX IF NOT EXISTS idx_media_watched ON media(watched);
    """)
    self.library_db.commit()


def _v21_db_close(self):
    try:
        if getattr(self, 'library_db', None):
            self.library_db.commit(); self.library_db.close()
    except Exception:
        pass


def _v21_probe(path):
    try:
        r=subprocess.run(["ffprobe","-v","error","-print_format","json","-show_format","-show_streams",path],
                         capture_output=True,text=True,creationflags=CREATE_NO_WINDOW,timeout=30)
        return json.loads(r.stdout or '{}')
    except Exception:
        return {}


def _v21_fps(v):
    try:
        a,b=str(v or '').split('/',1); return float(a)/float(b) if float(b) else 0.0
    except Exception:
        try:return float(v)
        except Exception:return 0.0


def _v21_index_file(self, path, probe=None):
    if not path or str(path).startswith(('http://','https://')) or not os.path.isfile(path): return
    probe=probe or _v21_probe(path); fmt=probe.get('format',{}); streams=probe.get('streams',[])
    vs=next((x for x in streams if x.get('codec_type')=='video'),{})
    aus=next((x for x in streams if x.get('codec_type')=='audio'),{})
    st=os.stat(path); title=os.path.splitext(os.path.basename(path))[0]
    dur=float(fmt.get('duration') or 0); br=int(float(fmt.get('bit_rate') or 0)) if fmt.get('bit_rate') else 0
    hdr=str(vs.get('color_transfer') or '')
    if 'smpte2084' in hdr.lower() or 'arib-std-b67' in hdr.lower(): hdr='HDR'
    self.library_db.execute("""INSERT INTO media(path,title,duration,width,height,fps,video_codec,audio_codec,bitrate,size,modified,hdr,pixel_format,language,added)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET title=excluded.title,duration=excluded.duration,width=excluded.width,height=excluded.height,
      fps=excluded.fps,video_codec=excluded.video_codec,audio_codec=excluded.audio_codec,bitrate=excluded.bitrate,size=excluded.size,modified=excluded.modified,
      hdr=excluded.hdr,pixel_format=excluded.pixel_format,language=excluded.language""",
      (os.path.abspath(path),title,dur,int(vs.get('width') or 0),int(vs.get('height') or 0),_v21_fps(vs.get('r_frame_rate')),
       vs.get('codec_name',''),aus.get('codec_name',''),br,st.st_size,st.st_mtime,hdr,vs.get('pix_fmt',''),aus.get('tags',{}).get('language',''),time.time()))
    self.library_db.commit()


def _v21_index_folder(self):
    folder=QFileDialog.getExistingDirectory(self,'Index Media Library')
    if not folder:return
    exts={'.mp4','.mkv','.mov','.avi','.webm','.m4v','.ts','.m2ts','.mp3','.flac','.wav','.aac','.m4a','.ogg','.opus'}
    count=0
    for root,_,files in os.walk(folder):
        for name in files:
            if os.path.splitext(name)[1].lower() in exts:
                self._v21_index_file(os.path.join(root,name)); count+=1
    self.log_event(f'Library indexed: {count} media files.',' #2ECC71'.strip())
    self._v21_show_library()


def _v21_show_library(self, mode='all'):
    if not getattr(self,'library_db',None):return
    q='SELECT path,title,duration,width,height,hdr,watched,rating,favorite,last_played FROM media'
    args=()
    if mode=='continue': q+=' WHERE watched=0 AND position>0'
    elif mode=='favorites': q+=' WHERE favorite=1'
    elif mode=='unwatched': q+=' WHERE watched=0'
    q+=' ORDER BY COALESCE(last_played,0) DESC, title COLLATE NOCASE'
    rows=self.library_db.execute(q,args).fetchall()
    text='\n'.join(f"{i+1}. {r[1]} | {int(r[3])}x{int(r[4])} | {r[5] or 'SDR'} | {self._format_time(int((r[2] or 0)*1000))} | {'Watched' if r[6] else 'Unwatched'} | ★{r[7]}" for i,r in enumerate(rows))
    if not text:text='No indexed media matches this view.'
    _adv_dialog_text(self,'Media Library',text)


def _v21_search_library(self):
    q=_adv_dialog_text(self,'Global Media Search','Search filename, title, tags, notes, subtitles or transcript:')
    if not q:return
    like='%'+q+'%'
    rows=self.library_db.execute("SELECT path,title,position,tags,notes FROM media WHERE title LIKE ? OR path LIKE ? OR tags LIKE ? OR notes LIKE ? ORDER BY title",(like,like,like,like)).fetchall()
    hits=[]
    for r in rows:hits.append(f"{r[1]} | {r[0]} | resume {self._format_time(int((r[2] or 0)*1000))}")
    # Search the currently loaded AI transcript too.
    for a,b,t,tr in getattr(self,'generated_subs',[]):
        if q.lower() in (t+' '+tr).lower(): hits.append(f"[Transcript {self._format_time(int(a*1000))}] {t} {tr}" )
    _adv_dialog_text(self,'Global Search Results','\n'.join(hits) if hits else 'No matches found.')


def _v21_set_rating(self):
    p=_adv_current_file(self)
    if not p:return
    val,ok=QInputDialog.getInt(self,'Rating','Rating (0–5):',0,0,5,1)
    if ok:
        self._v21_index_file(p); self.library_db.execute('UPDATE media SET rating=? WHERE path=?',(val,os.path.abspath(p))); self.library_db.commit()


def _v21_toggle_favorite(self):
    p=_adv_current_file(self)
    if not p:return
    self._v21_index_file(p); cur=self.library_db.execute('SELECT favorite FROM media WHERE path=?',(os.path.abspath(p),)).fetchone(); new=0 if cur and cur[0] else 1
    self.library_db.execute('UPDATE media SET favorite=? WHERE path=?',(new,os.path.abspath(p))); self.library_db.commit(); self.log_event(f'Favorite: {bool(new)}')


def _v21_edit_tags(self):
    p=_adv_current_file(self)
    if not p:return
    self._v21_index_file(p); old=self.library_db.execute('SELECT tags FROM media WHERE path=?',(os.path.abspath(p),)).fetchone(); old=old[0] if old else ''
    tags,ok=QInputDialog.getText(self,'Media Tags','Comma-separated tags:',text=old)
    if ok:self.library_db.execute('UPDATE media SET tags=? WHERE path=?',(tags,os.path.abspath(p)));self.library_db.commit()


def _v21_media_dashboard(self):
    rows=self.library_db.execute('SELECT COUNT(*),COALESCE(SUM(size),0),COALESCE(SUM(duration),0),COALESCE(SUM(watched),0),COALESCE(SUM(favorite),0) FROM media').fetchone()
    hw=self._v21_hardware_info(False)
    txt=f'Indexed files: {rows[0]}\nTotal size: {rows[1]/(1024**3):.2f} GB\nTotal duration: {rows[2]/3600:.2f} h\nWatched entries: {rows[3]}\nFavorites: {rows[4]}\n\nHardware/decoder hints:\n{hw}'
    _adv_dialog_text(self,'Media Dashboard',txt)


def _v21_hardware_info(self, dialog=True):
    lines=[f'OS: {platform.platform()}',f'CPU cores: {os.cpu_count() or "?"}']
    try:
        r=subprocess.run(['ffmpeg','-hide_banner','-hwaccels'],capture_output=True,text=True,creationflags=CREATE_NO_WINDOW,timeout=10)
        lines.append('FFmpeg HW acceleration:\n'+(r.stdout.strip() or r.stderr.strip() or 'Unavailable'))
    except Exception as e: lines.append(f'FFmpeg: {e}')
    try:
        r=subprocess.run(['ffmpeg','-hide_banner','-decoders'],capture_output=True,text=True,creationflags=CREATE_NO_WINDOW,timeout=10)
        dec=[x.strip() for x in r.stdout.splitlines() if any(k in x.lower() for k in ('h264','hevc','av1','vp9'))]
        lines.append('Video decoders:\n'+'\n'.join(dec[:40]))
    except Exception:pass
    text='\n'.join(lines)
    if dialog:_adv_dialog_text(self,'Hardware & Decoder Diagnostics',text)
    return text


def _v21_probe_current(self):
    p=_adv_require_file(self)
    if not p:return
    info=_v21_probe(p); fmt=info.get('format',{}); streams=info.get('streams',[])
    lines=[f"Container: {fmt.get('format_name','?')}",f"Duration: {fmt.get('duration','?')} s",f"Bitrate: {fmt.get('bit_rate','?')}",f"Size: {os.path.getsize(p)/1024/1024:.2f} MB"]
    for i,s in enumerate(streams): lines.append(f"\nStream {i}: {s.get('codec_type')} | {s.get('codec_name')} | {s.get('width','')}x{s.get('height','')} | {s.get('pix_fmt','')} | lang={s.get('tags',{}).get('language','')}")
    _adv_dialog_text(self,'Professional Media Inspector','\n'.join(lines))


def _v21_extract_chapters(self):
    p=_adv_require_file(self)
    if not p:return
    info=_v21_probe(p); ch=info.get('chapters',[])
    if not ch: QMessageBox.information(self,'Chapters','No embedded chapters found.'); return
    lines=[f"{i+1}. {c.get('tags',{}).get('title','Chapter')} — {self._format_time(int(float(c.get('start_time',0))*1000))}" for i,c in enumerate(ch)]
    _adv_dialog_text(self,'Embedded Chapters','\n'.join(lines))


def _v21_mark_watched(self):
    p=_adv_current_file(self)
    if not p:return
    self._v21_index_file(p); self.library_db.execute('UPDATE media SET watched=1,position=0 WHERE path=?',(os.path.abspath(p),)); self.library_db.commit()


def _v21_clear_watched(self):
    p=_adv_current_file(self)
    if not p:return
    self._v21_index_file(p); self.library_db.execute('UPDATE media SET watched=0 WHERE path=?',(os.path.abspath(p),)); self.library_db.commit()


def _v21_save_position(self):
    p=_adv_current_file(self)
    if not p:return
    self._v21_index_file(p); pos=self.player.position()/1000.0; dur=max(0,self.player.duration()/1000.0); watched=1 if dur>30 and pos/dur>=0.90 else 0
    self.library_db.execute('UPDATE media SET position=?,last_played=?,play_count=play_count+1,watched=? WHERE path=?',(pos,time.time(),watched,os.path.abspath(p))); self.library_db.commit()


def _v21_resume_current(self):
    p=_adv_current_file(self)
    if not p:return
    row=self.library_db.execute('SELECT position FROM media WHERE path=?',(os.path.abspath(p),)).fetchone()
    if row and row[0]>0:self.player.setPosition(int(row[0]*1000)); self.log_event(f'Resumed from {self._format_time(int(row[0]*1000))}')


def _v21_duplicate_scan(self):
    rows=self.library_db.execute('SELECT path,size,duration,width,height FROM media ORDER BY size DESC').fetchall(); groups={}
    for r in rows:groups.setdefault((r[1],round(r[2] or 0,1),r[3],r[4]),[]).append(r[0])
    dup=[g for g in groups.values() if len(g)>1]
    _adv_dialog_text(self,'Duplicate Candidates','\n\n'.join('\n'.join(x for x in g) for g in dup) if dup else 'No duplicate candidates found.')


def _v21_hash_library_current(self):
    p=_adv_require_file(self)
    if not p:return
    h=self._adv_hash_file(p); self._v21_index_file(p); self.library_db.execute('UPDATE media SET hash=? WHERE path=?',(h,os.path.abspath(p))); self.library_db.commit(); QMessageBox.information(self,'SHA-256',h)


def _v21_fix_subtitles(self):
    # Robust subtitle timing: use the next cue as the natural end boundary when
    # Whisper's segment end is too early. Never overlap the next cue and never
    # allow a cue to remain visible beyond the next dialogue.
    subs=[]
    for i,(a,b,t,tr) in enumerate(sorted(getattr(self,'generated_subs',[]),key=lambda x:x[0])):
        a=float(a); b=float(b)
        if i+1<len(self.generated_subs):
            nxt=float(sorted(self.generated_subs,key=lambda x:x[0])[i+1][0])
            if nxt>a: b=min(max(b,a+0.25),nxt-0.03)
        else: b=max(b,a+0.25)
        subs.append((a,b,t,tr))
    self.generated_subs=subs
    self._adv_subtitle_cursor=-1


def _v21_subtitle_tick(self):
    if not getattr(self,'is_video',False) or not getattr(self,'generated_subs',None):
        if self.subtitle_bar.text() or self.subtitle_bar_top.text(): self.subtitle_bar.clear();self.subtitle_bar_top.clear()
        return
    pos=(self.player.position()+int(getattr(self,'sub_delay_ms',0)))/1000.0
    subs=self.generated_subs; active=-1
    # Cursor keeps this O(1) in the common playback case, with binary-like
    # forward stepping and a fallback scan after seeking backwards.
    cur=getattr(self,'_adv_subtitle_cursor',-1)
    if 0<=cur<len(subs) and subs[cur][0] <= pos < subs[cur][1]: active=cur
    elif 0<=cur<len(subs) and pos>=subs[cur][1]:
        j=cur+1
        while j<len(subs) and subs[j][0]<=pos:
            if subs[j][0]<=pos<subs[j][1]: active=j;break
            j+=1
    if active<0:
        for j,(a,b,t,tr) in enumerate(subs):
            if a<=pos<b: active=j;break
    self._adv_subtitle_cursor=active
    native=trans=''
    if active>=0:
        _,_,native,trans=subs[active]
    mode=self.display_mode_combo.currentIndex()
    if mode==1: main=native or trans; top=''
    elif mode==2: main=trans or native; top=''
    else: main=native; top=('🌐 '+trans) if trans else ''
    if self.subtitle_bar.text()!=main:self.subtitle_bar.setText(main)
    if self.subtitle_bar_top.text()!=top:self.subtitle_bar_top.setText(top)


def _v21_safe_subtitle_finished(self,count=0):
    if getattr(self,'generated_subs',None): self._v21_fix_subtitles()
    self.log_event(f'AI subtitle timing normalized: {len(getattr(self,"generated_subs",[]))} cues.',' #2ECC71'.strip())


def _v21_add_job(self,kind,desc,status='queued'):
    try:self.library_db.execute('INSERT INTO jobs_v21(kind,description,status,created) VALUES(?,?,?,?)',(kind,desc,status,time.time()));self.library_db.commit()
    except Exception:pass


def _v21_job_center(self):
    rows=self.library_db.execute('SELECT id,kind,description,status,created,finished FROM jobs_v21 ORDER BY id DESC LIMIT 100').fetchall()
    lines=[]
    for r in rows:lines.append(f"#{r[0]} [{r[3]}] {r[1]} — {r[2]}")
    _adv_dialog_text(self,'Job Center','\n'.join(lines) if lines else 'No jobs recorded.')


def _v21_export_library(self):
    out,_=QFileDialog.getSaveFileName(self,'Export Library','omniplayer_library.csv','CSV (*.csv)')
    if not out:return
    rows=self.library_db.execute('SELECT path,title,duration,width,height,fps,video_codec,audio_codec,bitrate,size,last_played,position,play_count,watched,rating,favorite,tags,notes,hdr,pixel_format FROM media').fetchall()
    with open(out,'w',newline='',encoding='utf-8-sig') as f:
        w=_csv.writer(f);w.writerow(['path','title','duration','width','height','fps','video_codec','audio_codec','bitrate','size','last_played','position','play_count','watched','rating','favorite','tags','notes','hdr','pixel_format']);w.writerows(rows)
    self.log_event(f'Library exported: {out}')


def _v21_settings_panel(self):
    dlg=QDialog(self);dlg.setWindowTitle('OmniPlayer 21 Settings');lay=QVBoxLayout(dlg)
    opts=[('Remember playback position',True),('Auto-mark watched at 90%',True),('Normalize AI subtitle timing',True),('Use hardware acceleration when supported',True),('Create thumbnails on library index',False),('Network reconnect on stalls',True)]
    boxes=[]
    for label,default in opts:
        b=QCheckBox(label);b.setChecked(self.settings.value('v21_'+label,default,type=bool));lay.addWidget(b);boxes.append((label,b))
    save=QPushButton('Save');save.clicked.connect(dlg.accept);lay.addWidget(save)
    if dlg.exec():
        for label,b in boxes:self.settings.setValue('v21_'+label,b.isChecked())


def _v21_network_diagnostics(self):
    urls=['https://www.google.com','https://www.youtube.com']
    out=[]
    for u in urls:
        t=time.time()
        try:
            req=urllib.request.Request(u,method='HEAD',headers={'User-Agent':'OmniPlayerPro/21'})
            with urllib.request.urlopen(req,timeout=5) as r:out.append(f'{u}: OK {r.status} {time.time()-t:.2f}s')
        except Exception as e:out.append(f'{u}: FAIL {e}')
    _adv_dialog_text(self,'Network Diagnostics','\n'.join(out))


def _v21_watchdog(self):
    if not hasattr(self,'_v21_last_position'):self._v21_last_position=self.player.position();self._v21_stall_ticks=0;return
    now=self.player.position(); playing=self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState
    if playing and now==self._v21_last_position and self.player.duration()>0:
        self._v21_stall_ticks+=1
        if self._v21_stall_ticks>=30:
            self.log_event('Playback watchdog: possible stall detected.',' #F39C12'.strip());self.player.pause();QTimer.singleShot(250,self.player.play);self._v21_stall_ticks=0
    else:self._v21_stall_ticks=0
    self._v21_last_position=now


def _v21_thumbnail(self):
    p=_adv_require_file(self)
    if not p:return
    out=_adv_output(self,'_Thumbnail','.jpg')
    if out:_adv_run_ffmpeg(self,['-ss',str(self.player.position()/1000),'-frames:v','1','-q:v','2'],'Thumbnail',out)


def _v21_contact_preview(self):
    p=_adv_require_file(self)
    if not p:return
    out=_adv_output(self,'_Preview','.mp4')
    if out:_adv_run_ffmpeg(self,['-t','30','-vf','fps=2,scale=640:-2','-an','-c:v','libx264','-crf','24','-preset','veryfast'],'Preview',out)


def _v21_compare_media(self):
    files,_=QFileDialog.getOpenFileNames(self,'Compare Media Files','','Media (*.*)')
    if len(files)<2:return
    rows=[]
    for p in files[:6]:
        x=_v21_probe(p);f=x.get('format',{});v=next((s for s in x.get('streams',[]) if s.get('codec_type')=='video'),{});rows.append(f"{os.path.basename(p)}\n{f.get('format_name','?')} | {f.get('duration','?')}s | {v.get('codec_name','audio-only')} | {v.get('width','')}x{v.get('height','')} | {v.get('pix_fmt','')}")
    _adv_dialog_text(self,'Media Comparison','\n\n'.join(rows))


def _v21_auto_chapter_from_subs(self):
    if not self.generated_subs:return
    self.bookmarks.clear();self.bookmark_list.clear()
    last=-999;idx=1
    for a,b,t,tr in self.generated_subs:
        if a-last>=45:
            title=(t or tr or f'Chapter {idx}').replace('\n',' ')[:55]
            self.bookmarks.append((int(a*1000),title));self.bookmark_list.addItem(f'{title} ({self._format_time(int(a*1000))})');idx+=1;last=a
    self.bookmark_dock.show()


def _v21_install(self):
    self._v21_db_init()
    self._adv_subtitle_cursor=-1
    self._v21_last_position=self.player.position();self._v21_stall_ticks=0
    # Patch playback lifecycle without replacing the existing player.
    self.player.mediaStatusChanged.connect(lambda status: self._v21_on_media_status(status))
    self._v21_timer=QTimer(self);self._v21_timer.timeout.connect(self._v21_runtime_tick);self._v21_timer.start(500)
    self.log_event('OmniPlayer Pro 21.x services enabled.',' #2ECC71'.strip())


def _v21_on_media_status(self,status):
    if status==QMediaPlayer.MediaStatus.EndOfMedia:self._v21_save_position()


def _v21_runtime_tick(self):
    try:
        self._v21_subtitle_tick()
        self._v21_watchdog()
        if self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState and int(time.time()*2)%20==0:
            self._v21_save_position()
    except Exception as e:
        self.log_event(f'Runtime service warning: {e}',' #F39C12'.strip())



def _v21_smart_playlist(self):
    choice,ok=QInputDialog.getItem(self,'Smart Playlist','Rule:',['Recently Played','Unwatched 4K/HDR','Favorites','Longer than 90 minutes','High Rated (4+)'],0,False)
    if not ok:return
    if choice=='Recently Played': rows=self.library_db.execute('SELECT path,title FROM media WHERE last_played IS NOT NULL ORDER BY last_played DESC LIMIT 50').fetchall()
    elif choice=='Unwatched 4K/HDR': rows=self.library_db.execute("SELECT path,title FROM media WHERE watched=0 AND (width>=3840 OR hdr='HDR') ORDER BY title").fetchall()
    elif choice=='Favorites': rows=self.library_db.execute('SELECT path,title FROM media WHERE favorite=1 ORDER BY title').fetchall()
    elif choice=='Longer than 90 minutes': rows=self.library_db.execute('SELECT path,title FROM media WHERE duration>=5400 ORDER BY title').fetchall()
    else: rows=self.library_db.execute('SELECT path,title FROM media WHERE rating>=4 ORDER BY rating DESC,title').fetchall()
    self.playlist=[r[0] for r in rows];self.playlist_index=-1;self.playlist_widget.clear()
    for path,title in rows:self.playlist_widget.addItem(title or os.path.basename(path))
    self.log_event(f'Smart playlist created: {choice} ({len(rows)} items).')


def _v21_add_library_to_playlist(self):
    rows=self.library_db.execute('SELECT path,title FROM media ORDER BY title COLLATE NOCASE').fetchall()
    self.playlist=[];self.playlist_widget.clear()
    for path,title in rows:self.playlist.append(path);self.playlist_widget.addItem(title or os.path.basename(path))
    self.playlist_index=-1


def _v21_batch_transcode(self):
    files,_=QFileDialog.getOpenFileNames(self,'Batch Transcode','','Media (*.*)')
    if not files:return
    outdir=QFileDialog.getExistingDirectory(self,'Output Folder')
    if not outdir:return
    codec,ok=QInputDialog.getItem(self,'Video Codec',['libx264','libx265','libsvtav1'],0,False)
    if not ok:return
    for src in files:
        out=os.path.join(outdir,os.path.splitext(os.path.basename(src))[0]+'_encoded.mp4')
        cmd=['ffmpeg','-y','-i',src,'-c:v',codec,'-crf','22','-c:a','aac','-b:a','192k',out]
        self._v21_add_job('transcode',os.path.basename(src),'queued')
        # Run one-at-a-time through the existing task manager; the user can repeat safely.
        if not (self.active_bg_worker and self.active_bg_worker.isRunning()):
            self.run_bg_task(FFmpegWorker(cmd,f'Batch Transcode: {os.path.basename(src)}'))
        else:self.log_event(f'Queued batch item: {src}')


def _v21_screenshot_burst(self):
    p=_adv_require_file(self)
    if not p:return
    folder=QFileDialog.getExistingDirectory(self,'Screenshot Output')
    if not folder:return
    count,ok=QInputDialog.getInt(self,'Burst Screenshots','Number of frames:',10,2,200,1)
    if not ok:return
    dur=max(1,self.player.duration());fps=max(1,count/(dur/1000.0))
    pattern=os.path.join(folder,'frame_%05d.jpg')
    self._adv_run_ffmpeg(self,['-vf',f'fps={fps:g}','-q:v','2','-frames:v',str(count)],'Screenshot Burst',pattern)


def _v21_scene_detect(self):
    p=_adv_require_file(self)
    if not p:return
    out=_adv_output(self,'_Scenes','.txt')
    if out:
        pattern=out.rsplit('.',1)[0]+'_%04d.jpg'
        self._adv_run_ffmpeg(self,['-vf',"select='gt(scene,0.35)'",'-vsync','vfr','-q:v','2'],'Scene Detection',pattern)


def _v21_subtitle_convert(self):
    src,_=QFileDialog.getOpenFileName(self,'Open Subtitle','','Subtitles (*.srt *.vtt *.ass *.ssa)')
    if not src:return
    ext=QInputDialog.getItem(self,'Convert Subtitle','Target format:',['SRT','VTT','ASS'],0,False)[0]
    out=os.path.splitext(src)[0]+'.'+ext.lower()
    if ext=='VTT':
        data=open(src,encoding='utf-8-sig',errors='replace').read();
        if not data.lstrip().startswith('WEBVTT'): data='WEBVTT\n\n'+data
        data=re.sub(r'(\d{2}:\d{2}:\d{2}),(\d{3})',r'\1.\2',data)
        open(out,'w',encoding='utf-8').write(data)
    elif ext=='SRT':
        data=open(src,encoding='utf-8-sig',errors='replace').read();data=re.sub(r'(\d{2}:\d{2}:\d{2})\.(\d{3})',r'\1,\2',data);open(out,'w',encoding='utf-8').write(data.replace('WEBVTT','',1))
    else:
        data=open(src,encoding='utf-8-sig',errors='replace').read();open(out,'w',encoding='utf-8').write(data)
    self.log_event(f'Subtitle converted: {out}')


def _v21_repair_srt(self):
    src,_=QFileDialog.getOpenFileName(self,'Repair SRT','','SubRip (*.srt)')
    if not src:return
    data=open(src,encoding='utf-8-sig',errors='replace').read()
    data=data.replace('\r\n','\n').replace('\r','\n')
    blocks=[]
    for block in re.split(r'\n\s*\n',data):
        lines=block.strip().split('\n')
        if len(lines)>=2 and '-->' in lines[1]:
            m=re.search(r'(\d{1,2}:\d{2}:\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}:\d{2}:\d{2})[,.](\d{1,3})',lines[1])
            if m:
                def norm(t,ms):return f'{t},{int(ms):03d}'
                lines[0]=str(len(blocks)+1);lines[1]=norm(m.group(1),m.group(2))+' --> '+norm(m.group(3),m.group(4));blocks.append('\n'.join(lines))
    out=os.path.splitext(src)[0]+'_repaired.srt';open(out,'w',encoding='utf-8').write('\n\n'.join(blocks)+'\n');self.log_event(f'SRT repaired: {out}')


def _v21_cache_paths(self):
    cache=QStandardPaths.writableLocation(QStandardPaths.StandardLocation.CacheLocation);temp=QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)
    os.makedirs(cache,exist_ok=True);os.makedirs(temp,exist_ok=True);_adv_dialog_text(self,'Cache & Temp',f'Cache: {cache}\nTemp: {temp}\nDatabase: {self.library_db_path}')


def _v21_backup_database(self):
    out,_=QFileDialog.getSaveFileName(self,'Backup Library Database','omniplayer_library_backup.sqlite3','SQLite (*.sqlite3)')
    if out:
        self.library_db.commit();shutil.copy2(self.library_db_path,out);self.log_event(f'Library backup created: {out}')


def _v21_restore_database(self):
    src,_=QFileDialog.getOpenFileName(self,'Restore Library Database','','SQLite (*.sqlite3)')
    if not src:return
    if QMessageBox.question(self,'Restore','Replace current library database?')!=QMessageBox.StandardButton.Yes:return
    self._v21_db_close();shutil.copy2(src,self.library_db_path);self._v21_db_init();self.log_event('Library database restored.')

# Bind v21 methods.
for _n,_f in list(globals().items()):
    if _n.startswith('_v21_') and callable(_f): setattr(OmniPlayerPro,_n,_f)

# Preserve the fixed 20.x initializer, then install 21.x services.
_prev_init_v21=OmniPlayerPro.__init__
def _init_v21(self,*args,**kwargs):
    _prev_init_v21(self,*args,**kwargs)
    self._v21_install()
OmniPlayerPro.__init__=_init_v21

# Reliable AI subtitle rendering. The original tick used Whisper's raw segment
# end time, which can be much earlier than the next dialogue. v21 owns the
# subtitle clock so a cue remains visible until the next cue starts, then clears.
_prev_master_tick=OmniPlayerPro.master_tick
def _master_tick_v21(self):
    _prev_master_tick(self)
    self._v21_subtitle_tick()
OmniPlayerPro.master_tick=_master_tick_v21

# Save the current position whenever a new file is loaded.
_prev_play_target_v21=OmniPlayerPro._play_target
def _play_target_v21(self,path,resume_pos=None):
    try:
        old=getattr(self,'current_media',None)
        if old and old!=path:self._v21_save_position()
    except Exception:pass
    _prev_play_target_v21(self,path,resume_pos)
    try:self._v21_index_file(path)
    except Exception:pass
OmniPlayerPro._play_target=_play_target_v21

# Finish AI subtitle normalization when the worker reports completion.
try:
    _old_start_ai=OmniPlayerPro.start_ai
    def _start_ai_v21(self):
        _old_start_ai(self)
        try:
            worker=getattr(self,'active_bg_worker',None)
            if worker:
                worker.finished.connect(lambda: self._v21_safe_subtitle_finished())
        except Exception:pass
    OmniPlayerPro.start_ai=_start_ai_v21
except Exception:pass


def _v21_menu(self):
    menu=self.menuBar().addMenu('OmniPlayer 21')
    groups={
      'Library':[('Index Folder',self._v21_index_folder),('Add Library to Playlist',self._v21_add_library_to_playlist),('Smart Playlist',self._v21_smart_playlist),('All Media',lambda:self._v21_show_library('all')),('Continue Watching',lambda:self._v21_show_library('continue')),('Favorites',lambda:self._v21_show_library('favorites')),('Unwatched',lambda:self._v21_show_library('unwatched')),('Global Search',self._v21_search_library),('Dashboard',self._v21_media_dashboard),('Export Library CSV',self._v21_export_library)],
      'Playback & Reliability':[('Resume Current',self._v21_resume_current),('Mark Watched',self._v21_mark_watched),('Clear Watched',self._v21_clear_watched),('Hardware/Decoder Diagnostics',self._v21_hardware_info),('Playback Watchdog Status',lambda:self._v21_watchdog()),('Network Diagnostics',self._v21_network_diagnostics)],
      'Media Intelligence':[('Professional Inspector',self._v21_probe_current),('Embedded Chapters',self._v21_extract_chapters),('Compare Media',self._v21_compare_media),('Duplicate Candidates',self._v21_duplicate_scan),('SHA-256 Current File',self._v21_hash_library_current),('Current Thumbnail',self._v21_thumbnail),('Scene Detection',self._v21_scene_detect),('Screenshot Burst',self._v21_screenshot_burst)],
      'Organization':[('Set Rating',self._v21_set_rating),('Toggle Favorite',self._v21_toggle_favorite),('Edit Tags',self._v21_edit_tags),('30s Preview',self._v21_contact_preview),('AI Chapters from Transcript',self._v21_auto_chapter_from_subs)],
      'AI Subtitles':[('Normalize/Repair AI Timing',self._v21_fix_subtitles),('Next Dialogue',self._adv_jump_sub_next),('Previous Dialogue',self._adv_jump_sub_previous),('Export WebVTT',self._adv_export_vtt),('Export Transcript',self._adv_export_txt),('Convert Subtitle Format',self._v21_subtitle_convert),('Repair SRT',self._v21_repair_srt)],
      'System':[('Job Center',self._v21_job_center),('21.x Settings',self._v21_settings_panel),('Cache/Temp Paths',self._v21_cache_paths),('Backup Library',self._v21_backup_database),('Restore Library',self._v21_restore_database),('Batch Transcode',self._v21_batch_transcode)]}
    for g,items in groups.items():
        sub=menu.addMenu(g)
        for label,cb in items:
            a=QAction(label,self);a.triggered.connect(lambda checked=False,c=cb:c());sub.addAction(a)
    self.log_event('OmniPlayer 21 feature suite menu loaded.',' #2ECC71'.strip())

OmniPlayerPro._v21_menu=_v21_menu
_prev_install_menu=OmniPlayerPro._install_advanced_feature_menu
def _install_all_menus(self):
    _prev_install_menu(self);self._v21_menu()
OmniPlayerPro._install_advanced_feature_menu=_install_all_menus

_prev_close_v21=OmniPlayerPro.closeEvent
def _close_v21(self,event):
    try:self._v21_save_position();self._v21_db_close()
    except Exception:pass
    _prev_close_v21(self,event)
OmniPlayerPro.closeEvent=_close_v21

# =============================================================================
# OMNIPLAYER PRO 22.x — SUBTITLE ACCURACY + PRO FEATURE STUDIO
# =============================================================================
# This layer is intentionally appended so the existing application remains
# recognizable while the new behavior is centralized and easy to remove.
# Major fixes:
#   * AI subtitles end at the last spoken word instead of the next dialogue.
#   * Subtitle renderer uses strict [start, end) timing.
#   * One subtitle synchronization path owns the final display state.
#   * Optional subtitle tail, minimum/maximum duration, pause behavior, and
#     silence-gap protection are configurable.
#   * 100+ additional practical media-player commands are exposed in a single
#     Feature Studio menu.
# =============================================================================

import os as _f22_os
import json as _f22_json
import re as _f22_re
import time as _f22_time
import subprocess as _f22_subprocess
import math as _f22_math
from pathlib import Path as _f22_Path


def _f22_current_file(self):
    p = getattr(self, 'current_media', None)
    if not p or str(p).startswith(('http://', 'https://')):
        return None
    return str(p)


def _f22_require_file(self):
    p = _f22_current_file(self)
    if not p or not _f22_os.path.isfile(p):
        QMessageBox.information(self, 'Media', 'Load a local media file first.')
        return None
    return p


def _f22_log(self, text, color='#3498DB'):
    try:
        self.log_event(text, color)
    except Exception:
        pass


def _f22_clear_subtitle_display(self):
    try:
        self.subtitle_bar.clear()
        self.subtitle_bar_top.clear()
    except Exception:
        pass


def _f22_subtitle_options(self):
    return {
        'tail_ms': int(self.settings.value('f22_sub_tail_ms', 120, type=int)),
        'min_ms': int(self.settings.value('f22_sub_min_ms', 180, type=int)),
        'max_ms': int(self.settings.value('f22_sub_max_ms', 7000, type=int)),
        'gap_ms': int(self.settings.value('f22_sub_gap_ms', 650, type=int)),
        'hide_paused': self.settings.value('f22_sub_hide_paused', False, type=bool),
        'hide_muted': self.settings.value('f22_sub_hide_muted', False, type=bool),
    }


def _f22_fix_subtitles(self):
    """Speech-based normalization: never extend a cue into a silent gap."""
    raw = list(getattr(self, 'generated_subs', []) or [])
    if not raw:
        self._adv_subtitle_cursor = -1
        return

    raw.sort(key=lambda x: float(x[0]))
    opt = _f22_subtitle_options(self)
    out = []

    for i, item in enumerate(raw):
        try:
            a, b, t, tr = item[:4]
            a = max(0.0, float(a))
            b = max(a, float(b))
        except Exception:
            continue

        # Whisper's word_timestamps path already chooses the last spoken word
        # as `end`. Preserve that boundary and only add a tiny display tail.
        b += opt['tail_ms'] / 1000.0

        # Never let a cue overlap the next cue. This is a hard boundary.
        if i + 1 < len(raw):
            nxt = max(a, float(raw[i + 1][0]))
            b = min(b, max(a + opt['min_ms'] / 1000.0, nxt - 0.02))

        # Prevent pathological ultra-long cues while preserving natural speech.
        b = min(b, a + opt['max_ms'] / 1000.0)
        if b - a < opt['min_ms'] / 1000.0:
            b = a + opt['min_ms'] / 1000.0
            if i + 1 < len(raw):
                nxt = float(raw[i + 1][0])
                if b > nxt - 0.02:
                    b = max(a + 0.05, nxt - 0.02)

        out.append((a, b, str(t or '').strip(), str(tr or '').strip()))

    self.generated_subs = out
    self._adv_subtitle_cursor = -1
    _f22_log(self, f'Speech-aware subtitle timing repaired: {len(out)} cues.', '#2ECC71')


def _f22_subtitle_tick(self):
    if not getattr(self, 'is_video', False) or not getattr(self, 'generated_subs', None):
        _f22_clear_subtitle_display(self)
        return

    opt = _f22_subtitle_options(self)
    if opt['hide_paused'] and self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
        _f22_clear_subtitle_display(self)
        return

    if opt['hide_muted'] and self.audio_output.isMuted():
        _f22_clear_subtitle_display(self)
        return

    pos = (self.player.position() + int(getattr(self, 'sub_delay_ms', 0))) / 1000.0
    subs = self.generated_subs
    active = -1
    cur = getattr(self, '_f22_subtitle_cursor', -1)

    if 0 <= cur < len(subs) and subs[cur][0] <= pos < subs[cur][1]:
        active = cur
    elif 0 <= cur < len(subs) and pos >= subs[cur][1]:
        j = cur + 1
        while j < len(subs) and subs[j][0] <= pos:
            if subs[j][0] <= pos < subs[j][1]:
                active = j
                break
            j += 1
    else:
        # Binary search without requiring bisect to understand tuple shape.
        lo, hi = 0, len(subs) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if subs[mid][0] <= pos:
                if pos < subs[mid][1]:
                    active = mid
                    break
                lo = mid + 1
            else:
                hi = mid - 1

    self._f22_subtitle_cursor = active

    if active < 0:
        _f22_clear_subtitle_display(self)
        return

    _, _, native, trans = subs[active]
    mode = self.display_mode_combo.currentIndex()
    if mode == 1:
        main, top = (native or trans), ''
    elif mode == 2:
        main, top = (trans or native), ''
    else:
        main, top = native, ('🌐 ' + trans) if trans else ''

    if self.subtitle_bar.text() != main:
        self.subtitle_bar.setText(main)
    if self.subtitle_bar_top.text() != top:
        self.subtitle_bar_top.setText(top)


def _f22_subtitle_finished(self, count=0):
    if getattr(self, 'generated_subs', None):
        _f22_fix_subtitles(self)
    _f22_clear_subtitle_display(self)
    _f22_log(self, f'AI subtitles ready: {len(getattr(self, "generated_subs", []))} speech-timed cues.', '#2ECC71')


def _f22_subtitle_settings(self):
    opt = _f22_subtitle_options(self)
    dlg = QDialog(self)
    dlg.setWindowTitle('AI Subtitle Timing & Silence Control')
    dlg.resize(460, 330)
    lay = QGridLayout(dlg)

    controls = []
    for row, (label, key, value, lo, hi, step) in enumerate([
        ('Display tail after speech (ms)', 'tail_ms', opt['tail_ms'], 0, 1000, 10),
        ('Minimum cue duration (ms)', 'min_ms', opt['min_ms'], 50, 3000, 10),
        ('Maximum cue duration (ms)', 'max_ms', opt['max_ms'], 1000, 20000, 100),
        ('Silence gap reference (ms)', 'gap_ms', opt['gap_ms'], 100, 3000, 10),
    ]):
        lay.addWidget(QLabel(label), row, 0)
        box = QSpinBox()
        box.setRange(lo, hi)
        box.setSingleStep(step)
        box.setValue(value)
        lay.addWidget(box, row, 1)
        controls.append((key, box))

    hide_pause = QCheckBox('Hide subtitles while paused')
    hide_pause.setChecked(opt['hide_paused'])
    lay.addWidget(hide_pause, 4, 0, 1, 2)

    hide_mute = QCheckBox('Hide subtitles while muted')
    hide_mute.setChecked(opt['hide_muted'])
    lay.addWidget(hide_mute, 5, 0, 1, 2)

    info = QLabel('The renderer never extends a cue to the next dialogue.\n'
                  'Whisper word timing remains the authoritative speech boundary.')
    info.setWordWrap(True)
    lay.addWidget(info, 6, 0, 1, 2)

    buttons = QHBoxLayout()
    save = QPushButton('Save & Repair Current Subtitles')
    cancel = QPushButton('Cancel')
    buttons.addWidget(save); buttons.addWidget(cancel)
    lay.addLayout(buttons, 7, 0, 1, 2)
    cancel.clicked.connect(dlg.reject)

    def apply():
        for key, box in controls:
            self.settings.setValue('f22_sub_' + key, box.value())
        self.settings.setValue('f22_sub_hide_paused', hide_pause.isChecked())
        self.settings.setValue('f22_sub_hide_muted', hide_mute.isChecked())
        _f22_fix_subtitles(self)
        _f22_subtitle_tick(self)
        dlg.accept()

    save.clicked.connect(apply)
    dlg.exec()


def _f22_edit_current_cue(self):
    if not getattr(self, 'generated_subs', None):
        return
    pos = (self.player.position() + int(getattr(self, 'sub_delay_ms', 0))) / 1000.0
    idx = next((i for i, (a,b,_,_) in enumerate(self.generated_subs) if a <= pos < b), -1)
    if idx < 0:
        return
    a,b,t,tr = self.generated_subs[idx]
    text, ok = QInputDialog.getMultiLineText(self, 'Edit Subtitle', 'Native subtitle:', t)
    if not ok:
        return
    self.generated_subs[idx] = (a,b,text.strip(),tr)
    _f22_subtitle_tick(self)


def _f22_shift_selected_subtitle(self, delta_ms):
    if not getattr(self, 'generated_subs', None):
        return
    pos = self.player.position()/1000.0
    idx = next((i for i,(a,b,_,_) in enumerate(self.generated_subs) if a <= pos < b), -1)
    if idx < 0:
        return
    a,b,t,tr = self.generated_subs[idx]
    d = delta_ms/1000.0
    self.generated_subs[idx] = (max(0,a+d), max(max(0,a+d)+0.05,b+d), t,tr)
    _f22_fix_subtitles(self)


def _f22_merge_with_next(self):
    if not getattr(self, 'generated_subs', None):
        return
    pos=self.player.position()/1000.0
    idx=next((i for i,(a,b,_,_) in enumerate(self.generated_subs) if a<=pos<b),-1)
    if idx<0 or idx+1>=len(self.generated_subs): return
    a,b,t,tr=self.generated_subs[idx]
    na,nb,nt,ntr=self.generated_subs[idx+1]
    merged=((t+' '+nt).strip(), (tr+' '+ntr).strip())
    self.generated_subs[idx]=(a,nb,merged[0],merged[1])
    del self.generated_subs[idx+1]
    _f22_fix_subtitles(self)


def _f22_split_current(self):
    if not getattr(self, 'generated_subs', None): return
    pos=self.player.position()/1000.0
    idx=next((i for i,(a,b,_,_) in enumerate(self.generated_subs) if a<pos<b),-1)
    if idx<0: return
    a,b,t,tr=self.generated_subs[idx]
    words=t.split()
    if len(words)<2 or not (a+0.15 < pos < b-0.15): return
    ratio=(pos-a)/max(0.001,b-a)
    cut=max(1,min(len(words)-1,int(round(len(words)*ratio))))
    t1=' '.join(words[:cut]); t2=' '.join(words[cut:])
    mid=a+(b-a)*(cut/len(words))
    self.generated_subs[idx:idx+1]=[(a,mid,t1,''),(mid,b,t2,'')]
    _f22_fix_subtitles(self)


def _f22_export_ass(self):
    if not getattr(self,'generated_subs',None): return
    out,_=QFileDialog.getSaveFileName(self,'Export ASS Subtitle','subtitles.ass','ASS (*.ass)')
    if not out:return
    def ts(x):
        x=max(0,float(x)); h=int(x//3600);m=int((x%3600)//60);s=x%60
        return f'{h:d}:{m:02d}:{s:05.2f}'
    lines=['[Script Info]','ScriptType: v4.00+','PlayResX: 1920','PlayResY: 1080','',
           '[V4+ Styles]','Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
           'Style: Default,Segoe UI,48,&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,1,0,1,2,1,2,60,60,45,1','',
           '[Events]','Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    for i,(a,b,t,tr) in enumerate(self.generated_subs,1):
        text=t + (r'\\N'+tr if tr else '')
        lines.append(f'Dialogue: 0,{ts(a)},{ts(b)},Default,,0,0,0,,{text}')
    _f22_os.makedirs(_f22_os.path.dirname(out) or '.',exist_ok=True)
    open(out,'w',encoding='utf-8').write('\n'.join(lines))
    _f22_log(self,'ASS subtitle exported: '+out,'#2ECC71')


def _f22_export_json(self):
    if not getattr(self,'generated_subs',None): return
    out,_=QFileDialog.getSaveFileName(self,'Export Subtitle JSON','subtitles.json','JSON (*.json)')
    if not out:return
    data=[{'start':a,'end':b,'native':t,'translation':tr} for a,b,t,tr in self.generated_subs]
    open(out,'w',encoding='utf-8').write(_f22_json.dumps(data,ensure_ascii=False,indent=2))
    _f22_log(self,'Subtitle JSON exported: '+out,'#2ECC71')


def _f22_import_subtitle_json(self):
    path,_=QFileDialog.getOpenFileName(self,'Import Subtitle JSON','','JSON (*.json)')
    if not path:return
    try:
        data=_f22_json.loads(open(path,encoding='utf-8').read())
        self.generated_subs=[(float(x['start']),float(x['end']),x.get('native',''),x.get('translation','')) for x in data]
        _f22_fix_subtitles(self); _f22_subtitle_tick(self)
    except Exception as e:
        QMessageBox.warning(self,'Subtitle Import',str(e))


def _f22_clear_and_reload_subs(self):
    self.generated_subs=[]; self._adv_subtitle_cursor=-1; _f22_clear_subtitle_display(self)


def _f22_auto_repair_subtitles(self):
    _f22_fix_subtitles(self); _f22_subtitle_tick(self)


def _f22_subtitle_report(self):
    subs=getattr(self,'generated_subs',[]) or []
    if not subs:
        QMessageBox.information(self,'Subtitle Report','No generated subtitles.')
        return
    durations=[b-a for a,b,_,_ in subs]
    gaps=[max(0,subs[i+1][0]-subs[i][1]) for i in range(len(subs)-1)]
    words=sum(len(_f22_re.findall(r"\b[\w'-]+\b",t or '')) for _,_,t,_ in subs)
    chars=sum(len(t or '') for _,_,t,_ in subs)
    avg= sum(durations)/len(durations)
    gmax=max(gaps or [0])
    msg=(f'Cues: {len(subs)}\nWords: {words}\nCharacters: {chars}\n'
         f'Average cue duration: {avg:.2f}s\nLongest silent gap: {gmax:.2f}s\n'
         f'Longest cue: {max(durations):.2f}s')
    QMessageBox.information(self,'Subtitle Quality Report',msg)


def _f22_copy_current_subtitle(self):
    pos=self.player.position()/1000.0
    for a,b,t,tr in getattr(self,'generated_subs',[]):
        if a<=pos<b:
            QApplication.clipboard().setText(t + (('\n'+tr) if tr else ''))
            return


def _f22_jump_next_silence(self):
    subs=getattr(self,'generated_subs',[]) or []
    pos=self.player.position()/1000.0
    for i,(a,b,_,_) in enumerate(subs[:-1]):
        if b>pos and subs[i+1][0]-b>=_f22_subtitle_options(self)['gap_ms']/1000:
            self.player.setPosition(int(b*1000)); return


def _f22_jump_next_dialogue(self):
    for a,b,t,tr in getattr(self,'generated_subs',[]):
        if a>self.player.position()/1000.0:
            self.player.setPosition(int(a*1000)); return

# ---------- Playback feature helpers ----------
def _f22_skip(self, sec):
    self.player.setPosition(max(0,min(self.player.duration(), self.player.position()+int(sec*1000))))

def _f22_frame_step(self, direction=1):
    # Default to ~30 FPS; avoids decoder-specific frame APIs.
    _f22_skip(self, direction/30.0)

def _f22_jump_pct(self, pct):
    if self.player.duration()>0:self.player.setPosition(int(self.player.duration()*pct/100))

def _f22_toggle_loop_current_sub(self):
    pos=self.player.position()/1000.0
    idx=next((i for i,(a,b,_,_) in enumerate(getattr(self,'generated_subs',[]) or []) if a<=pos<b),-1)
    if idx<0:return
    a,b,_,_=self.generated_subs[idx]
    if getattr(self,'_f22_sub_loop',None)==idx:
        self._f22_sub_loop=None; self.log_event('Subtitle cue loop OFF')
    else:
        self._f22_sub_loop=(idx,a,b); self.log_event(f'Subtitle cue loop: {self._format_time(int(a*1000))}')

def _f22_tick_extra(self):
    loop=getattr(self,'_f22_sub_loop',None)
    if loop and len(loop)>=3:
        _,a,b=loop
        if self.player.position()/1000.0>=b:self.player.setPosition(int(a*1000))

# ---------- Media / export helpers ----------
def _f22_ffmpeg(self,args,task,output=None):
    p=_f22_require_file(self)
    if not p:return
    cmd=['ffmpeg','-y','-hide_banner','-loglevel','warning','-i',p]+list(args)
    if output:cmd.append(output)
    self.run_bg_task(FFmpegWorker(cmd,task))

def _f22_output(self,suffix,ext='.mp4'):
    p=_f22_require_file(self)
    if not p:return None
    root,_=_f22_os.path.splitext(p)
    return root+suffix+ext

def _f22_extract_audio(self, codec, ext, bitrate=None):
    out=_f22_output(self,'_Audio',ext)
    if not out:return
    args=['-vn','-c:a',codec]
    if bitrate:args += ['-b:a',bitrate]
    _f22_ffmpeg(self,args,'Audio extraction',out)

def _f22_screenshot_at(self, offset=0.0):
    p=_f22_require_file(self)
    if not p:return
    sec=max(0,self.player.position()/1000.0+offset)
    out=_f22_os.path.join(_f22_os.path.dirname(p),f'frame_{int(sec*1000)}ms.png')
    _f22_subprocess.Popen(['ffmpeg','-y','-ss',str(sec),'-i',p,'-frames:v','1',out],creationflags=CREATE_NO_WINDOW)
    _f22_log(self,f'Frame saved: {out}','#2ECC71')

def _f22_screenshot_burst_custom(self):
    p=_f22_require_file(self)
    if not p:return
    folder=QFileDialog.getExistingDirectory(self,'Burst Output')
    if not folder:return
    count,ok=QInputDialog.getInt(self,'Burst Screenshots','Frames:',20,2,500,1)
    if not ok:return
    start=self.player.position()/1000.0
    span=QInputDialog.getDouble(self,'Burst Screenshots','Duration seconds:',5,0.2,600,1)[0]
    fps=count/max(0.1,span)
    cmd=['ffmpeg','-y','-ss',str(start),'-t',str(span),'-i',p,'-vf',f'fps={fps:g}','-q:v','2',_f22_os.path.join(folder,'burst_%05d.jpg')]
    self.run_bg_task(FFmpegWorker(cmd,'Custom Screenshot Burst'))

def _f22_probe_summary(self):
    p=_f22_require_file(self)
    if not p:return
    try:
        r=_f22_subprocess.run(['ffprobe','-v','error','-show_entries','format=duration,size,bit_rate,format_name','-of','default=noprint_wrappers=1',p],capture_output=True,text=True,creationflags=CREATE_NO_WINDOW,timeout=20)
        QMessageBox.information(self,'Quick Media Summary',r.stdout.strip() or r.stderr.strip())
    except Exception as e:QMessageBox.warning(self,'ffprobe',str(e))

def _f22_reencode_fast(self):
    out=_f22_output(self,'_Fast','.mp4')
    if out:_f22_ffmpeg(self,['-c:v','libx264','-preset','veryfast','-crf','23','-c:a','aac','-b:a','160k'],'Fast H.264 export',out)

def _f22_reencode_quality(self):
    out=_f22_output(self,'_HQ','.mp4')
    if out:_f22_ffmpeg(self,['-c:v','libx264','-preset','slow','-crf','18','-c:a','aac','-b:a','256k'],'High quality export',out)

def _f22_h265_export(self):
    out=_f22_output(self,'_H265','.mp4')
    if out:_f22_ffmpeg(self,['-c:v','libx265','-preset','medium','-crf','22','-c:a','aac','-b:a','192k'],'H.265 export',out)

def _f22_av1_export(self):
    out=_f22_output(self,'_AV1','.mkv')
    if out:_f22_ffmpeg(self,['-c:v','libsvtav1','-crf','30','-preset','6','-c:a','libopus','-b:a','160k'],'AV1 export',out)

def _f22_strip_metadata(self):
    out=_f22_output(self,'_Clean','.mkv')
    if out:_f22_ffmpeg(self,['-map','0','-map_metadata','-1','-c','copy'],'Strip metadata',out)

def _f22_extract_cover(self):
    p=_f22_require_file(self)
    if not p:return
    out=_f22_os.path.splitext(p)[0]+'_cover.jpg'
    _f22_ffmpeg(self,['-an','-vcodec','mjpeg','-frames:v','1'],'Cover extraction',out)

def _f22_blackbar_crop(self):
    out=_f22_output(self,'_NoBars','.mp4')
    if out:_f22_ffmpeg(self,['-vf','cropdetect=24:16:0'],'Black-bar analysis',None)

def _f22_color_adjust(self):
    text,ok=QInputDialog.getText(self,'Color Adjust','brightness:contrast:saturation',text='0:1:1')
    if ok and _f22_re.fullmatch(r'-?\d+(?:\.\d+)?:-?\d+(?:\.\d+)?:-?\d+(?:\.\d+)?',text.strip()):
        b,c,s=text.split(':')
        out=_f22_output(self,'_Color','.mp4')
        if out:_f22_ffmpeg(self,['-vf',f'eq=brightness={b}:contrast={c}:saturation={s}','-c:v','libx264','-crf','20','-c:a','copy'],'Color adjustment',out)

def _f22_resize_preset(self, size):
    out=_f22_output(self,f'_{size.replace(":","x")}', '.mp4')
    if out:_f22_ffmpeg(self,['-vf',f'scale={size}:force_original_aspect_ratio=decrease','-c:v','libx264','-crf','20','-c:a','copy'],'Resize '+size,out)

def _f22_audio_lufs(self):
    p=_f22_require_file(self)
    if not p:return
    try:
        r=_f22_subprocess.run(['ffmpeg','-hide_banner','-i',p,'-af','ebur128=framelog=verbose','-f','null','-'],capture_output=True,text=True,creationflags=CREATE_NO_WINDOW,timeout=120)
        report=(r.stderr or '')[-6000:]
        QMessageBox.information(self,'EBU R128 Loudness',report)
    except Exception as e:QMessageBox.warning(self,'Loudness',str(e))

def _f22_audio_silence_scan(self):
    p=_f22_require_file(self)
    if not p:return
    try:
        r=_f22_subprocess.run(['ffmpeg','-hide_banner','-i',p,'-af','silencedetect=noise=-35dB:d=0.4','-f','null','-'],capture_output=True,text=True,creationflags=CREATE_NO_WINDOW,timeout=120)
        QMessageBox.information(self,'Silence Scan',(r.stderr or '')[-10000:])
    except Exception as e:QMessageBox.warning(self,'Silence Scan',str(e))

# ---------- Organization / library ----------
def _f22_set_note(self):
    p=_f22_current_file(self)
    if not p:return
    self._v21_index_file(p)
    old=self.library_db.execute('SELECT notes FROM media WHERE path=?',(os.path.abspath(p),)).fetchone()
    val,ok=QInputDialog.getMultiLineText(self,'Media Note','Note:',old[0] if old else '')
    if ok:
        self.library_db.execute('UPDATE media SET notes=? WHERE path=?',(val,os.path.abspath(p)));self.library_db.commit()

def _f22_show_tags_notes(self):
    p=_f22_current_file(self)
    if not p:return
    row=self.library_db.execute('SELECT tags,notes,rating,favorite,watched FROM media WHERE path=?',(os.path.abspath(p),)).fetchone()
    QMessageBox.information(self,'Media Organization',str(row or 'No indexed record'))

def _f22_toggle_watched(self):
    p=_f22_current_file(self)
    if not p:return
    self._v21_index_file(p)
    row=self.library_db.execute('SELECT watched FROM media WHERE path=?',(os.path.abspath(p),)).fetchone()
    new=0 if row and row[0] else 1
    self.library_db.execute('UPDATE media SET watched=? WHERE path=?',(new,os.path.abspath(p)));self.library_db.commit()

def _f22_reset_resume(self):
    p=_f22_current_file(self)
    if p:
        self.resume_data.pop(p,None)
        self.library_db.execute('UPDATE media SET position=0 WHERE path=?',(os.path.abspath(p),));self.library_db.commit()

def _f22_scan_current_folder(self):
    p=_f22_current_file(self)
    if not p:return
    folder=os.path.dirname(p)
    count=0
    exts={'.mp4','.mkv','.mov','.avi','.webm','.m4v','.ts','.m2ts','.mp3','.flac','.wav','.aac','.m4a','.ogg','.opus'}
    for root,_,names in os.walk(folder):
        for n in names:
            if os.path.splitext(n)[1].lower() in exts:
                self._v21_index_file(os.path.join(root,n));count+=1
    _f22_log(self,f'Current folder indexed: {count} files.','#2ECC71')

def _f22_media_counts(self):
    r=self.library_db.execute('SELECT COUNT(*),COALESCE(SUM(size),0),COALESCE(SUM(duration),0) FROM media').fetchone()
    QMessageBox.information(self,'Library Counts',f'Files: {r[0]}\nSize: {r[1]/1024**3:.2f} GB\nDuration: {r[2]/3600:.2f} hours')

def _f22_cleanup_missing(self):
    rows=self.library_db.execute('SELECT path FROM media').fetchall();n=0
    for (path,) in rows:
        if not os.path.exists(path):
            self.library_db.execute('DELETE FROM media WHERE path=?',(path,));n+=1
    self.library_db.commit();_f22_log(self,f'Removed {n} missing library records.','#F39C12')

def _f22_export_library_json(self):
    out,_=QFileDialog.getSaveFileName(self,'Export Library JSON','omniplayer_library.json','JSON (*.json)')
    if not out:return
    rows=self.library_db.execute('SELECT * FROM media').fetchall()
    cols=[d[0] for d in self.library_db.execute('SELECT * FROM media LIMIT 1').description]
    open(out,'w',encoding='utf-8').write(_f22_json.dumps([dict(zip(cols,r)) for r in rows],ensure_ascii=False,indent=2))

def _f22_clear_playlist_and_keep_current(self):
    cur=self.current_media
    self.playlist=[cur] if cur else []
    self.playlist_widget.clear()
    if cur:self.playlist_widget.addItem(os.path.basename(str(cur)))

def _f22_remove_current_from_playlist(self):
    p=self.current_media
    if not p:return
    while p in self.playlist:self.playlist.remove(p)
    self.playlist_widget.clear();self.playlist_widget.addItems([os.path.basename(x) for x in self.playlist])

# ---------- UI / system ----------
def _f22_command_search(self):
    menu=self._f22_feature_menu if hasattr(self,'_f22_feature_menu') else None
    q,_=QInputDialog.getText(self,'Feature Search','Search commands:')
    if not q or not menu:return
    q=q.lower()
    hits=[]
    for action in menu.findChildren(QAction):
        if q in action.text().lower():hits.append(action.text())
    _adv_dialog_text(self,'Command Search','Matches:\n'+('\n'.join(hits) if hits else 'No matches'))

def _f22_copy_diagnostics(self):
    lines=[f'OS: {_f22_os.name}',f'Python: {sys.version.split()[0]}',f'PyQt6: OK',f'AI_AVAILABLE: {AI_AVAILABLE}',f'FFmpeg: {shutil.which("ffmpeg") or "NOT FOUND"}',f'ffprobe: {shutil.which("ffprobe") or "NOT FOUND"}']
    text='\n'.join(lines);QApplication.clipboard().setText(text);QMessageBox.information(self,'Diagnostics',text)

def _f22_reset_subtitle_timing_defaults(self):
    for k,v in [('tail_ms',120),('min_ms',180),('max_ms',7000),('gap_ms',650)]:self.settings.setValue('f22_sub_'+k,v)
    self.settings.setValue('f22_sub_hide_paused',False);self.settings.setValue('f22_sub_hide_muted',False)
    _f22_fix_subtitles(self);_f22_subtitle_tick(self)

def _f22_toggle_subtitle_container(self):
    self.subtitle_container.setVisible(not self.subtitle_container.isVisible())

def _f22_repair_current_subtitle_overlap(self):
    subs=sorted(getattr(self,'generated_subs',[]) or [], key=lambda x:x[0]);out=[]
    for i,(a,b,t,tr) in enumerate(subs):
        if i and a < out[-1][1]:
            pa,pb,pt,ptr=out[-1]; out[-1]=(pa,max(pa,a-0.02),pt,ptr)
        out.append((a,b,t,tr))
    self.generated_subs=out;_f22_fix_subtitles(self);_f22_subtitle_tick(self)

def _f22_export_current_frame_with_subtitle(self):
    p=_f22_require_file(self)
    if not p:return
    sec=self.player.position()/1000
    out,_=QFileDialog.getSaveFileName(self,'Save Current Frame','frame_with_subtitle.png','PNG (*.png)')
    if not out:return
    # Render the current video frame; subtitle is handled by the Qt overlay and
    # therefore cannot be faithfully burned from QVideoWidget with FFmpeg.
    pix=self.video_widget.grab();pix.save(out,'PNG')
    _f22_log(self,'Current UI frame saved: '+out,'#2ECC71')

# Register new methods.
_F22_METHODS = {k:v for k,v in globals().items() if k.startswith('_f22_') and callable(v)}
for _f22_name,_f22_fn in _F22_METHODS.items():
    setattr(OmniPlayerPro,_f22_name,_f22_fn)

# Keep the user's existing public v21 names working, but redirect them to the
# speech-aware timing implementation.
OmniPlayerPro._v21_fix_subtitles = _f22_fix_subtitles
OmniPlayerPro._v21_subtitle_tick = _f22_subtitle_tick
OmniPlayerPro._v21_safe_subtitle_finished = _f22_subtitle_finished

# Replace the old master tick wrapper with one that runs the original player UI
# maintenance and exactly one subtitle engine.
_old_master_tick_f22 = getattr(OmniPlayerPro, 'master_tick', None)
def _master_tick_f22(self):
    if _old_master_tick_f22:
        _old_master_tick_f22(self)
    _f22_subtitle_tick(self)
    _f22_tick_extra(self)
OmniPlayerPro.master_tick = _master_tick_f22

# Do not let the old v21 installer create a second independent subtitle timer.
_old_v21_install_f22 = getattr(OmniPlayerPro, '_v21_install', None)
def _v21_install_f22(self):
    if _old_v21_install_f22:
        _old_v21_install_f22(self)
    try:
        if hasattr(self,'_v21_timer') and self._v21_timer:
            self._v21_timer.stop()
    except Exception:
        pass
    self._adv_subtitle_cursor=-1
    self._f22_subtitle_cursor=-1
    _f22_fix_subtitles(self) if getattr(self,'generated_subs',None) else None
    self.log_event('OmniPlayer Pro 22 subtitle engine enabled. Speech end is authoritative.','#2ECC71')
OmniPlayerPro._v21_install = _v21_install_f22

# Rebind v21 start-AI completion hook so normalization happens after all cues arrive.
_old_start_ai_f22 = getattr(OmniPlayerPro,'start_ai',None)
def _start_ai_f22(self):
    if _old_start_ai_f22:
        _old_start_ai_f22(self)
    try:
        worker=getattr(self,'active_bg_worker',None)
        if worker:
            try: worker.finished.disconnect()
            except Exception: pass
            worker.finished.connect(lambda: _f22_subtitle_finished(self))
    except Exception:
        pass
OmniPlayerPro.start_ai=_start_ai_f22

# --------------------------- Feature Studio menu -------------------------------
def _f22_install_feature_studio(self):
    menu=self.menuBar().addMenu('Feature Studio 22')
    self._f22_feature_menu=menu
    groups={
        'Subtitle AI': [
            ('Subtitle Timing Settings', self._f22_subtitle_settings),
            ('Auto Repair Subtitle Timing', self._f22_auto_repair_subtitles),
            ('Subtitle Quality Report', self._f22_subtitle_report),
            ('Edit Current Cue', self._f22_edit_current_cue),
            ('Shift Current Cue -250ms', lambda: self._f22_shift_selected_subtitle(-250)),
            ('Shift Current Cue +250ms', lambda: self._f22_shift_selected_subtitle(250)),
            ('Merge Current Cue With Next', self._f22_merge_with_next),
            ('Split Current Cue', self._f22_split_current),
            ('Jump To Next Dialogue', self._f22_jump_next_dialogue),
            ('Jump To Next Long Silence', self._f22_jump_next_silence),
            ('Copy Current Subtitle', self._f22_copy_current_subtitle),
            ('Export ASS', self._f22_export_ass),
            ('Export JSON', self._f22_export_json),
            ('Import Subtitle JSON', self._f22_import_subtitle_json),
            ('Reset Subtitle Timing Defaults', self._f22_reset_subtitle_timing_defaults),
            ('Hide/Show Subtitle Deck', self._f22_toggle_subtitle_container),
            ('Repair Subtitle Overlaps', self._f22_repair_current_subtitle_overlap),
            ('Clear Generated Subtitle Cache', self._f22_clear_and_reload_subs),
        ],
        'Playback Lab': [
            ('Skip 3s', lambda: self._f22_skip(3)), ('Skip 5s', lambda: self._f22_skip(5)),
            ('Skip 15s', lambda: self._f22_skip(15)), ('Skip 30s', lambda: self._f22_skip(30)),
            ('Back 3s', lambda: self._f22_skip(-3)), ('Back 5s', lambda: self._f22_skip(-5)),
            ('Back 15s', lambda: self._f22_skip(-15)), ('Back 30s', lambda: self._f22_skip(-30)),
            ('Jump 10%', lambda: self._f22_jump_pct(10)), ('Jump 20%', lambda: self._f22_jump_pct(20)),
            ('Jump 50%', lambda: self._f22_jump_pct(50)), ('Jump 80%', lambda: self._f22_jump_pct(80)),
            ('Jump 90%', lambda: self._f22_jump_pct(90)),
            ('Frame Forward', lambda: self._f22_frame_step(1)),
            ('Frame Backward', lambda: self._f22_frame_step(-1)),
            ('Toggle Current Subtitle Loop', self._f22_toggle_loop_current_sub),
            ('Save Current Frame + UI', self._f22_export_current_frame_with_subtitle),
            ('Always On Top', self._adv_toggle_always_on_top),
            ('Schedule Pause', self._adv_toggle_pause_after),
        ],
        'Media Export': [
            ('Fast H.264 Export', self._f22_reencode_fast),
            ('High Quality H.264 Export', self._f22_reencode_quality),
            ('H.265 Export', self._f22_h265_export),
            ('AV1 Export', self._f22_av1_export),
            ('Strip Metadata', self._f22_strip_metadata),
            ('Extract Cover Frame', self._f22_extract_cover),
            ('Capture Current Frame', lambda: self._f22_screenshot_at(0)),
            ('Capture -1s Frame', lambda: self._f22_screenshot_at(-1)),
            ('Capture +1s Frame', lambda: self._f22_screenshot_at(1)),
            ('Custom Screenshot Burst', self._f22_screenshot_burst_custom),
            ('Resize 3840x2160', lambda: self._f22_resize_preset('3840:2160')),
            ('Resize 2560x1440', lambda: self._f22_resize_preset('2560:1440')),
            ('Resize 1920x1080', lambda: self._f22_resize_preset('1920:1080')),
            ('Resize 1280x720', lambda: self._f22_resize_preset('1280:720')),
            ('Resize 854x480', lambda: self._f22_resize_preset('854:480')),
            ('Color Adjustment', self._f22_color_adjust),
        ],
        'Audio Lab': [
            ('Extract WAV', lambda: self._f22_extract_audio('pcm_s16le','.wav')),
            ('Extract FLAC', lambda: self._f22_extract_audio('flac','.flac')),
            ('Extract Opus 160k', lambda: self._f22_extract_audio('libopus','.opus','160k')),
            ('Extract AAC 256k', lambda: self._f22_extract_audio('aac','.m4a','256k')),
            ('Measure EBU R128 Loudness', self._f22_audio_lufs),
            ('Scan Silence', self._f22_audio_silence_scan),
            ('Normalize to -16 LUFS', self._adv_audio_normalize),
            ('Dialogue Noise Reduction', self._adv_audio_denoise),
            ('Dialogue Compressor', self._adv_audio_compressor),
            ('Peak Limiter', self._adv_audio_limiter),
            ('Bass Boost', self._adv_audio_bass),
            ('Treble Boost', self._adv_audio_treble),
            ('Low Pass 12kHz', self._adv_audio_lowpass),
            ('High Pass 80Hz', self._adv_audio_highpass),
        ],
        'Library & Organization': [
            ('Scan Current Folder', self._f22_scan_current_folder),
            ('Library Counts', self._f22_media_counts),
            ('Cleanup Missing Records', self._f22_cleanup_missing),
            ('Export Library JSON', self._f22_export_library_json),
            ('Set Media Note', self._f22_set_note),
            ('Show Tags / Notes / State', self._f22_show_tags_notes),
            ('Toggle Watched', self._f22_toggle_watched),
            ('Reset Resume Position', self._f22_reset_resume),
            ('Remove Current From Playlist', self._f22_remove_current_from_playlist),
            ('Keep Only Current In Playlist', self._f22_clear_playlist_and_keep_current),
            ('Add Entire Folder', self._adv_playlist_add_folder),
            ('Remove Duplicate Playlist Entries', self._adv_playlist_dedupe),
            ('Sort Playlist', self._adv_playlist_sort_name),
            ('Reverse Playlist', self._adv_playlist_reverse),
            ('Randomize Playlist', self._adv_playlist_randomize),
            ('Export M3U8', self._adv_playlist_export),
            ('Import M3U8', self._adv_playlist_import),
            ('Remove Missing Playlist Files', self._adv_playlist_remove_missing),
        ],
        'Inspection & Diagnostics': [
            ('Quick Media Summary', self._f22_probe_summary),
            ('Professional Inspector', self._v21_probe_current),
            ('Stream Inspector', self._adv_show_stream_table),
            ('Advanced Media Report', self._adv_media_report),
            ('Export ffprobe JSON', self._adv_export_probe_json),
            ('SHA-256 Current File', self._adv_hash_current),
            ('Verify SHA-256', self._adv_verify_hash),
            ('Hardware / Decoder Diagnostics', self._v21_hardware_info),
            ('Dependency Diagnostics', self._adv_check_dependencies),
            ('Copy System Diagnostics', self._f22_copy_diagnostics),
            ('Network Diagnostics', self._v21_network_diagnostics),
            ('Show Config Path', self._adv_show_config_path),
            ('Show Cache Path', self._adv_show_cache_path),
            ('Show Temp Path', self._adv_show_temp_path),
            ('Clear Telemetry Log', self._adv_clear_log),
            ('Export Telemetry Log', self._adv_export_log),
        ],
        'Video Effects': [
            ('Grayscale', self._adv_grayscale), ('Sepia', self._adv_sepia),
            ('Sharpen', self._adv_sharpen), ('Blur', self._adv_blur),
            ('Mirror Horizontal', self._adv_flip_h), ('Flip Vertical', self._adv_flip_v),
            ('Video Denoise', self._adv_denoise_video), ('Deinterlace', self._adv_deinterlace),
            ('Rotate 90 CW', lambda: self._adv_rotate_video()), ('Crop Video', self._adv_crop_video),
            ('Change FPS', self._adv_change_fps), ('Scale Video Custom', self._adv_scale_video),
            ('Extract Video Frames', self._adv_extract_frames),
            ('Current Thumbnail', self._v21_thumbnail),
            ('Scene Detection', self._v21_scene_detect),
            ('Contact Sheet Custom', self._adv_contact_sheet_custom),
            ('Create 30s Preview', self._adv_make_preview),
        ],
        'AI / Intelligence': [
            ('Generate AI Subtitles', self.start_ai),
            ('AI Auto Chapters', self.generate_ai_chapters),
            ('AI Chapters From Transcript', self._v21_auto_chapter_from_subs),
            ('Transcript Search', self._adv_find_transcript),
            ('Next Subtitle', self._adv_jump_sub_next),
            ('Previous Subtitle', self._adv_jump_sub_previous),
            ('Export WebVTT', self._adv_export_vtt),
            ('Export Plain Transcript', self._adv_export_txt),
            ('Transcript Statistics', self._adv_transcript_stats),
            ('TMDB Metadata', self.fetch_metadata),
            ('Scene Detection', self._v21_scene_detect),
            ('Screenshot Burst', self._v21_screenshot_burst),
        ],
        'Security & Network': [
            ('Encrypt Current File', self.encrypt_file),
            ('Unlock Vault File', self.play_encrypted_media_prompt),
            ('Secure Delete', self.secure_delete),
            ('Open Network Stream', self.open_network_stream),
            ('Open YouTube Stream', self.open_youtube_stream),
            ('Cast To Chromecast', self.cast_to_chromecast),
            ('Toggle DLNA Server', self.toggle_dlna_server),
            ('Toggle Voice Control', self.toggle_voice_control),
        ],
        'Interface': [
            ('Toggle Fullscreen', self.toggle_fullscreen),
            ('Toggle PiP', self.toggle_pip_mode),
            ('Toggle Controls', self.toggle_ui_controls),
            ('Compact Interface', self._adv_compact_ui),
            ('Toggle Playlist Dock', self._adv_toggle_playlist),
            ('Toggle Bookmark Dock', self._adv_toggle_bookmarks),
            ('Toggle Telemetry Console', self._adv_toggle_console),
            ('Reset View Layout', self._adv_reset_view),
            ('Dark Theme', self._adv_set_theme_dark),
            ('Light Theme', self._adv_set_theme_light),
            ('Sapphire Theme', self._adv_set_theme_sapphire),
            ('Toggle Status Bar', self._adv_toggle_status),
            ('Command Search', self._f22_command_search),
            ('Keyboard Shortcuts', self.show_shortcuts),
        ],
    }
    for group_name, items in groups.items():
        sub=menu.addMenu(group_name)
        for label, cb in items:
            act=QAction(label,self)
            act.triggered.connect(lambda checked=False, callback=cb: callback())
            sub.addAction(act)
    # Extra command-count marker for diagnostics.
    count=sum(len(x) for x in groups.values())
    self.log_event(f'Feature Studio 22 loaded: {count} additional commands.','#2ECC71')

OmniPlayerPro._f22_install_feature_studio=_f22_install_feature_studio

# Install Feature Studio after the existing v21 menus have been installed.
_prev_init_f22 = OmniPlayerPro.__init__
def _init_f22(self,*args,**kwargs):
    _prev_init_f22(self,*args,**kwargs)
    try:
        self._f22_install_feature_studio()
    except Exception as e:
        try:self.log_event(f'Feature Studio install warning: {e}','#F39C12')
        except Exception:pass
OmniPlayerPro.__init__=_init_f22



# =============================================================================
# OMNIPLAYER PRO 23.x — MODERN 3D GLASS UI + ADVANCED ACTION DECK
# =============================================================================
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QToolButton, QSizePolicy


def _v23_local(self):
    p = getattr(self, 'current_media', None)
    return str(p) if p and not str(p).startswith(('http://','https://')) and os.path.isfile(str(p)) else None

def _v23_seek(self, sec):
    try:
        target=max(0,min(self.player.duration(), self.player.position()+int(sec*1000)))
        self.player.setPosition(target); self._f22_subtitle_cursor=-1; self._adv_subtitle_cursor=-1
    except Exception as e: self.log_event(f'Seek error: {e}', '#E74C3C')

def _v23_seek_percent(self, pct):
    if self.player.duration()>0:
        self.player.setPosition(int(self.player.duration()*pct/100)); self._f22_subtitle_cursor=-1

def _v23_frame(self, n=1):
    try:
        was=self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState
        if was:self.player.pause()
        fps=30.0; p=_v23_local(self)
        if p:
            info=_v21_probe(p); vs=next((x for x in info.get('streams',[]) if x.get('codec_type')=='video'),{})
            fps=_v21_fps(vs.get('avg_frame_rate') or vs.get('r_frame_rate')) or 30.0
        self.player.setPosition(max(0,self.player.position()+int(n*1000/fps)))
        if was:self.player.play()
    except Exception: pass

def _v23_screenshot(self, suffix='shot'):
    if not self.is_video:return
    out=os.path.join(self.screenshot_path,f'{suffix}_{int(time.time()*1000)}.png')
    self.video_widget.grab().save(out,'PNG'); self.log_event(f'Screenshot: {out}','#2ECC71')

def _v23_ffmpeg(self, args, title, ext='.mp4'):
    p=_v23_local(self)
    if not p: self.log_event('Local media required.','#F39C12'); return
    root,_=os.path.splitext(p); out=root+'_'+re.sub(r'[^A-Za-z0-9_-]+','_',title)+ext
    self._f22_ffmpeg(args,title,out)

def _v23_audio_mp3(self): _v23_ffmpeg(self,['-vn','-c:a','libmp3lame','-q:a','2'],'MP3','.mp3')
def _v23_audio_ogg(self): _v23_ffmpeg(self,['-vn','-c:a','libvorbis','-q:a','6'],'OGG','.ogg')

def _v23_thumbnail_strip(self):
    p=_v23_local(self)
    if p:self._f22_ffmpeg(['-vf','fps=1/10,scale=240:-1,tile=5x4','-q:v','3'],'Thumbnail Strip',os.path.splitext(p)[0]+'_strip.jpg')

def _v23_keyframes(self):
    p=_v23_local(self)
    if p:self._f22_ffmpeg(['-vf','select=eq(pict_type\\,I)','-vsync','vfr','-q:v','2'],'Keyframe Extraction',os.path.splitext(p)[0]+'_keyframes_%05d.jpg')

def _v23_black_scan(self):
    p=_v23_local(self)
    if not p:return
    cmd=['ffmpeg','-y','-hide_banner','-i',p,'-vf','blackdetect=d=0.5:pix_th=0.10','-an','-f','null','-']
    try:
        r=subprocess.run(cmd,capture_output=True,text=True,creationflags=CREATE_NO_WINDOW,timeout=180)
        out=os.path.splitext(p)[0]+'_blackdetect.txt'; Path(out).write_text(r.stderr,encoding='utf-8',errors='ignore'); self.log_event(f'Black-frame scan: {out}','#2ECC71')
    except Exception as e:self.log_event(str(e),'#E74C3C')

def _v23_scenes(self):
    p=_v23_local(self)
    if not p:return
    out=os.path.splitext(p)[0]+'_scenes.txt'; cmd=['ffmpeg','-hide_banner','-i',p,'-vf',"select='gt(scene,0.30)',showinfo",'-f','null','-']
    try:
        r=subprocess.run(cmd,capture_output=True,text=True,creationflags=CREATE_NO_WINDOW,timeout=180)
        Path(out).write_text('\n'.join([x for x in r.stderr.splitlines() if 'pts_time:' in x]),encoding='utf-8'); self.log_event(f'Scene candidates: {out}','#2ECC71')
    except Exception as e:self.log_event(str(e),'#E74C3C')

def _v23_copy_time(self): QApplication.clipboard().setText(self._format_time(self.player.position())); self.log_event('Current time copied.')
def _v23_copy_title(self): QApplication.clipboard().setText(os.path.basename(str(self.current_media or '')))
def _v23_copy_sub(self): self._f22_copy_current_subtitle()
def _v23_first_dialogue(self):
    if getattr(self,'generated_subs',None): self.player.setPosition(int(self.generated_subs[0][0]*1000))
def _v23_last_dialogue(self):
    if getattr(self,'generated_subs',None): self.player.setPosition(int(self.generated_subs[-1][0]*1000))
def _v23_loop10(self): self.ab_loop_start=max(0,self.player.position()-5000);self.ab_loop_end=self.player.position()+5000
def _v23_loop30(self): self.ab_loop_start=max(0,self.player.position()-15000);self.ab_loop_end=self.player.position()+15000
def _v23_25(self): self.change_volume(25)
def _v23_50(self): self.change_volume(50)
def _v23_75(self): self.change_volume(75)
def _v23_100(self): self.change_volume(100)
def _v23_150(self): self.change_volume(150)
def _v23_speed05(self): self._adv_toggle_playback_rate(0.5)
def _v23_speed1(self): self._adv_toggle_playback_rate(1.0)
def _v23_speed125(self): self._adv_toggle_playback_rate(1.25)
def _v23_speed15(self): self._adv_toggle_playback_rate(1.5)
def _v23_speed2(self): self._adv_toggle_playback_rate(2.0)
def _v23_modern_theme(self):
    qss="""QMainWindow{background:#080b12;color:#edf3ff} QWidget{color:#eaf1ff;font-family:'Segoe UI'} QFrame,QGroupBox,QDockWidget{background:#121824;border:1px solid #304666;border-radius:14px} QLineEdit,QTextEdit,QComboBox,QSpinBox{background:#0d1422;border:1px solid #2b405e;border-radius:9px;padding:7px} QTabWidget::pane{background:#0c1220;border:1px solid #304666;border-radius:12px} QTabBar::tab{background:#101827;padding:9px 16px;border-radius:9px;margin:2px} QTabBar::tab:selected{background:#315fb1;color:white;font-weight:700} QPushButton,QToolButton{background:#142238;border:1px solid #38577e;border-radius:10px;padding:7px 10px;font-weight:600} QPushButton:hover,QToolButton:hover{background:#1d3555} QStatusBar{background:#0b101a;border-top:1px solid #22324a}"""
    self.setStyleSheet(qss)
    for obj in [getattr(self,'controls_frame',None),getattr(self,'display_container',None)]:
        if obj:
            eff=QGraphicsDropShadowEffect(obj);eff.setBlurRadius(26);eff.setOffset(0,7);eff.setColor(QColor(0,0,0,180));obj.setGraphicsEffect(eff)

def _v23_button(self,text,cb,primary=False):
    b=QToolButton(); b.setText(text); b.clicked.connect(cb); b.setSizePolicy(QSizePolicy.Policy.Minimum,QSizePolicy.Policy.Fixed)
    if primary:b.setStyleSheet('QToolButton{background:#315fb1;color:white;font-weight:800;border:1px solid #6e9be0;border-radius:10px;padding:7px 11px}')
    return b

def _v23_build_ribbon(self):
    bar=QToolBar('Pro 3D Ribbon',self);bar.setMovable(False);bar.setFloatable(False);bar.setStyleSheet('QToolBar{background:#0a101b;border:1px solid #263b5a;border-radius:14px;padding:5px;}');self.addToolBar(Qt.ToolBarArea.TopToolBarArea,bar);self._v23_ribbon=bar
    items=[('⏪5s',lambda:self._v23_seek(-5)),('⏪30s',lambda:self._v23_seek(-30)),('▶/⏸',self.toggle_play),('30s⏩',lambda:self._v23_seek(30)),('5s⏩',lambda:self._v23_seek(5)),('🎯50%',lambda:self._v23_seek_percent(50)),('🤖AI',self.start_ai),('📑Chapters',self.generate_ai_chapters),('✎Subtitle',self._f22_edit_current_cue),('🔧Repair',self._f22_auto_repair_subtitles),('📷Screenshot',lambda:_v23_screenshot(self)),('📊Stats',self.toggle_stats),('⋮Commands',self._f22_command_search)]
    for t,c in items:bar.addWidget(self._v23_button(t,c,t in ('▶/⏸','🤖AI')))

def _v23_build_deck(self):
    if not hasattr(self,'controls_frame'):return
    deck=QFrame(self.controls_frame);lay=QHBoxLayout(deck);lay.setContentsMargins(6,4,6,4);lay.setSpacing(5)
    items=[('Frame−',lambda:self._v23_frame(-1)),('Frame+',lambda:self._v23_frame(1)),('Zoom',self._v23_set_zoom),('25%',_v23_25),('50%',_v23_50),('75%',_v23_75),('100%',_v23_100),('150%',_v23_150),('0.5×',_v23_speed05),('1×',_v23_speed1),('1.25×',_v23_speed125),('1.5×',_v23_speed15),('2×',_v23_speed2),('Loop10',_v23_loop10),('Loop30',_v23_loop30),('ClearLoop',self.clear_loop),('CopyTime',_v23_copy_time),('NextDlg',self._f22_jump_next_dialogue),('NextSilence',self._f22_jump_next_silence)]
    for t,c in items:lay.addWidget(self._v23_button(t,c))
    lay.addStretch(); self.controls_frame.layout().insertWidget(max(0,self.controls_frame.layout().count()-1),deck);self._v23_deck=deck

def _v23_groups(self):
    return {
      'Playback Pro': [('Start',lambda:self._v23_seek_percent(0)),('10%',lambda:self._v23_seek_percent(10)),('25%',lambda:self._v23_seek_percent(25)),('50%',lambda:self._v23_seek_percent(50)),('75%',lambda:self._v23_seek_percent(75)),('90%',lambda:self._v23_seek_percent(90)),('End',lambda:self._v23_seek_percent(100)),('Frame Back',lambda:self._v23_frame(-1)),('Frame Forward',lambda:self._v23_frame(1)),('Loop 10s',_v23_loop10),('Loop 30s',_v23_loop30),('Clear Loop',self.clear_loop),('Zoom',self._v23_set_zoom),('Copy Time',_v23_copy_time),('Pause/Resume',self.toggle_play),('Always On Top',self._adv_toggle_always_on_top)],
      'Subtitle Pro': [('Edit Cue',self._f22_edit_current_cue),('Split Cue',self._f22_split_current),('Merge Cue',self._f22_merge_with_next),('Shift -250ms',self._adv_sub_delay_minus),('Shift +250ms',self._adv_sub_delay_plus),('Font Up',self._adv_sub_size_plus),('Font Down',self._adv_sub_size_minus),('Style',self.subtitle_style_dialog),('Timing Settings',self._f22_subtitle_settings),('Repair Timing',self._f22_auto_repair_subtitles),('Quality Report',self._f22_subtitle_report),('First Dialogue',_v23_first_dialogue),('Last Dialogue',_v23_last_dialogue),('Copy Subtitle',_v23_copy_sub),('Export ASS',self._f22_export_ass),('Export JSON',self._f22_export_json),('Import JSON',self._f22_import_subtitle_json)],
      'Video Intelligence': [('Media Summary',self._f22_probe_summary),('Stream Inspector',self._adv_show_stream_table),('Keyframes',_v23_keyframes),('Black Frame Scan',_v23_black_scan),('Scene Candidates',_v23_scenes),('Thumbnail Strip',_v23_thumbnail_strip),('Frame Capture',lambda:self._f22_screenshot_at(0)),('Burst Capture',self._f22_screenshot_burst_custom),('Contact Sheet',self._adv_contact_sheet_custom),('GIF',self._adv_convert_gif_high_quality),('Preview',self._adv_make_preview),('Color Adjust',self._f22_color_adjust),('Crop',self._adv_crop_video)],
      'Audio Pro': [('WAV',lambda:self._f22_extract_audio('pcm_s16le','.wav')),('FLAC',lambda:self._f22_extract_audio('flac','.flac')),('MP3',_v23_audio_mp3),('OGG',_v23_audio_ogg),('AAC',lambda:self._f22_extract_audio('aac','.m4a','256k')),('LUFS Scan',self._f22_audio_lufs),('Silence Scan',self._f22_audio_silence_scan),('Normalize',self._adv_audio_normalize),('Denoise',self._adv_audio_denoise),('Compressor',self._adv_audio_compressor),('Limiter',self._adv_audio_limiter),('Bass',self._adv_audio_bass),('Treble',self._adv_audio_treble)],
      'Library Pro': [('Continue',lambda:self._v21_show_library('continue')),('Favorites',lambda:self._v21_show_library('favorites')),('Unwatched',lambda:self._v21_show_library('unwatched')),('Scan Folder',self._f22_scan_current_folder),('Counts',self._f22_media_counts),('Cleanup Missing',self._f22_cleanup_missing),('Export JSON',self._f22_export_library_json),('Set Note',self._f22_set_note),('Tags/State',self._f22_show_tags_notes),('Toggle Watched',self._f22_toggle_watched),('Reset Resume',self._f22_reset_resume),('Deduplicate Playlist',self._adv_playlist_dedupe),('Sort Playlist',self._adv_playlist_sort_name),('Randomize',self._adv_playlist_randomize),('Export M3U8',self._adv_playlist_export)],
      'Conversion Pro': [('Fast H264',self._f22_reencode_fast),('HQ H264',self._f22_reencode_quality),('H265',self._f22_h265_export),('AV1',self._f22_av1_export),('Remux MP4',lambda:self._adv_remux('.mp4')),('Remux MKV',lambda:self._adv_remux('.mkv')),('Remux MOV',lambda:self._adv_remux('.mov')),('Strip Metadata',self._f22_strip_metadata),('Cover Frame',self._f22_extract_cover),('4K',lambda:self._f22_resize_preset('3840:2160')),('2K',lambda:self._f22_resize_preset('2560:1440')),('1080p',lambda:self._f22_resize_preset('1920:1080')),('720p',lambda:self._f22_resize_preset('1280:720'))],
      'AI Studio': [('AI Subtitles',self.start_ai),('AI Chapters',self.generate_ai_chapters),('Subtitle Report',self._f22_subtitle_report),('Transcript Search',self._adv_find_transcript),('Next Subtitle',self._adv_jump_sub_next),('Previous Subtitle',self._adv_jump_sub_previous),('WebVTT',self._adv_export_vtt),('Transcript TXT',self._adv_export_txt),('TMDB',self.fetch_metadata),('Scene Detection',self._v21_scene_detect),('Screenshot Burst',self._v21_screenshot_burst)],
      'System & UI': [('3D Glass Theme',_v23_modern_theme),('Transparency',lambda:self.setWindowOpacity(0.9 if self.windowOpacity()>0.99 else 1.0)),('All Docks',lambda:(self._adv_toggle_playlist(),self._adv_toggle_bookmarks(),self._adv_toggle_console())),('Reset View',self._adv_reset_view),('Controls',self.toggle_ui_controls),('Playlist Dock',self._adv_toggle_playlist),('Bookmarks',self._adv_toggle_bookmarks),('Telemetry',self._adv_toggle_console),('Status Bar',self._adv_toggle_status),('Dependencies',self._adv_check_dependencies),('Hardware',self._v21_hardware_info),('Diagnostics',self._f22_copy_diagnostics),('Config Path',self._adv_show_config_path),('Cache Path',self._adv_show_cache_path),('Temp Path',self._adv_show_temp_path)]}

def _v23_install_menu(self):
    menu=self.menuBar().addMenu('🚀 Pro Studio 23');self._v23_menu=menu;groups=_v23_groups(self)
    for g,items in groups.items():
        sub=menu.addMenu(g)
        for label,cb in items:
            a=QAction(label,self);a.triggered.connect(lambda checked=False,c=cb:c());sub.addAction(a)
    self.log_event(f'Pro Studio 23 loaded: {sum(len(v) for v in groups.values())} advanced actions.','#2ECC71')

for _n,_f in list(globals().items()):
    if _n.startswith('_v23_') and callable(_f): setattr(OmniPlayerPro,_n,_f)

_prev_init_v23=OmniPlayerPro.__init__
def _init_v23(self,*args,**kwargs):
    _prev_init_v23(self,*args,**kwargs)
    try:
        self._v23_modern_theme();self._v23_build_ribbon();self._v23_build_deck();self._v23_install_menu()
    except Exception as e:
        try:self.log_event(f'Pro Studio 23 warning: {e}','#F39C12')
        except Exception:pass
OmniPlayerPro.__init__=_init_v23

# ============================================================================
# OMNIPLAYER PRO 24 - STUDIO HUD / ADVANCED CONTROL SURFACE
# Visible, mouse-friendly controls for the existing advanced feature engine.
# ============================================================================

def _v23_set_zoom(self):
    """Cycle the viewport zoom used by the player UI."""
    levels = [0.75, 1.0, 1.25, 1.5, 2.0]
    cur = float(getattr(self, 'zoom_factor', 1.0))
    try:
        idx = min(range(len(levels)), key=lambda i: abs(levels[i] - cur))
        nxt = levels[(idx + 1) % len(levels)]
    except Exception:
        nxt = 1.0
    self.set_zoom(nxt)
    try:
        self.lbl_stats.setText(f"ZOOM {nxt:.2f}×")
    except Exception:
        pass
    try:
        self.log_event(f"Viewport zoom: {nxt:.2f}×", '#5DADE2')
    except Exception:
        pass

OmniPlayerPro._v23_set_zoom = _v23_set_zoom


def _v24_set_playback_rate(self, rate):
    self.playback_speed = float(rate)
    try:
        self.player.setPlaybackRate(float(rate))
    except Exception:
        pass
    try:
        self.log_event(f"Playback speed: {rate:g}×", '#5DADE2')
    except Exception:
        pass


def _v24_toggle_mute(self):
    try:
        muted = bool(self.audio_output.isMuted())
        self.audio_output.setMuted(not muted)
        if hasattr(self, '_v24_mute_btn'):
            self._v24_mute_btn.setText('🔇' if not muted else '🔊')
        self.log_event(f"Audio {'muted' if not muted else 'unmuted'}", '#F5B041')
    except Exception as e:
        self.log_event(f"Mute error: {e}", '#E74C3C')


def _v24_open_file(self):
    try:
        f, _ = QFileDialog.getOpenFileName(self, 'Open Media', '', 'Media files (*.*)')
        if f:
            self._play_target(f)
    except Exception as e:
        self.log_event(str(e), '#E74C3C')


def _v24_toggle_stats(self):
    try:
        self.toggle_stats()
        self._v24_refresh_hud()
    except Exception:
        pass


def _v24_refresh_hud(self):
    try:
        pos = int(self.player.position())
        dur = int(self.player.duration())
        title = os.path.basename(str(self.current_media or 'No media loaded'))
        cur = self._format_time(pos)
        end = self._format_time(dur) if dur > 0 else '--:--'
        state = 'PLAYING' if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState else 'PAUSED'
        if hasattr(self, '_v24_hud_title'):
            self._v24_hud_title.setText(title)
        if hasattr(self, '_v24_hud_time'):
            self._v24_hud_time.setText(f'{cur} / {end}')
        if hasattr(self, '_v24_hud_state'):
            self._v24_hud_state.setText(f'● {state}')
        if hasattr(self, '_v24_hud_sub'):
            subs = 'AI SUBTITLES' if getattr(self, 'generated_subs', None) else 'SUBTITLES OFF'
            loop = ' • A/B LOOP' if getattr(self, 'ab_loop_start', -1) >= 0 and getattr(self, 'ab_loop_end', -1) >= 0 else ''
            self._v24_hud_sub.setText(subs + loop)
    except Exception:
        pass


def _v24_quick_bookmark(self):
    try:
        self.add_bookmark(f"Marker {self._format_time(self.player.position())}")
    except Exception:
        pass


def _v24_copy_media_path(self):
    try:
        QApplication.clipboard().setText(str(self.current_media or ''))
        self.log_event('Media path copied to clipboard.', '#2ECC71')
    except Exception:
        pass


def _v24_jump_percent(self, pct):
    try:
        dur = max(0, int(self.player.duration()))
        self.player.setPosition(int(dur * float(pct) / 100.0))
    except Exception:
        pass


def _v24_build_hud(self):
    cw = self.centralWidget()
    if cw is None or cw.layout() is None:
        return
    hud = QFrame(cw)
    hud.setObjectName('StudioHUD')
    hud.setMinimumHeight(58)
    lay = QHBoxLayout(hud)
    lay.setContentsMargins(14, 8, 14, 8)
    lay.setSpacing(10)

    brand = QLabel('◈ OMNI STUDIO')
    brand.setObjectName('HudBrand')
    brand.setMinimumWidth(130)
    lay.addWidget(brand)

    title = QLabel('No media loaded')
    title.setObjectName('HudTitle')
    lay.addWidget(title, 1)
    self._v24_hud_title = title

    state = QLabel('● IDLE')
    state.setObjectName('HudState')
    lay.addWidget(state)
    self._v24_hud_state = state

    sub = QLabel('SUBTITLES OFF')
    sub.setObjectName('HudSub')
    lay.addWidget(sub)
    self._v24_hud_sub = sub

    tm = QLabel('00:00 / --:--')
    tm.setObjectName('HudTime')
    tm.setMinimumWidth(120)
    tm.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    lay.addWidget(tm)
    self._v24_hud_time = tm

    cw.layout().insertWidget(0, hud)
    self._v24_hud = hud
    self._v24_refresh_hud()


def _v24_button(self, text, callback, accent=False, tooltip=''):
    b = QToolButton()
    b.setText(text)
    b.setToolTip(tooltip or text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setMinimumHeight(34)
    b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    b.clicked.connect(callback)
    if accent:
        b.setObjectName('AccentToolButton')
    return b


def _v24_build_quick_dock(self):
    dock = QDockWidget('Studio Command Deck', self)
    dock.setObjectName('StudioCommandDeck')
    dock.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
    panel = QWidget()
    root = QVBoxLayout(panel)
    root.setContentsMargins(10, 10, 10, 10)
    root.setSpacing(8)

    header = QLabel('CONTROL CENTER')
    header.setObjectName('DeckHeader')
    root.addWidget(header)

    tabs = QTabWidget()
    root.addWidget(tabs, 1)

    # Playback tab
    p = QWidget(); pl = QGridLayout(p); pl.setSpacing(6)
    playback = [
        ('⏪ 5s', lambda: self._v23_seek(-5), 'Previous 5 seconds'),
        ('⏩ 5s', lambda: self._v23_seek(5), 'Next 5 seconds'),
        ('⏪ 30s', lambda: self._v23_seek(-30), 'Previous 30 seconds'),
        ('⏩ 30s', lambda: self._v23_seek(30), 'Next 30 seconds'),
        ('▶ / ⏸', self.toggle_play, 'Play or pause'),
        ('⏮', self.prev_playlist_item, 'Previous playlist item'),
        ('⏭', self.next_playlist, 'Next playlist item'),
        ('⏱ 0.5×', lambda: _v24_set_playback_rate(self, .5), 'Half speed'),
        ('⏱ 1×', lambda: _v24_set_playback_rate(self, 1.0), 'Normal speed'),
        ('⏱ 1.5×', lambda: _v24_set_playback_rate(self, 1.5), '1.5x speed'),
        ('⏱ 2×', lambda: _v24_set_playback_rate(self, 2.0), 'Double speed'),
        ('🔖 Marker', lambda: _v24_quick_bookmark(self), 'Add a bookmark at the current time'),
        ('A/B 10s', self._v23_loop10, 'Loop around current position'),
        ('A/B 30s', self._v23_loop30, 'Longer loop around current position'),
        ('Clear Loop', self.clear_loop, 'Clear A/B loop'),
        ('🎯 50%', lambda: _v24_jump_percent(self, 50), 'Jump to the middle of the media'),
    ]
    for i, (txt, cb, tip) in enumerate(playback):
        pl.addWidget(_v24_button(self, txt, cb, txt == '▶ / ⏸', tip), i // 2, i % 2)
    tabs.addTab(p, 'Playback')

    # AI / subtitle tab
    a = QWidget(); al = QGridLayout(a); al.setSpacing(6)
    ai_items = [
        ('🤖 AI Subtitles', self.start_ai),
        ('🧠 AI Chapters', self.generate_ai_chapters),
        ('✎ Edit Cue', self._f22_edit_current_cue),
        ('✚ Split Cue', self._f22_split_current),
        ('⇄ Merge Cue', self._f22_merge_with_next),
        ('↔ Repair Timing', self._f22_auto_repair_subtitles),
        ('◀ Previous Cue', self._adv_jump_sub_previous),
        ('Next Cue ▶', self._adv_jump_sub_next),
        ('Next Dialogue', self._f22_jump_next_dialogue),
        ('Next Silence', self._f22_jump_next_silence),
        ('Timing Settings', self._f22_subtitle_settings),
        ('Quality Report', self._f22_subtitle_report),
        ('Export ASS', self._f22_export_ass),
        ('Export VTT', self._adv_export_vtt),
        ('Transcript TXT', self._adv_export_txt),
        ('Copy Subtitle', self._f22_copy_current_subtitle),
    ]
    for i, (txt, cb) in enumerate(ai_items):
        al.addWidget(_v24_button(self, txt, cb, txt.startswith('🤖')), i // 2, i % 2)
    tabs.addTab(a, 'AI & Subtitles')

    # Media lab tab
    m = QWidget(); ml = QGridLayout(m); ml.setSpacing(6)
    media_items = [
        ('📂 Open', _v24_open_file),
        ('📷 Screenshot', lambda: _v23_screenshot(self)),
        ('🎞 Contact Sheet', self._adv_contact_sheet_custom),
        ('🧩 Thumbnail Strip', self._v23_thumbnail_strip),
        ('I-Frames', self._v23_keyframes),
        ('Black Frame Scan', self._v23_black_scan),
        ('Scene Candidates', self._v23_scenes),
        ('Media Summary', self._f22_probe_summary),
        ('Stream Inspector', self._adv_show_stream_table),
        ('Advanced Report', self._adv_media_report),
        ('Preview 30s', self._adv_make_preview),
        ('GIF Export', self._adv_convert_gif_high_quality),
        ('H264 Fast', self._f22_reencode_fast),
        ('H264 HQ', self._f22_reencode_quality),
        ('H265', self._f22_h265_export),
        ('AV1', self._f22_av1_export),
    ]
    for i, (txt, cb) in enumerate(media_items):
        ml.addWidget(_v24_button(self, txt, cb, txt in ('📂 Open', '📷 Screenshot')), i // 2, i % 2)
    tabs.addTab(m, 'Media Lab')

    # Audio / UI tab
    u = QWidget(); ul = QGridLayout(u); ul.setSpacing(6)
    ui_items = [
        ('🔊 Mute', _v24_toggle_mute),
        ('25% Vol', lambda: self.change_volume(25)),
        ('50% Vol', lambda: self.change_volume(50)),
        ('100% Vol', lambda: self.change_volume(100)),
        ('150% Vol', lambda: self.change_volume(150)),
        ('Zoom', self._v23_set_zoom),
        ('⛶ Fullscreen', self.toggle_fullscreen),
        ('▣ PiP', self.toggle_pip_mode),
        ('Stats', _v24_toggle_stats),
        ('Always On Top', self._adv_toggle_always_on_top),
        ('Playlist', self._adv_toggle_playlist),
        ('Bookmarks', self._adv_toggle_bookmarks),
        ('Telemetry', self._adv_toggle_console),
        ('Glass Theme', self._v23_modern_theme),
        ('Compact UI', self._adv_compact_ui),
        ('Reset View', self._adv_reset_view),
    ]
    for i, (txt, cb) in enumerate(ui_items):
        b = _v24_button(self, txt, cb, txt in ('🔊 Mute', '⛶ Fullscreen'))
        if txt == '🔊 Mute':
            self._v24_mute_btn = b
        ul.addWidget(b, i // 2, i % 2)
    tabs.addTab(u, 'Audio & UI')

    copy = QToolButton(); copy.setText('Copy media path'); copy.clicked.connect(lambda: _v24_copy_media_path(self))
    copy.setCursor(Qt.CursorShape.PointingHandCursor)
    root.addWidget(copy)
    dock.setWidget(panel)
    self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
    self._v24_quick_dock = dock


def _v24_install_shortcuts(self):
    shortcuts = [
        ('Space', self.toggle_play),
        ('Ctrl+O', _v24_open_file),
        ('Ctrl+Shift+S', lambda: _v23_screenshot(self)),
        ('Ctrl+Shift+B', lambda: _v24_quick_bookmark(self)),
        ('Alt+Left', lambda: self._v23_seek(-5)),
        ('Alt+Right', lambda: self._v23_seek(5)),
        ('Ctrl+Shift+R', self._f22_auto_repair_subtitles),
        ('Ctrl+Shift+A', self.start_ai),
        ('Ctrl+Shift+L', self._v23_loop10),
        ('Ctrl+Shift+M', _v24_toggle_mute),
    ]
    for seq, cb in shortcuts:
        a = QAction(self)
        a.setShortcut(QKeySequence(seq))
        a.setShortcutContext(Qt.ShortcutContext.ApplicationShortcut)
        a.triggered.connect(cb)
        self.addAction(a)


def _v24_modern_theme(self):
    qss = r"""
    QMainWindow, QWidget { background: #070b12; color: #eaf2ff; font-family: 'Segoe UI'; }
    QToolBar { background: #0a111c; border: 0; padding: 5px; spacing: 5px; }
    #StudioHUD { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #0b1424, stop:0.55 #111d31, stop:1 #0b1320); border: 1px solid #294664; border-radius: 14px; }
    #HudBrand { color: #7fc4ff; font-weight: 900; letter-spacing: 2px; }
    #HudTitle { color: #f5f9ff; font-size: 14px; font-weight: 700; }
    #HudState { color: #62e6a7; font-size: 11px; font-weight: 800; }
    #HudSub { color: #c3a3ff; font-size: 10px; font-weight: 800; }
    #HudTime { color: #91a9c4; font-family: Consolas; font-weight: 700; }
    #StudioCommandDeck { background: #0a111d; border: 1px solid #263f60; }
    #StudioCommandDeck QWidget { background: #0a111d; }
    #DeckHeader { color: #8cbaf0; font-size: 11px; font-weight: 900; letter-spacing: 2px; padding: 5px; }
    QTabWidget::pane { background: #0b1320; border: 1px solid #29435f; border-radius: 12px; }
    QTabBar::tab { background: #111c2c; color: #8fa7c3; padding: 8px 12px; margin: 2px; border-radius: 8px; }
    QTabBar::tab:selected { background: #244b78; color: #ffffff; font-weight: 800; }
    QToolButton, QPushButton { background: #101d2e; border: 1px solid #315274; border-radius: 9px; padding: 7px; color: #edf5ff; font-weight: 650; }
    QToolButton:hover, QPushButton:hover { background: #173350; border-color: #5a8cc0; }
    QToolButton:pressed, QPushButton:pressed { background: #21527d; }
    #AccentToolButton { background: #2862a1; border-color: #78aee4; color: #ffffff; font-weight: 900; }
    QSlider::groove:horizontal { height: 6px; background: #162437; border-radius: 3px; }
    QSlider::handle:horizontal { width: 16px; margin: -6px 0; border-radius: 8px; background: #6ea9e5; border: 1px solid #c3e2ff; }
    QDockWidget { color: #bad5f2; font-weight: 800; titlebar-close-icon: none; }
    QStatusBar { background: #080d15; border-top: 1px solid #20344b; color: #8da5bf; }
    QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #0b1421; border: 1px solid #28425f; border-radius: 8px; padding: 6px; }
    QListWidget, QTableWidget { background: #0a111b; border: 1px solid #263e59; border-radius: 10px; }
    QHeaderView::section { background: #132238; color: #abc6e4; padding: 5px; border: none; }
    """
    self.setStyleSheet(qss)


def _v24_after_tick(self):
    try:
        _v24_refresh_hud(self)
    except Exception:
        pass

# Install methods on the main class.
for _name, _fn in list(globals().items()):
    if _name.startswith('_v24_') and callable(_fn):
        setattr(OmniPlayerPro, _name, _fn)

# v24 initialization wraps the existing v23 initialization so all previous
# functions remain available and only the visible presentation is extended.
_prev_init_v24 = OmniPlayerPro.__init__
def _init_v24(self, *args, **kwargs):
    _prev_init_v24(self, *args, **kwargs)
    try:
        _v24_modern_theme(self)
        _v24_build_hud(self)
        _v24_build_quick_dock(self)
        _v24_install_shortcuts(self)
        self._v24_hud_timer = QTimer(self)
        self._v24_hud_timer.timeout.connect(lambda: _v24_after_tick(self))
        self._v24_hud_timer.start(350)
        self.log_event('Omni Studio 24 interface loaded: visible control center + HUD + shortcuts.', '#2ECC71')
    except Exception as e:
        try:
            self.log_event(f'Omni Studio 24 warning: {e}', '#F39C12')
        except Exception:
            pass
OmniPlayerPro.__init__ = _init_v24

# ============================================================================
# OMNI STUDIO 25 — COMPLETE GUI REDESIGN
# ============================================================================
class _OmniGlowBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(34)
        self.progress = 0.0
        self.markers = []
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_progress(self, value):
        self.progress = max(0.0, min(1.0, float(value)))
        self.update()

    def mousePressEvent(self, event):
        if self.width() > 1:
            x = max(0, min(self.width(), event.position().x()))
            self.progress = x / self.width()
            self.update()
            try:
                window = self.window()
                player = getattr(window, 'player', None)
                if player is not None:
                    p = int(player.duration() * self.progress)
                    player.setPosition(p)
            except Exception:
                pass
        super().mousePressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self.rect().adjusted(4, 9, -4, -9)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor('#111b2d'))
        p.drawRoundedRect(r, 8, 8)
        fill = QRect(r.left(), r.top(), int(r.width() * self.progress), r.height())
        p.setBrush(QColor('#63a4ff'))
        p.drawRoundedRect(fill, 8, 8)
        x = int(r.left() + r.width() * self.progress)
        p.setBrush(QColor('#eaf5ff'))
        p.drawEllipse(x - 7, r.center().y() - 7, 14, 14)
        p.setBrush(QColor('#8a5cff'))
        for m in self.markers:
            mx = int(r.left() + r.width() * max(0.0, min(1.0, m)))
            p.drawRect(mx - 1, r.top() - 4, 3, r.height() + 8)


class _OmniVUWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.level = 0.2
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._pulse)
        self.timer.start(70)

    def _pulse(self):
        try:
            playing = self.window().player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
            target = 0.68 if playing else 0.16
        except Exception:
            target = 0.16
        self.level = self.level * 0.86 + target * 0.14
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor('#090f1b'))
        w = max(10, self.width() // 18)
        for i in range(18):
            phase = math.sin((i + 1) * 0.75 + time.time() * 3.0)
            h = int(max(5, (self.height() - 12) * (0.15 + 0.42 * self.level + 0.22 * abs(phase))))
            x = 6 + i * w
            y = self.height() - h - 6
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor('#365f9b' if i % 3 else '#7c5cff'))
            p.drawRoundedRect(x, y, max(3, w - 4), h, 3, 3)


def _v25_button(self, text, callback, primary=False, checkable=False):
    b = QToolButton()
    b.setText(text)
    b.setToolTip(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setMinimumHeight(38)
    b.setCheckable(checkable)
    b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    b.clicked.connect(callback)
    if primary:
        b.setObjectName('V25Primary')
    return b


def _v25_make_card(title, subtitle=''):
    card = QFrame()
    card.setObjectName('V25Card')
    lay = QVBoxLayout(card)
    lay.setContentsMargins(14, 12, 14, 12)
    lay.setSpacing(8)
    head = QLabel(title)
    head.setObjectName('V25CardTitle')
    lay.addWidget(head)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName('V25CardSub')
        sub.setWordWrap(True)
        lay.addWidget(sub)
    return card, lay


def _v25_update_meta(self):
    try:
        path = str(self.current_media or '')
        name = os.path.basename(path) if path else 'No media loaded'
        self._v25_title.setText(name)
        ext = os.path.splitext(path)[1].upper().replace('.', '') if path else '--'
        size = '--'
        if path and os.path.exists(path):
            size = f'{os.path.getsize(path) / (1024*1024):.1f} MB'
        self._v25_meta.setText(f'{ext or "MEDIA"}  •  {size}')
    except Exception:
        pass


def _v25_refresh(self):
    try:
        dur = max(0, int(self.player.duration()))
        pos = max(0, int(self.player.position()))
        self._v25_time_left.setText(self._format_time(pos))
        self._v25_time_right.setText(self._format_time(dur) if dur else '--:--')
        self._v25_progress.set_progress((pos / dur) if dur else 0.0)
        state = self.player.playbackState()
        is_play = state == QMediaPlayer.PlaybackState.PlayingState
        self._v25_play.setText('⏸' if is_play else '▶')
        self._v25_state.setText('PLAYING' if is_play else 'PAUSED')
        self._v25_state.setProperty('playing', is_play)
        self._v25_state.style().unpolish(self._v25_state); self._v25_state.style().polish(self._v25_state)
        self._v25_substat.setText('AI SUBTITLES READY' if getattr(self, 'generated_subs', None) else 'SUBTITLES OFF')
        self._v25_vu.update()
        _v25_update_meta(self)
    except Exception:
        pass


def _v25_seek(self, seconds):
    try:
        p = max(0, int(self.player.position()) + int(seconds * 1000))
        d = int(self.player.duration())
        if d > 0: p = min(p, d)
        self.player.setPosition(p)
    except Exception:
        pass


def _v25_set_volume(self, value):
    try:
        self.change_volume(int(value))
        self._v25_vol.setText(f'{int(value)}%')
    except Exception:
        pass


def _v25_open(self):
    try:
        self.open_file()
        QTimer.singleShot(100, lambda: _v25_update_meta(self))
    except Exception:
        pass


def _v25_toggle_playlist(self):
    try:
        self._adv_toggle_playlist()
    except Exception:
        try: self.playlist_dock.setVisible(not self.playlist_dock.isVisible())
        except Exception: pass


def _v25_toggle_bookmarks(self):
    try: self._adv_toggle_bookmarks()
    except Exception: pass


def _v25_toggle_inspector(self):
    try:
        self._v25_inspector.setVisible(not self._v25_inspector.isVisible())
    except Exception:
        pass


def _v25_toggle_command_bar(self):
    try:
        self._v25_command.setVisible(not self._v25_command.isVisible())
    except Exception:
        pass


def _v25_fit_sidebar(self):
    try:
        self._v25_splitter.setSizes([220, max(700, self.width()-560), 300])
    except Exception:
        pass


def _v25_build_gui(self):
    # Keep engine widgets/objects, replace only the presentation shell.
    old = self.centralWidget()
    try:
        old.layout().removeWidget(self.display_container)
        old.layout().removeWidget(self.controls_frame)
    except Exception:
        pass
    self.display_container.setParent(None)
    self.controls_frame.setParent(None)
    self.controls_frame.hide()

    # Hide classic docks/toolbars; functionality remains available from the new UI.
    for tb in self.findChildren(QToolBar):
        tb.setVisible(False)
    try:
        self.menu_bar.setVisible(False)
    except Exception:
        pass
    for dock in self.findChildren(QDockWidget):
        dock.hide()

    root = QWidget()
    root.setObjectName('V25Root')
    self.setCentralWidget(root)
    root_l = QVBoxLayout(root)
    root_l.setContentsMargins(12, 12, 12, 10)
    root_l.setSpacing(10)

    # Premium header
    header = QFrame(); header.setObjectName('V25Header')
    hl = QHBoxLayout(header); hl.setContentsMargins(16, 10, 16, 10); hl.setSpacing(10)
    brand = QLabel('◈ OMNI'); brand.setObjectName('V25Brand'); hl.addWidget(brand)
    mode = QLabel('STUDIO PLAYER  •  ULTIMATE'); mode.setObjectName('V25Mode'); hl.addWidget(mode)
    hl.addStretch()
    self._v25_state = QLabel('PAUSED'); self._v25_state.setObjectName('V25State'); hl.addWidget(self._v25_state)
    self._v25_substat = QLabel('SUBTITLES OFF'); self._v25_substat.setObjectName('V25SubStat'); hl.addWidget(self._v25_substat)
    self._v25_meta = QLabel('MEDIA  •  --'); self._v25_meta.setObjectName('V25Meta'); hl.addWidget(self._v25_meta)
    root_l.addWidget(header)

    # Workspace splitter
    splitter = QSplitter(Qt.Orientation.Horizontal); splitter.setChildrenCollapsible(False)
    self._v25_splitter = splitter

    # Left library rail
    left = QFrame(); left.setObjectName('V25Rail')
    ll = QVBoxLayout(left); ll.setContentsMargins(10, 10, 10, 10); ll.setSpacing(8)
    lab = QLabel('LIBRARY'); lab.setObjectName('V25Section'); ll.addWidget(lab)
    bopen = _v25_button(self, '＋  Open Media', _v25_open, True); ll.addWidget(bopen)
    self._v25_search = QLineEdit(); self._v25_search.setPlaceholderText('Search playlist...'); ll.addWidget(self._v25_search)
    # Reuse existing playlist widget directly.
    try:
        self.playlist_widget.setParent(left)
        self.playlist_widget.setVisible(True)
        ll.addWidget(self.playlist_widget, 1)
    except Exception:
        dummy = QLabel('Playlist unavailable'); ll.addWidget(dummy, 1)
    row = QHBoxLayout();
    row.addWidget(_v25_button(self, '⏮', self.prev_playlist_item)); row.addWidget(_v25_button(self, '⏭', self.next_playlist));
    ll.addLayout(row)
    splitter.addWidget(left)

    # Center cinematic player
    center = QWidget(); cl = QVBoxLayout(center); cl.setContentsMargins(0,0,0,0); cl.setSpacing(8)
    title_row = QHBoxLayout();
    self._v25_title = QLabel('No media loaded'); self._v25_title.setObjectName('V25Title'); title_row.addWidget(self._v25_title, 1)
    title_row.addWidget(_v25_button(self, '☰ Commands', _v25_toggle_command_bar))
    title_row.addWidget(_v25_button(self, '⚙ View', self._adv_reset_view))
    cl.addLayout(title_row)

    video_shell = QFrame(); video_shell.setObjectName('V25VideoShell')
    vs = QVBoxLayout(video_shell); vs.setContentsMargins(2,2,2,2); vs.setSpacing(2)
    vs.addWidget(self.display_container, 1)
    cl.addWidget(video_shell, 1)

    # Transport panel
    transport = QFrame(); transport.setObjectName('V25Transport'); tl = QVBoxLayout(transport); tl.setContentsMargins(12,10,12,10); tl.setSpacing(8)
    self._v25_progress = _OmniGlowBar(); tl.addWidget(self._v25_progress)
    tr = QHBoxLayout(); tr.setSpacing(7)
    self._v25_time_left = QLabel('00:00'); self._v25_time_right = QLabel('--:--'); tr.addWidget(self._v25_time_left)
    tr.addStretch()
    for txt, cb in [('−30', lambda: _v25_seek(self,-30)), ('−5', lambda: _v25_seek(self,-5))]: tr.addWidget(_v25_button(self, txt, cb))
    self._v25_play = _v25_button(self, '▶', self.toggle_play, True); self._v25_play.setFixedWidth(70); tr.addWidget(self._v25_play)
    for txt, cb in [('+5', lambda: _v25_seek(self,5)), ('+30', lambda: _v25_seek(self,30))]: tr.addWidget(_v25_button(self, txt, cb))
    tr.addStretch(); tr.addWidget(self._v25_time_right)
    tl.addLayout(tr)
    row2 = QHBoxLayout(); row2.setSpacing(6)
    for txt, cb in [('⏮ Prev', self.prev_playlist_item), ('⏹ Stop', self.stop_playback), ('⏭ Next', self.next_playlist), ('🔖 Marker', _v24_quick_bookmark), ('A/B 10s', self._v23_loop10), ('A/B 30s', self._v23_loop30), ('⌗ Fullscreen', self.toggle_fullscreen), ('▣ PiP', self.toggle_pip_mode)]:
        row2.addWidget(_v25_button(self, txt, cb))
    tl.addLayout(row2)
    center_controls = QHBoxLayout(); center_controls.setSpacing(8)
    center_controls.addWidget(QLabel('Speed'))
    sp = QComboBox();
    for v in [0.5,0.75,1.0,1.25,1.5,2.0,3.0,4.0]: sp.addItem(f'{v:g}×', v)
    sp.setCurrentIndex(2); sp.currentIndexChanged.connect(lambda i: _v24_set_playback_rate(self, sp.itemData(i))); center_controls.addWidget(sp)
    center_controls.addWidget(QLabel('Volume'))
    vsld = QSlider(Qt.Orientation.Horizontal); vsld.setRange(0,500); vsld.setValue(100); vsld.setMaximumWidth(180); vsld.valueChanged.connect(self.change_volume); center_controls.addWidget(vsld,1)
    self._v25_vol = QLabel('100%'); center_controls.addWidget(self._v25_vol)
    center_controls.addWidget(_v25_button(self, '🔇 Mute', _v24_toggle_mute))
    center_controls.addWidget(_v25_button(self, '🎙 Voice', self.toggle_voice_control))
    center_controls.addWidget(_v25_button(self, '📺 Cast', self.cast_to_chromecast, True))
    tl.addLayout(center_controls)
    cl.addWidget(transport)
    splitter.addWidget(center)

    # Right intelligence/inspector rail
    right = QFrame(); right.setObjectName('V25Inspector')
    rl = QVBoxLayout(right); rl.setContentsMargins(10,10,10,10); rl.setSpacing(8)
    sec = QLabel('LIVE INSPECTOR'); sec.setObjectName('V25Section'); rl.addWidget(sec)
    self._v25_cards = []
    card, lay = _v25_make_card('MEDIA INTELLIGENCE', 'Quick actions for your current file.')
    for text, cb in [('📊 Stream Inspector', self._adv_show_stream_table), ('🧠 Media Summary', self._f22_probe_summary), ('🎞 Scene Candidates', self._v23_scenes), ('🖼 Contact Sheet', self._adv_contact_sheet_custom)]:
        lay.addWidget(_v25_button(self, text, cb))
    rl.addWidget(card)
    card2, lay2 = _v25_make_card('AI & SUBTITLES', 'Timing, translation, export and repair.')
    for text, cb in [('🤖 Generate AI Subs', self.start_ai), ('↔ Repair Timing', self._f22_auto_repair_subtitles), ('✎ Edit Current Cue', self._f22_edit_current_cue), ('📄 Export SRT', self.export_subtitles)]:
        lay2.addWidget(_v25_button(self, text, cb))
    rl.addWidget(card2)
    card3, lay3 = _v25_make_card('AUDIO LAB', 'Fast access to audio processing.')
    for text, cb in [('🎚 Equalizer', self.show_equalizer), ('🎵 Rip MP3', self.rip_mp3), ('🔊 Boost Audio', self.boost_audio)]:
        lay3.addWidget(_v25_button(self, text, cb))
    rl.addWidget(card3)
    vu_card, vul = _v25_make_card('AUDIO MONITOR')
    self._v25_vu = _OmniVUWidget(); self._v25_vu.setMinimumHeight(86); vul.addWidget(self._v25_vu); rl.addWidget(vu_card)
    rl.addStretch()
    splitter.addWidget(right)
    root_l.addWidget(splitter, 1)

    # Bottom command ribbon
    ribbon = QFrame(); ribbon.setObjectName('V25Ribbon'); rbl = QHBoxLayout(ribbon); rbl.setContentsMargins(10,7,10,7); rbl.setSpacing(7)
    cmds = [('Open', _v25_open), ('Screenshot', lambda: _v23_screenshot(self)), ('Keyframes', self._v23_keyframes), ('Black Frames', self._v23_black_scan), ('Thumbnails', self._v23_thumbnail_strip), ('AI Chapters', self.generate_ai_chapters), ('Repair Subs', self._f22_auto_repair_subtitles), ('Export ASS', self._f22_export_ass), ('Network Cast', self.cast_to_chromecast), ('Playlist', _v25_toggle_playlist), ('Bookmarks', _v25_toggle_bookmarks), ('Inspector', _v25_toggle_inspector)]
    for text, cb in cmds:
        rbl.addWidget(_v25_button(self, text, cb))
    root_l.addWidget(ribbon)

    # Install a search filter on the reused playlist.
    try:
        self._v25_search.textChanged.connect(lambda t: [it.setHidden(bool(t.strip()) and t.lower() not in it.text().lower()) for it in [self.playlist_widget.item(i) for i in range(self.playlist_widget.count())]])
    except Exception:
        pass
    _v25_fit_sidebar(self)
    _v25_update_meta(self)
    _v25_refresh(self)


def _v25_theme(self):
    self.setStyleSheet(r'''
    QMainWindow, QWidget#V25Root { background: #060a12; color: #eaf3ff; font-family: "Segoe UI"; }
    #V25Header, #V25Rail, #V25Inspector, #V25Transport, #V25Ribbon { background: #0b1321; border: 1px solid #223752; border-radius: 16px; }
    #V25Header { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #0b1425, stop:.55 #101b2f, stop:1 #0a1322); }
    #V25Brand { color: #72b4ff; font-size: 20px; font-weight: 900; letter-spacing: 3px; }
    #V25Mode { color: #7890ac; font-size: 10px; font-weight: 800; letter-spacing: 2px; }
    #V25State { color: #7ce0b1; font-weight: 900; }
    #V25State[playing="true"] { color: #6eb9ff; }
    #V25SubStat { color: #b999ff; font-weight: 800; }
    #V25Meta { color: #7890aa; font-family: Consolas; }
    #V25Title { color: #f4f8ff; font-size: 16px; font-weight: 850; padding-left: 5px; }
    #V25VideoShell { background: #030508; border: 1px solid #1c2e46; border-radius: 14px; }
    #V25Card { background: #0b1422; border: 1px solid #243a56; border-radius: 12px; }
    #V25CardTitle, #V25Section { color: #8cb6e4; font-size: 10px; font-weight: 900; letter-spacing: 1.8px; }
    #V25CardSub { color: #718aa5; font-size: 10px; }
    QToolButton { background: #111f31; color: #d9e8f7; border: 1px solid #2a4563; border-radius: 9px; padding: 7px 9px; font-weight: 700; }
    QToolButton:hover { background: #19334f; border-color: #5a8fc4; }
    QToolButton:pressed, QToolButton:checked { background: #234d78; border-color: #78b6f4; }
    #V25Rail QToolButton, #V25Inspector QToolButton { min-height: 32px; }
    #V25Primary { background: #315f9c; color: #fff; border-color: #73a9e0; font-weight: 900; }
    #V25Primary:hover { background: #3a70b7; }
    QLineEdit, QComboBox { background: #09111e; border: 1px solid #243c57; border-radius: 8px; padding: 7px; color: #e8f2fc; }
    QSlider::groove:horizontal { height: 5px; background: #17273a; border-radius: 3px; }
    QSlider::sub-page:horizontal { background: #477fb8; border-radius: 3px; }
    QSlider::handle:horizontal { width: 14px; margin: -5px 0; border-radius: 7px; background: #84c1ff; border: 1px solid #d4edff; }
    QListWidget { background: #08101b; border: 1px solid #1e344e; border-radius: 10px; padding: 5px; }
    QListWidget::item { padding: 9px 7px; border-radius: 7px; color: #a9bfd5; }
    QListWidget::item:hover { background: #10263c; color: #fff; }
    QListWidget::item:selected { background: #204d79; color: #fff; }
    QSplitter::handle { background: #0c1521; }
    QStatusBar { background: #060b13; color: #738ba7; border-top: 1px solid #17283b; }
    QScrollBar:vertical { background: #07101a; width: 10px; margin: 2px; }
    QScrollBar::handle:vertical { background: #263d56; border-radius: 5px; min-height: 30px; }
    ''')


# Attach methods
OmniPlayerPro._v25_button = _v25_button
OmniPlayerPro._v25_make_card = staticmethod(_v25_make_card)
OmniPlayerPro._v25_update_meta = _v25_update_meta
OmniPlayerPro._v25_refresh = _v25_refresh
OmniPlayerPro._v25_seek = _v25_seek
OmniPlayerPro._v25_set_volume = _v25_set_volume
OmniPlayerPro._v25_open = _v25_open
OmniPlayerPro._v25_toggle_playlist = _v25_toggle_playlist
OmniPlayerPro._v25_toggle_bookmarks = _v25_toggle_bookmarks
OmniPlayerPro._v25_toggle_inspector = _v25_toggle_inspector
OmniPlayerPro._v25_toggle_command_bar = _v25_toggle_command_bar
OmniPlayerPro._v25_fit_sidebar = _v25_fit_sidebar
OmniPlayerPro._v25_build_gui = _v25_build_gui
OmniPlayerPro._v25_theme = _v25_theme

_prev_init_v25 = OmniPlayerPro.__init__
def _init_v25(self, *args, **kwargs):
    _prev_init_v25(self, *args, **kwargs)
    try:
        _v25_theme(self)
        _v25_build_gui(self)
        self._v25_timer = QTimer(self)
        self._v25_timer.timeout.connect(lambda: _v25_refresh(self))
        self._v25_timer.start(150)
        self.log_event('Omni Studio 25: complete cinematic GUI installed.', '#6EB7FF')
    except Exception as e:
        try: self.log_event(f'Omni Studio 25 GUI warning: {e}', '#F39C12')
        except Exception: pass
OmniPlayerPro.__init__ = _init_v25

# =============================================================================
# OMNI STUDIO 26 — RESPONSIVE PROFESSIONAL UI / FEATURE COMMAND CENTER
# Fixes the v25 three-pane squeeze and exposes advanced controls without menus.
# =============================================================================
from PyQt6.QtWidgets import QScrollArea, QToolButton


def _v26_btn(self, text, callback, primary=False, compact=False, checkable=False):
    b = QToolButton()
    b.setText(text)
    b.setToolTip(text)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setCheckable(checkable)
    b.setMinimumHeight(32 if compact else 38)
    b.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    b.clicked.connect(callback)
    if primary:
        b.setObjectName('V26Primary')
    return b


def _v26_card(title, subtitle=''):
    card = QFrame()
    card.setObjectName('V26Card')
    lay = QVBoxLayout(card)
    lay.setContentsMargins(12, 11, 12, 11)
    lay.setSpacing(7)
    h = QLabel(title)
    h.setObjectName('V26CardTitle')
    lay.addWidget(h)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName('V26CardSub')
        s.setWordWrap(True)
        lay.addWidget(s)
    return card, lay


def _v26_scroll_panel(widget):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    scroll.setWidget(widget)
    return scroll


def _v26_refresh(self):
    try:
        dur = max(0, int(self.player.duration()))
        pos = max(0, int(self.player.position()))
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self._v26_time.setText(f'{self._format_time(pos)} / {self._format_time(dur) if dur else "--:--"}')
        self._v26_progress.set_progress(pos / dur if dur else 0.0)
        self._v26_play.setText('⏸  Pause' if playing else '▶  Play')
        self._v26_state.setText('PLAYING' if playing else 'PAUSED')
        self._v26_state.setProperty('playing', playing)
        self._v26_state.style().unpolish(self._v26_state)
        self._v26_state.style().polish(self._v26_state)
        title = os.path.basename(str(self.current_media or 'No media loaded'))
        self._v26_title.setText(title)
        self._v26_subs.setText('AI SUBTITLES READY' if getattr(self, 'generated_subs', None) else 'SUBTITLES OFF')
        if hasattr(self, '_v26_volume'):
            self._v26_volume.setText(f'{int(self.audio_output.volume() * 100)}%')
        self._v26_vu.update()
    except Exception:
        pass


def _v26_seek(self, seconds):
    try:
        d = int(self.player.duration())
        p = max(0, int(self.player.position()) + int(seconds * 1000))
        self.player.setPosition(min(p, d) if d > 0 else p)
    except Exception:
        pass


def _v26_set_vol(self, value):
    try:
        self.change_volume(int(value))
        self._v26_volume.setText(f'{int(value)}%')
    except Exception:
        pass


def _v26_build_ui(self):
    # Detach/reparent engine widgets from the v25 shell.
    for tb in self.findChildren(QToolBar):
        tb.hide()
    for dock in self.findChildren(QDockWidget):
        dock.hide()
    try:
        self.menuBar().hide()
    except Exception:
        pass

    root = QWidget()
    root.setObjectName('V26Root')
    self.setCentralWidget(root)
    root_l = QVBoxLayout(root)
    root_l.setContentsMargins(10, 10, 10, 10)
    root_l.setSpacing(8)

    # ---------- Header ----------
    header = QFrame(); header.setObjectName('V26Header')
    hl = QHBoxLayout(header); hl.setContentsMargins(14, 9, 14, 9); hl.setSpacing(9)
    brand = QLabel('◈ OMNI'); brand.setObjectName('V26Brand'); hl.addWidget(brand)
    mode = QLabel('STUDIO 26  /  MEDIA COMMAND CENTER'); mode.setObjectName('V26Mode'); hl.addWidget(mode)
    hl.addStretch()
    self._v26_state = QLabel('PAUSED'); self._v26_state.setObjectName('V26State'); hl.addWidget(self._v26_state)
    self._v26_subs = QLabel('SUBTITLES OFF'); self._v26_subs.setObjectName('V26Subs'); hl.addWidget(self._v26_subs)
    self._v26_time = QLabel('00:00 / --:--'); self._v26_time.setObjectName('V26Time'); hl.addWidget(self._v26_time)
    root_l.addWidget(header)

    # ---------- Responsive workspace ----------
    splitter = QSplitter(Qt.Orientation.Horizontal)
    splitter.setChildrenCollapsible(False)
    splitter.setHandleWidth(5)
    self._v26_splitter = splitter

    # Left: library/search/playlist.
    left = QFrame(); left.setObjectName('V26Side')
    ll = QVBoxLayout(left); ll.setContentsMargins(10, 10, 10, 10); ll.setSpacing(8)
    lab = QLabel('LIBRARY'); lab.setObjectName('V26Section'); ll.addWidget(lab)
    ll.addWidget(_v26_btn(self, '＋  OPEN MEDIA', self.load_local_media, primary=True))
    self._v26_search = QLineEdit(); self._v26_search.setPlaceholderText('Search playlist…'); ll.addWidget(self._v26_search)
    self.playlist_widget.setParent(left); self.playlist_widget.show(); ll.addWidget(self.playlist_widget, 1)
    row = QHBoxLayout(); row.addWidget(_v26_btn(self, '⏮ Previous', self.prev_playlist_item, compact=True)); row.addWidget(_v26_btn(self, 'Next ⏭', self.next_playlist, compact=True)); ll.addLayout(row)
    row2 = QHBoxLayout(); row2.addWidget(_v26_btn(self, 'Shuffle', self.toggle_shuffle, compact=True)); row2.addWidget(_v26_btn(self, 'Repeat', self.toggle_repeat, compact=True)); ll.addLayout(row2)
    splitter.addWidget(left)

    # Center: video + timeline + transport.
    center = QWidget(); cl = QVBoxLayout(center); cl.setContentsMargins(0, 0, 0, 0); cl.setSpacing(7)
    title_row = QHBoxLayout()
    self._v26_title = QLabel('No media loaded'); self._v26_title.setObjectName('V26Title'); title_row.addWidget(self._v26_title, 1)
    title_row.addWidget(_v26_btn(self, '⌘ COMMANDS', self._v26_command_dialog, compact=True))
    title_row.addWidget(_v26_btn(self, '⚙ LAYOUT', self._adv_reset_view, compact=True))
    cl.addLayout(title_row)

    video = QFrame(); video.setObjectName('V26Video')
    vl = QVBoxLayout(video); vl.setContentsMargins(2, 2, 2, 2); vl.setSpacing(2)
    self.display_container.setParent(video); self.display_container.show(); vl.addWidget(self.display_container, 1)
    cl.addWidget(video, 1)

    transport = QFrame(); transport.setObjectName('V26Transport'); tl = QVBoxLayout(transport); tl.setContentsMargins(10, 9, 10, 9); tl.setSpacing(7)
    self._v26_progress = _OmniGlowBar(); tl.addWidget(self._v26_progress)
    tm = QHBoxLayout(); tm.setSpacing(6)
    for txt, sec in [('−60', -60), ('−10', -10), ('−5', -5)]: tm.addWidget(_v26_btn(self, txt, lambda s=sec: _v26_seek(self, s), compact=True))
    self._v26_play = _v26_btn(self, '▶  Play', self.toggle_play, primary=True); self._v26_play.setFixedWidth(110); tm.addWidget(self._v26_play)
    for txt, sec in [('+5', 5), ('+10', 10), ('+60', 60)]: tm.addWidget(_v26_btn(self, txt, lambda s=sec: _v26_seek(self, s), compact=True))
    tm.addStretch()
    tm.addWidget(_v26_btn(self, '⏹ Stop', self.stop_playback, compact=True))
    tm.addWidget(_v26_btn(self, '⛶ Fullscreen', self.toggle_fullscreen, compact=True))
    tl.addLayout(tm)

    row = QHBoxLayout(); row.setSpacing(7)
    row.addWidget(_v26_btn(self, '🔖 Marker', _v24_quick_bookmark, compact=True))
    row.addWidget(_v26_btn(self, 'A/B Loop', self._v23_loop10, compact=True))
    row.addWidget(_v26_btn(self, 'Frame −', lambda: self._v23_frame(-1), compact=True))
    row.addWidget(_v26_btn(self, 'Frame +', lambda: self._v23_frame(1), compact=True))
    row.addWidget(QLabel('Speed')); self._v26_speed = QComboBox()
    for v in [0.25,0.5,0.75,1.0,1.25,1.5,2.0,3.0,4.0]: self._v26_speed.addItem(f'{v:g}×', v)
    self._v26_speed.setCurrentIndex(3); self._v26_speed.currentIndexChanged.connect(lambda i: _v24_set_playback_rate(self, self._v26_speed.itemData(i))); row.addWidget(self._v26_speed)
    row.addWidget(QLabel('Volume'))
    vs = QSlider(Qt.Orientation.Horizontal); vs.setRange(0, 500); vs.setValue(100); vs.setMinimumWidth(90); vs.setMaximumWidth(170); vs.valueChanged.connect(lambda v: _v26_set_vol(self, v)); row.addWidget(vs)
    self._v26_volume = QLabel('100%'); row.addWidget(self._v26_volume)
    row.addWidget(_v26_btn(self, '🔇 Mute', _v24_toggle_mute, compact=True))
    row.addWidget(_v26_btn(self, '📺 Cast', self.cast_to_chromecast, primary=True, compact=True))
    tl.addLayout(row)
    cl.addWidget(transport)
    splitter.addWidget(center)

    # Right: always visible, scrollable intelligence rail.
    right_shell = QFrame(); right_shell.setObjectName('V26RightShell')
    rr = QVBoxLayout(right_shell); rr.setContentsMargins(8, 8, 8, 8); rr.setSpacing(7)
    top = QHBoxLayout(); lab = QLabel('INTELLIGENCE'); lab.setObjectName('V26Section'); top.addWidget(lab); top.addStretch(); top.addWidget(_v26_btn(self, 'Hide', self._v26_toggle_right, compact=True)); rr.addLayout(top)

    body = QWidget(); bl = QVBoxLayout(body); bl.setContentsMargins(2, 2, 6, 2); bl.setSpacing(8)
    card, lay = _v26_card('MEDIA INTELLIGENCE', 'Inspect streams and detect structure.')
    for text, cb in [
        ('📊 Stream Inspector', self._adv_show_stream_table),
        ('🧠 Media Summary', self._f22_probe_summary),
        ('🎞 Scene Detection', self._v23_scenes),
        ('🖼 Contact Sheet', self._adv_contact_sheet_custom),
        ('🔑 Keyframes', self._v23_keyframes),
        ('⬛ Black Frame Scan', self._v23_black_scan),
    ]: lay.addWidget(_v26_btn(self, text, cb, compact=True))
    bl.addWidget(card)

    card, lay = _v26_card('AI • SUBTITLES', 'Transcribe, repair, navigate and export.')
    for text, cb in [
        ('🤖 Generate AI Subtitles', self.start_ai),
        ('🧠 AI Chapters', self.generate_ai_chapters),
        ('↔ Repair Timing', self._f22_auto_repair_subtitles),
        ('✎ Edit Current Cue', self._f22_edit_current_cue),
        ('⇄ Split / Merge Cue', self._f22_split_current),
        ('🔎 Transcript Search', self._adv_find_transcript),
        ('📄 Export SRT', self.export_subtitles),
        ('ASS / VTT / TXT', self._f22_export_ass),
    ]: lay.addWidget(_v26_btn(self, text, cb, compact=True))
    bl.addWidget(card)

    card, lay = _v26_card('AUDIO LAB', 'Fast mixing and restoration controls.')
    for text, cb in [
        ('🎚 10-Band Equalizer', self.show_equalizer),
        ('🔊 Loudness Normalize', self._adv_audio_normalize),
        ('🧹 Dialogue Denoise', self._adv_audio_denoise),
        ('🎛 Compressor', self._adv_audio_compressor),
        ('🚦 Peak Limiter', self._adv_audio_limiter),
        ('🎵 Rip MP3', self.rip_mp3),
        ('🌊 Extract FLAC', lambda: self._f22_extract_audio('flac','.flac')),
    ]: lay.addWidget(_v26_btn(self, text, cb, compact=True))
    bl.addWidget(card)

    card, lay = _v26_card('TOOLS • OUTPUT', 'Creation, conversion and diagnostics.')
    for text, cb in [
        ('📸 Screenshot', lambda: _v23_screenshot(self)),
        ('🎞 30s Preview', self._adv_make_preview),
        ('🧩 Thumbnail Strip', self._v23_thumbnail_strip),
        ('4K Upscale', self.run_esrgan),
        ('⚙ FFmpeg Inspector', self._adv_media_report),
        ('🧪 Dependencies', self._adv_check_dependencies),
        ('📝 Telemetry Console', self._adv_toggle_console),
    ]: lay.addWidget(_v26_btn(self, text, cb, compact=True))
    bl.addWidget(card)

    vu_card, vul = _v26_card('LIVE AUDIO MONITOR')
    self._v26_vu = _OmniVUWidget(); self._v26_vu.setMinimumHeight(78); vul.addWidget(self._v26_vu); bl.addWidget(vu_card)
    bl.addStretch(1)
    rr.addWidget(_v26_scroll_panel(body), 1)
    splitter.addWidget(right_shell)
    self._v26_right = right_shell

    # Critical fix: sizes and stretch factors designed for 1020px minimums.
    left.setMinimumWidth(210); left.setMaximumWidth(330)
    right_shell.setMinimumWidth(275); right_shell.setMaximumWidth(390)
    splitter.setStretchFactor(0, 0); splitter.setStretchFactor(1, 1); splitter.setStretchFactor(2, 0)
    splitter.setSizes([230, max(480, self.width() - 535), 305])
    root_l.addWidget(splitter, 1)

    # Bottom quick-access strip.
    bottom = QFrame(); bottom.setObjectName('V26Bottom'); br = QHBoxLayout(bottom); br.setContentsMargins(8, 6, 8, 6); br.setSpacing(6)
    for text, cb in [
        ('Open', self.open_file), ('Library', lambda: self._v21_show_library('all')), ('Bookmarks', _v25_toggle_bookmarks),
        ('AI Subs', self.start_ai), ('AI Chapters', self.generate_ai_chapters), ('Screenshot', lambda: _v23_screenshot(self)),
        ('EQ', self.show_equalizer), ('Metadata', self.fetch_metadata), ('DLNA', self.toggle_dlna_server),
        ('Cast', self.cast_to_chromecast), ('Vault', self.play_encrypted_media_prompt), ('Diagnostics', self._f22_copy_diagnostics),
    ]: br.addWidget(_v26_btn(self, text, cb, compact=True))
    root_l.addWidget(bottom)

    try:
        self._v26_search.textChanged.connect(lambda t: [
            it.setHidden(bool(t.strip()) and t.lower() not in it.text().lower())
            for it in [self.playlist_widget.item(i) for i in range(self.playlist_widget.count())]
        ])
    except Exception:
        pass

    _v26_refresh(self)


def _v26_toggle_right(self):
    try:
        self._v26_right.setVisible(not self._v26_right.isVisible())
        if self._v26_right.isVisible():
            self._v26_splitter.setSizes([230, max(480, self.width() - 535), 305])
        else:
            self._v26_splitter.setSizes([230, max(650, self.width() - 250), 0])
    except Exception:
        pass


def _v26_command_dialog(self):
    dlg = QDialog(self)
    dlg.setWindowTitle('Omni Command Center')
    dlg.resize(720, 560)
    root = QVBoxLayout(dlg)
    root.addWidget(QLabel('ADVANCED COMMAND CENTER'))
    search = QLineEdit(); search.setPlaceholderText('Search advanced commands…'); root.addWidget(search)
    listw = QListWidget(); root.addWidget(listw, 1)
    actions = [
        ('Playback: skip 5 / 10 / 30 seconds', lambda: _v26_seek(self, 10)),
        ('Playback: add bookmark', lambda: _v24_quick_bookmark(self)),
        ('Playback: frame step forward', lambda: self._v23_frame(1)),
        ('Playback: frame step backward', lambda: self._v23_frame(-1)),
        ('AI: generate subtitles', self.start_ai), ('AI: repair subtitle timing', self._f22_auto_repair_subtitles),
        ('AI: generate chapters', self.generate_ai_chapters), ('AI: transcript search', self._adv_find_transcript),
        ('Media: stream inspector', self._adv_show_stream_table), ('Media: scene detection', self._v23_scenes),
        ('Media: contact sheet', self._adv_contact_sheet_custom), ('Media: keyframes', self._v23_keyframes),
        ('Audio: equalizer', self.show_equalizer), ('Audio: normalize loudness', self._adv_audio_normalize),
        ('Audio: denoise', self._adv_audio_denoise), ('Audio: limiter', self._adv_audio_limiter),
        ('Output: H.264 HQ', self._f22_reencode_quality), ('Output: H.265', self._f22_h265_export),
        ('Output: AV1', self._f22_av1_export), ('Output: 4K upscale', self.run_esrgan),
        ('Network: Chromecast', self.cast_to_chromecast), ('Network: DLNA server', self.toggle_dlna_server),
        ('Library: scan folder', self._f22_scan_current_folder), ('Library: smart playlist', self._v21_smart_playlist),
        ('System: dependencies', self._adv_check_dependencies), ('System: diagnostics', self._f22_copy_diagnostics),
    ]
    for name, cb in actions:
        item = QListWidgetItem(name); item.setData(Qt.ItemDataRole.UserRole, cb); listw.addItem(item)
    def filtered(text):
        q = text.lower().strip()
        for i in range(listw.count()):
            listw.item(i).setHidden(bool(q) and q not in listw.item(i).text().lower())
    search.textChanged.connect(filtered)
    def run_item(item):
        cb = item.data(Qt.ItemDataRole.UserRole)
        if callable(cb):
            cb(); dlg.accept()
    listw.itemDoubleClicked.connect(run_item)
    dlg.exec()


# Attach and replace only the final presentation layer.
OmniPlayerPro._v26_btn = _v26_btn
OmniPlayerPro._v26_build_ui = _v26_build_ui
OmniPlayerPro._v26_refresh = _v26_refresh
OmniPlayerPro._v26_seek = _v26_seek
OmniPlayerPro._v26_set_vol = _v26_set_vol
OmniPlayerPro._v26_toggle_right = _v26_toggle_right
OmniPlayerPro._v26_command_dialog = _v26_command_dialog

_prev_init_v26 = OmniPlayerPro.__init__
def _init_v26(self, *args, **kwargs):
    _prev_init_v26(self, *args, **kwargs)
    try:
        self.setMinimumSize(1000, 650)
        self.setStyleSheet(r'''
        QMainWindow, QWidget#V26Root { background: #050912; color: #eaf2ff; font-family: "Segoe UI"; }
        #V26Header, #V26Side, #V26RightShell, #V26Transport, #V26Bottom { background: #0a1320; border: 1px solid #1e3550; border-radius: 14px; }
        #V26Header { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #0a1322, stop:.6 #101e31, stop:1 #0a1421); }
        #V26Brand { color: #77bcff; font-size: 20px; font-weight: 900; letter-spacing: 3px; }
        #V26Mode { color: #758ca6; font-size: 10px; font-weight: 850; letter-spacing: 1.8px; }
        #V26State { color: #76dfa9; font-size: 10px; font-weight: 900; }
        #V26State[playing="true"] { color: #75b9ff; }
        #V26Subs { color: #bb9cff; font-size: 10px; font-weight: 850; }
        #V26Time { color: #8da7c2; font-family: Consolas; font-size: 11px; font-weight: 750; }
        #V26Title { color: #f5f8ff; font-size: 15px; font-weight: 850; padding-left: 3px; }
        #V26Video { background: #02050a; border: 1px solid #1b2d44; border-radius: 14px; }
        #V26Card { background: #0a1422; border: 1px solid #203953; border-radius: 11px; }
        #V26CardTitle, #V26Section { color: #8bb7e4; font-size: 10px; font-weight: 900; letter-spacing: 1.5px; }
        #V26CardSub { color: #6e879f; font-size: 9px; }
        QToolButton { background: #101e30; color: #d8e7f7; border: 1px solid #294663; border-radius: 8px; padding: 7px 9px; font-weight: 700; }
        QToolButton:hover { background: #17324c; border-color: #5488ba; }
        QToolButton:pressed, QToolButton:checked { background: #214a72; border-color: #72ace0; }
        #V26Primary { background: #2c61a0; color: #fff; border-color: #6fa9e7; font-weight: 900; }
        #V26Primary:hover { background: #3771b7; }
        QLineEdit, QComboBox { background: #08111d; border: 1px solid #28415c; border-radius: 8px; padding: 7px; color: #eaf3ff; }
        QListWidget { background: #07101a; border: 1px solid #1b334d; border-radius: 9px; padding: 4px; }
        QListWidget::item { padding: 8px 6px; border-radius: 6px; color: #a8bfd5; }
        QListWidget::item:hover { background: #10263c; color: #fff; }
        QListWidget::item:selected { background: #214e79; color: #fff; }
        QSplitter::handle { background: #0d1825; }
        QScrollBar:vertical { background: #07101a; width: 9px; margin: 2px; }
        QScrollBar::handle:vertical { background: #29445f; border-radius: 4px; min-height: 28px; }
        QSlider::groove:horizontal { height: 5px; background: #152538; border-radius: 3px; }
        QSlider::sub-page:horizontal { background: #477fb8; border-radius: 3px; }
        QSlider::handle:horizontal { width: 14px; margin: -5px 0; border-radius: 7px; background: #86c4ff; border: 1px solid #e0f2ff; }
        QStatusBar { background: #050a12; color: #7f98b1; border-top: 1px solid #17283a; }
        ''')
        _v26_build_ui(self)
        self._v26_timer = QTimer(self)
        self._v26_timer.timeout.connect(lambda: _v26_refresh(self))
        self._v26_timer.start(150)
        self.log_event('Omni Studio 26: responsive command-center GUI installed.', '#6FB8FF')
    except Exception as e:
        try: self.log_event(f'Omni Studio 26 GUI warning: {e}', '#F39C12')
        except Exception: pass

OmniPlayerPro.__init__ = _init_v26



# =============================================================================
# OMNI STUDIO CLASSIC+ — keep the original UI, polish the presentation only.
# Fullscreen intentionally leaves only the video/subtitle display visible.
# =============================================================================
def _classic_plus_theme(self):
    self.setStyleSheet(r"""
    QMainWindow, QWidget { background: #0f1116; color: #e9edf3; font-family: "Segoe UI"; }
    QMenuBar { background: #171a21; color: #dfe6ef; border-bottom: 1px solid #292f3a; padding: 3px 6px; }
    QMenuBar::item { padding: 7px 10px; border-radius: 6px; }
    QMenuBar::item:selected { background: #2d5f95; color: white; }
    QMenu { background: #191d24; color: #e7edf5; border: 1px solid #303844; padding: 5px; }
    QMenu::item { padding: 7px 22px 7px 12px; border-radius: 5px; }
    QMenu::item:selected { background: #2d5f95; color: white; }
    QToolBar { background: #141820; border: 0; border-bottom: 1px solid #2a313d; spacing: 5px; padding: 5px; }
    QDockWidget { background: #151922; color: #c7d4e3; font-weight: 700; border: 1px solid #2a323f; }
    QDockWidget::title { background: #1a1f28; padding: 7px; }
    QFrame { border-radius: 8px; }
    #display_container { background: #050608; border: 1px solid #2d3542; }
    QGroupBox { background: #151922; border: 1px solid #2b3441; border-radius: 8px; margin-top: 8px; padding-top: 8px; font-weight: 700; }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #8fc7ff; }
    QTabWidget::pane { background: #151922; border: 1px solid #2b3441; border-radius: 8px; }
    QTabBar::tab { background: #1b2029; color: #aeb9c8; padding: 8px 14px; margin: 2px; border-radius: 6px; }
    QTabBar::tab:hover { background: #252c37; color: #fff; }
    QTabBar::tab:selected { background: #2f679e; color: white; font-weight: 700; }
    QPushButton { background: #202631; color: #e9eff7; border: 1px solid #394555; border-radius: 7px; padding: 7px 10px; font-weight: 600; }
    QPushButton:hover { background: #2a3442; border-color: #5b7694; }
    QPushButton:pressed { background: #31577e; }
    QLineEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox { background: #10151d; color: #e9edf3; border: 1px solid #303947; border-radius: 6px; padding: 6px; }
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #4b8bc5; }
    QListWidget, QTableWidget { background: #10151d; alternate-background-color: #151b24; color: #dae3ed; border: 1px solid #303947; border-radius: 6px; }
    QListWidget::item { padding: 6px; border-radius: 5px; }
    QListWidget::item:hover { background: #202a36; }
    QListWidget::item:selected { background: #2c5d8f; color: white; }
    QHeaderView::section { background: #1b222c; color: #b8c8da; padding: 6px; border: 0; }
    QSlider::groove:horizontal { height: 6px; background: #252c37; border-radius: 3px; }
    QSlider::sub-page:horizontal { background: #4084c0; border-radius: 3px; }
    QSlider::handle:horizontal { width: 15px; margin: -5px 0; border-radius: 8px; background: #8ec8ff; border: 1px solid #d9efff; }
    QScrollBar:vertical { background: #10151d; width: 10px; margin: 2px; }
    QScrollBar::handle:vertical { background: #344150; border-radius: 5px; min-height: 24px; }
    QStatusBar { background: #11161e; color: #91a3b7; border-top: 1px solid #28313d; }
    """)
    try:
        self.display_container.setObjectName('display_container')
    except Exception:
        pass


def _classic_plus_toggle_fullscreen(self):
    if not getattr(self, 'is_fullscreen', False):
        self._classic_plus_restore = {
            'menu': self.menuBar().isVisible(),
            'controls': self.controls_frame.isVisible(),
            'status': self.status_bar.isVisible(),
            'docks': [(d, d.isVisible()) for d in self.findChildren(QDockWidget)],
            'toolbars': [(t, t.isVisible()) for t in self.findChildren(QToolBar)],
        }
        self.is_fullscreen = True
        self.menuBar().hide()
        self.controls_frame.hide()
        self.status_bar.hide()
        for d, _ in self._classic_plus_restore['docks']:
            d.hide()
        for t, _ in self._classic_plus_restore['toolbars']:
            t.hide()
        self.showFullScreen()
        self.video_widget.setFocus()
        self.log_event('Fullscreen: video + subtitles only.', '#5DADE2')
    else:
        self.showNormal()
        self.is_fullscreen = False
        state = getattr(self, '_classic_plus_restore', {})
        self.menuBar().setVisible(state.get('menu', True))
        self.controls_frame.setVisible(state.get('controls', True))
        self.status_bar.setVisible(state.get('status', True))
        for d, visible in state.get('docks', []):
            d.setVisible(visible)
        for t, visible in state.get('toolbars', []):
            t.setVisible(visible)
        self.log_event('Fullscreen exited.', '#5DADE2')


_classic_plus_base_init = _original_init_20

def _classic_plus_init(self, *args, **kwargs):
    _classic_plus_base_init(self, *args, **kwargs)
    try:
        self._v21_install()
    except Exception as e:
        try: self.log_event(f'Library/reliability service warning: {e}', '#F39C12')
        except Exception: pass
    try:
        self._f22_install_feature_studio()
    except Exception as e:
        try: self.log_event(f'Feature Studio warning: {e}', '#F39C12')
        except Exception: pass
    try:
        _classic_plus_theme(self)
        self.setMinimumSize(1020, 640)
        self.resize(1400, 900)
        if hasattr(self, 'command_center'):
            self.command_center.setMinimumHeight(175)
        self.log_event('OmniPlayer Classic+ interface loaded.', '#5DADE2')
    except Exception as e:
        try: self.log_event(f'Classic+ UI warning: {e}', '#F39C12')
        except Exception: pass

OmniPlayerPro.__init__ = _classic_plus_init
OmniPlayerPro.toggle_fullscreen = _classic_plus_toggle_fullscreen


# =============================================================================
# OMNIPLAYER PRO 28 — CLASSIC UI ENHANCEMENT + PLAYBACK/WORKFLOW UPGRADE
# Keeps the classic layout while adding higher-end workflow features without
# replacing the familiar control surface.
# =============================================================================
from PyQt6.QtWidgets import (
    QScrollArea, QDialogButtonBox, QDoubleSpinBox, QTextBrowser, QFormLayout,
    QSlider as _QSlider, QListWidget as _QListWidget, QMessageBox as _QMessageBox
)
from PyQt6.QtGui import QShortcut

def _p28_local_file(self):
    p=str(getattr(self,'current_media','') or '')
    return p if p and not p.lower().startswith(('http://','https://')) and os.path.isfile(p) else None

def _p28_set_window_title(self, text=None):
    p=_p28_local_file(self)
    if text is not None:
        self.setWindowTitle(text); return
    self.setWindowTitle(f"OmniPlayer Pro | {os.path.basename(p) if p else 'Ready'}")

def _p28_restore_ui(self):
    state=getattr(self,'_classic_plus_restore',{}) or {}
    for obj,key in [(getattr(self,'menu_bar',None),'menu'),(getattr(self,'controls_frame',None),'controls'),(getattr(self,'status_bar',None),'status')]:
        if obj is not None and key in state: obj.setVisible(state[key])
    for obj,vis in state.get('docks',[]):
        try: obj.setVisible(vis)
        except Exception: pass
    for obj,vis in state.get('toolbars',[]):
        try: obj.setVisible(vis)
        except Exception: pass

def _p28_fullscreen(self):
    if not getattr(self,'is_fullscreen',False):
        self._classic_plus_restore={
            'menu':self.menu_bar.isVisible(),
            'controls':self.controls_frame.isVisible(),
            'status':self.status_bar.isVisible(),
            'docks':[(d,d.isVisible()) for d in self.findChildren(QDockWidget)],
            'toolbars':[(t,t.isVisible()) for t in self.findChildren(QToolBar)],
        }
        self.menu_bar.hide(); self.controls_frame.hide(); self.status_bar.hide()
        for d in self.findChildren(QDockWidget): d.hide()
        for t in self.findChildren(QToolBar): t.hide()
        try: self.visualizer.hide()
        except Exception: pass
        self.showFullScreen(); self.is_fullscreen=True
        self.video_widget.setFocus()
        self.log_event('Fullscreen: video + subtitles only.','#5DADE2')
    else:
        self.showNormal(); self.is_fullscreen=False; _p28_restore_ui(self)
        self.video_widget.setFocus()
        self.log_event('Fullscreen exited.','#5DADE2')

def _p28_perform_seek(self, val):
    duration=max(0,int(self.player.duration()))
    target=max(0,min(int(val),duration)) if duration else max(0,int(val))
    resume=bool(getattr(self,'_resume_after_seek',False))
    self._resume_after_seek=False
    try:
        self.player.pause()
        self.player.setPosition(target)
    except Exception as e:
        self.log_event(f'Seek error: {e}','#E74C3C')
        return
    self.is_seeking=False
    if resume:
        # Let the renderer settle after a large decoder seek.
        QTimer.singleShot(180, lambda: self.player.play())

def _p28_seek_ended(self):
    self.is_seeking=False

def _p28_step_frame(self, direction=1):
    if not self.is_video: return
    p=_p28_local_file(self)
    fps=30.0
    if p:
        try:
            info=_v21_probe(p); vs=next((x for x in info.get('streams',[]) if x.get('codec_type')=='video'),{})
            fps=_v21_fps(vs.get('avg_frame_rate') or vs.get('r_frame_rate')) or 30.0
        except Exception: pass
    was=self.player.playbackState()==QMediaPlayer.PlaybackState.PlayingState
    if was: self.player.pause()
    target=max(0,min(self.player.duration(),self.player.position()+int(direction*1000.0/fps)))
    self.player.setPosition(target)

def _p28_apply_video_filter(self, filter_expr, label):
    p=_p28_local_file(self)
    if not p: return
    root=os.path.splitext(p)[0]
    out=root+'_'+label.replace(' ','_').lower()+'.mp4'
    try:
        self._f22_ffmpeg(['-vf',filter_expr,'-c:v','libx264','-crf','18','-c:a','copy'],label,out)
    except Exception as e: self.log_event(str(e),'#E74C3C')

def _p28_video_adjust_dialog(self):
    if not _p28_local_file(self): return
    d=QDialog(self); d.setWindowTitle('Video Adjustment'); d.resize(420,240)
    f=QFormLayout(d)
    vals={}
    for name,default in [('Brightness',0.0),('Contrast',1.0),('Saturation',1.0),('Gamma',1.0)]:
        sp=QDoubleSpinBox(); sp.setRange(-2.0 if name=='Brightness' else 0.1,2.0); sp.setSingleStep(0.05); sp.setValue(default); vals[name]=sp; f.addRow(name,sp)
    bb=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel); f.addRow(bb); bb.accepted.connect(d.accept); bb.rejected.connect(d.reject)
    if d.exec():
        vf=f"eq=brightness={vals['Brightness'].value()}:contrast={vals['Contrast'].value()}:saturation={vals['Saturation'].value()}:gamma={vals['Gamma'].value()}"
        _p28_apply_video_filter(self,vf,'Color Adjusted')

def _p28_replaygain_scan(self):
    p=_p28_local_file(self)
    if not p: return
    try:
        r=subprocess.run(['ffmpeg','-hide_banner','-i',p,'-af','ebur128=framelog=verbose','-f','null','-'],capture_output=True,text=True,creationflags=CREATE_NO_WINDOW,timeout=180)
        text=r.stderr
        import re as _re
        matches=_re.findall(r'I:\s*(-?\d+(?:\.\d+)?) LUFS',text)
        integrated=matches[-1] if matches else 'N/A'
        _adv_dialog_text(self,'Loudness / ReplayGain Scan',f'Integrated loudness: {integrated} LUFS\n\nUse the Audio Lab normalization tools to create a normalized copy.')
    except Exception as e: self.log_event(f'Loudness scan failed: {e}','#E74C3C')

def _p28_scan_silence(self):
    p=_p28_local_file(self)
    if not p: return
    out=os.path.splitext(p)[0]+'_silence_scan.txt'
    try:
        r=subprocess.run(['ffmpeg','-hide_banner','-i',p,'-af','silencedetect=noise=-35dB:d=0.4','-f','null','-'],capture_output=True,text=True,creationflags=CREATE_NO_WINDOW,timeout=180)
        Path(out).write_text(r.stderr,encoding='utf-8',errors='ignore')
        self.log_event(f'Silence scan saved: {out}','#2ECC71')
    except Exception as e: self.log_event(str(e),'#E74C3C')

def _p28_load_external_subtitle(self):
    path,_=QFileDialog.getOpenFileName(self,'Load Subtitle File','','Subtitles (*.srt *.ass *.ssa *.vtt *.sub)')
    if not path: return
    try:
        text=Path(path).read_text(encoding='utf-8-sig',errors='replace')
        import re as _re
        cues=[]
        if path.lower().endswith('.vtt'):
            blocks=_re.split(r'\n\s*\n',text)
            for b in blocks:
                m=_re.search(r'(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3}).*?\n(.+)',b,re.S)
                if m:
                    def ts(x):
                        h,mi,s=x.replace('.',':').split(':'); return int((int(h)*3600+int(mi)*60+int(s))*1000+int(x.split('.')[-1]))
                    cues.append((ts(m.group(1)),ts(m.group(2)),m.group(3).strip(),''))
        else:
            blocks=_re.split(r'\n\s*\n',text)
            def parse_ts(x):
                x=x.replace(',','.'); h,mi,rest=x.split(':'); sec,ms=rest.split('.'); return (int(h)*3600+int(mi)*60+int(sec))*1000+int(ms)
            for b in blocks:
                m=_re.search(r'(\d{1,2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*(\d{1,2}:\d{2}:\d{2}[,.]\d{3})',b)
                if m:
                    body=_re.sub(r'^.*?-->.*?$', '', b, flags=_re.M).strip()
                    cues.append((parse_ts(m.group(1))/1000.0,parse_ts(m.group(2))/1000.0,body,''))
        if cues:
            # Normalize milliseconds to seconds and replace the current generated subtitle track.
            norm=[]
            for a,b,t,tr in cues:
                norm.append((a/1000.0 if a>10000 else a,b/1000.0 if b>10000 else b,t,tr))
            self.generated_subs=norm
            self.log_event(f'External subtitles loaded: {os.path.basename(path)} ({len(norm)} cues)',' #2ECC71'.strip())
        else:
            raise ValueError('No subtitle cues detected')
    except Exception as e:
        _QMessageBox.warning(self,'Subtitle Import Failed',str(e))

def _p28_export_vtt(self):
    if not getattr(self,'generated_subs',None): return
    out,_=QFileDialog.getSaveFileName(self,'Export WebVTT','subtitles.vtt','WebVTT (*.vtt)')
    if not out:return
    def ts(sec):
        sec=max(0,float(sec)); h=int(sec//3600); sec-=h*3600; m=int(sec//60); sec-=m*60; s=int(sec); ms=int(round((sec-s)*1000)); return f'{h:02d}:{m:02d}:{s:02d}.{ms:03d}'
    with open(out,'w',encoding='utf-8') as f:
        f.write('WEBVTT\n\n')
        for i,(a,b,t,tr) in enumerate(self.generated_subs,1): f.write(f'{i}\n{ts(a)} --> {ts(b)}\n{t}\n\n')
    self.log_event(f'WebVTT saved: {out}','#2ECC71')

def _p28_export_transcript(self):
    if not getattr(self,'generated_subs',None): return
    out,_=QFileDialog.getSaveFileName(self,'Export Transcript','transcript.txt','Text (*.txt)')
    if not out:return
    with open(out,'w',encoding='utf-8') as f:
        for a,b,t,tr in self.generated_subs:
            f.write(f'[{self._format_time(int(a*1000))}] {t}' + (f'\n[{self._format_time(int(a*1000))}] {tr}' if tr else '') + '\n')
    self.log_event(f'Transcript saved: {out}','#2ECC71')

def _p28_media_stats(self):
    p=_p28_local_file(self)
    if not p:return
    try:
        info=_v21_probe(p)
        v=next((x for x in info.get('streams',[]) if x.get('codec_type')=='video'),{})
        a=next((x for x in info.get('streams',[]) if x.get('codec_type')=='audio'),{})
        fmt=info.get('format',{})
        msg=(f"File: {os.path.basename(p)}\nSize: {os.path.getsize(p)/1024/1024:.1f} MB\n"
             f"Container: {fmt.get('format_name','N/A')}\nDuration: {fmt.get('duration','N/A')} s\n"
             f"Video: {v.get('codec_name','N/A')} {v.get('width','?')}x{v.get('height','?')} @ {v.get('r_frame_rate','?')}\n"
             f"Audio: {a.get('codec_name','N/A')} {a.get('sample_rate','?')} Hz / {a.get('channels','?')} ch")
        _adv_dialog_text(self,'Professional Media Summary',msg)
    except Exception as e: self.log_event(f'Media summary failed: {e}','#E74C3C')

def _p28_aspect(self):
    # Window-level aspect presets using Qt's video widget aspect mode.
    try:
        from PyQt6.QtMultimedia import QVideoFrame
    except Exception: pass
    choices=[('Fit',Qt.AspectRatioMode.KeepAspectRatio),('Stretch',Qt.AspectRatioMode.IgnoreAspectRatio),('Crop',Qt.AspectRatioMode.KeepAspectRatioByExpanding)]
    labels=[x[0] for x in choices]
    item,ok=QInputDialog.getItem(self,'Video Display Mode','Mode:',labels,0,False)
    if ok:
        mode=choices[labels.index(item)][1]
        try:self.video_widget.setAspectRatioMode(mode)
        except Exception: pass

def _p28_screenshot_burst(self):
    if not self.is_video:return
    outdir,_=QFileDialog.getExistingDirectory(self,'Choose Screenshot Folder'),''
    if not outdir:return
    count,ok=QInputDialog.getInt(self,'Screenshot Burst','Number of frames:',5,2,60,1)
    if not ok:return
    dur=max(1,self.player.duration()); pos=self.player.position(); span=min(10000,dur)
    for i in range(count):
        target=max(0,min(dur,pos-span//2 + int(span*i/max(1,count-1))))
        self.player.setPosition(target); QApplication.processEvents(); time.sleep(0.08)
        self.video_widget.grab().save(os.path.join(outdir,f'frame_{i+1:03d}.png'),'PNG')
    self.player.setPosition(pos); self.log_event(f'Screenshot burst exported: {count} frames',' #2ECC71'.strip())

def _p28_show_about(self):
    about = (
        '<h2>OmniPlayer Pro — Classic 29</h2>'
        '<p><b>Created by:</b> Tejinder Pal Singh</p>'
        '<p><b>Interface:</b> Classic OmniPlayer interface with enhanced playback reliability and media tools.</p>'
        '<p><b>Third-party components:</b> PyQt6, Qt Multimedia, FFmpeg, faster-whisper, yt-dlp, PyChromecast, SpeechRecognition, cryptography, pynvml and other optional components.</p>'
        '<p><b>Licensing:</b> See the included LICENSE.txt, EULA.txt and THIRD_PARTY_NOTICES.txt files before redistribution.</p>'
        '<p><b>Important:</b> Third-party licensing terms remain applicable to their respective components.</p>'
    )
    _QMessageBox.information(self,'About OmniPlayer Pro',about)

def _p28_install_menu(self):
    if hasattr(self,'_p28_menu'): return
    menu=self.menuBar().addMenu('Pro Tools')
    self._p28_menu=menu
    playback=menu.addMenu('Playback & Navigation')
    for label,cb in [
        ('Frame Forward',lambda:_p28_step_frame(self,1)),('Frame Backward',lambda:_p28_step_frame(self,-1)),
        ('Jump To Time',self.jump_to_time),('Set A-B Start',self.set_loop_a),('Set A-B End',self.set_loop_b),('Clear A-B Loop',self.clear_loop),
        ('25% Position',lambda:self.player.setPosition(int(self.player.duration()*.25))),('50% Position',lambda:self.player.setPosition(int(self.player.duration()*.50))),('75% Position',lambda:self.player.setPosition(int(self.player.duration()*.75))),('100% Position',lambda:self.player.setPosition(self.player.duration())),
        ('Playback Speed…',self.set_playback_speed)]:
        _add=QAction(label,self); _add.triggered.connect(cb); playback.addAction(_add)
    video=menu.addMenu('Video Lab')
    for label,cb in [('Display Aspect Mode',lambda:_p28_aspect(self)),('Colour / Exposure Adjustment',self._p28_video_adjust_dialog),('Grayscale Copy',lambda:_p28_apply_video_filter(self,'format=gray','Grayscale')),('Sharpened Copy',lambda:_p28_apply_video_filter(self,'unsharp=5:5:1.0:5:5:0.0','Sharpened')),('Denoised Copy',lambda:_p28_apply_video_filter(self,'hqdn3d','Denoised')),('Deinterlace Copy',lambda:_p28_apply_video_filter(self,'yadif','Deinterlaced')),('Mirror Copy',lambda:_p28_apply_video_filter(self,'hflip','Mirrored')),('Flip Vertical Copy',lambda:_p28_apply_video_filter(self,'vflip','Flipped')),('Screenshot Burst',self._p28_screenshot_burst)]:
        a=QAction(label,self);a.triggered.connect(cb);video.addAction(a)
    audio=menu.addMenu('Audio Lab')
    for label,cb in [('ReplayGain / LUFS Scan',self._p28_replaygain_scan),('Silence Scan',self._p28_scan_silence),('10-Band EQ',self.show_equalizer),('Dialogue Noise Reduction',self._adv_audio_denoise),('Normalize Loudness',self._adv_audio_normalize),('Dynamic Compressor',self._adv_audio_compressor),('Peak Limiter',self._adv_audio_limiter),('Bass Boost',self._adv_audio_bass),('Treble Boost',self._adv_audio_treble)]:
        a=QAction(label,self);a.triggered.connect(cb);audio.addAction(a)
    subs=menu.addMenu('Subtitles & Transcript')
    for label,cb in [('Load SRT / ASS / VTT',self._p28_load_external_subtitle),('Export SRT',self.export_subtitles),('Export WebVTT',self._p28_export_vtt),('Export Plain Transcript',self._p28_export_transcript),('Subtitle Style',self.subtitle_style_dialog),('Sync Delay',self.adjust_sub_sync),('AI Generate',self.start_ai),('AI Chapters',self.generate_ai_chapters),('Repair Timing',self._f22_auto_repair_subtitles),('Transcript Search',self._adv_find_transcript)]:
        a=QAction(label,self);a.triggered.connect(cb);subs.addAction(a)
    lib=menu.addMenu('Library & Organization')
    for label,cb in [('Scan Current Folder',self._f22_scan_current_folder),('Library Counts',self._f22_media_counts),('Cleanup Missing',self._f22_cleanup_missing),('Smart Playlist',self._v21_smart_playlist),('Export Library JSON',self._f22_export_library_json),('Set Media Note',self._f22_set_note),('Toggle Watched',self._f22_toggle_watched),('Reset Resume',self._f22_reset_resume),('Deduplicate Playlist',self._adv_playlist_dedupe),('Sort Playlist',self._adv_playlist_sort_name),('Randomize Playlist',self._adv_playlist_randomize),('Import M3U8',self._adv_playlist_import),('Export M3U8',self._adv_playlist_export)]:
        a=QAction(label,self);a.triggered.connect(cb);lib.addAction(a)
    inspect=menu.addMenu('Inspector & Diagnostics')
    for label,cb in [('Professional Media Summary',self._p28_media_stats),('Stream Inspector',self._adv_show_stream_table),('Advanced Media Report',self._adv_media_report),('Hardware Diagnostics',self._v21_hardware_info),('Dependency Diagnostics',self._adv_check_dependencies),('Network Diagnostics',self._v21_network_diagnostics),('Export Telemetry Log',self._adv_export_log),('Copy Diagnostics',self._f22_copy_diagnostics)]:
        a=QAction(label,self);a.triggered.connect(cb);inspect.addAction(a)
    ui=menu.addMenu('Interface')
    for label,cb in [('Fullscreen (Video + Subs)',self.toggle_fullscreen),('Picture in Picture',self.toggle_pip_mode),('Toggle Playlist',self._adv_toggle_playlist),('Toggle Bookmarks',self._adv_toggle_bookmarks),('Toggle Telemetry',self._adv_toggle_console),('Toggle Status Bar',self._adv_toggle_status),('Reset View',self._adv_reset_view),('Dark Theme',self._adv_set_theme_dark),('Light Theme',self._adv_set_theme_light),('Sapphire Theme',self._adv_set_theme_sapphire)]:
        a=QAction(label,self);a.triggered.connect(cb);ui.addAction(a)
    self.log_event('Pro Tools installed: enhanced classic workflow enabled.','#2ECC71')

def _p28_build_shortcuts(self):
    shortcuts=[('Space',self.toggle_play),('F',self.toggle_fullscreen),('Ctrl+O',self.load_local_media),('Left',self.skip_backward),('Right',self.skip_forward),('Shift+Left',lambda:_p28_step_frame(self,-1)),('Shift+Right',lambda:_p28_step_frame(self,1)),('M',self.toggle_mute),('A',self.set_loop_a),('B',self.set_loop_b),('C',self.clear_loop),('Ctrl+B',lambda:self.add_bookmark())]
    for seq,cb in shortcuts:
        sc=QShortcut(QKeySequence(seq),self);sc.activated.connect(cb)

def _p28_polish_classic_ui(self):
    # Remove any perceptual gap between video and subtitle deck and keep the deck tight.
    try:
        dl=self.display_container.layout(); dl.setContentsMargins(0,0,0,0); dl.setSpacing(0)
        self.subtitle_container.setMinimumHeight(56); self.subtitle_container.setMaximumHeight(76)
        sl=self.subtitle_container.layout(); sl.setContentsMargins(8,2,8,2); sl.setSpacing(0)
        self.subtitle_bar_top.setMaximumHeight(24)
        self.subtitle_bar.setMinimumHeight(30)
        self.display_container.setStyleSheet('QFrame{background:#000;border:1px solid #252b34;border-radius:9px;}')
    except Exception: pass

def _p28_wrap_init(self,*args,**kwargs):
    _p28_previous_init(self,*args,**kwargs)
    try:
        _p28_polish_classic_ui(self)
        _p28_install_menu(self)
        _p28_build_shortcuts(self)
        self.log_event('OmniPlayer Pro Classic 28 enhancements active.','#5DADE2')
    except Exception as e:
        try:self.log_event(f'Classic 28 enhancement warning: {e}','#F39C12')
        except Exception:pass

# Bind enhancement methods before replacing the initializer.
OmniPlayerPro._p28_video_adjust_dialog=_p28_video_adjust_dialog
OmniPlayerPro._p28_replaygain_scan=_p28_replaygain_scan
OmniPlayerPro._p28_scan_silence=_p28_scan_silence
OmniPlayerPro._p28_load_external_subtitle=_p28_load_external_subtitle
OmniPlayerPro._p28_export_vtt=_p28_export_vtt
OmniPlayerPro._p28_export_transcript=_p28_export_transcript
OmniPlayerPro._p28_media_stats=_p28_media_stats
OmniPlayerPro._p28_screenshot_burst=_p28_screenshot_burst
_p28_previous_init=OmniPlayerPro.__init__
OmniPlayerPro.__init__=_p28_wrap_init
OmniPlayerPro.toggle_fullscreen=_p28_fullscreen
OmniPlayerPro.perform_seek=_p28_perform_seek
OmniPlayerPro.seek_ended=_p28_seek_ended

# =============================================================================
# FINAL APPLICATION ENTRY POINT
# Keep startup after all feature/UI patch layers so Classic 28 is installed.
# =============================================================================
if __name__ == "__main__":
    try:
        myappid = 'twofishy.omniplayer.pro.ultimate.26'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    app = QApplication(sys.argv)
    icon_path = resource_path("app_icon.ico")
    app.setWindowIcon(QIcon(icon_path))
    app.setStyle("Fusion")

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(5, 9, 18))
    palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    app.setPalette(palette)

    player = OmniPlayerPro()
    player.setWindowIcon(QIcon(icon_path))
    player.show()

    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        if os.path.exists(filepath):
            if filepath.lower().endswith('.tjz'):
                player.play_encrypted_media_direct(filepath)
            else:
                player._play_target(filepath)

    sys.exit(app.exec())
