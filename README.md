# readaloud

Select text in any app on Ubuntu, press a hotkey, and hear it read aloud by a local neural voice. A small follow-along window highlights the current sentence and word as it speaks.

Everything runs offline on your machine using [Piper](https://github.com/OHF-Voice/piper1-gpl) for speech.

## Features

- Reads the current selection (or the clipboard) from any app
- Highlights the sentence and word being spoken
- Starts quickly on long text: speaks one sentence at a time while preparing the next
- Adjustable speed, remembered between runs
- Pause, resume, and close from the keyboard

## Setup (Ubuntu)

```bash
sudo apt install python3-tk wl-clipboard xclip pulseaudio-utils pipx
pipx install piper-tts
```

Download a voice (the model and its `.json` config must sit together):

```bash
mkdir -p ~/.local/share/piper && cd ~/.local/share/piper
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx.json
```

Copy the script somewhere with a clean path:

```bash
mkdir -p ~/bin
cp readaloud.py ~/bin/readaloud.py
python3 ~/bin/readaloud.py "Hello, this is a test."
```

## Hotkey

Settings → Keyboard → Custom Shortcuts → add:

- **Command:** `/usr/bin/python3 /home/YOURUSER/bin/readaloud.py`
- **Shortcut:** for example `Ctrl+Alt+R`

Then select text anywhere and press the shortcut. If an app doesn't expose its selection (some Wayland apps), press `Ctrl+C` first and use the shortcut again.

## Keys in the reading window

| Key | Action |
| --- | --- |
| Space | Pause / resume |
| `+` / `-` | Faster / slower (0.5x to 3x, applies a couple of sentences ahead) |
| Esc | Close |

Pressing the hotkey again replaces the running instance.

## Configuration

| Setting | How |
| --- | --- |
| Voice | Set `READALOUD_VOICE` to the path of another `.onnx` voice, or change the default near the top of the script |
| Speed | Use `+` / `-` in the window, or set `READALOUD_SPEED` (for example `1.5`) |

Browse more voices at [rhasspy.github.io/piper-samples](https://rhasspy.github.io/piper-samples).

## Notes and limits

- Highlighting is shown in the reader's own window, not inside the original app.
- Word timing is estimated from sentence length, so it can drift slightly on numbers and unusual words.
- Voice models are large and are not included in this repo; download them as shown above.

## Troubleshooting

- **Nothing happens:** run the script from a terminal with a text argument and read any error it prints.
- **"voice model not found":** check the path in `READALOUD_VOICE` or the default in the script, and make sure the `.onnx.json` file is next to the model.
- **No sound:** confirm `paplay` works (`paplay /usr/share/sounds/alsa/Front_Center.wav`).
