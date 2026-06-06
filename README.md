# TikTok-Transkriber für Content-Analyse

Lädt TikTok-Videos herunter und transkribiert sie mit Whisper, damit der
gesprochene Inhalt (Hook, Skript, Verkaufsargumente) analysiert werden kann –
gedacht als Recherche-Werkzeug für den Aufbau eines eigenen TikTok Shops.

## Was es macht

1. Holt Video-Metadaten (Caption, Autor, Likes, Kommentare, Views) via `yt-dlp`.
2. Lädt die Audiospur und transkribiert sie mit `faster-whisper`.
3. Speichert pro Video eine Markdown-Datei in `transcripts/`.

## Voraussetzungen

- Python 3.9+
- `ffmpeg` (System-Paket: `apt-get install ffmpeg`)
- Python-Pakete: `pip install -r requirements.txt`

## Nutzung

```bash
# Ein Video
python3 transcribe.py "https://www.tiktok.com/@creator/video/123..."

# Mehrere Videos auf einmal
python3 transcribe.py "<url1>" "<url2>" "<url3>"

# Größeres Modell für bessere Genauigkeit (langsamer)
python3 transcribe.py --model small "<url>"
```

Modelle nach Geschwindigkeit/Genauigkeit: `tiny`, `base`, `small`, `medium`, `large-v3`.
Für deutschsprachige Videos liefert `small` oder `medium` deutlich bessere Ergebnisse als `tiny`.

## Hinweis

Nur für eigene Recherche und Analyse öffentlich zugänglicher Inhalte verwenden.
Urheber- und Plattformrechte (TikTok-Nutzungsbedingungen) beachten.
