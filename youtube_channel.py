#!/usr/bin/env python3
"""Kompletter Kanal-Transkriber fuer YouTube (Videos + Shorts).

Holt fuer jedes Video die deutschen Auto-Untertitel (schnell). Wo keine
Untertitel existieren, faellt das Skript optional auf Whisper zurueck.
Speichert pro Video eine Markdown-Datei + eine Gesamtuebersicht.

Nutzung:
    python3 youtube_channel.py <channel-or-playlist-url> [--whisper-fallback]
    python3 youtube_channel.py --ids ID1 ID2 ...
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "transcripts"
PLAYER = "youtube:player_client=android"  # umgeht Bot-Check auf Cloud-IPs
SUB_LANGS = "de-orig,de,en-orig,en"

# --- Egress-Proxy-CA fuer SSL (siehe transcribe.py) ---
CUSTOM_CA_DIR = Path("/usr/local/share/ca-certificates")
_CA_MARKER = "# tiktok-transcriber: egress CAs appended"


def ensure_ca() -> None:
    if not CUSTOM_CA_DIR.is_dir():
        return
    try:
        import certifi
    except ImportError:
        return
    bundle = Path(certifi.where())
    if _CA_MARKER in bundle.read_text(encoding="utf-8", errors="ignore"):
        return
    extra = [p.read_text(encoding="utf-8", errors="ignore")
             for p in sorted(CUSTOM_CA_DIR.glob("*.crt"))]
    if extra:
        with bundle.open("a", encoding="utf-8") as fh:
            fh.write(f"\n{_CA_MARKER}\n")
            for cert in extra:
                fh.write("\n" + cert.strip() + "\n")


def yt(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["yt-dlp", "--no-warnings", "--extractor-args", PLAYER, *args],
        capture_output=True, text=True,
    )


def list_entries(url: str) -> list[dict]:
    """Listet alle Video-IDs/Titel einer Kanal-/Playlist-URL."""
    proc = yt("--flat-playlist", "--print",
              "%(id)s\t%(title)s\t%(duration)s", url)
    out = []
    for line in proc.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0]:
            out.append({"id": parts[0], "title": parts[1],
                        "duration": parts[2] if len(parts) > 2 else "NA"})
    return out


def vtt_to_text(vtt: str) -> str:
    """Wandelt VTT-Untertitel in fortlaufenden, entdoppelten Text um."""
    lines = []
    for raw in vtt.splitlines():
        line = raw.strip()
        if (not line or line == "WEBVTT" or "-->" in line
                or line.isdigit() or line.startswith(("Kind:", "Language:", "NOTE"))):
            continue
        line = re.sub(r"<[^>]+>", "", line)  # inline-tags entfernen
        line = re.sub(r"\[[^\]]*\]", "", line).strip()  # [Musik] etc.
        if line:
            lines.append(line)
    # aufeinanderfolgende Duplikate entfernen (VTT wiederholt Zeilen oft)
    deduped = []
    for ln in lines:
        if not deduped or deduped[-1] != ln:
            deduped.append(ln)
    text = " ".join(deduped)
    return re.sub(r"\s+", " ", text).strip()


def get_captions(vid: str, tmp: Path) -> tuple[str, str]:
    """Laedt Auto-Untertitel. Gibt (text, sprache) oder ('', '') zurueck."""
    url = f"https://www.youtube.com/watch?v={vid}"
    yt("--skip-download", "--write-auto-subs", "--write-subs",
       "--sub-langs", SUB_LANGS, "--sub-format", "vtt",
       "-o", str(tmp / "%(id)s.%(ext)s"), url)
    for lang in ("de-orig", "de", "en-orig", "en"):
        f = tmp / f"{vid}.{lang}.vtt"
        if f.exists():
            return vtt_to_text(f.read_text(encoding="utf-8", errors="ignore")), lang
    # irgendeine vorhandene vtt nehmen
    any_vtt = list(tmp.glob(f"{vid}.*.vtt"))
    if any_vtt:
        lang = any_vtt[0].name.split(".")[-2]
        return vtt_to_text(any_vtt[0].read_text(encoding="utf-8", errors="ignore")), lang
    return "", ""


def whisper_transcribe(vid: str, tmp: Path, model_name: str) -> tuple[str, str]:
    url = f"https://www.youtube.com/watch?v={vid}"
    yt("-x", "--audio-format", "wav", "-o", str(tmp / f"{vid}.%(ext)s"), url)
    wavs = list(tmp.glob(f"{vid}*.wav"))
    if not wavs:
        return "", ""
    from faster_whisper import WhisperModel
    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, info = model.transcribe(str(wavs[0]), beam_size=5)
    return " ".join(s.text.strip() for s in segments).strip(), info.language


def metadata(vid: str) -> dict:
    proc = yt("--dump-json", f"https://www.youtube.com/watch?v={vid}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}


def process(entry: dict, kind: str, whisper_fallback: bool, model: str) -> dict:
    vid = entry["id"]
    print(f"  [{kind}] {vid}  {entry['title'][:60]}")
    meta = metadata(vid)
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        text, lang = get_captions(vid, tmp)
        source = "auto-captions"
        if not text and whisper_fallback:
            print("      keine Untertitel -> Whisper ...")
            text, lang = whisper_transcribe(vid, tmp, model)
            source = "whisper"

    title = meta.get("title") or entry["title"]
    author = meta.get("channel") or meta.get("uploader") or "unbekannt"
    out_file = OUTPUT_DIR / f"{kind}_{vid}.md"
    out_file.write_text(
        f"# {title}\n\n"
        f"- **Typ:** {kind}\n"
        f"- **Autor:** {author}\n"
        f"- **URL:** https://www.youtube.com/watch?v={vid}\n"
        f"- **Dauer (s):** {meta.get('duration', entry.get('duration'))}\n"
        f"- **Views:** {meta.get('view_count', 'n/a')} | "
        f"**Likes:** {meta.get('like_count', 'n/a')} | "
        f"**Kommentare:** {meta.get('comment_count', 'n/a')}\n"
        f"- **Upload:** {meta.get('upload_date', 'n/a')}\n"
        f"- **Quelle:** {source} ({lang})\n"
        f"- **Beschreibung:** {(meta.get('description') or '')[:500]}\n\n"
        f"## Transkript\n\n{text or '(kein Transkript verfuegbar)'}\n",
        encoding="utf-8",
    )
    return {"id": vid, "kind": kind, "title": title,
            "views": meta.get("view_count"), "likes": meta.get("like_count"),
            "chars": len(text), "source": source, "lang": lang}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url", nargs="?", help="Kanal-/Playlist-URL")
    ap.add_argument("--videos-url"); ap.add_argument("--shorts-url")
    ap.add_argument("--whisper-fallback", action="store_true")
    ap.add_argument("--model", default="small")
    ap.add_argument("--limit", type=int, default=0, help="max. Anzahl (Test)")
    args = ap.parse_args()

    ensure_ca()
    OUTPUT_DIR.mkdir(exist_ok=True)

    jobs = []
    if args.videos_url:
        jobs += [(e, "video") for e in list_entries(args.videos_url)]
    if args.shorts_url:
        jobs += [(e, "short") for e in list_entries(args.shorts_url)]
    if args.url:
        jobs += [(e, "video") for e in list_entries(args.url)]
    if args.limit:
        jobs = jobs[:args.limit]

    print(f"Verarbeite {len(jobs)} Eintraege ...")
    summary = []
    for entry, kind in jobs:
        try:
            summary.append(process(entry, kind, args.whisper_fallback, args.model))
        except Exception as exc:  # noqa: BLE001
            print(f"      Fehler: {exc}", file=sys.stderr)

    (OUTPUT_DIR / "_uebersicht.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for s in summary if s["chars"] > 0)
    print(f"\nFertig: {ok}/{len(summary)} mit Transkript.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
