#!/usr/bin/env python3
"""
readaloud: select text in any app, press a hotkey, hear it read with a
follow-along window that highlights the current sentence and word.

Usage:
    readaloud.py              read the current selection (falls back to clipboard)
    readaloud.py "some text"  read the given text

Keys in the window: Space = pause/resume, + / - = faster / slower, Esc = close.
Speed changes apply a couple of sentences ahead and are remembered next time.
Pressing the hotkey again replaces the running instance.
"""
import bisect
import os
import queue
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
import wave

HOME = os.path.expanduser("~")
MODEL = os.path.expanduser(
    os.environ.get("READALOUD_VOICE", "~/.local/share/piper/en_US-ryan-high.onnx")
)
PIPER = shutil.which("piper") or os.path.join(HOME, ".local/bin/piper")
PIDFILE = os.path.join(tempfile.gettempdir(), "readaloud.pid")
SPEED_FILE = os.path.join(HOME, ".config", "readaloud", "speed")
MIN_SPEED, MAX_SPEED, STEP = 0.5, 3.0, 0.25


def load_speed():
    """READALOUD_SPEED env wins, then the saved value, then 1.0."""
    try:
        if os.environ.get("READALOUD_SPEED"):
            v = float(os.environ["READALOUD_SPEED"])
        else:
            v = float(open(SPEED_FILE).read().strip())
    except Exception:
        v = 1.0
    return min(MAX_SPEED, max(MIN_SPEED, v))


def save_speed(v):
    try:
        os.makedirs(os.path.dirname(SPEED_FILE), exist_ok=True)
        with open(SPEED_FILE, "w") as f:
            f.write(f"{v:.2f}")
    except OSError:
        pass


# ---------- single instance ----------
def replace_previous_instance():
    try:
        old = int(open(PIDFILE).read().strip())
        with open(f"/proc/{old}/cmdline", "rb") as f:
            if b"readaloud" in f.read():
                os.kill(old, signal.SIGTERM)
                time.sleep(0.2)
    except Exception:
        pass
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))


# ---------- get text ----------
def grab_text():
    if len(sys.argv) > 1:
        return " ".join(sys.argv[1:])
    cmds = []
    if os.environ.get("WAYLAND_DISPLAY"):
        cmds += [["wl-paste", "-p", "-n"], ["wl-paste", "-n"]]
    cmds += [
        ["xclip", "-o", "-selection", "primary"],
        ["xclip", "-o", "-selection", "clipboard"],
    ]
    for c in cmds:
        if shutil.which(c[0]):
            try:
                out = subprocess.run(c, capture_output=True, text=True, timeout=2).stdout
            except Exception:
                continue
            if out.strip():
                return out
    return ""


# ---------- speech ----------
_flag = {"name": None}  # remembers which length-scale spelling this Piper accepts


def synth(sentence, path, length_scale=1.0):
    """length_scale < 1 is faster, > 1 is slower."""
    base = [PIPER, "-m", MODEL, "-f", path]
    data = " ".join(sentence.split())
    candidates = [_flag["name"]] if _flag["name"] is not None else [
        "--length-scale", "--length_scale", ""]
    err = ""
    for flag in candidates:
        cmd = base + ([flag, f"{length_scale:.3f}"] if flag else [])
        r = subprocess.run(cmd, input=data, text=True, capture_output=True)
        if r.returncode == 0:
            _flag["name"] = flag
            return
        err = r.stderr
    raise RuntimeError(err.strip()[-300:] or "piper failed")


def player_cmd(path):
    for name, args in (("paplay", []), ("pw-play", []), ("aplay", ["-q"])):
        if shutil.which(name):
            return [name, *args, path]
    raise RuntimeError("No audio player found (install pulseaudio-utils)")


class State:
    idx = -1          # sentence currently playing
    t0 = 0.0          # monotonic start time of current sentence
    dur = 1.0         # duration of current sentence (s)
    paused = False
    pause_at = 0.0
    proc = None
    done = False
    error = None


def main():
    text = grab_text().strip()
    if not text:
        sys.exit("readaloud: nothing selected")
    if not os.path.exists(MODEL):
        sys.exit(f"readaloud: voice model not found: {MODEL}")

    replace_previous_instance()

    sentences = [
        (m.start(), m.end())
        for m in re.finditer(r"\S.*?(?:[.!?]+(?=\s|$)|\n|$)", text)
    ]
    tmp = tempfile.mkdtemp(prefix="readaloud-")
    stop = threading.Event()
    st = State()
    speed = {"v": load_speed()}
    q = queue.Queue(maxsize=2)

    def producer():
        for i, (s, e) in enumerate(sentences):
            if stop.is_set():
                return
            path = os.path.join(tmp, f"{i}.wav")
            try:
                synth(text[s:e], path, 1.0 / speed["v"])
                with wave.open(path) as w:
                    dur = w.getnframes() / w.getframerate()
            except Exception as ex:
                st.error = f"Speech error: {ex}"
                q.put(None)
                return
            q.put((i, path, dur))
        q.put(None)

    def player():
        while not stop.is_set():
            item = q.get()
            if item is None:
                st.done = True
                return
            i, path, dur = item
            try:
                cmd = player_cmd(path)
            except RuntimeError as ex:
                st.error = str(ex)
                return
            st.dur = max(dur, 0.05)
            st.t0 = time.monotonic()
            st.idx = i
            st.proc = subprocess.Popen(cmd, stderr=subprocess.DEVNULL)
            st.proc.wait()
            try:
                os.remove(path)
            except OSError:
                pass

    threading.Thread(target=producer, daemon=True).start()
    threading.Thread(target=player, daemon=True).start()

    # ---------- window ----------
    root = tk.Tk()
    root.title(f"Read Aloud \u2014 {speed['v']:.2f}x")
    root.geometry("820x520")
    root.attributes("-topmost", True)

    box = tk.Text(
        root, wrap="word", font=("Sans", 16), bg="#1e1e2e", fg="#7f849c",
        padx=28, pady=22, spacing2=6, relief="flat", cursor="arrow",
    )
    box.pack(fill="both", expand=True)
    box.insert("1.0", text)
    box.config(state="disabled")
    box.tag_config("sent", background="#313244", foreground="#cdd6f4")
    box.tag_config("word", background="#f9e2af", foreground="#11111b")
    box.tag_raise("word")

    word_cache = {}

    def words_for(i):
        if i not in word_cache:
            s, e = sentences[i]
            ws = [(m.start() + s, m.end() + s) for m in re.finditer(r"\S+", text[s:e])]
            total = sum(b - a + 1 for a, b in ws) or 1
            cum, acc = [], 0
            for a, b in ws:
                acc += b - a + 1
                cum.append(acc / total)
            word_cache[i] = (ws, cum)
        return word_cache[i]

    def quit_all(*_):
        stop.set()
        try:
            if st.proc and st.proc.poll() is None:
                st.proc.kill()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            os.remove(PIDFILE)
        except OSError:
            pass
        root.destroy()

    def toggle_pause(*_):
        p = st.proc
        if not p or p.poll() is not None:
            return
        if not st.paused:
            p.send_signal(signal.SIGSTOP)
            st.paused = True
            st.pause_at = time.monotonic()
        else:
            p.send_signal(signal.SIGCONT)
            st.t0 += time.monotonic() - st.pause_at  # keep highlight in sync
            st.paused = False

    def change_speed(delta):
        speed["v"] = round(min(MAX_SPEED, max(MIN_SPEED, speed["v"] + delta)), 2)
        save_speed(speed["v"])
        root.title(f"Read Aloud \u2014 {speed['v']:.2f}x")

    for key in ("<plus>", "<equal>", "<KP_Add>"):
        root.bind(key, lambda e: change_speed(STEP))
    for key in ("<minus>", "<KP_Subtract>"):
        root.bind(key, lambda e: change_speed(-STEP))
    root.bind("<Escape>", quit_all)
    root.bind("<space>", toggle_pause)
    root.protocol("WM_DELETE_WINDOW", quit_all)
    signal.signal(signal.SIGTERM, lambda *a: root.after(0, quit_all))

    shown = {"idx": -1, "word": None}

    def tick():
        if st.error:
            box.config(state="normal")
            box.insert("end", f"\n\n[{st.error}]")
            box.config(state="disabled")
            st.error = None
        i = st.idx
        if i >= 0 and not st.paused:
            if i != shown["idx"]:
                s, e = sentences[i]
                box.tag_remove("sent", "1.0", "end")
                box.tag_add("sent", f"1.0+{s}c", f"1.0+{e}c")
                shown["idx"] = i
            frac = min((time.monotonic() - st.t0) / st.dur, 1.0)
            ws, cum = words_for(i)
            if ws:
                k = min(bisect.bisect_left(cum, frac), len(ws) - 1)
                if shown["word"] != (i, k):
                    a, b = ws[k]
                    box.tag_remove("word", "1.0", "end")
                    box.tag_add("word", f"1.0+{a}c", f"1.0+{b}c")
                    box.see(f"1.0+{a}c")
                    shown["word"] = (i, k)
        if st.done and st.proc and st.proc.poll() is not None:
            root.after(1200, quit_all)
            return
        root.after(30, tick)

    tick()
    root.mainloop()


if __name__ == "__main__":
    main()
