# Rhea <3 Chess

A Pygame chess adventure game with story scenes, character powers, shops, and bundled Stockfish support.

## GitHub Actions Builds

This repo has a GitHub Actions workflow that builds:

- Windows executable artifacts
- macOS app artifacts

Open the repo's `Actions` tab, click a workflow run, and download the artifacts from the `Artifacts` section at the bottom of the run page.

## Running The macOS App

After downloading and unzipping the macOS artifact, run the app binary from Terminal:

```bash
cd /path/to/unzipped/folder
./RheaChess.app/Contents/MacOS/RheaChess
```

If macOS says `permission denied`, run:

```bash
chmod +x ./RheaChess.app/Contents/MacOS/RheaChess
./RheaChess.app/Contents/MacOS/RheaChess
```

If macOS blocks the app because it was downloaded from the internet, run:

```bash
xattr -dr com.apple.quarantine ./RheaChess.app
chmod +x ./RheaChess.app/Contents/MacOS/RheaChess
./RheaChess.app/Contents/MacOS/RheaChess
```

Running it from Terminal is also the easiest way to see crash output and tracebacks if the app fails.
