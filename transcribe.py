#!/usr/bin/env python3
"""TikTok-Video-Transkription fuer Content-Analyse.

Laedt ein oder mehrere TikTok-Videos (Audio) per yt-dlp herunter und
transkribiert sie mit faster-whisper. Gibt Transkript + Metadaten
(Caption, Autor, Stats) als Markdown aus.

Nutzung:
    python3 transcribe.py <tiktok-url> [<tiktok-url> ...]
    python3 transcribe.py --model small <url>

Modelle (Geschwindigkeit vs. Genauigkeit): tiny, base, small, medium, large-v3
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "transcripts"

# Egress-Proxy-Umgebungen (z. B. Claude Code on the web) nutzen ein eigenes
# CA-Zertifikat. yt-dlp verifiziert ueber certifi -> dort muss die Proxy-CA
# bekannt sein, sonst schlaegt der SSL-Handshake fehl.
CUSTOM_CA_DIR = Path("/usr/local/share/ca-certificates")
_CA_MARKER = "# tiktok-transcriber: egress CAs appended"


def ensure_ca() -> None:
    """Fuegt vorhandene Egress-Proxy-CAs einmalig ins certifi-Bundle ein."""
    if not CUSTOM_CA_DIR.is_dir():
        return
    try:
        import certifi
    except ImportError:
        return
    bundle = Path(certifi.where())
    content = bundle.read_text(encoding="utf-8", errors="ignore")
    if _CA_MARKER in content:
        return
    extra = [p.read_text(encoding="utf-8", errors="ignore")
             for p in sorted(CUSTOM_CA_DIR.glob("*.crt"))]
    if not extra:
        return
    with bundle.open("a", encoding="utf-8") as fh:
        fh.write(f"\n{_CA_MARKER}\n")
        for cert in extra:
            fh.write("\n" + cert.strip() + "\n")


def fetch_metadata(url: str) -> dict:
    """Holt Video-Metadaten ohne Download (Caption, Autor, Stats)."""
    proc = subprocess.run(
        ["yt-dlp", "--dump-json", "--no-warnings", url],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return {}
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}


def download_audio(url: str, out_path: Path) -> bool:
    """Laedt nur die Audiospur als wav herunter."""
    proc = subprocess.run(
        ["yt-dlp", "-x", "--audio-format", "wav", "--no-warnings",
         "-o", str(out_path), url],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(f"  Download-Fehler: {proc.stderr.strip()[:200]}", file=sys.stderr)
    return proc.returncode == 0


def transcribe(audio_path: Path, model_name: str) -> tuple[str, str]:
    """Transkribiert die Audiodatei. Gibt (text, sprache) zurueck."""
    from faster_whisper import WhisperModel

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(audio_path), beam_size=5)
    text = " ".join(seg.text.strip() for seg in segments)
    return text.strip(), info.language


def process(url: str, model_name: str) -> None:
    print(f"\n=> {url}")
    meta = fetch_metadata(url)
    title = meta.get("title") or meta.get("description") or "video"
    author = meta.get("uploader") or meta.get("uploader_id") or "unbekannt"
    vid = meta.get("id", "video")

    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "audio.wav"
        # yt-dlp haengt die Endung selbst an -> Stamm ohne .wav uebergeben
        if not download_audio(url, Path(tmp) / "audio"):
            print("  uebersprungen (Download fehlgeschlagen)")
            return
        # gefundene wav-Datei suchen
        wavs = list(Path(tmp).glob("*.wav"))
        if not wavs:
            print("  uebersprungen (keine Audiodatei)")
            return
        print("  transkribiere ...")
        text, lang = transcribe(wavs[0], model_name)

    OUTPUT_DIR.mkdir(exist_ok=True)
    out_file = OUTPUT_DIR / f"{author}_{vid}.md"
    out_file.write_text(
        f"# {title}\n\n"
        f"- **Autor:** {author}\n"
        f"- **URL:** {url}\n"
        f"- **Likes:** {meta.get('like_count', 'n/a')} | "
        f"**Kommentare:** {meta.get('comment_count', 'n/a')} | "
        f"**Views:** {meta.get('view_count', 'n/a')}\n"
        f"- **Caption:** {meta.get('description', '')}\n"
        f"- **Sprache:** {lang}\n\n"
        f"## Transkript\n\n{text}\n",
        encoding="utf-8",
    )
    print(f"  gespeichert: {out_file}")
    print(f"  --- Transkript ---\n  {text[:500]}")


def main() -> int:
    parser = argparse.ArgumentParser(description="TikTok-Videos transkribieren")
    parser.add_argument("urls", nargs="+", help="TikTok-Video-URL(s)")
    parser.add_argument("--model", default="small",
                        help="Whisper-Modell (tiny/base/small/medium/large-v3)")
    args = parser.parse_args()

    ensure_ca()
    for url in args.urls:
        try:
            process(url, args.model)
        except Exception as exc:  # noqa: BLE001
            print(f"  Fehler bei {url}: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
