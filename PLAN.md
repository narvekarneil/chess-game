# Chess Game Planning File (GUI-First)

## Goal
Build a Python GUI chess game that uses:
- `python-chess` for legal move generation, game state, SAN/UCI/FEN/PGN handling.
- `stockfish` (PyPI wrapper) for engine moves and evaluation.
- `pygame` for the game window, mouse input, and board rendering.

## Stack Decision (Easy + Reliable)
Recommended path:
1. `pygame` for GUI rendering and click handling.
2. `python-chess` for all game rules (no custom legality logic).
3. `stockfish` wrapper for AI.

Why this is easiest:
- Clean split of concerns (rendering vs rules vs engine).
- Strong docs and long-term community usage.
- We keep full control over the board UI and can scale features later.

## Online Findings (April 17, 2026)
- `stockfish` on PyPI is actively maintained (latest `5.1.0`, released April 14, 2026; Python `>=3.10`).
- `python-chess` docs provide:
  - `Board.legal_moves`, `push()`, `pop()`, `is_game_over()`.
  - Optional `chess.svg.board()` rendering helper.
  - Built-in UCI engine integration (`chess.engine.SimpleEngine.popen_uci`) as an alternative engine path.
- `pygame` docs clearly support the pieces we need:
  - display/window setup (`pygame.display.set_mode()`).
  - mouse and event loop (`pygame.event.get()`, mouse button events).
- Possible helper libs:
  - `python-chess-gui` (new package; Jan 30, 2026) exists, but is early-stage beta and less flexible for our own game architecture.
  - `chess-board` (last release July 14, 2023) can display boards, but is older and less ideal for a custom project.
  - `chessboard-image` is great for generating static board images, but not a full interactive GUI by itself.

## MVP Scope (GUI)
1. Playable human-vs-engine chess in a desktop window.
2. Click-to-select and click-to-move pieces.
3. Legal move highlighting.
4. Engine move after player move.
5. End-game detection and result banner.
6. Basic controls: `undo`, `new game`, `quit`.

## Dependencies
- Python 3.10+
- `python-chess`
- `stockfish` (PyPI package)
- `pygame`
- Stockfish binary installed on system and path configured
- Optional later: `chessboard-image` (for export/snapshots), not required for MVP

## Architecture Plan

### 1. Core Modules
- `src/main.py`
  - startup, main loop, scene wiring
- `src/game_state.py`
  - `chess.Board` state, selection state, move history, game result
- `src/engine.py`
  - Stockfish wrapper init/config
  - FEN sync + best move query
- `src/ui/board_view.py`
  - draw squares, pieces, highlights, last move, check marker
- `src/ui/input_controller.py`
  - mouse-to-square mapping and click move flow
- `src/assets.py`
  - piece image loading and scaling
- `src/config.py`
  - board size, colors, engine path, depth/skill

### 2. Runtime Flow
1. Initialize `pygame`, load assets, create `chess.Board()`.
2. Initialize Stockfish wrapper (validate engine path once at startup).
3. Main loop:
   - Read events (`QUIT`, mouse click, key press).
   - If player turn, map click to origin/target squares.
   - Build candidate move(s), verify with `move in board.legal_moves`.
   - Push player move.
   - If game not over, sync FEN and fetch engine move, then push it.
   - Render board + pieces + highlights + status text.
4. Show game-over result (`board.result()` plus reason).

## Milestones

### Milestone 1: GUI Bootstrap
- Create `src/` layout and app entry.
- Open pygame window and draw empty 8x8 board.
- Add board coordinates + frame timing.

### Milestone 2: Interactive Board
- Load piece sprites.
- Render from `chess.Board` position.
- Click-select piece and click destination square.
- Validate and apply legal moves only.

### Milestone 3: Engine Turn
- Configure Stockfish path/settings.
- After human move, call engine for best move.
- Apply engine move and redraw.
- Handle missing binary/path errors with clear UI message.

### Milestone 4: UX + Rules Feedback
- Show legal move dots for selected piece.
- Highlight last move and king-in-check square.
- Add `undo`, `new game`, and `quit`.
- Show checkmate/stalemate/draw messages.

### Milestone 5: Polish
- Add move list panel (SAN).
- Add optional flip-board and side selection.
- Add optional FEN copy/load + PGN export.

## Risks and Mitigations
- Risk: Stockfish binary path issues.
  - Mitigation: startup validation + actionable error text with platform hints.
- Risk: Input edge cases (misclicks, promotions).
  - Mitigation: explicit square-selection state machine; promotion prompt defaults to queen.
- Risk: Engine/UI freeze during move search.
  - Mitigation: keep depth/time modest for MVP; optionally move engine call to worker thread later.

## Testing Plan
- Unit tests:
  - square coordinate mapping
  - move candidate conversion
  - promotion handling
- Integration tests:
  - player move -> engine response loop
  - undo behavior across player/engine turns
- Manual QA checklist:
  - castling, en passant, promotion
  - check/checkmate/stalemate banners
  - window close + restart behavior

## Next Actions
1. Implement Milestone 1 now (`pygame` window + drawable chessboard grid).
2. Add piece assets and board rendering from `python-chess`.
3. Wire click-to-move using `board.legal_moves`.
4. Add Stockfish move response and basic controls.
