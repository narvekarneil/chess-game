"""Room-based chess adventure with sprites, dialogue, and chess battles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
import io
import json
import os
from pathlib import Path
import random
import shutil
import sys
import platform
from typing import Iterable

import chess
import chess.engine
import chess.svg
import pygame

try:
    import cairosvg
except Exception:
    cairosvg = None


class GameMode(Enum):
    EXPLORATION = auto()
    CHESS = auto()
    DIALOGUE = auto()
    PETTING = auto()


class RoomType(Enum):
    START = auto()
    CHESS_BATTLE = auto()
    POST_WIN = auto()


class MoveRuleMode(Enum):
    LEGAL_ONLY = auto()
    ALLOW_ILLEGAL = auto()


@dataclass(frozen=True)
class DialogueLine:
    speaker: str
    text: str
    portrait_key: str | None = None


@dataclass(frozen=True)
class PowerDefinition:
    power_id: str
    character_id: str
    name: str
    description: str
    target_prompt: str | None
    short_label: str
    target_kind: str = "none"


@dataclass(frozen=True)
class PopupOption:
    option_id: str
    title: str
    description: str
    enabled: bool = True


@dataclass(frozen=True)
class Doorway:
    rect: pygame.Rect
    target_room: int
    requires_unlock: bool = False
    unlock_flag: str | None = None
    label: str = "Door"


@dataclass(frozen=True)
class NpcSpawn:
    npc_id: str
    x: int
    y: int
    color: tuple[int, int, int]
    size: int = 56


@dataclass(frozen=True)
class RoomConfig:
    room_type: RoomType
    room_name: str
    walk_bounds: pygame.Rect
    doorways: tuple[Doorway, ...]
    npc_spawns: tuple[NpcSpawn, ...]
    dialogue_script_id: str | None = None
    chess_opponent_id: str | None = None


@dataclass
class RoomProgress:
    current_room_index: int = 0
    chess_room_cleared: bool = False
    chess_exit_unlocked: bool = False

    def is_unlocked(self, flag: str | None) -> bool:
        if flag is None:
            return True
        if flag == "chess_exit_unlocked":
            return self.chess_exit_unlocked
        return False


@dataclass
class SaveState:
    points: int = 0
    pragya_unlocked: bool = False
    isha_unlocked: bool = False
    gounder_unlocked: bool = False
    pragya_extra_spawns: int = 0
    isha_extra_capacity: int = 0
    gounder_extra_capacity: int = 0
    pragya_spawn_rate_boosts: int = 0
    isha_spawn_rate_boosts: int = 0
    gounder_spawn_rate_boosts: int = 0
    chess_entries: int = 0
    neil_attempts: int = 0
    intro_seen: bool = False


@dataclass(frozen=True)
class UiConfig:
    width: int = 1240
    height: int = 840
    fps: int = 60
    board_pixels: int = 600
    board_top: int = 120
    background: tuple[int, int, int] = (24, 26, 34)
    panel_bg: tuple[int, int, int] = (14, 14, 20)
    light_square: tuple[int, int, int] = (240, 217, 181)
    dark_square: tuple[int, int, int] = (181, 136, 99)
    player_color: tuple[int, int, int] = (120, 220, 255)
    selected_square: tuple[int, int, int] = (248, 241, 119)
    legal_target: tuple[int, int, int] = (88, 170, 96)
    npc_outline: tuple[int, int, int] = (245, 245, 245)
    text: tuple[int, int, int] = (235, 235, 235)
    muted_text: tuple[int, int, int] = (180, 185, 200)
    door_locked: tuple[int, int, int] = (90, 90, 90)
    door_open: tuple[int, int, int] = (90, 180, 120)
    dialogue_bg: tuple[int, int, int] = (10, 10, 18)
    dialogue_border: tuple[int, int, int] = (235, 235, 235)

    @property
    def square_size(self) -> int:
        return self.board_pixels // 8

    @property
    def board_left(self) -> int:
        return (self.width - self.board_pixels) // 2

    @property
    def board_rect(self) -> pygame.Rect:
        return pygame.Rect(self.board_left, self.board_top, self.board_pixels, self.board_pixels)


class PlayerSprite:
    """Top-down player sprite with smooth movement and collision rect."""

    def __init__(
        self,
        x: float,
        y: float,
        size: int = 48,
        speed: float = 4.8,
        sprite_img: pygame.Surface | None = None,
    ) -> None:
        self.x = x
        self.y = y
        self.size = size
        self.speed = speed
        self.idle_tick = random.randint(0, 119)
        self.sprite_img = (
            pygame.transform.smoothscale(sprite_img, (size, size)) if sprite_img is not None else None
        )
        self.rect = pygame.Rect(int(x), int(y), size, size)
        self._update_rect()

    def _update_rect(self) -> None:
        bob = 2 if (self.idle_tick // 20) % 2 == 0 else 0
        self.rect.topleft = (int(self.x), int(self.y) - bob)

    def set_position(self, x: float, y: float) -> None:
        self.x = x
        self.y = y
        self._update_rect()

    def update(self, keys: pygame.key.ScancodeWrapper, bounds: pygame.Rect) -> None:
        self.idle_tick = (self.idle_tick + 1) % 120
        dx = 0.0
        dy = 0.0
        if keys[pygame.K_a] or keys[pygame.K_LEFT]:
            dx -= self.speed
        if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
            dx += self.speed
        if keys[pygame.K_w] or keys[pygame.K_UP]:
            dy -= self.speed
        if keys[pygame.K_s] or keys[pygame.K_DOWN]:
            dy += self.speed

        if dx != 0.0 and dy != 0.0:
            dx *= 0.7071
            dy *= 0.7071

        self.x = max(bounds.left, min(bounds.right - self.size, self.x + dx))
        self.y = max(bounds.top, min(bounds.bottom - self.size, self.y + dy))
        self._update_rect()

    def draw(self, screen: pygame.Surface, color: tuple[int, int, int]) -> None:
        if self.sprite_img is not None:
            screen.blit(self.sprite_img, self.rect)
            return
        pygame.draw.rect(screen, color, self.rect, border_radius=10)
        eye = self.rect.inflate(-self.size * 0.62, -self.size * 0.62)
        pygame.draw.rect(screen, (20, 20, 30), eye, border_radius=6)


class NpcSprite:
    """NPC sprite with placeholder idle animation hook and optional image path."""

    def __init__(
        self,
        npc_id: str,
        x: int,
        y: int,
        color: tuple[int, int, int],
        size: int = 56,
        sprite_img: pygame.Surface | None = None,
    ) -> None:
        self.npc_id = npc_id
        self.base_x = x
        self.base_y = y
        self.color = color
        self.size = size
        self.sprite_img = (
            pygame.transform.smoothscale(sprite_img, (size, size)) if sprite_img is not None else None
        )
        self.idle_tick = random.randint(0, 119)
        self.rect = pygame.Rect(x, y, size, size)
        self._update_rect()

    def _update_rect(self) -> None:
        bob = 2 if (self.idle_tick // 20) % 2 == 0 else 0
        self.rect.topleft = (self.base_x, self.base_y - bob)

    def update(self) -> None:
        self.idle_tick = (self.idle_tick + 1) % 120
        self._update_rect()

    def draw(self, screen: pygame.Surface, outline: tuple[int, int, int]) -> None:
        if self.sprite_img is not None:
            screen.blit(self.sprite_img, self.rect)
            pygame.draw.rect(screen, outline, self.rect, width=2, border_radius=10)
            return
        pygame.draw.rect(screen, self.color, self.rect, border_radius=10)
        pygame.draw.rect(screen, outline, self.rect, width=2, border_radius=10)
        eye = self.rect.inflate(-self.size * 0.58, -self.size * 0.58)
        pygame.draw.rect(screen, (22, 22, 30), eye, border_radius=6)

    def distance_to(self, player_rect: pygame.Rect) -> float:
        return pygame.Vector2(self.rect.center).distance_to(player_rect.center)


class ChessAdventureGame:
    def __init__(self) -> None:
        pygame.init()
        self.config = UiConfig()
        self.screen = pygame.display.set_mode((self.config.width, self.config.height))
        pygame.display.set_caption("Poop")
        self.clock = pygame.time.Clock()

        self.ui_font = pygame.font.SysFont("consolas", 20)
        self.small_font = pygame.font.SysFont("consolas", 16)
        self.piece_font = pygame.font.SysFont("segoeuisymbol", int(self.config.square_size * 0.76))
        self.dialogue_font = pygame.font.SysFont("consolas", 22)
        self.banner_font = pygame.font.SysFont("consolas", 44, bold=True)
        self.loss_font = pygame.font.SysFont("consolas", 52, bold=True)
        self.use_unicode_board_pieces = False

        self.mode = GameMode.EXPLORATION
        self.previous_mode_before_dialogue = GameMode.EXPLORATION
        self.move_rule_mode = MoveRuleMode.LEGAL_ONLY
        self.hareni_elo = 1700

        self.progress = RoomProgress()
        self.room_configs = self._build_room_configs()
        self.npcs_by_room = self._build_room_npcs()
        self.entry_dialogue_seen: set[int] = set()

        self.player = PlayerSprite(140, 560, sprite_img=self._load_player_sprite())
        self.active_door_hint: str | None = None
        self.show_interact_hint = False

        self.board = chess.Board()
        self.selected_square: chess.Square | None = None
        self.player_color = chess.WHITE
        self.opponent_color = chess.BLACK
        self.opponent_move_cooldown = 0
        self.neil_elo = 2400
        self.confusion_blunder_threshold_cp = 120
        self.chess_result_message = "Play as White. Defeat Neil to unlock the exit."
        self.pre_fight_dialogue_played = False
        self.post_win_dialogue_played = False
        self.match_is_finished = False

        self.dialogue_queue: list[DialogueLine] = []
        self.dialogue_index = 0

        self.dialogue_scripts = self._build_dialogue_scripts()
        self.portrait_colors = self._build_portrait_colors()
        self.power_definitions = self._build_power_definitions()
        self.save_path = Path("save_state.json")
        self.save_state = self._show_loading_menu()
        self.pending_unlock_npc: str | None = None
        self.unlock_cost_by_npc: dict[str, int] = {
            "pragya_locked": 5,
            "isha_locked": 25,
            "gounder_locked": 50,
        }
        self.npc_display_name: dict[str, str] = {
            "pragya_locked": "Pragya",
            "isha_locked": "Isha",
            "gounder_locked": "Gounder",
        }
        self.svg_cache_key: tuple[
            str,
            int | None,
            tuple[int, ...],
            str,
            tuple[tuple[int, str], ...],
            tuple[tuple[int, tuple[str, ...]], ...],
            tuple[str, ...],
            bool,
            bool,
        ] | None = None
        self.svg_board_surface: pygame.Surface | None = None
        self.svg_piece_surfaces = self._load_piece_surfaces()
        self.empowered_pawns: dict[chess.Square, set[str]] = {}
        self.active_global_powers: set[str] = set()
        self.next_turn_global_powers: set[str] = set()
        self.paralyzed_enemy_pieces: dict[chess.Square, int] = {}
        self.death_foretold_targets: dict[chess.Square, int] = {}
        self.dodge_ready_squares: set[chess.Square] = set()
        self.character_powers_taken_this_match: dict[str, int] = {}
        self.active_help_tiles: dict[chess.Square, str] = {}
        self.player_turn_index = 0
        self.help_tiles_rolled_this_turn = False
        self.active_help_characters_this_turn: set[str] = set()
        self.pending_power_offer_ids: list[str] = []
        self.pending_power_character_id: str | None = None
        self.awaiting_power_choice = False
        self.awaiting_power_target_power_id: str | None = None
        self.awaiting_power_sacrifice_power_id: str | None = None
        self.pending_power_target_square: chess.Square | None = None
        self.awaiting_pawn_exchange_side: str | None = None
        self.open_power_choice_after_dialogue = False
        self.awaiting_shop_choice = False
        self.open_shop_after_dialogue = False
        self.pending_shop_character_id: str | None = None
        self.shop_power_scroll = 0
        self.power_sidebar_scroll = 0
        self.awaiting_unlock_choice = False
        self.open_unlock_choice_after_dialogue = False
        self.awaiting_practice_choice = False
        self.open_practice_choice_after_dialogue = False
        self.practice_mode = False
        self.awaiting_return_to_lobby_confirm = False
        self.awaiting_loss_ack = False
        self.loss_screen_started_ms = 0
        self.opponent_skip_turns = 0
        self.player_skip_turns = 0
        self.opponent_confused_next_move = False
        self.takeback_available = 0
        self.gamer_god_visible_this_turn = False
        self.gamer_god_hint_moves: list[chess.Move] = []
        self.stockfish_path = self._find_stockfish_path()
        self.stockfish_top_move_cache: dict[str, list[chess.Move]] = {}
        self.stockfish_eval_cache: dict[str, int | None] = {}
        self.show_intro_neil = False
        self.portrait_cache: dict[str, pygame.Surface | None] = {}
        self.character_face_cache: dict[tuple[str, int], pygame.Surface | None] = {}
        self.pet_scene_surface = self._load_pet_scene_surface()
        self.open_pet_scene_after_dialogue = False
        self.state_snapshot_stack: list[dict[str, object]] = []

        self._position_player_for_room(self.progress.current_room_index)
        if not self.save_state.intro_seen:
            self.save_state.intro_seen = True
            self._save_state()
            self.show_intro_neil = True
            self.start_dialogue(self.dialogue_scripts["intro_cutscene"])
        else:
            self._trigger_room_entry_dialogue_if_needed()

    def _show_loading_menu(self) -> SaveState:
        has_save = self.save_path.exists()
        mode = "select"

        title_font = pygame.font.SysFont("consolas", 38, bold=True)
        menu_font = pygame.font.SysFont("consolas", 26, bold=True)
        info_font = pygame.font.SysFont("consolas", 18)

        load_rect = pygame.Rect(self.config.width // 2 - 170, 290, 340, 60)
        new_rect = pygame.Rect(self.config.width // 2 - 170, 370, 340, 60)
        yes_rect = pygame.Rect(self.config.width // 2 - 170, 430, 160, 56)
        no_rect = pygame.Rect(self.config.width // 2 + 10, 430, 160, 56)

        while True:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    raise SystemExit
                if event.type == pygame.KEYDOWN:
                    if mode == "select":
                        if event.key == pygame.K_l:
                            return self._load_save_state()
                        if event.key == pygame.K_n:
                            if has_save:
                                mode = "confirm_new"
                            else:
                                return SaveState()
                    else:
                        if event.key == pygame.K_y:
                            self._delete_save_if_exists()
                            return SaveState()
                        if event.key in (pygame.K_n, pygame.K_ESCAPE):
                            mode = "select"
                if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if mode == "select":
                        if load_rect.collidepoint(event.pos):
                            return self._load_save_state()
                        if new_rect.collidepoint(event.pos):
                            if has_save:
                                mode = "confirm_new"
                            else:
                                return SaveState()
                    else:
                        if yes_rect.collidepoint(event.pos):
                            self._delete_save_if_exists()
                            return SaveState()
                        if no_rect.collidepoint(event.pos):
                            mode = "select"

            self.screen.fill((16, 18, 26))
            title = title_font.render("cool game", True, self.config.text)
            self.screen.blit(title, (self.config.width // 2 - title.get_width() // 2, 130))

            if mode == "select":
                pygame.draw.rect(self.screen, (72, 112, 172), load_rect, border_radius=10)
                pygame.draw.rect(self.screen, (92, 162, 118), new_rect, border_radius=10)
                pygame.draw.rect(self.screen, (230, 230, 230), load_rect, width=2, border_radius=10)
                pygame.draw.rect(self.screen, (230, 230, 230), new_rect, width=2, border_radius=10)

                load_text = menu_font.render("Load Game", True, self.config.text)
                new_text = menu_font.render("Start New", True, self.config.text)
                self.screen.blit(
                    load_text,
                    (load_rect.centerx - load_text.get_width() // 2, load_rect.centery - load_text.get_height() // 2),
                )
                self.screen.blit(
                    new_text,
                    (new_rect.centerx - new_text.get_width() // 2, new_rect.centery - new_text.get_height() // 2),
                )

                save_msg = "Save found: yes" if has_save else "Save found: no (load starts fresh)"
                hint = info_font.render("Press L to load, N for new game", True, self.config.muted_text)
                save_info = info_font.render(save_msg, True, self.config.muted_text)
                self.screen.blit(save_info, (self.config.width // 2 - save_info.get_width() // 2, 455))
                self.screen.blit(hint, (self.config.width // 2 - hint.get_width() // 2, 478))
            else:
                warn = menu_font.render("Start New will delete existing save.", True, (250, 220, 120))
                sub = info_font.render("Continue?", True, self.config.text)
                self.screen.blit(warn, (self.config.width // 2 - warn.get_width() // 2, 330))
                self.screen.blit(sub, (self.config.width // 2 - sub.get_width() // 2, 365))

                pygame.draw.rect(self.screen, (170, 90, 90), yes_rect, border_radius=10)
                pygame.draw.rect(self.screen, (90, 120, 160), no_rect, border_radius=10)
                pygame.draw.rect(self.screen, (230, 230, 230), yes_rect, width=2, border_radius=10)
                pygame.draw.rect(self.screen, (230, 230, 230), no_rect, width=2, border_radius=10)

                yes_text = menu_font.render("Delete", True, self.config.text)
                no_text = menu_font.render("Cancel", True, self.config.text)
                self.screen.blit(
                    yes_text,
                    (yes_rect.centerx - yes_text.get_width() // 2, yes_rect.centery - yes_text.get_height() // 2),
                )
                self.screen.blit(
                    no_text,
                    (no_rect.centerx - no_text.get_width() // 2, no_rect.centery - no_text.get_height() // 2),
                )

                hint = info_font.render("Press Y to delete, N/Esc to cancel", True, self.config.muted_text)
                self.screen.blit(hint, (self.config.width // 2 - hint.get_width() // 2, 500))

            pygame.display.flip()
            self.clock.tick(self.config.fps)

    def _delete_save_if_exists(self) -> None:
        try:
            if self.save_path.exists():
                self.save_path.unlink()
        except OSError:
            pass

    def _load_player_sprite(self) -> pygame.Surface | None:
        sprite_path = Path("assets") / "rhea happy.png"
        if not sprite_path.exists():
            return None
        try:
            return pygame.image.load(str(sprite_path)).convert_alpha()
        except pygame.error:
            return None

    def _load_pet_scene_surface(self) -> pygame.Surface | None:
        sprite_path = Path("assets") / "rhea and circe.png"
        if not sprite_path.exists():
            return None
        try:
            return pygame.image.load(str(sprite_path)).convert_alpha()
        except pygame.error:
            return None

    def _load_npc_sprite(self, npc_id: str) -> pygame.Surface | None:
        sprite_map = {
            "circe": Path("assets") / "circe.png",
            "rival": Path("assets") / "neil happy.png",
            "intro_neil": Path("assets") / "neil happy.png",
            "pragya_locked": Path("assets") / "pragya.png",
            "isha_locked": Path("assets") / "isha.png",
            "gounder_locked": Path("assets") / "gounder.png",
        }
        sprite_path = sprite_map.get(npc_id)
        if sprite_path is None or not sprite_path.exists():
            return None
        try:
            return pygame.image.load(str(sprite_path)).convert_alpha()
        except pygame.error:
            return None

    def _character_face_surface(self, character_id: str, size: int) -> pygame.Surface | None:
        cache_key = (character_id, size)
        if cache_key in self.character_face_cache:
            return self.character_face_cache[cache_key]
        npc_lookup = {
            "pragya": "pragya_locked",
            "isha": "isha_locked",
            "gounder": "gounder_locked",
        }
        npc_id = npc_lookup.get(character_id)
        if npc_id is None:
            return None
        surface = self._load_npc_sprite(npc_id)
        if surface is None:
            return None
        scaled = pygame.transform.smoothscale(surface, (size, size))
        self.character_face_cache[cache_key] = scaled
        return scaled

    def _speaker_sprite_surface(self, key: str | None) -> pygame.Surface | None:
        if key is None:
            return None
        if key in self.portrait_cache:
            return self.portrait_cache[key]

        surface: pygame.Surface | None = None
        if key in {"Rhea", "You"}:
            surface = self._load_player_sprite()
        else:
            npc_lookup = {
                "Neil": "rival",
                "Circe": "circe",
                "Pragya": "pragya_locked",
                "Isha": "isha_locked",
                "Gounder": "gounder_locked",
            }
            npc_id = npc_lookup.get(key)
            if npc_id is not None:
                surface = self._load_npc_sprite(npc_id)
        if surface is not None:
            surface = pygame.transform.smoothscale(surface, (72, 72))
        self.portrait_cache[key] = surface
        return surface

    def _load_svg_surface(self, svg_text: str, name: str) -> pygame.Surface | None:
        if cairosvg is not None:
            try:
                png_bytes = cairosvg.svg2png(bytestring=svg_text.encode("utf-8"))
                return pygame.image.load(io.BytesIO(png_bytes), f"{name}.png").convert_alpha()
            except Exception:
                pass
        try:
            return pygame.image.load(io.BytesIO(svg_text.encode("utf-8")), name).convert_alpha()
        except pygame.error:
            return None

    def _load_piece_surfaces(self) -> dict[tuple[int, bool], pygame.Surface]:
        surfaces: dict[tuple[int, bool], pygame.Surface] = {}
        base_target_size = max(10, int(self.config.square_size * 0.9))
        piece_name_by_type = {
            chess.PAWN: "pawn",
            chess.KNIGHT: "knight",
            chess.BISHOP: "bishop",
            chess.ROOK: "rook",
            chess.QUEEN: "queen",
            chess.KING: "king",
        }
        for color in (chess.WHITE, chess.BLACK):
            for piece_type in chess.PIECE_TYPES:
                color_name = "white" if color == chess.WHITE else "black"
                piece_name = piece_name_by_type[piece_type]
                piece_path = Path("assets") / "pieces-basic-png" / f"{color_name}-{piece_name}.png"
                if not piece_path.exists():
                    continue
                try:
                    surf = pygame.image.load(str(piece_path)).convert_alpha()
                except pygame.error:
                    continue
                if surf is None:
                    continue
                opaque = surf.get_bounding_rect(min_alpha=1)
                if opaque.width > 0 and opaque.height > 0:
                    surf = surf.subsurface(opaque).copy()
                target_size = base_target_size
                if piece_type == chess.PAWN:
                    target_size = max(10, int(base_target_size * 0.86))
                surf = pygame.transform.smoothscale(surf, (target_size, target_size))
                surfaces[(piece_type, color)] = surf
        return surfaces

    def _load_save_state(self) -> SaveState:
        if not self.save_path.exists():
            return SaveState()
        try:
            data = json.loads(self.save_path.read_text(encoding="utf-8"))
            points_value = data.get("points")
            if points_value is None:
                # Backward compatibility: old saves used chess_entries as top-right counter.
                points_value = data.get("chess_entries", 0)
            return SaveState(
                points=int(points_value),
                pragya_unlocked=bool(data.get("pragya_unlocked", False)),
                isha_unlocked=bool(data.get("isha_unlocked", False)),
                gounder_unlocked=bool(data.get("gounder_unlocked", False)),
                pragya_extra_spawns=int(data.get("pragya_extra_spawns", 0)),
                isha_extra_capacity=int(data.get("isha_extra_capacity", 0)),
                gounder_extra_capacity=int(data.get("gounder_extra_capacity", 0)),
                pragya_spawn_rate_boosts=int(data.get("pragya_spawn_rate_boosts", 0)),
                isha_spawn_rate_boosts=int(data.get("isha_spawn_rate_boosts", 0)),
                gounder_spawn_rate_boosts=int(data.get("gounder_spawn_rate_boosts", 0)),
                chess_entries=int(data.get("chess_entries", 0)),
                neil_attempts=int(data.get("neil_attempts", data.get("chess_entries", 0))),
                intro_seen=bool(data.get("intro_seen", False)),
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            return SaveState()

    def _save_state(self) -> None:
        payload = {
            "points": self.save_state.points,
            "pragya_unlocked": self.save_state.pragya_unlocked,
            "isha_unlocked": self.save_state.isha_unlocked,
            "gounder_unlocked": self.save_state.gounder_unlocked,
            "pragya_extra_spawns": self.save_state.pragya_extra_spawns,
            "isha_extra_capacity": self.save_state.isha_extra_capacity,
            "gounder_extra_capacity": self.save_state.gounder_extra_capacity,
            "pragya_spawn_rate_boosts": self.save_state.pragya_spawn_rate_boosts,
            "isha_spawn_rate_boosts": self.save_state.isha_spawn_rate_boosts,
            "gounder_spawn_rate_boosts": self.save_state.gounder_spawn_rate_boosts,
            "chess_entries": self.save_state.chess_entries,
            "neil_attempts": self.save_state.neil_attempts,
            "intro_seen": self.save_state.intro_seen,
        }
        self.save_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _build_portrait_colors(self) -> dict[str, tuple[int, int, int]]:
        return {
            "???": (0, 0, 0),
            "Circe": (190, 150, 255),
            "Neil": (232, 108, 108),
            "Pragya": (140, 190, 255),
            "Isha": (234, 164, 100),
            "Gounder": (132, 212, 230),
            "Friend": (122, 214, 148),
            "You": self.config.player_color,
            "Rhea": self.config.player_color,
        }

    def _character_color(self, character_id: str) -> str:
        colors = {
            "pragya": "#f08cd6",
            "isha": "#6c5ce7",
            "gounder": "#5fcd7a",
        }
        return colors.get(character_id, "#f08cd6")

    def _character_display_name(self, character_id: str) -> str:
        names = {
            "pragya": "Pragya",
            "isha": "Isha",
            "gounder": "Gounder",
        }
        return names.get(character_id, character_id.title())

    def _power_ids_for_character(self, character_id: str) -> list[str]:
        return [power_id for power_id, power in self.power_definitions.items() if power.character_id == character_id]

    def _character_is_unlocked(self, character_id: str) -> bool:
        if character_id == "pragya":
            return self.save_state.pragya_unlocked
        if character_id == "isha":
            return self.save_state.isha_unlocked
        if character_id == "gounder":
            return self.save_state.gounder_unlocked
        return False

    def _character_power_capacity(self, character_id: str) -> int:
        if character_id == "pragya":
            return min(10, 1 + self.save_state.pragya_extra_spawns)
        if character_id == "isha":
            return min(10, 1 + self.save_state.isha_extra_capacity)
        if character_id == "gounder":
            return min(10, 1 + self.save_state.gounder_extra_capacity)
        return 1

    def _character_power_count(self, character_id: str) -> int:
        return self.character_powers_taken_this_match.get(character_id, 0)

    def _character_can_receive_more_powers(self, character_id: str) -> bool:
        power_ids = self._power_ids_for_character(character_id)
        if not power_ids:
            return False
        return self._character_power_count(character_id) < self._character_power_capacity(character_id)

    def _character_spawn_rate_boost_count(self, character_id: str) -> int:
        if character_id == "pragya":
            return self.save_state.pragya_spawn_rate_boosts
        if character_id == "isha":
            return self.save_state.isha_spawn_rate_boosts
        if character_id == "gounder":
            return self.save_state.gounder_spawn_rate_boosts
        return 0

    def _character_spawn_start_move(self, character_id: str) -> int:
        if character_id == "isha":
            return 5
        if character_id == "gounder":
            return 10
        return 1

    def _character_can_spawn_on_current_turn(self, character_id: str) -> bool:
        current_move_number = self.player_turn_index + 1
        return current_move_number >= self._character_spawn_start_move(character_id)

    def _character_spawn_chance(self, character_id: str) -> float:
        return min(0.8, 0.10 + 0.10 * self._character_spawn_rate_boost_count(character_id))

    def _character_spawn_rate_shop_sold_out(self, character_id: str) -> bool:
        return self._character_spawn_rate_boost_count(character_id) >= 7

    def _spawnable_characters(self) -> list[str]:
        return [
            character_id
            for character_id in ("pragya", "isha", "gounder")
            if (
                self._character_is_unlocked(character_id)
                and self._character_can_receive_more_powers(character_id)
                and self._character_can_spawn_on_current_turn(character_id)
            )
        ]

    def _build_power_definitions(self) -> dict[str, PowerDefinition]:
        return {
            "capture_forward": PowerDefinition(
                power_id="capture_forward",
                character_id="pragya",
                name="Forward Capture + Side Step",
                description="One pawn may capture one square straight forward and move one square left or right.",
                target_prompt="Select 1 pawn for forward capture and side step.",
                short_label="Capture forward + move sideways",
                target_kind="pawn",
            ),
            "summon_pawn": PowerDefinition(
                power_id="summon_pawn",
                character_id="pragya",
                name="Summon Pawn",
                description="Place a new pawn on any empty square.",
                target_prompt="Select any empty square for the new pawn.",
                short_label="Summon Pawn",
                target_kind="empty_square",
            ),
            "paralyze": PowerDefinition(
                power_id="paralyze",
                character_id="pragya",
                name="Paralyze",
                description="Choose an enemy piece. It cannot move for 2 turns.",
                target_prompt="Select 1 enemy piece to paralyze.",
                short_label="Paralyze",
                target_kind="enemy_piece",
            ),
            "double": PowerDefinition(
                power_id="double",
                character_id="isha",
                name="Double",
                description="Move again now, but sacrifice a pawn of your choosing.",
                target_prompt="Select 1 pawn to sacrifice for Double.",
                short_label="Double",
                target_kind="pawn",
            ),
            "pawn_exchange": PowerDefinition(
                power_id="pawn_exchange",
                character_id="isha",
                name="Pawn Exchange",
                description="Choose one of your pawns and one enemy pawn to remove if possible.",
                target_prompt="Select one of your pawns to remove.",
                short_label="Pawn Exchange",
            ),
            "dragon_knights": PowerDefinition(
                power_id="dragon_knights",
                character_id="isha",
                name="Dragon Knights",
                description="Choose a knight to move like a bishop too, then sacrifice a pawn.",
                target_prompt="Select 1 knight for Dragon Knights.",
                short_label="Dragon Knights",
                target_kind="knight",
            ),
            "dragon_queen": PowerDefinition(
                power_id="dragon_queen",
                character_id="isha",
                name="Dragon Queen",
                description="Choose a queen to move like a knight too, then sacrifice a minor or major piece.",
                target_prompt="Select 1 queen for Dragon Queen.",
                short_label="Dragon Queen",
                target_kind="queen",
            ),
            "death_foretold": PowerDefinition(
                power_id="death_foretold",
                character_id="isha",
                name="Doomed",
                description="Choose any piece other than a king or queen. In 5 turns it will be removed.",
                target_prompt="Select 1 non-king, non-queen piece.",
                short_label="Doomed",
                target_kind="non_king_queen_piece",
            ),
            "underpromote": PowerDefinition(
                power_id="underpromote",
                character_id="pragya",
                name="Underpromote",
                description="Choose an enemy queen, rook, knight, or bishop and demote it by tier.",
                target_prompt="Select 1 enemy queen, rook, knight, or bishop.",
                short_label="Underpromote",
                target_kind="enemy_underpromotable",
            ),
            "gamer_god": PowerDefinition(
                power_id="gamer_god",
                character_id="gounder",
                name="Gamer God",
                description="See the top 3 recommended engine moves next turn.",
                target_prompt=None,
                short_label="Gamer God",
            ),
            "future_sight": PowerDefinition(
                power_id="future_sight",
                character_id="gounder",
                name="Future Sight",
                description="See the evaluation bar.",
                target_prompt=None,
                short_label="Future Sight",
            ),
            "takeback": PowerDefinition(
                power_id="takeback",
                character_id="gounder",
                name="Takeback",
                description="Get one takeback use.",
                target_prompt=None,
                short_label="Takeback",
            ),
            "confusion": PowerDefinition(
                power_id="confusion",
                character_id="gounder",
                name="Confusion",
                description="On the next move, your opponent plays much worse.",
                target_prompt=None,
                short_label="Confusion",
            ),
            "dodge": PowerDefinition(
                power_id="dodge",
                character_id="gounder",
                name="Dodge",
                description="Choose one of your pieces. The next time it is captured, it jumps to a random empty adjacent square.",
                target_prompt="Select 1 of your pieces for Dodge.",
                short_label="Dodge",
                target_kind="own_piece",
            ),
            "king_power": PowerDefinition(
                power_id="king_power",
                character_id="gounder",
                name="King",
                description="Choose your king. It can move like a queen.",
                target_prompt="Select your king.",
                short_label="King",
                target_kind="king",
            ),
        }

    def _find_stockfish_path(self) -> str | None:
        env_override = os.environ.get("STOCKFISH_PATH")
        if env_override:
            override_path = Path(env_override).expanduser()
            if override_path.exists():
                return str(override_path)

        project_root = Path.cwd()
        candidates: list[Path] = []

        if sys.platform.startswith("win"):
            candidates.extend(
                [
                    project_root / "stockfish.exe",
                    project_root / "engines" / "windows" / "stockfish.exe",
                ]
            )
        elif sys.platform == "darwin":
            machine = platform.machine().lower()
            if machine in ("arm64", "aarch64"):
                candidates.extend(
                    [
                        project_root / "engines" / "macos" / "stockfish-macos-arm64",
                        project_root / "stockfish-macos",
                        project_root / "engines" / "macos" / "stockfish",
                        project_root / "engines" / "macos" / "stockfish-macos",
                    ]
                )
            else:
                candidates.extend(
                    [
                        project_root / "engines" / "macos" / "stockfish-macos-x86-64",
                        project_root / "stockfish-macos",
                        project_root / "engines" / "macos" / "stockfish",
                        project_root / "engines" / "macos" / "stockfish-macos",
                    ]
                )
        else:
            candidates.extend(
                [
                    project_root / "stockfish",
                    project_root / "engines" / "linux" / "stockfish",
                ]
            )

        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

        configured = shutil.which("stockfish") or shutil.which("stockfish.exe")
        if configured is not None:
            return configured
        return None

    def _build_dialogue_scripts(self) -> dict[str, list[DialogueLine]]:
        return {
            "intro_cutscene": [
                DialogueLine("Rhea", "Oww.. where am I?"),
                DialogueLine("Neil", "Hehe..."),
                DialogueLine("Rhea", "?? Where are we, am I dreaming."),
                DialogueLine("Neil", "Nope. This is my birthday present to you, we can play chess!"),
                DialogueLine("Rhea", "I already told you I don't want to play chess"),
                DialogueLine("Neil", "Well..."),
                DialogueLine("Neil", "Too bad. I'm trapping you in this game so you have to play with me."),
                DialogueLine("Neil", "You can't leave until you win. Ahahahaha"),
                DialogueLine("Neil", "I'll see you in our big match."),
                DialogueLine("Rhea", "... So abusive :C"),
            ],
            "entry_chess": [
                DialogueLine("Neil", "You made it. Let's play!!"),
            ],
            "entry_post_win": [
                DialogueLine("Rhea", "Yayy I'm finally freee"),
                DialogueLine("Rhea", "But don't worry I'll keep playing with you sometimes!"),
                DialogueLine("Neil", "Yayy"),
                DialogueLine("Neil", "Happy birthday!"),
            ],
            "circe_practice_offer": [
                DialogueLine("Circe", "Meow."),
            ],
            "pragya_locked": [
                DialogueLine("???", "You need 5 points to unlock this character."),
            ],
            "pragya_unlocked": [
                DialogueLine("Pragya", "Hi Rhea <3"),
                DialogueLine("Pragya", "Please buy my wares."),
            ],
            "pragya_unlocked_now": [
                DialogueLine("Pragya", "RHEA!!"),
                DialogueLine("Pragya", "I found you, I followed your scent into here"),
                DialogueLine("Pragya", "It was a dangerous journey. But I'll help you out of here!"),
                DialogueLine("Rhea", "Woahh, I need your help I keep losing :C"),
                DialogueLine("Pragya", "Don't worry, I found some things that will help you."),
            ],
            "isha_locked": [
                DialogueLine("???", "You need 25 points to unlock this character."),
            ],
            "isha_unlocked": [
                DialogueLine("Isha", "Hola Rhea"),
            ],
            "isha_unlocked_now": [
                DialogueLine("Isha", "Rhea!! I followed Pragya's scent and found you stuck here"),
                DialogueLine("Rhea", "Woah yayy"),
                DialogueLine("Rhea", "I didn't know you guys were all so good at chess..."),
            ],
            "gounder_locked": [
                DialogueLine("???", "You need 50 points to unlock this character."),
            ],
            "gounder_unlocked": [
                DialogueLine("Gounder", "Let's power up."),
            ],
            "gounder_unlocked_now": [
                DialogueLine("Gounder", "Sup bro."),
                DialogueLine("Rhea", "Gounder?? You're here to help me too? That's so sweet."),
                DialogueLine("Gounder", "..."),
            ],
            "post_win": [
                DialogueLine("Neil", "Wow..."),
                DialogueLine("Neil", "I can't believe it's over"),
                DialogueLine("Neil", "It only took you..."),
                DialogueLine("Neil", "Now I'll have nobody to play chess with :C."),
                DialogueLine("Neil", "You can leave back to the real world using the door on the right."),
            ],
        }

    def _post_win_dialogue_lines(self) -> list[DialogueLine]:
        attempts = self.save_state.neil_attempts
        return [
            DialogueLine("Neil", "Wow..."),
            DialogueLine("Neil", "I can't believe it's over"),
            DialogueLine("Neil", f"It only took you... {attempts} attempts."),
            DialogueLine("Neil", "Now I'll have nobody to play chess with :C."),
            DialogueLine("Neil", "You can leave back to the real world using the door on the right."),
        ]

    def _build_room_configs(self) -> list[RoomConfig]:
        c = self.config
        safe_walk = pygame.Rect(40, 40, c.width - 80, c.height - 120)
        start_door = Doorway(
            rect=pygame.Rect(c.width - 82, c.height // 2 - 80, 42, 160),
            target_room=1,
            requires_unlock=False,
            label="To Chess Room",
        )
        chess_exit = Doorway(
            rect=pygame.Rect(c.width - 82, c.height // 2 - 80, 42, 160),
            target_room=2,
            requires_unlock=True,
            unlock_flag="chess_exit_unlocked",
            label="Exit (Win Required)",
        )

        return [
            RoomConfig(
                room_type=RoomType.START,
                room_name="Start Area",
                walk_bounds=safe_walk,
                doorways=(start_door,),
                npc_spawns=(
                    NpcSpawn("intro_neil", 520, c.height // 2, (210, 88, 88)),
                    NpcSpawn("circe", 180, 500, (84, 146, 235)),
                    NpcSpawn("pragya_locked", 380, 500, (20, 20, 20)),
                    NpcSpawn("isha_locked", 610, 500, (20, 20, 20)),
                    NpcSpawn("gounder_locked", 840, 500, (20, 20, 20)),
                ),
                dialogue_script_id=None,
            ),
            RoomConfig(
                room_type=RoomType.CHESS_BATTLE,
                room_name="Chess Chamber",
                walk_bounds=safe_walk,
                doorways=(chess_exit,),
                npc_spawns=(NpcSpawn("rival", c.width // 2 - 28, 36, (210, 88, 88)),),
                dialogue_script_id="entry_chess",
                chess_opponent_id="neil",
            ),
            RoomConfig(
                room_type=RoomType.POST_WIN,
                room_name="Post-Win Room",
                walk_bounds=safe_walk,
                doorways=(),
                npc_spawns=(NpcSpawn("rival", c.width // 2 - 28, 270, (210, 88, 88)),),
                dialogue_script_id="friend_chat",
            ),
        ]

    def _build_room_npcs(self) -> dict[int, list[NpcSprite]]:
        npc_map: dict[int, list[NpcSprite]] = {}
        for index, room in enumerate(self.room_configs):
            npc_map[index] = [
                NpcSprite(
                    spawn.npc_id,
                    spawn.x,
                    spawn.y,
                    spawn.color,
                    spawn.size,
                    sprite_img=self._load_npc_sprite(spawn.npc_id),
                )
                for spawn in room.npc_spawns
            ]
        return npc_map

    def _current_room(self) -> RoomConfig:
        return self.room_configs[self.progress.current_room_index]

    def _current_npcs(self) -> list[NpcSprite]:
        npcs = list(self.npcs_by_room[self.progress.current_room_index])
        if self.progress.current_room_index == 0 and self.save_state.intro_seen and not self.show_intro_neil:
            npcs = [npc for npc in npcs if npc.npc_id != "intro_neil"]
        return npcs

    def _room_entry_script_id(self, room_type: RoomType) -> str | None:
        if room_type == RoomType.CHESS_BATTLE:
            return "entry_chess"
        if room_type == RoomType.POST_WIN:
            return "entry_post_win"
        return None

    def _position_player_for_room(self, room_index: int) -> None:
        room = self.room_configs[room_index]
        if room.room_type == RoomType.START:
            self.player.set_position(86, self.config.height // 2)
        elif room.room_type == RoomType.CHESS_BATTLE:
            self.player.set_position(self.config.width // 2 - 24, self.config.board_top + self.config.board_pixels + 32)
        else:
            self.player.set_position(86, self.config.height // 2)

    def _trigger_room_entry_dialogue_if_needed(self) -> None:
        room_index = self.progress.current_room_index
        room = self._current_room()
        if self.practice_mode and room.room_type == RoomType.CHESS_BATTLE:
            return
        script_id = self._room_entry_script_id(room.room_type)
        if script_id and room_index not in self.entry_dialogue_seen:
            self.entry_dialogue_seen.add(room_index)
            self.start_dialogue(self.dialogue_scripts[script_id])

    def start_dialogue(self, lines: Iterable[DialogueLine]) -> None:
        queued = [
            DialogueLine(line.speaker, "meow meow", line.portrait_key) if line.speaker == "Circe" else line
            for line in lines
        ]
        if not queued:
            return
        if self.mode != GameMode.DIALOGUE:
            self.previous_mode_before_dialogue = self.mode
        self.mode = GameMode.DIALOGUE
        self.dialogue_queue = queued
        self.dialogue_index = 0

    def advance_dialogue(self) -> None:
        self.dialogue_index += 1
        if self.dialogue_index < len(self.dialogue_queue):
            return
        self.dialogue_queue = []
        self.dialogue_index = 0
        self.show_intro_neil = False
        self.mode = self.previous_mode_before_dialogue
        if self.open_power_choice_after_dialogue:
            self.open_power_choice_after_dialogue = False
            self.awaiting_power_choice = True
        if self.open_shop_after_dialogue:
            self.open_shop_after_dialogue = False
            self.awaiting_shop_choice = True
        if self.open_unlock_choice_after_dialogue:
            self.open_unlock_choice_after_dialogue = False
            self.awaiting_unlock_choice = True
        if self.open_practice_choice_after_dialogue:
            self.open_practice_choice_after_dialogue = False
            self.awaiting_practice_choice = True
        if self.open_pet_scene_after_dialogue:
            self.open_pet_scene_after_dialogue = False
            self.mode = GameMode.PETTING

    def _piece_point_value(self, piece: chess.Piece | None) -> int:
        if piece is None:
            return 0
        values = {
            chess.PAWN: 1,
            chess.KNIGHT: 3,
            chess.BISHOP: 3,
            chess.ROOK: 5,
            chess.QUEEN: 9,
            chess.KING: 0,
        }
        return values.get(piece.piece_type, 0)

    def _push_state_snapshot(self) -> None:
        self.state_snapshot_stack.append(
            {
                "board": self.board.copy(stack=True),
                "empowered_pawns": {square: set(power_ids) for square, power_ids in self.empowered_pawns.items()},
                "active_global_powers": set(self.active_global_powers),
                "next_turn_global_powers": set(self.next_turn_global_powers),
                "paralyzed_enemy_pieces": dict(self.paralyzed_enemy_pieces),
                "death_foretold_targets": dict(self.death_foretold_targets),
                "dodge_ready_squares": set(self.dodge_ready_squares),
                "character_powers_taken_this_match": dict(self.character_powers_taken_this_match),
                "active_help_tiles": dict(self.active_help_tiles),
                "player_turn_index": self.player_turn_index,
                "help_tiles_rolled_this_turn": self.help_tiles_rolled_this_turn,
                "active_help_characters_this_turn": set(self.active_help_characters_this_turn),
                "opponent_skip_turns": self.opponent_skip_turns,
                "player_skip_turns": self.player_skip_turns,
                "opponent_confused_next_move": self.opponent_confused_next_move,
                "gamer_god_visible_this_turn": self.gamer_god_visible_this_turn,
                "gamer_god_hint_moves": list(self.gamer_god_hint_moves),
                "chess_result_message": self.chess_result_message,
            }
        )

    def _use_takeback(self) -> bool:
        if self.takeback_available <= 0 or not self.state_snapshot_stack:
            return False
        snapshot = self.state_snapshot_stack.pop()
        self.board = snapshot["board"].copy(stack=True)
        self.empowered_pawns = {square: set(power_ids) for square, power_ids in snapshot["empowered_pawns"].items()}
        self.active_global_powers = set(snapshot["active_global_powers"])
        self.next_turn_global_powers = set(snapshot["next_turn_global_powers"])
        self.paralyzed_enemy_pieces = dict(snapshot["paralyzed_enemy_pieces"])
        self.death_foretold_targets = dict(snapshot["death_foretold_targets"])
        self.dodge_ready_squares = set(snapshot["dodge_ready_squares"])
        self.character_powers_taken_this_match = dict(snapshot["character_powers_taken_this_match"])
        self.active_help_tiles = dict(snapshot["active_help_tiles"])
        self.player_turn_index = int(snapshot["player_turn_index"])
        self.help_tiles_rolled_this_turn = bool(snapshot["help_tiles_rolled_this_turn"])
        self.active_help_characters_this_turn = set(snapshot["active_help_characters_this_turn"])
        self.opponent_skip_turns = int(snapshot["opponent_skip_turns"])
        self.player_skip_turns = int(snapshot["player_skip_turns"])
        self.opponent_confused_next_move = bool(snapshot["opponent_confused_next_move"])
        self.gamer_god_visible_this_turn = bool(snapshot["gamer_god_visible_this_turn"])
        self.gamer_god_hint_moves = list(snapshot["gamer_god_hint_moves"])
        self.chess_result_message = str(snapshot["chess_result_message"])
        self.takeback_available = max(0, self.takeback_available - 1)
        self.selected_square = None
        self.svg_cache_key = None
        self.svg_board_surface = None
        return True

    def can_apply_move(self, move: chess.Move) -> bool:
        """Single move gate for legal mode now and illegal mode later."""
        if self.move_rule_mode == MoveRuleMode.LEGAL_ONLY:
            return move in self.board.legal_moves or move in self._custom_player_moves()
        if self.move_rule_mode == MoveRuleMode.ALLOW_ILLEGAL:
            # Scaffold path for future custom illegal-move gameplay.
            return move in self.board.legal_moves or move in self._custom_player_moves()
        return False

    def mouse_to_square(self, mouse_pos: tuple[int, int]) -> chess.Square | None:
        board_rect = self.config.board_rect
        x, y = mouse_pos
        if not board_rect.collidepoint(x, y):
            return None
        col = (x - board_rect.left) // self.config.square_size
        row = (y - board_rect.top) // self.config.square_size
        rank = 7 - row
        return chess.square(col, rank)

    def square_to_screen(self, square: chess.Square) -> tuple[int, int]:
        file_index = chess.square_file(square)
        rank_index = chess.square_rank(square)
        row = 7 - rank_index
        x = self.config.board_left + file_index * self.config.square_size
        y = self.config.board_top + row * self.config.square_size
        return x, y

    def legal_targets_for(self, from_square: chess.Square | None) -> set[chess.Square]:
        if from_square is None:
            return set()
        targets: set[chess.Square] = set()
        for move in self.board.legal_moves:
            if move.from_square == from_square:
                targets.add(move.to_square)
        for move in self._custom_player_moves():
            if move.from_square == from_square:
                targets.add(move.to_square)
        return targets

    def build_move(self, from_square: chess.Square, to_square: chess.Square) -> chess.Move:
        piece = self.board.piece_at(from_square)
        if piece and piece.piece_type == chess.PAWN:
            to_rank = chess.square_rank(to_square)
            if to_rank in (0, 7):
                return chess.Move(from_square, to_square, promotion=chess.QUEEN)
        return chess.Move(from_square, to_square)

    def _custom_player_moves(self) -> dict[chess.Move, str]:
        if self.board.turn != self.player_color:
            return {}

        moves: dict[chess.Move, str] = {}
        for from_square, power_ids in self.empowered_pawns.items():
            piece = self.board.piece_at(from_square)
            if piece is None or piece.color != self.player_color:
                continue
            for power_id in power_ids:
                for move in self._custom_moves_for_power(from_square, power_id):
                    if move in self.board.legal_moves:
                        continue
                    if self._would_be_legal_after_custom_apply(move):
                        moves[move] = power_id
        return moves

    def _custom_moves_for_power(self, from_square: chess.Square, power_id: str) -> list[chess.Move]:
        if power_id == "capture_forward":
            return self._forward_capture_moves(from_square) + self._side_step_moves(from_square)
        if power_id == "dragon_knights":
            return self._dragon_knight_moves(from_square)
        if power_id == "dragon_queen":
            return self._dragon_queen_moves(from_square)
        if power_id == "king_power":
            return self._king_power_moves(from_square)
        return []

    def _forward_capture_moves(self, from_square: chess.Square) -> list[chess.Move]:
        direction = 1 if self.player_color == chess.WHITE else -1
        target_rank = chess.square_rank(from_square) + direction
        if not 0 <= target_rank <= 7:
            return []
        to_square = chess.square(chess.square_file(from_square), target_rank)
        target_piece = self.board.piece_at(to_square)
        if target_piece is None or target_piece.color == self.player_color:
            return []
        return [self.build_move(from_square, to_square)]

    def _side_step_moves(self, from_square: chess.Square) -> list[chess.Move]:
        rank_index = chess.square_rank(from_square)
        moves: list[chess.Move] = []
        for file_delta in (-1, 1):
            target_file = chess.square_file(from_square) + file_delta
            if not 0 <= target_file <= 7:
                continue
            to_square = chess.square(target_file, rank_index)
            if self.board.piece_at(to_square) is not None:
                continue
            moves.append(self.build_move(from_square, to_square))
        return moves

    def _side_capture_moves(self, from_square: chess.Square) -> list[chess.Move]:
        rank_index = chess.square_rank(from_square)
        moves: list[chess.Move] = []
        for file_delta in (-1, 1):
            target_file = chess.square_file(from_square) + file_delta
            if not 0 <= target_file <= 7:
                continue
            to_square = chess.square(target_file, rank_index)
            target_piece = self.board.piece_at(to_square)
            if target_piece is None or target_piece.color == self.player_color:
                continue
            moves.append(self.build_move(from_square, to_square))
        return moves

    def _dragon_knight_moves(self, from_square: chess.Square) -> list[chess.Move]:
        piece = self.board.piece_at(from_square)
        if piece is None or piece.piece_type != chess.KNIGHT:
            return []
        return self._bishop_like_moves(from_square)

    def _dragon_queen_moves(self, from_square: chess.Square) -> list[chess.Move]:
        piece = self.board.piece_at(from_square)
        if piece is None or piece.piece_type != chess.QUEEN:
            return []
        moves: list[chess.Move] = []
        rank_index = chess.square_rank(from_square)
        file_index = chess.square_file(from_square)
        for file_delta, rank_delta in (
            (1, 2), (2, 1), (2, -1), (1, -2),
            (-1, -2), (-2, -1), (-2, 1), (-1, 2),
        ):
            target_file = file_index + file_delta
            target_rank = rank_index + rank_delta
            if not (0 <= target_file <= 7 and 0 <= target_rank <= 7):
                continue
            to_square = chess.square(target_file, target_rank)
            target_piece = self.board.piece_at(to_square)
            if target_piece is not None and target_piece.color == self.player_color:
                continue
            moves.append(self.build_move(from_square, to_square))
        return moves

    def _king_power_moves(self, from_square: chess.Square) -> list[chess.Move]:
        piece = self.board.piece_at(from_square)
        if piece is None or piece.piece_type != chess.KING:
            return []
        moves: list[chess.Move] = []
        moves.extend(self._rook_like_moves(from_square))
        moves.extend(self._bishop_like_moves(from_square))
        return moves

    def _rook_like_moves(self, from_square: chess.Square) -> list[chess.Move]:
        moves: list[chess.Move] = []
        file_index = chess.square_file(from_square)
        rank_index = chess.square_rank(from_square)
        for file_step, rank_step in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            cur_file = file_index + file_step
            cur_rank = rank_index + rank_step
            while 0 <= cur_file <= 7 and 0 <= cur_rank <= 7:
                to_square = chess.square(cur_file, cur_rank)
                target_piece = self.board.piece_at(to_square)
                if target_piece is None:
                    moves.append(self.build_move(from_square, to_square))
                else:
                    if target_piece.color != self.player_color:
                        moves.append(self.build_move(from_square, to_square))
                    break
                cur_file += file_step
                cur_rank += rank_step
        return moves

    def _bishop_like_moves(self, from_square: chess.Square) -> list[chess.Move]:
        moves: list[chess.Move] = []
        file_index = chess.square_file(from_square)
        rank_index = chess.square_rank(from_square)
        for file_step, rank_step in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
            cur_file = file_index + file_step
            cur_rank = rank_index + rank_step
            while 0 <= cur_file <= 7 and 0 <= cur_rank <= 7:
                to_square = chess.square(cur_file, cur_rank)
                target_piece = self.board.piece_at(to_square)
                if target_piece is None:
                    moves.append(self.build_move(from_square, to_square))
                else:
                    if target_piece.color != self.player_color:
                        moves.append(self.build_move(from_square, to_square))
                    break
                cur_file += file_step
                cur_rank += rank_step
        return moves

    def _would_be_legal_after_custom_apply(self, move: chess.Move) -> bool:
        board_copy = self.board.copy(stack=False)
        moving_piece = board_copy.piece_at(move.from_square)
        if moving_piece is None:
            return False
        self._apply_custom_move_on_board(board_copy, move)
        king_square = board_copy.king(moving_piece.color)
        if king_square is None:
            return False
        return not board_copy.is_attacked_by(not moving_piece.color, king_square)

    def _apply_custom_move_on_board(self, board: chess.Board, move: chess.Move) -> None:
        piece = board.piece_at(move.from_square)
        if piece is None:
            raise ValueError("Custom move requires a moving piece.")

        board.remove_piece_at(move.from_square)
        board.remove_piece_at(move.to_square)
        promoted_piece = piece
        if move.promotion is not None:
            promoted_piece = chess.Piece(move.promotion, piece.color)
        board.set_piece_at(move.to_square, promoted_piece)
        board.turn = not board.turn
        board.ep_square = None
        board.halfmove_clock = 0
        if piece.color == chess.BLACK:
            board.fullmove_number += 1

    def _apply_move(self, move: chess.Move) -> bool:
        if move in self.board.legal_moves:
            self._push_state_snapshot()
            moving_piece = self.board.piece_at(move.from_square)
            captured_square = self._captured_square_for_legal_move(move)
            captured_piece = self.board.piece_at(captured_square) if captured_square is not None else None
            self.board.push(move)
            dodge_destination = self._maybe_resolve_dodge(captured_square, captured_piece, move.to_square)
            self._update_empowered_pawns_after_move(move, moving_piece, captured_square)
            self._update_square_effects_after_move(move, captured_square, dodge_destination)
            if moving_piece is not None:
                self._tick_end_of_move_effects(moving_piece.color)
            if moving_piece is not None and moving_piece.color == self.player_color:
                self.save_state.points += self._piece_point_value(captured_piece)
                self._save_state()
            return True
        custom_moves = self._custom_player_moves()
        if move in custom_moves:
            self._push_state_snapshot()
            moving_piece = self.board.piece_at(move.from_square)
            captured_piece = self.board.piece_at(move.to_square)
            self._apply_custom_move_on_board(self.board, move)
            dodge_destination = self._maybe_resolve_dodge(move.to_square, captured_piece, move.to_square)
            self._update_empowered_pawns_after_move(move, moving_piece, move.to_square)
            self._update_square_effects_after_move(move, move.to_square, dodge_destination)
            if moving_piece is not None:
                self._tick_end_of_move_effects(moving_piece.color)
            if moving_piece is not None and moving_piece.color == self.player_color:
                self.save_state.points += self._piece_point_value(captured_piece)
                self._save_state()
            if captured_piece is not None and captured_piece.piece_type == chess.KING:
                self._complete_player_victory("Victory! Rhea captured the enemy king and unlocked the exit.")
            return True
        return False

    def _captured_square_for_legal_move(self, move: chess.Move) -> chess.Square | None:
        if self.board.is_en_passant(move):
            return chess.square(chess.square_file(move.to_square), chess.square_rank(move.from_square))
        if self.board.piece_at(move.to_square) is not None:
            return move.to_square
        return None

    def _update_empowered_pawns_after_move(
        self,
        move: chess.Move,
        moving_piece: chess.Piece | None,
        captured_square: chess.Square | None,
    ) -> None:
        moved_powers = self.empowered_pawns.pop(move.from_square, set())
        if captured_square is not None:
            self.empowered_pawns.pop(captured_square, None)
        if (
            moved_powers
            and moving_piece is not None
            and moving_piece.color == self.player_color
        ):
            self.empowered_pawns[move.to_square] = set(moved_powers)

    def _update_square_effects_after_move(
        self,
        move: chess.Move,
        captured_square: chess.Square | None,
        dodge_destination: chess.Square | None,
    ) -> None:
        if move.from_square in self.paralyzed_enemy_pieces:
            turns = self.paralyzed_enemy_pieces.pop(move.from_square)
            self.paralyzed_enemy_pieces[move.to_square] = turns
        if captured_square is not None and captured_square != dodge_destination:
            self.paralyzed_enemy_pieces.pop(captured_square, None)

        if move.from_square in self.death_foretold_targets:
            turns = self.death_foretold_targets.pop(move.from_square)
            self.death_foretold_targets[move.to_square] = turns
        if captured_square is not None and captured_square != dodge_destination:
            self.death_foretold_targets.pop(captured_square, None)

        if move.from_square in self.dodge_ready_squares:
            self.dodge_ready_squares.discard(move.from_square)
            self.dodge_ready_squares.add(move.to_square)
        if captured_square is not None:
            self.dodge_ready_squares.discard(captured_square)
        if dodge_destination is not None:
            self.dodge_ready_squares.add(dodge_destination)

    def _maybe_resolve_dodge(
        self,
        captured_square: chess.Square | None,
        captured_piece: chess.Piece | None,
        blocked_square: chess.Square,
    ) -> chess.Square | None:
        if captured_square is None or captured_piece is None or captured_square not in self.dodge_ready_squares:
            return None
        options = self._adjacent_empty_squares(captured_square, {blocked_square})
        print(
            f"[Dodge] Trigger on {chess.square_name(captured_square)}. "
            f"Adjacent options: {[chess.square_name(sq) for sq in options]}"
        )
        if not options:
            options = [
                square
                for square in chess.SQUARES
                if square != blocked_square and self.board.piece_at(square) is None
            ]
            print(
                f"[Dodge] No adjacent escape squares found; "
                f"falling back to any empty square: {[chess.square_name(sq) for sq in options[:12]]}"
            )
        if not options:
            self.dodge_ready_squares.discard(captured_square)
            return None
        destination = random.choice(options)
        self.board.set_piece_at(destination, captured_piece)
        self.dodge_ready_squares.discard(captured_square)
        print(f"[Dodge] Moved captured piece to {chess.square_name(destination)}")
        return destination

    def _tick_end_of_move_effects(self, moved_color: bool) -> None:
        updated_dooms: dict[chess.Square, int] = {}
        for square, turns in self.death_foretold_targets.items():
            remaining = turns - 1
            if remaining <= 0:
                self.board.remove_piece_at(square)
                self.empowered_pawns.pop(square, None)
                self.dodge_ready_squares.discard(square)
                self.paralyzed_enemy_pieces.pop(square, None)
                continue
            updated_dooms[square] = remaining
        self.death_foretold_targets = updated_dooms

        if moved_color == self.opponent_color:
            updated_paralysis: dict[chess.Square, int] = {}
            for square, turns in self.paralyzed_enemy_pieces.items():
                remaining = turns - 1
                if remaining > 0:
                    updated_paralysis[square] = remaining
            self.paralyzed_enemy_pieces = updated_paralysis

    def _clear_expired_piece_powers(self) -> None:
        stale_squares = [
            square
            for square, power_ids in self.empowered_pawns.items()
            if self.board.piece_at(square) is None or not power_ids
        ]
        for square in stale_squares:
            self.empowered_pawns.pop(square, None)

    def _top_stockfish_moves(self, board: chess.Board, top_n: int = 5) -> list[chess.Move]:
        if self.stockfish_path is None:
            print("[Stockfish] Binary not found on PATH or project root.")
            return []

        cache_key = f"{board.fen()}|{top_n}"
        if cache_key in self.stockfish_top_move_cache:
            cached_moves = self.stockfish_top_move_cache[cache_key]
            print(f"[Stockfish] Using cached top moves: {[move.uci() for move in cached_moves]}")
            return self.stockfish_top_move_cache[cache_key]

        legal_moves = list(board.legal_moves)
        if not legal_moves:
            return []

        try:
            with chess.engine.SimpleEngine.popen_uci(self.stockfish_path) as engine:
                try:
                    engine.configure({"UCI_LimitStrength": False, "Skill Level": 20})
                except chess.engine.EngineError:
                    pass
                info = engine.analyse(
                    board,
                    chess.engine.Limit(depth=12),
                    multipv=min(top_n, len(legal_moves)),
                )
        except (FileNotFoundError, chess.engine.EngineError, OSError):
            print(f"[Stockfish] Failed to analyse position with binary: {self.stockfish_path}")
            return []

        infos = info if isinstance(info, list) else [info]
        top_moves: list[chess.Move] = []
        for line in infos:
            pv = line.get("pv")
            if not pv:
                continue
            move = pv[0]
            if move in legal_moves and move not in top_moves:
                top_moves.append(move)

        self.stockfish_top_move_cache[cache_key] = top_moves
        print(f"[Stockfish] Analysed top moves: {[move.uci() for move in top_moves]}")
        return top_moves

    def _stockfish_eval(self, board: chess.Board) -> int | None:
        if self.stockfish_path is None:
            return None
        cache_key = board.fen()
        if cache_key in self.stockfish_eval_cache:
            return self.stockfish_eval_cache[cache_key]
        try:
            with chess.engine.SimpleEngine.popen_uci(self.stockfish_path) as engine:
                try:
                    engine.configure({"UCI_LimitStrength": False, "Skill Level": 20})
                except chess.engine.EngineError:
                    pass
                info = engine.analyse(board, chess.engine.Limit(depth=10))
        except (FileNotFoundError, chess.engine.EngineError, OSError):
            return None

        score = info.get("score")
        if score is None:
            return None
        value = score.pov(self.player_color).score(mate_score=10000)
        self.stockfish_eval_cache[cache_key] = value
        return value

    def _engine_play_move(self, board: chess.Board, rating: int) -> chess.Move | None:
        if self.stockfish_path is None:
            return None
        try:
            with chess.engine.SimpleEngine.popen_uci(self.stockfish_path) as engine:
                try:
                    engine.configure({"UCI_LimitStrength": True, "UCI_Elo": rating})
                except chess.engine.EngineError:
                    pass
                result = engine.play(board, chess.engine.Limit(depth=10))
                return result.move
        except (FileNotFoundError, chess.engine.EngineError, OSError):
            return None

    def _engine_confusion_blunder_move(self, board: chess.Board, legal_moves: list[chess.Move]) -> chess.Move | None:
        if self.stockfish_path is None or not legal_moves:
            return None
        try:
            with chess.engine.SimpleEngine.popen_uci(self.stockfish_path) as engine:
                try:
                    engine.configure({"UCI_LimitStrength": False, "Skill Level": 20})
                except chess.engine.EngineError:
                    pass

                best_info = engine.analyse(board, chess.engine.Limit(depth=10))
                best_score = best_info.get("score")
                if best_score is None:
                    return None
                best_cp = best_score.pov(self.opponent_color).score(mate_score=10000)
                if best_cp is None:
                    return None

                candidates: list[tuple[int, chess.Move]] = []
                all_scored: list[tuple[int, chess.Move]] = []
                for move in legal_moves:
                    board_copy = board.copy(stack=False)
                    board_copy.push(move)
                    info = engine.analyse(board_copy, chess.engine.Limit(depth=8))
                    score = info.get("score")
                    if score is None:
                        continue
                    move_cp = score.pov(self.opponent_color).score(mate_score=10000)
                    if move_cp is None:
                        continue
                    drop = best_cp - move_cp
                    all_scored.append((drop, move))
                    if drop >= self.confusion_blunder_threshold_cp:
                        candidates.append((drop, move))

                if candidates:
                    candidates.sort(key=lambda item: item[0], reverse=True)
                    chosen = random.choice([move for _, move in candidates[: min(3, len(candidates))]])
                    print(f"[Confusion] Forced blunder move: {chosen.uci()} with drop >= {self.confusion_blunder_threshold_cp}cp")
                    return chosen

                if all_scored:
                    all_scored.sort(key=lambda item: item[0], reverse=True)
                    chosen = all_scored[0][1]
                    print(f"[Confusion] No threshold blunder found; using largest drop move: {chosen.uci()}")
                    return chosen
        except (FileNotFoundError, chess.engine.EngineError, OSError):
            return None
        return None

    def _choose_help_tile_square(self) -> chess.Square | None:
        candidate_moves = self._top_stockfish_moves(self.board, top_n=5)
        if not candidate_moves:
            print("[HelpTile] No candidate move available for help tile.")
            return None
        selected_move = random.choice(candidate_moves)
        print(f"[HelpTile] Selected Stockfish move for help tile: {selected_move.uci()}")
        return selected_move.to_square

    def _roll_help_tile_characters_for_turn(self) -> list[str]:
        candidates = self._spawnable_characters()
        if not candidates:
            return []
        if self.player_turn_index == 0:
            selected = random.choice(candidates)
            print(f"[HelpTile] Turn 1 guaranteed spawn: {selected}")
            return [selected]
        rolled: list[str] = []
        for character_id in candidates:
            spawn_chance = self._character_spawn_chance(character_id)
            if random.random() <= spawn_chance:
                rolled.append(character_id)
        print(
            f"[HelpTile] Rolled spawns for turn {self.player_turn_index + 1}: {rolled} "
            f"with chances { {char_id: self._character_spawn_chance(char_id) for char_id in candidates} }"
        )
        return rolled

    def _schedule_help_tiles_for_turn(self) -> None:
        if self.mode != GameMode.CHESS or self.match_is_finished or self.board.turn != self.player_color:
            return
        self.help_tiles_rolled_this_turn = True
        self.active_help_tiles = {}
        self.active_help_characters_this_turn = set()
        char_ids = self._roll_help_tile_characters_for_turn()
        if not char_ids:
            return
        square_choices: dict[chess.Square, list[str]] = {}
        for character_id in char_ids:
            square = self._choose_help_tile_square()
            if square is None:
                continue
            square_choices.setdefault(square, []).append(character_id)
        for square, characters in square_choices.items():
            chosen = random.choice(characters)
            self.active_help_tiles[square] = chosen
            self.active_help_characters_this_turn.add(chosen)
            print(f"[HelpTile] {chosen} scheduled on {chess.square_name(square)}")

    def _power_offer_ids_for_character(self, character_id: str) -> list[str]:
        power_ids = self._power_ids_for_character(character_id)
        if "future_sight" in self.active_global_powers:
            power_ids = [power_id for power_id in power_ids if power_id != "future_sight"]
        if len(power_ids) <= 2:
            return list(power_ids)
        return random.sample(power_ids, 2)

    def _start_character_power_offer(self, character_id: str) -> None:
        power_ids = self._power_offer_ids_for_character(character_id)
        if not power_ids:
            self.chess_result_message = f"{self._character_display_name(character_id)} has no powers ready yet."
            return
        display_name = self._character_display_name(character_id)
        self.pending_power_character_id = character_id
        self.pending_power_offer_ids = power_ids
        self.chess_result_message = f"{display_name} is offering a power."
        self.open_power_choice_after_dialogue = True
        self.start_dialogue(
            [
                DialogueLine(display_name, f"I'm here! Choose one of my powers"),
            ]
        )

    def _grant_global_power(self, power_id: str) -> None:
        power = self.power_definitions[power_id]
        if power_id == "gamer_god":
            self._mark_power_used(power_id)
            self.next_turn_global_powers.add(power_id)
            self.chess_result_message = "Gamer God prepared. You'll see the top 3 moves next turn."
            return
        if power_id == "future_sight":
            self._mark_power_used(power_id)
            self.active_global_powers.add(power_id)
            self.chess_result_message = "Future Sight active. The evaluation bar is visible."
            return
        if power_id == "pawn_exchange":
            self._push_state_snapshot()
            self._mark_power_used(power_id)
            player_pawns = self._player_piece_squares({chess.PAWN})
            opponent_pawns = self._opponent_piece_squares({chess.PAWN})
            if player_pawns:
                self.awaiting_pawn_exchange_side = "player"
                self.chess_result_message = "Pawn Exchange: select one of your pawns to remove."
            elif opponent_pawns:
                self.awaiting_pawn_exchange_side = "opponent"
                self.chess_result_message = "Pawn Exchange: select one enemy pawn to remove."
            else:
                self.chess_result_message = "Pawn Exchange had nothing to remove."
            return
        if power_id == "takeback":
            self._mark_power_used(power_id)
            self.takeback_available += 1
            self.chess_result_message = "Takeback ready. Press U during chess to use it."
            return
        if power_id == "confusion":
            self._mark_power_used(power_id)
            self.opponent_confused_next_move = True
            self.chess_result_message = "Confusion applied. Neil will blunder next move."
            return
        self._mark_power_used(power_id)
        self.active_global_powers.add(power_id)
        self.chess_result_message = f"{power.short_label} activated."

    def _consume_help_tile(self, move: chess.Move) -> None:
        character_id = self.active_help_tiles.get(move.to_square)
        if character_id is None:
            self.active_help_tiles = {}
            self.active_help_characters_this_turn = set()
            return
        self._start_character_power_offer(character_id)
        self.active_help_tiles = {}
        self.active_help_characters_this_turn = set()

    def _cancel_pending_power_selection(self) -> None:
        if self.awaiting_pawn_exchange_side is not None:
            current = self.character_powers_taken_this_match.get("isha", 0)
            self.character_powers_taken_this_match["isha"] = max(0, current - 1)
        self.awaiting_power_target_power_id = None
        self.awaiting_power_sacrifice_power_id = None
        self.pending_power_target_square = None
        self.awaiting_pawn_exchange_side = None

    def _apply_targeted_power(self, power_id: str, square: chess.Square) -> None:
        piece = self.board.piece_at(square)
        if piece is None and power_id != "summon_pawn":
            return
        self._push_state_snapshot()
        if power_id == "summon_pawn":
            if self.board.piece_at(square) is not None:
                self.chess_result_message = "Summon Pawn needs an empty square."
                return
            if chess.square_rank(square) == (7 if self.player_color == chess.WHITE else 0):
                self.chess_result_message = "Summon Pawn cannot place a pawn on the opponent's back rank."
                return
            self.board.set_piece_at(square, chess.Piece(chess.PAWN, self.player_color))
            self._mark_power_used(power_id)
            self.chess_result_message = f"Summoned a pawn on {chess.square_name(square)}."
            return
        if power_id == "double":
            self.board.remove_piece_at(square)
            self.empowered_pawns.pop(square, None)
            self._mark_power_used(power_id)
            self.board.push(chess.Move.null())
            self.chess_result_message = "Double activated. Move again now."
            self.help_tiles_rolled_this_turn = False
            return
        if power_id == "paralyze":
            self.paralyzed_enemy_pieces[square] = 2
            self._mark_power_used(power_id)
            self.chess_result_message = f"Paralyze applied on {chess.square_name(square)} for 2 turns."
            return
        if power_id == "death_foretold":
            self.death_foretold_targets[square] = 5
            self._mark_power_used(power_id)
            self.chess_result_message = f"Doomed marked {chess.square_name(square)}."
            return
        if power_id == "underpromote":
            new_piece_type = piece.piece_type
            if piece.piece_type == chess.QUEEN:
                new_piece_type = chess.ROOK
            elif piece.piece_type == chess.ROOK:
                new_piece_type = random.choice([chess.KNIGHT, chess.BISHOP])
            elif piece.piece_type in {chess.KNIGHT, chess.BISHOP}:
                new_piece_type = chess.PAWN
            self.board.set_piece_at(square, chess.Piece(new_piece_type, piece.color))
            self.paralyzed_enemy_pieces.pop(square, None)
            self._mark_power_used(power_id)
            piece_name = chess.piece_name(new_piece_type)
            self.chess_result_message = f"Underpromoted {chess.square_name(square)} into a {piece_name}."
            return
        if power_id == "dodge":
            self.dodge_ready_squares.add(square)
            self._mark_power_used(power_id)
            self.chess_result_message = f"Dodge primed on {chess.square_name(square)}."
            return

    def _option_button_height(self, option: PopupOption, width: int) -> int:
        wrapped_lines = self._wrap_text(option.description, self.small_font, width - 28)
        return max(76, 34 + len(wrapped_lines) * 16 + 16)

    def _popup_rect(self, options: list[PopupOption]) -> pygame.Rect:
        content_height = 0
        for option in options:
            content_height += self._option_button_height(option, 440 - 56) + 14
        height = max(230, 92 + content_height)
        return pygame.Rect(self.config.width // 2 - 220, self.config.height // 2 - height // 2, 440, height)

    def _popup_button_rects(self, options: list[PopupOption]) -> list[tuple[pygame.Rect, PopupOption]]:
        popup = self._popup_rect(options)
        rects: list[tuple[pygame.Rect, PopupOption]] = []
        y = popup.top + 72
        for option in options:
            height = self._option_button_height(option, popup.width - 56)
            rect = pygame.Rect(popup.left + 28, y, popup.width - 56, height)
            rects.append((rect, option))
            y += height + 14
        return rects

    def _shop_popup_rect(self, options: list[PopupOption]) -> pygame.Rect:
        content_height = 0
        for option in options:
            content_height += self._option_button_height(option, 360 - 48) + 14
        height = max(360, 104 + content_height)
        return pygame.Rect(self.config.width // 2 - 340, self.config.height // 2 - height // 2, 680, height)

    def _shop_popup_button_rects(self, options: list[PopupOption]) -> list[tuple[pygame.Rect, PopupOption]]:
        popup = self._shop_popup_rect(options)
        left_width = 360
        rects: list[tuple[pygame.Rect, PopupOption]] = []
        y = popup.top + 72
        for option in options:
            height = self._option_button_height(option, left_width - 48)
            rect = pygame.Rect(popup.left + 24, y, left_width - 48, height)
            rects.append((rect, option))
            y += height + 14
        return rects

    def _shop_popup_close_rect(self) -> pygame.Rect:
        popup = self._shop_popup_rect(self._shop_options(self.pending_shop_character_id))
        return pygame.Rect(popup.right - 42, popup.top + 10, 28, 28)

    def _shop_popup_side_panel_rect(self) -> pygame.Rect:
        popup = self._shop_popup_rect(self._shop_options(self.pending_shop_character_id))
        return pygame.Rect(popup.left + 372, popup.top + 58, popup.width - 396, popup.height - 82)

    def _shop_power_content_height(self, character_id: str | None) -> int:
        height = 0
        power_ids = self._power_ids_for_character(character_id or "pragya")
        for power_id in power_ids:
            power = self.power_definitions[power_id]
            height += 18
            height += 16 * len(self._wrap_text(power.description, self.small_font, 240))
            height += 10
        return height

    def _clamp_shop_power_scroll(self) -> None:
        side_panel = self._shop_popup_side_panel_rect()
        visible_height = max(1, side_panel.height - 52)
        content_height = self._shop_power_content_height(self.pending_shop_character_id)
        self.shop_power_scroll = max(0, min(self.shop_power_scroll, max(0, content_height - visible_height)))

    def _player_pawn_squares(self) -> list[chess.Square]:
        pawn_squares: list[chess.Square] = []
        for square, piece in self.board.piece_map().items():
            if piece.color == self.player_color and piece.piece_type == chess.PAWN:
                pawn_squares.append(square)
        return sorted(pawn_squares)

    def _opponent_piece_squares(self, piece_types: set[int]) -> list[chess.Square]:
        result: list[chess.Square] = []
        for square, piece in self.board.piece_map().items():
            if piece.color == self.opponent_color and piece.piece_type in piece_types:
                result.append(square)
        return sorted(result)

    def _player_piece_squares(self, piece_types: set[int]) -> list[chess.Square]:
        result: list[chess.Square] = []
        for square, piece in self.board.piece_map().items():
            if piece.color == self.player_color and piece.piece_type in piece_types:
                result.append(square)
        return sorted(result)

    def _power_sacrifice_candidate_squares(self, power_id: str, target_square: chess.Square | None) -> list[chess.Square]:
        if power_id == "dragon_knights":
            return self._player_piece_squares({chess.PAWN})
        if power_id == "dragon_queen":
            return [
                square
                for square in self._player_piece_squares({chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN})
                if square != target_square
            ]
        return []

    def _power_sacrifice_prompt(self, power_id: str) -> str:
        if power_id == "dragon_knights":
            return "Select 1 pawn to sacrifice."
        if power_id == "dragon_queen":
            return "Select 1 minor or major piece to sacrifice."
        return "Select 1 piece to sacrifice."

    def _power_target_candidate_squares(self, power_id: str) -> list[chess.Square]:
        definition = self.power_definitions[power_id]
        if definition.target_kind == "pawn":
            return self._player_piece_squares({chess.PAWN})
        if definition.target_kind == "knight":
            return self._player_piece_squares({chess.KNIGHT})
        if definition.target_kind == "queen":
            return self._player_piece_squares({chess.QUEEN})
        if definition.target_kind == "king":
            return self._player_piece_squares({chess.KING})
        if definition.target_kind == "empty_square":
            return [
                square
                for square in chess.SQUARES
                if (
                    self.board.piece_at(square) is None
                    and chess.square_rank(square) != (7 if self.player_color == chess.WHITE else 0)
                )
            ]
        if definition.target_kind == "own_piece":
            return self._player_piece_squares(set(chess.PIECE_TYPES))
        if definition.target_kind == "enemy_piece":
            return self._opponent_piece_squares(set(chess.PIECE_TYPES))
        if definition.target_kind == "enemy_underpromotable":
            return self._opponent_piece_squares({chess.QUEEN, chess.ROOK, chess.KNIGHT, chess.BISHOP})
        if definition.target_kind == "non_king_queen_piece":
            return sorted(
                square
                for square, piece in self.board.piece_map().items()
                if piece.piece_type not in {chess.KING, chess.QUEEN}
            )
        return []

    def _power_target_is_valid(self, power_id: str, square: chess.Square) -> bool:
        return square in self._power_target_candidate_squares(power_id)

    def _mark_power_used(self, power_id: str) -> None:
        character_id = self.power_definitions[power_id].character_id
        self.character_powers_taken_this_match[character_id] = self.character_powers_taken_this_match.get(character_id, 0) + 1

    def _adjacent_empty_squares(self, center_square: chess.Square, blocked: set[chess.Square] | None = None) -> list[chess.Square]:
        blocked = blocked or set()
        result: list[chess.Square] = []
        file_index = chess.square_file(center_square)
        rank_index = chess.square_rank(center_square)
        for df in (-1, 0, 1):
            for dr in (-1, 0, 1):
                if df == 0 and dr == 0:
                    continue
                tf = file_index + df
                tr = rank_index + dr
                if not (0 <= tf <= 7 and 0 <= tr <= 7):
                    continue
                sq = chess.square(tf, tr)
                if sq in blocked or self.board.piece_at(sq) is not None:
                    continue
                result.append(sq)
        return result

    def _lost_player_pawn_count(self) -> int:
        return max(0, 8 - len(self._player_piece_squares({chess.PAWN})))

    def _assign_power_to_piece(self, square: chess.Square, power_id: str) -> None:
        power_ids = self.empowered_pawns.setdefault(square, set())
        power_ids.add(power_id)
        character_id = self.power_definitions[power_id].character_id
        self.character_powers_taken_this_match[character_id] = self.character_powers_taken_this_match.get(character_id, 0) + 1
        power_name = self.power_definitions[power_id].short_label
        square_name = chess.square_name(square)
        self.chess_result_message = f"{power_name} applied on {square_name}."

    def _draw_power_sidebar(self) -> None:
        panel = self._power_sidebar_rect()
        pygame.draw.rect(self.screen, (18, 20, 28), panel, border_radius=12)
        pygame.draw.rect(self.screen, (235, 235, 235), panel, width=2, border_radius=12)

        title = self.ui_font.render("Rhea's Powers", True, self.config.text)
        self.screen.blit(title, (panel.left + 16, panel.top + 14))

        content_top = panel.top + 52
        clip_rect = pygame.Rect(panel.left + 10, content_top, panel.width - 20, panel.height - 62)
        previous_clip = self.screen.get_clip()
        self.screen.set_clip(clip_rect)
        y = content_top - self.power_sidebar_scroll
        remaining_title = self.small_font.render("Remaining This Match", True, self.config.text)
        self.screen.blit(remaining_title, (panel.left + 16, y))
        y += 22
        for character_id in ("pragya", "isha", "gounder"):
            if not self._character_is_unlocked(character_id):
                continue
            remaining = max(0, self._character_power_capacity(character_id) - self._character_power_count(character_id))
            total = self._character_power_capacity(character_id)
            line = self.small_font.render(
                f"{self._character_display_name(character_id)} {remaining}/{total} remaining",
                True,
                self.config.text,
            )
            self.screen.blit(line, (panel.left + 16, y))
            y += 20

        y += 10
        active_title = self.small_font.render("Active Powers", True, self.config.text)
        self.screen.blit(active_title, (panel.left + 16, y))
        y += 22
        if not self.empowered_pawns and not self.active_global_powers and not self.next_turn_global_powers and self.takeback_available <= 0:
            empty = self.small_font.render("No active powers yet.", True, self.config.muted_text)
            self.screen.blit(empty, (panel.left + 16, y))
            self.screen.set_clip(previous_clip)
            return

        if self.takeback_available > 0:
            button = self._takeback_button_rect()
            pygame.draw.rect(self.screen, (48, 54, 74), button, border_radius=8)
            pygame.draw.rect(self.screen, (235, 235, 235), button, width=2, border_radius=8)
            label = self.small_font.render(f"Use Takeback (U) x{self.takeback_available}", True, self.config.text)
            self.screen.blit(label, (button.left + 10, button.top + 7))
            y = button.bottom + 10

        for square, turns in sorted(self.paralyzed_enemy_pieces.items()):
            label = self.small_font.render(f"Pragya: Paralyze {chess.square_name(square)} ({turns})", True, self.config.text)
            self.screen.blit(label, (panel.left + 16, y))
            y += 22

        for square, turns in sorted(self.death_foretold_targets.items()):
            label = self.small_font.render(f"Isha: Doomed {chess.square_name(square)} ({turns})", True, self.config.text)
            self.screen.blit(label, (panel.left + 16, y))
            y += 22

        for square in sorted(self.dodge_ready_squares):
            label = self.small_font.render(f"Gounder: Dodge {chess.square_name(square)}", True, self.config.text)
            self.screen.blit(label, (panel.left + 16, y))
            y += 22

        for power_id in sorted(self.active_global_powers):
            power = self.power_definitions[power_id]
            label = self.small_font.render(f"{self._character_display_name(power.character_id)}: {power.short_label}", True, self.config.text)
            self.screen.blit(label, (panel.left + 16, y))
            y += 22

        for power_id in sorted(self.next_turn_global_powers):
            power = self.power_definitions[power_id]
            label = self.small_font.render(f"{self._character_display_name(power.character_id)}: {power.short_label} (next)", True, self.config.text)
            self.screen.blit(label, (panel.left + 16, y))
            y += 22

        for square, power_ids in sorted(self.empowered_pawns.items()):
            square_label = self.small_font.render(chess.square_name(square), True, (244, 197, 216))
            self.screen.blit(square_label, (panel.left + 16, y))
            y += 22
            for power_id in sorted(power_ids):
                power = self.power_definitions[power_id]
                line = self.small_font.render(f"{self._character_display_name(power.character_id)}: {power.short_label}", True, self.config.text)
                self.screen.blit(line, (panel.left + 34, y))
                y += 20
            y += 10
        self.screen.set_clip(previous_clip)

        content_height = y - (content_top - self.power_sidebar_scroll)
        visible_height = max(1, clip_rect.height)
        if content_height > visible_height:
            track = pygame.Rect(panel.right - 10, content_top, 4, clip_rect.height)
            pygame.draw.rect(self.screen, (70, 72, 82), track, border_radius=3)
            thumb_height = max(24, int(track.height * visible_height / content_height))
            max_scroll = max(1, content_height - visible_height)
            thumb_top = track.top + int((track.height - thumb_height) * self.power_sidebar_scroll / max_scroll)
            thumb = pygame.Rect(track.left, thumb_top, track.width, thumb_height)
            pygame.draw.rect(self.screen, (235, 235, 235), thumb, border_radius=3)

    def _takeback_button_rect(self) -> pygame.Rect:
        panel = self._power_sidebar_rect()
        return pygame.Rect(panel.left + 16, panel.top + 144, panel.width - 32, 30)

    def _power_sidebar_rect(self) -> pygame.Rect:
        return pygame.Rect(self.config.width - 280, 88, 248, 570)

    def _power_sidebar_content_height(self) -> int:
        height = 22 + 20 * sum(1 for character_id in ("pragya", "isha", "gounder") if self._character_is_unlocked(character_id))
        height += 32
        if not self.empowered_pawns and not self.active_global_powers and not self.next_turn_global_powers and self.takeback_available <= 0:
            return height + 22
        if self.takeback_available > 0:
            height += 40
        height += 22 * len(self.paralyzed_enemy_pieces)
        height += 22 * len(self.death_foretold_targets)
        height += 22 * len(self.dodge_ready_squares)
        height += 22 * len(self.active_global_powers)
        height += 22 * len(self.next_turn_global_powers)
        for power_ids in self.empowered_pawns.values():
            height += 22
            height += 20 * len(power_ids)
            height += 10
        return height

    def _clamp_power_sidebar_scroll(self) -> None:
        panel = self._power_sidebar_rect()
        visible_height = max(1, panel.height - 62)
        content_height = self._power_sidebar_content_height()
        self.power_sidebar_scroll = max(0, min(self.power_sidebar_scroll, max(0, content_height - visible_height)))

    def _draw_board_coordinates(self) -> None:
        board_rect = self.config.board_rect
        files = "abcdefgh"
        for col, label in enumerate(files):
            x = board_rect.left + col * self.config.square_size + self.config.square_size // 2
            text = self.small_font.render(label, True, self.config.text)
            self.screen.blit(text, (x - text.get_width() // 2, board_rect.bottom + 6))
        for row, rank in enumerate("87654321"):
            y = board_rect.top + row * self.config.square_size + self.config.square_size // 2
            text = self.small_font.render(rank, True, self.config.text)
            self.screen.blit(text, (board_rect.left - text.get_width() - 8, y - text.get_height() // 2))

    def _close_button_rect(self) -> pygame.Rect:
        return pygame.Rect(self.config.width - 56, 16, 32, 32)

    def _draw_close_button(self) -> None:
        rect = self._close_button_rect()
        pygame.draw.rect(self.screen, (96, 44, 58), rect, border_radius=8)
        pygame.draw.rect(self.screen, (235, 235, 235), rect, width=2, border_radius=8)
        x_text = self.ui_font.render("X", True, self.config.text)
        self.screen.blit(x_text, (rect.centerx - x_text.get_width() // 2, rect.centery - x_text.get_height() // 2 - 1))

    def _draw_loss_overlay(self) -> None:
        overlay = pygame.Surface((self.config.width, self.config.height), pygame.SRCALPHA)
        overlay.fill((12, 10, 16, 185))
        self.screen.blit(overlay, (0, 0))

        title = self.loss_font.render("You lose", True, (255, 220, 220))
        self.screen.blit(title, (self.config.width // 2 - title.get_width() // 2, self.config.height // 2 - 70))

        elapsed = pygame.time.get_ticks() - self.loss_screen_started_ms
        if elapsed >= 3000:
            hint = self.dialogue_font.render("Press any key to return to lobby", True, (245, 245, 250))
            self.screen.blit(hint, (self.config.width // 2 - hint.get_width() // 2, self.config.height // 2 + 6))

    def _draw_birthday_banner(self) -> None:
        overlay = pygame.Surface((self.config.width, 84), pygame.SRCALPHA)
        overlay.fill((255, 220, 90, 210))
        self.screen.blit(overlay, (0, 18))
        label = self.banner_font.render("Happy birthday!!", True, (78, 26, 26))
        self.screen.blit(label, (self.config.width // 2 - label.get_width() // 2, 36))

    def _draw_popup(self, title_text: str, hint_text: str, options: list[PopupOption]) -> None:
        overlay = pygame.Surface((self.config.width, self.config.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        popup = self._popup_rect(options)
        pygame.draw.rect(self.screen, (18, 20, 28), popup, border_radius=12)
        pygame.draw.rect(self.screen, (240, 140, 214), popup, width=3, border_radius=12)

        title = self.ui_font.render(title_text, True, self.config.text)
        hint = self.small_font.render(hint_text, True, self.config.muted_text)
        self.screen.blit(title, (popup.left + 24, popup.top + 18))
        self.screen.blit(hint, (popup.left + 24, popup.top + 44))

        for rect, option in self._popup_button_rects(options):
            fill_color = (48, 54, 74) if option.enabled else (58, 58, 58)
            text_color = self.config.text if option.enabled else self.config.muted_text
            pygame.draw.rect(self.screen, fill_color, rect, border_radius=10)
            pygame.draw.rect(self.screen, (235, 235, 235), rect, width=2, border_radius=10)
            name = self.small_font.render(option.title, True, text_color)
            self.screen.blit(name, (rect.left + 14, rect.top + 10))
            wrapped_lines = self._wrap_text(option.description, self.small_font, rect.width - 28)
            for idx, line in enumerate(wrapped_lines):
                desc = self.small_font.render(line, True, self.config.muted_text)
                self.screen.blit(desc, (rect.left + 14, rect.top + 30 + idx * 16))

    def _draw_shop_popup(self, character_id: str | None) -> None:
        options = self._shop_options(character_id)
        self._clamp_shop_power_scroll()
        overlay = pygame.Surface((self.config.width, self.config.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))

        popup = self._shop_popup_rect(options)
        pygame.draw.rect(self.screen, (18, 20, 28), popup, border_radius=12)
        pygame.draw.rect(self.screen, (240, 140, 214), popup, width=3, border_radius=12)

        shop_name = self._character_display_name(character_id or "pragya")
        title = self.ui_font.render(f"{shop_name}'s Shop", True, self.config.text)
        hint = self.small_font.render("Click an item to buy it", True, self.config.muted_text)
        self.screen.blit(title, (popup.left + 24, popup.top + 18))
        self.screen.blit(hint, (popup.left + 24, popup.top + 44))

        close_rect = self._shop_popup_close_rect()
        pygame.draw.rect(self.screen, (96, 44, 58), close_rect, border_radius=8)
        pygame.draw.rect(self.screen, (235, 235, 235), close_rect, width=2, border_radius=8)
        close_text = self.small_font.render("X", True, self.config.text)
        self.screen.blit(close_text, (close_rect.centerx - close_text.get_width() // 2, close_rect.centery - close_text.get_height() // 2))

        for rect, option in self._shop_popup_button_rects(options):
            fill_color = (48, 54, 74) if option.enabled else (58, 58, 58)
            text_color = self.config.text if option.enabled else self.config.muted_text
            pygame.draw.rect(self.screen, fill_color, rect, border_radius=10)
            pygame.draw.rect(self.screen, (235, 235, 235), rect, width=2, border_radius=10)
            name = self.small_font.render(option.title, True, text_color)
            self.screen.blit(name, (rect.left + 14, rect.top + 10))
            wrapped_lines = self._wrap_text(option.description, self.small_font, rect.width - 28)
            for idx, line in enumerate(wrapped_lines):
                desc = self.small_font.render(line, True, self.config.muted_text)
                self.screen.blit(desc, (rect.left + 14, rect.top + 30 + idx * 16))

        side_panel = self._shop_popup_side_panel_rect()
        pygame.draw.rect(self.screen, (28, 30, 40), side_panel, border_radius=10)
        pygame.draw.rect(self.screen, (235, 235, 235), side_panel, width=2, border_radius=10)
        side_title = self.small_font.render("Powers", True, self.config.text)
        self.screen.blit(side_title, (side_panel.left + 14, side_panel.top + 12))
        spawn_note = self.small_font.render(
            f"Spawns from move {self._character_spawn_start_move(character_id or 'pragya')}",
            True,
            self.config.muted_text,
        )
        self.screen.blit(spawn_note, (side_panel.left + 14, side_panel.top + 28))
        content_top = side_panel.top + 62
        clip_rect = pygame.Rect(side_panel.left + 10, content_top, side_panel.width - 20, side_panel.height - 58)
        previous_clip = self.screen.get_clip()
        self.screen.set_clip(clip_rect)
        y = content_top - self.shop_power_scroll
        power_ids = self._power_ids_for_character(character_id or "pragya")
        for power_id in power_ids:
            power = self.power_definitions[power_id]
            name = self.small_font.render(power.name, True, self.config.text)
            self.screen.blit(name, (side_panel.left + 14, y))
            y += 18
            for line in self._wrap_text(power.description, self.small_font, side_panel.width - 28):
                desc = self.small_font.render(line, True, self.config.muted_text)
                self.screen.blit(desc, (side_panel.left + 14, y))
                y += 16
            y += 10
        self.screen.set_clip(previous_clip)

        content_height = self._shop_power_content_height(character_id)
        visible_height = max(1, clip_rect.height)
        if content_height > visible_height:
            track = pygame.Rect(side_panel.right - 10, content_top, 4, clip_rect.height)
            pygame.draw.rect(self.screen, (70, 72, 82), track, border_radius=3)
            thumb_height = max(24, int(track.height * visible_height / content_height))
            max_scroll = max(1, content_height - visible_height)
            thumb_top = track.top + int((track.height - thumb_height) * self.shop_power_scroll / max_scroll)
            thumb = pygame.Rect(track.left, thumb_top, track.width, thumb_height)
            pygame.draw.rect(self.screen, (235, 235, 235), thumb, border_radius=3)

    def _power_popup_options(self) -> list[PopupOption]:
        return [
            PopupOption(
                option_id=power_id,
                title=self.power_definitions[power_id].name,
                description=self.power_definitions[power_id].description,
            )
            for power_id in self.pending_power_offer_ids[:2]
        ]

    def _return_to_lobby_options(self) -> list[PopupOption]:
        return [
            PopupOption("return_to_lobby_yes", "Return to Lobby", "Leave this chess game and go back to the lobby."),
            PopupOption("return_to_lobby_no", "Keep Playing", "Stay in the current chess game."),
        ]

    def _practice_game_options(self) -> list[PopupOption]:
        return [
            PopupOption("practice_yes", "Yes", "Start a practice chess game with Circe's help."),
            PopupOption("practice_no", "No", "Stay in the lobby for now."),
        ]

    def _unlock_options(self) -> list[PopupOption]:
        npc_id = self.pending_unlock_npc
        if npc_id is None:
            return []
        required = self.unlock_cost_by_npc.get(npc_id, 0)
        return [
            PopupOption("unlock_yes", "Yes", f"Spend {required} points to unlock this character."),
            PopupOption("unlock_no", "No", "Keep your points for now."),
        ]

    def _svg_render_key(
        self,
    ) -> tuple[str, int | None, tuple[int, ...], str, tuple[tuple[int, str], ...], tuple[tuple[int, tuple[str, ...]], ...], tuple[str, ...], bool, bool]:
        legal_targets = tuple(sorted(self.legal_targets_for(self.selected_square)))
        last_move = self.board.peek().uci() if self.board.move_stack else ""
        help_tiles = tuple(sorted((square, character_id) for square, character_id in self.active_help_tiles.items()))
        empowered = tuple(sorted((square, tuple(sorted(power_ids))) for square, power_ids in self.empowered_pawns.items()))
        next_globals = tuple(sorted(self.next_turn_global_powers))
        return (
            self.board.fen(),
            self.selected_square,
            legal_targets,
            last_move,
            help_tiles,
            empowered,
            next_globals,
            self.gamer_god_visible_this_turn,
            "future_sight" in self.active_global_powers,
        )

    def _render_svg_board_surface(self) -> pygame.Surface | None:
        key = self._svg_render_key()
        if key == self.svg_cache_key and self.svg_board_surface is not None:
            return self.svg_board_surface

        fill: dict[chess.Square, str] = {}
        if self.selected_square is not None:
            fill[self.selected_square] = "#f6f085"
        for target_square in self.legal_targets_for(self.selected_square):
            fill[target_square] = "#7ccf7c"
        for square, character_id in self.active_help_tiles.items():
            fill[square] = self._character_color(character_id)

        svg = chess.svg.board(
            board=None,
            size=self.config.board_pixels,
            coordinates=False,
            borders=False,
            lastmove=self.board.peek() if self.board.move_stack else None,
            fill=fill,
            colors={
                "square light": "#f0d9b5",
                "square dark": "#b58863",
            },
        )

        surface = self._load_svg_surface(svg, "board.svg")
        if surface is None:
            return None
        opaque = surface.get_bounding_rect(min_alpha=1)
        if opaque.width > 0 and opaque.height > 0:
            surface = surface.subsurface(opaque).copy()
        if surface.get_width() != self.config.board_pixels or surface.get_height() != self.config.board_pixels:
            surface = pygame.transform.smoothscale(surface, (self.config.board_pixels, self.config.board_pixels))
        self.svg_cache_key = key
        self.svg_board_surface = surface
        return surface

    def _draw_board_pieces(self) -> None:
        for square, piece in self.board.piece_map().items():
            x, y = self.square_to_screen(square)
            piece_surface = None if self.use_unicode_board_pieces else self.svg_piece_surfaces.get((piece.piece_type, piece.color))
            if piece_surface is not None:
                offset_x = (self.config.square_size - piece_surface.get_width()) // 2
                offset_y = (self.config.square_size - piece_surface.get_height()) // 2
                self.screen.blit(piece_surface, (x + offset_x, y + offset_y))
                continue
            # Unicode piece renderer.
            symbol = piece.unicode_symbol()
            color = (248, 248, 248) if piece.color == chess.WHITE else (22, 22, 22)
            text = self.piece_font.render(symbol, True, color)
            centered_x = x + self.config.square_size // 2 - text.get_width() // 2
            centered_y = y + self.config.square_size // 2 - text.get_height() // 2 - 2
            self.screen.blit(text, (centered_x, centered_y))

        powered_squares = set(self.empowered_pawns) | set(self.dodge_ready_squares)
        star_font = pygame.font.SysFont("consolas", max(14, int(self.config.square_size * 0.28)), bold=True)
        for square in powered_squares:
            x, y = self.square_to_screen(square)
            star = star_font.render("*", True, (255, 120, 214))
            self.screen.blit(
                star,
                (
                    x + self.config.square_size // 2 - star.get_width() // 2,
                    y + self.config.square_size // 2 - star.get_height() // 2,
                ),
            )

    def _draw_help_tile_faces(self) -> None:
        face_size = max(18, int(self.config.square_size * 0.72))
        for square, character_id in self.active_help_tiles.items():
            face_surface = self._character_face_surface(character_id, face_size)
            if face_surface is None:
                continue
            x, y = self.square_to_screen(square)
            face_x = x + (self.config.square_size - face_surface.get_width()) // 2
            face_y = y + (self.config.square_size - face_surface.get_height()) // 2
            self.screen.blit(face_surface, (face_x, face_y))

    def _draw_power_target_hints(self) -> None:
        target_squares: list[chess.Square] = []
        color = (255, 120, 214)
        if self.awaiting_pawn_exchange_side == "player":
            target_squares = self._player_piece_squares({chess.PAWN})
            color = (255, 120, 214)
        elif self.awaiting_pawn_exchange_side == "opponent":
            target_squares = self._opponent_piece_squares({chess.PAWN})
            color = (122, 216, 255)
        elif self.awaiting_power_sacrifice_power_id is not None:
            target_squares = self._power_sacrifice_candidate_squares(
                self.awaiting_power_sacrifice_power_id,
                self.pending_power_target_square,
            )
            color = (122, 216, 255)
        elif self.awaiting_power_target_power_id is not None:
            target_squares = self._power_target_candidate_squares(self.awaiting_power_target_power_id)
        for square in target_squares:
            x, y = self.square_to_screen(square)
            square_rect = pygame.Rect(x, y, self.config.square_size, self.config.square_size)
            pygame.draw.rect(self.screen, color, square_rect, width=4, border_radius=6)

    def _draw_gamer_god_hints(self) -> None:
        if not self.gamer_god_visible_this_turn:
            return
        arrow_colors = [
            (92, 205, 255),
            (120, 255, 190),
            (255, 210, 110),
        ]
        for index, move in enumerate(self.gamer_god_hint_moves):
            from_x, from_y = self.square_to_screen(move.from_square)
            to_x, to_y = self.square_to_screen(move.to_square)
            start = (
                from_x + self.config.square_size // 2,
                from_y + self.config.square_size // 2,
            )
            end = (
                to_x + self.config.square_size // 2,
                to_y + self.config.square_size // 2,
            )
            color = arrow_colors[index % len(arrow_colors)]
            pygame.draw.line(self.screen, color, start, end, 6)

            dx = end[0] - start[0]
            dy = end[1] - start[1]
            length = max(1.0, (dx * dx + dy * dy) ** 0.5)
            ux = dx / length
            uy = dy / length
            head_length = 16
            head_width = 10
            base_x = end[0] - ux * head_length
            base_y = end[1] - uy * head_length
            perp_x = -uy
            perp_y = ux
            arrow_head = [
                end,
                (
                    int(base_x + perp_x * head_width),
                    int(base_y + perp_y * head_width),
                ),
                (
                    int(base_x - perp_x * head_width),
                    int(base_y - perp_y * head_width),
                ),
            ]
            pygame.draw.polygon(self.screen, color, arrow_head)

    def _draw_eval_bar(self) -> None:
        if "future_sight" not in self.active_global_powers:
            return
        eval_score = self._stockfish_eval(self.board)
        if eval_score is None:
            return
        bar_rect = pygame.Rect(self.config.board_left - 46, self.config.board_top, 16, self.config.board_pixels)
        pygame.draw.rect(self.screen, (32, 32, 40), bar_rect, border_radius=8)
        pygame.draw.rect(self.screen, (235, 235, 235), bar_rect, width=2, border_radius=8)
        normalized = max(-1000, min(1000, eval_score)) / 1000.0
        white_ratio = (normalized + 1.0) / 2.0
        white_height = int(bar_rect.height * white_ratio)
        black_height = bar_rect.height - white_height
        if black_height > 4:
            black_rect = pygame.Rect(bar_rect.left + 2, bar_rect.top + 2, bar_rect.width - 4, black_height - 4)
            pygame.draw.rect(self.screen, (22, 22, 22), black_rect, border_radius=6)
        if white_height > 4:
            white_rect = pygame.Rect(bar_rect.left + 2, bar_rect.bottom - white_height + 2, bar_rect.width - 4, white_height - 4)
            pygame.draw.rect(self.screen, (245, 245, 245), white_rect, border_radius=6)

    def _nearby_npc(self) -> NpcSprite | None:
        max_dist = 110.0
        if self._current_room().room_type == RoomType.CHESS_BATTLE:
            max_dist = 460.0

        nearest: NpcSprite | None = None
        nearest_dist = max_dist + 1.0
        for npc in self._current_npcs():
            dist = npc.distance_to(self.player.rect)
            if dist <= max_dist and dist < nearest_dist:
                nearest = npc
                nearest_dist = dist
        return nearest

    def _dialogue_for_npc(self, npc: NpcSprite) -> list[DialogueLine] | None:
        if npc.npc_id == "circe":
            self.open_practice_choice_after_dialogue = True
            return self.dialogue_scripts.get("circe_practice_offer")
        if npc.npc_id in self.unlock_cost_by_npc:
            if self._is_npc_unlocked(npc.npc_id):
                character_id = npc.npc_id.replace("_locked", "")
                self.pending_shop_character_id = character_id
                self.shop_power_scroll = 0
                self.open_shop_after_dialogue = True
                script_id = f"{character_id}_unlocked"
                return self.dialogue_scripts.get(script_id)
            required = self.unlock_cost_by_npc[npc.npc_id]
            if self._can_afford_unlock(npc.npc_id):
                self.pending_unlock_npc = npc.npc_id
                self.open_unlock_choice_after_dialogue = True
                return [
                    DialogueLine("???", f"Spend {required} points to unlock this character?"),
                ]
            script_id = npc.npc_id
            return self.dialogue_scripts.get(script_id)
        room = self._current_room()
        if room.dialogue_script_id is None:
            return None
        return self.dialogue_scripts.get(room.dialogue_script_id)

    def _is_npc_unlocked(self, npc_id: str) -> bool:
        if npc_id == "pragya_locked":
            return self.save_state.pragya_unlocked
        if npc_id == "isha_locked":
            return self.save_state.isha_unlocked
        if npc_id == "gounder_locked":
            return self.save_state.gounder_unlocked
        return False

    def _set_npc_unlocked(self, npc_id: str) -> None:
        if npc_id == "pragya_locked":
            self.save_state.pragya_unlocked = True
        elif npc_id == "isha_locked":
            self.save_state.isha_unlocked = True
        elif npc_id == "gounder_locked":
            self.save_state.gounder_unlocked = True

    def _can_afford_unlock(self, npc_id: str) -> bool:
        cost = self.unlock_cost_by_npc[npc_id]
        if npc_id == "pragya_locked":
            return self.save_state.points > cost
        return self.save_state.points >= cost

    def _shop_item_cost(self, item_id: str) -> int:
        if item_id in {
            "pragya_extra_spawn",
            "isha_extra_capacity",
            "gounder_extra_capacity",
            "pragya_spawn_rate_boost",
            "isha_spawn_rate_boost",
            "gounder_spawn_rate_boost",
        }:
            return 10
        return 0

    def _character_shop_sold_out(self, character_id: str) -> bool:
        if character_id == "pragya":
            return self._character_power_capacity(character_id) >= 10
        if character_id == "isha":
            return self._character_power_capacity(character_id) >= 10
        if character_id == "gounder":
            return self._character_power_capacity(character_id) >= 10
        return True

    def _shop_options(self, character_id: str | None) -> list[PopupOption]:
        if character_id is None:
            return []
        if character_id == "pragya":
            options: list[PopupOption] = []
            if self._character_shop_sold_out(character_id):
                options.append(PopupOption("pragya_extra_spawn_sold_out", "Sold Out", "Pragya power capacity is permanently maxed at 10/10.", False))
            else:
                count = self._character_power_capacity(character_id)
                options.append(
                    PopupOption(
                        "pragya_extra_spawn",
                        "Pragya Powers +1",
                        f"Costs 10 points. Permanent Pragya power capacity: {count}/10.",
                    )
                )
            if self._character_spawn_rate_shop_sold_out(character_id):
                options.append(PopupOption("pragya_spawn_rate_boost_sold_out", "Sold Out", "Pragya spawn rate boosts are maxed at +70%.", False))
            else:
                boost_count = self._character_spawn_rate_boost_count(character_id)
                chance_pct = int(self._character_spawn_chance(character_id) * 100)
                options.append(
                    PopupOption(
                        "pragya_spawn_rate_boost",
                        "Pragya Spawn Rate +10%",
                        f"Costs 10 points. Permanent spawn rate boosts: {boost_count}/7. Current chance: {chance_pct}%.",
                    )
                )
            return options
        if character_id == "isha":
            options = []
            if self._character_shop_sold_out(character_id):
                options.append(PopupOption("isha_extra_capacity_sold_out", "Sold Out", "Isha power capacity is permanently maxed at 10/10.", False))
            else:
                count = self._character_power_capacity(character_id)
                options.append(
                    PopupOption(
                        "isha_extra_capacity",
                        "Isha Powers +1",
                        f"Costs 10 points. Permanent Isha power capacity: {count}/10.",
                    )
                )
            if self._character_spawn_rate_shop_sold_out(character_id):
                options.append(PopupOption("isha_spawn_rate_boost_sold_out", "Sold Out", "Isha spawn rate boosts are maxed at +70%.", False))
            else:
                boost_count = self._character_spawn_rate_boost_count(character_id)
                chance_pct = int(self._character_spawn_chance(character_id) * 100)
                options.append(
                    PopupOption(
                        "isha_spawn_rate_boost",
                        "Isha Spawn Rate +10%",
                        f"Costs 10 points. Permanent spawn rate boosts: {boost_count}/7. Current chance: {chance_pct}%.",
                    )
                )
            return options
        if character_id == "gounder":
            options = []
            if self._character_shop_sold_out(character_id):
                options.append(PopupOption("gounder_extra_capacity_sold_out", "Sold Out", "Gounder power capacity is permanently maxed at 10/10.", False))
            else:
                count = self._character_power_capacity(character_id)
                options.append(
                    PopupOption(
                        "gounder_extra_capacity",
                        "Gounder Powers +1",
                        f"Costs 10 points. Permanent Gounder power capacity: {count}/10.",
                    )
                )
            if self._character_spawn_rate_shop_sold_out(character_id):
                options.append(PopupOption("gounder_spawn_rate_boost_sold_out", "Sold Out", "Gounder spawn rate boosts are maxed at +70%.", False))
            else:
                boost_count = self._character_spawn_rate_boost_count(character_id)
                chance_pct = int(self._character_spawn_chance(character_id) * 100)
                options.append(
                    PopupOption(
                        "gounder_spawn_rate_boost",
                        "Gounder Spawn Rate +10%",
                        f"Costs 10 points. Permanent spawn rate boosts: {boost_count}/7. Current chance: {chance_pct}%.",
                    )
                )
            return options
        return []

    def _buy_shop_item(self, item_id: str) -> None:
        cost = self._shop_item_cost(item_id)
        if self.save_state.points < cost:
            shop_speaker = self._character_display_name(self.pending_shop_character_id or "pragya")
            self.start_dialogue([DialogueLine(shop_speaker, "You need more points for that.")])
            return

        self.save_state.points -= cost
        if item_id == "pragya_extra_spawn":
            self.save_state.pragya_extra_spawns = min(9, self.save_state.pragya_extra_spawns + 1)
            self._save_state()
            self.start_dialogue(
                [DialogueLine("Pragya", "Yayyy see you in the game Rhea.")]
            )
            return
        if item_id == "pragya_spawn_rate_boost":
            self.save_state.pragya_spawn_rate_boosts = min(7, self.save_state.pragya_spawn_rate_boosts + 1)
            self._save_state()
            self.start_dialogue([DialogueLine("Pragya", "I'll try to show up more often now <3")])
            return
        if item_id == "isha_extra_capacity":
            self.save_state.isha_extra_capacity = min(9, self.save_state.isha_extra_capacity + 1)
            self._save_state()
            self.start_dialogue([DialogueLine("Isha", "You'll see more of me now B)")])
            return
        if item_id == "isha_spawn_rate_boost":
            self.save_state.isha_spawn_rate_boosts = min(7, self.save_state.isha_spawn_rate_boosts + 1)
            self._save_state()
            self.start_dialogue([DialogueLine("Isha", "I'll pop in more often now.")])
            return
        if item_id == "gounder_extra_capacity":
            self.save_state.gounder_extra_capacity = min(9, self.save_state.gounder_extra_capacity + 1)
            self._save_state()
            self.start_dialogue([DialogueLine("Gounder", "More room for my blessings.")])
            return
        if item_id == "gounder_spawn_rate_boost":
            self.save_state.gounder_spawn_rate_boosts = min(7, self.save_state.gounder_spawn_rate_boosts + 1)
            self._save_state()
            self.start_dialogue([DialogueLine("Gounder", "I will manifest more reliably.")])
            return

        self._save_state()

    def _enter_room(self, room_index: int, *, practice_mode: bool = False) -> None:
        self.progress.current_room_index = room_index
        self.active_door_hint = None
        self.show_interact_hint = False
        self.selected_square = None

        room = self._current_room()
        if room.room_type == RoomType.CHESS_BATTLE:
            self.practice_mode = practice_mode
            self.save_state.chess_entries += 1
            if not practice_mode:
                self.save_state.neil_attempts += 1
            self.save_state.points += 1
            self._save_state()
            self._start_chess_match()
        else:
            self.practice_mode = False
            self.mode = GameMode.EXPLORATION
            self._position_player_for_room(room_index)

        self._trigger_room_entry_dialogue_if_needed()

    def _start_chess_match(self) -> None:
        self.board.reset()
        self.match_is_finished = False
        self.mode = GameMode.CHESS
        self.selected_square = None
        self.chess_result_message = "Play as White. Defeat Neil to unlock the exit."
        self.opponent_move_cooldown = 0
        self.pre_fight_dialogue_played = False
        self.post_win_dialogue_played = False
        self.empowered_pawns = {}
        self.active_global_powers = set()
        self.next_turn_global_powers = set()
        self.paralyzed_enemy_pieces = {}
        self.death_foretold_targets = {}
        self.dodge_ready_squares = set()
        self.character_powers_taken_this_match = {}
        self.active_help_tiles = {}
        self.active_help_characters_this_turn = set()
        self.pending_power_offer_ids = []
        self.pending_power_character_id = None
        self.power_sidebar_scroll = 0
        self.awaiting_power_choice = False
        self.awaiting_power_target_power_id = None
        self.awaiting_power_sacrifice_power_id = None
        self.pending_power_target_square = None
        self.awaiting_pawn_exchange_side = None
        self.open_power_choice_after_dialogue = False
        self.awaiting_shop_choice = False
        self.open_shop_after_dialogue = False
        self.pending_shop_character_id = None
        self.awaiting_unlock_choice = False
        self.open_unlock_choice_after_dialogue = False
        self.awaiting_practice_choice = False
        self.open_practice_choice_after_dialogue = False
        self.awaiting_return_to_lobby_confirm = False
        self.awaiting_loss_ack = False
        self.loss_screen_started_ms = 0
        self.opponent_skip_turns = 0
        self.gamer_god_visible_this_turn = False
        self.gamer_god_hint_moves = []
        self.player_turn_index = 0
        self.help_tiles_rolled_this_turn = False
        self.takeback_available = 0
        self.player_skip_turns = 0
        self.opponent_confused_next_move = False
        self.state_snapshot_stack = []
        self._position_player_for_room(self.progress.current_room_index)

    def _complete_player_victory(self, message: str) -> None:
        self.match_is_finished = True
        if not self.practice_mode:
            self.progress.chess_room_cleared = True
            self.progress.chess_exit_unlocked = True
        self.chess_result_message = message
        if self.practice_mode:
            self.mode = GameMode.EXPLORATION
            self.progress.current_room_index = 0
            self._position_player_for_room(0)
            self.practice_mode = False
            self.start_dialogue([DialogueLine("Circe", "Meow.")])
            return

        self.mode = GameMode.EXPLORATION
        if not self.post_win_dialogue_played:
            self.post_win_dialogue_played = True
            self.start_dialogue(self._post_win_dialogue_lines())

    def _return_to_lobby_from_chess(self) -> None:
        self.mode = GameMode.EXPLORATION
        self.practice_mode = False
        self.progress.current_room_index = 0
        self.selected_square = None
        self.awaiting_power_choice = False
        self.awaiting_power_target_power_id = None
        self.awaiting_power_sacrifice_power_id = None
        self.pending_power_target_square = None
        self.awaiting_pawn_exchange_side = None
        self.pending_power_character_id = None
        self.power_sidebar_scroll = 0
        self.paralyzed_enemy_pieces = {}
        self.death_foretold_targets = {}
        self.dodge_ready_squares = set()
        self.awaiting_shop_choice = False
        self.pending_shop_character_id = None
        self.awaiting_unlock_choice = False
        self.pending_unlock_npc = None
        self.awaiting_return_to_lobby_confirm = False
        self.awaiting_loss_ack = False
        self.loss_screen_started_ms = 0
        self.active_help_tiles = {}
        self._position_player_for_room(0)
        self._save_state()

    def _evaluate_match_end(self) -> None:
        if not self.board.is_game_over():
            return
        self.match_is_finished = True
        result = self.board.result()
        player_win = result == "1-0" if self.player_color == chess.WHITE else result == "0-1"
        if player_win:
            self._complete_player_victory("Victory! Exit door unlocked. Walk right to continue.")
        else:
            if self.practice_mode:
                self.mode = GameMode.EXPLORATION
                self.progress.current_room_index = 0
                self._position_player_for_room(0)
                self.chess_result_message = "Practice game finished."
                self.practice_mode = False
                self.start_dialogue([DialogueLine("Circe", "Meow.")])
                return
            self.chess_result_message = "You lose"
            self.awaiting_loss_ack = True
            self.loss_screen_started_ms = pygame.time.get_ticks()

    def _maybe_make_opponent_move(self) -> None:
        if self.mode != GameMode.CHESS or self.match_is_finished:
            return
        if (
            self.awaiting_power_choice
            or self.awaiting_power_target_power_id is not None
            or self.awaiting_power_sacrifice_power_id is not None
            or self.awaiting_pawn_exchange_side is not None
            or self.open_power_choice_after_dialogue
            or self.awaiting_shop_choice
            or self.awaiting_return_to_lobby_confirm
        ):
            return
        if self.board.turn != self.opponent_color:
            return
        if self.opponent_skip_turns > 0:
            self._push_state_snapshot()
            self.opponent_skip_turns -= 1
            self.board.push(chess.Move.null())
            self.chess_result_message = "The opponent skipped their turn."
            self.help_tiles_rolled_this_turn = False
            return
        if self.opponent_move_cooldown > 0:
            self.opponent_move_cooldown -= 1
            return
        paralyzed_squares = set(self.paralyzed_enemy_pieces)
        legal = [move for move in self.board.legal_moves if move.from_square not in paralyzed_squares]
        if not legal:
            self._push_state_snapshot()
            self.board.push(chess.Move.null())
            self.chess_result_message = "A paralyzed enemy piece could not move."
            self.help_tiles_rolled_this_turn = False
            self._tick_end_of_move_effects(self.opponent_color)
            self._evaluate_match_end()
            return
        if self.opponent_confused_next_move:
            move = self._engine_confusion_blunder_move(self.board, legal)
        else:
            move = self._engine_play_move(self.board, self.neil_elo)
        if move is None or move not in legal:
            move = random.choice(legal)
        self.opponent_confused_next_move = False
        moving_piece = self.board.piece_at(move.from_square)
        captured_square = self._captured_square_for_legal_move(move)
        captured_piece = self.board.piece_at(captured_square) if captured_square is not None else None
        self.board.push(move)
        dodge_destination = self._maybe_resolve_dodge(captured_square, captured_piece, move.to_square)
        self._update_empowered_pawns_after_move(move, moving_piece, captured_square)
        self._update_square_effects_after_move(move, captured_square, dodge_destination)
        self._tick_end_of_move_effects(self.opponent_color)
        self.gamer_god_visible_this_turn = False
        self.gamer_god_hint_moves = []
        self.opponent_move_cooldown = 18
        self.help_tiles_rolled_this_turn = False
        self._evaluate_match_end()

    def _handle_doorway_collisions(self) -> None:
        room = self._current_room()
        self.active_door_hint = None
        for door in room.doorways:
            unlocked = (not door.requires_unlock) or self.progress.is_unlocked(door.unlock_flag)
            if self.player.rect.colliderect(door.rect):
                if unlocked:
                    self._enter_room(door.target_room)
                    return
                self.active_door_hint = f"{door.label}: locked (win chess match first)"

    def _draw_room_background(self) -> None:
        self.screen.fill(self.config.background)

    def _draw_doors(self) -> None:
        room = self._current_room()
        for door in room.doorways:
            unlocked = (not door.requires_unlock) or self.progress.is_unlocked(door.unlock_flag)
            color = self.config.door_open if unlocked else self.config.door_locked
            pygame.draw.rect(self.screen, color, door.rect, border_radius=6)
            pygame.draw.rect(self.screen, (22, 22, 28), door.rect, width=2, border_radius=6)

    def _draw_chess_board(self) -> None:
        board_rect = self.config.board_rect
        self._draw_eval_bar()
        svg_surface = self._render_svg_board_surface()
        if svg_surface is not None:
            self.screen.blit(svg_surface, board_rect.topleft)
            self._draw_help_tile_faces()
            self._draw_board_pieces()
            self._draw_power_target_hints()
            self._draw_gamer_god_hints()
            self._draw_board_coordinates()
            return

        # Fallback renderer when SVG loading is not available in this pygame build.
        pygame.draw.rect(self.screen, self.config.panel_bg, board_rect.inflate(24, 24), border_radius=12)
        legal_targets = self.legal_targets_for(self.selected_square) if self.mode == GameMode.CHESS else set()
        for row in range(8):
            for col in range(8):
                square = chess.square(col, 7 - row)
                base_color = self.config.light_square if (row + col) % 2 == 0 else self.config.dark_square
                if square in self.active_help_tiles:
                    color_hex = self._character_color(self.active_help_tiles[square]).lstrip("#")
                    base_color = tuple(int(color_hex[i : i + 2], 16) for i in (0, 2, 4))
                square_rect = pygame.Rect(
                    board_rect.left + col * self.config.square_size,
                    board_rect.top + row * self.config.square_size,
                    self.config.square_size,
                    self.config.square_size,
                )
                pygame.draw.rect(self.screen, base_color, square_rect)
                if self.selected_square is not None and square == self.selected_square:
                    pygame.draw.rect(self.screen, self.config.selected_square, square_rect, width=4)
                if square in legal_targets:
                    pygame.draw.circle(self.screen, self.config.legal_target, square_rect.center, self.config.square_size // 8)
        self._draw_help_tile_faces()
        self._draw_board_pieces()
        self._draw_power_target_hints()
        self._draw_gamer_god_hints()
        self._draw_board_coordinates()

    def _portrait_surface(self, key: str | None) -> pygame.Surface | None:
        if key is None:
            return None
        sprite_surface = self._speaker_sprite_surface(key)
        if sprite_surface is not None:
            return sprite_surface
        color = self.portrait_colors.get(key, (130, 130, 130))
        surf = pygame.Surface((72, 72))
        surf.fill((18, 18, 26))
        pygame.draw.rect(surf, color, pygame.Rect(6, 6, 60, 60), border_radius=8)
        pygame.draw.rect(surf, (235, 235, 235), pygame.Rect(6, 6, 60, 60), width=2, border_radius=8)
        return surf

    def draw_dialogue_box(
        self,
        speaker_name: str,
        text: str,
        portrait_surface_or_none: pygame.Surface | None,
    ) -> None:
        w = self.config.width
        h = self.config.height
        box = pygame.Rect(32, h - 190, w - 64, 150)
        pygame.draw.rect(self.screen, self.config.dialogue_bg, box, border_radius=10)
        pygame.draw.rect(self.screen, self.config.dialogue_border, box, width=2, border_radius=10)

        text_x = box.left + 18
        if portrait_surface_or_none is not None:
            self.screen.blit(portrait_surface_or_none, (box.left + 14, box.top + 14))
            text_x = box.left + 100

        speaker_surface = self.dialogue_font.render(speaker_name, True, self.config.text)
        self.screen.blit(speaker_surface, (text_x, box.top + 14))

        wrapped_lines = self._wrap_text(text, self.dialogue_font, box.width - (text_x - box.left) - 18)
        for idx, line in enumerate(wrapped_lines[:3]):
            line_surface = self.dialogue_font.render(line, True, self.config.text)
            self.screen.blit(line_surface, (text_x, box.top + 48 + idx * 28))

        hint = self.small_font.render("SPACE or Left Click to continue", True, self.config.muted_text)
        self.screen.blit(hint, (box.right - hint.get_width() - 16, box.bottom - 28))

    def _draw_pet_scene(self) -> None:
        overlay = pygame.Surface((self.config.width, self.config.height), pygame.SRCALPHA)
        overlay.fill((10, 10, 16, 210))
        self.screen.blit(overlay, (0, 0))

        if self.pet_scene_surface is not None:
            image = self.pet_scene_surface.copy()
            image_rect = image.get_rect()
            max_width = self.config.width - 80
            max_height = self.config.height - 120
            scale = min(max_width / image_rect.width, max_height / image_rect.height)
            scaled = pygame.transform.smoothscale(image, (max(1, int(image_rect.width * scale)), max(1, int(image_rect.height * scale))))
            rect = scaled.get_rect(center=(self.config.width // 2, self.config.height // 2 - 12))
            pygame.draw.rect(self.screen, (245, 245, 250), rect.inflate(16, 16), border_radius=14)
            self.screen.blit(scaled, rect.topleft)
        else:
            fallback = self.dialogue_font.render("Rhea and Circe <3", True, (245, 245, 250))
            self.screen.blit(fallback, (self.config.width // 2 - fallback.get_width() // 2, self.config.height // 2 - 16))

        hint = self.dialogue_font.render("Left Click to continue", True, (245, 245, 250))
        self.screen.blit(hint, (self.config.width // 2 - hint.get_width() // 2, self.config.height - 58))

    def _wrap_text(self, text: str, font: pygame.font.Font, max_width: int) -> list[str]:
        words = text.split()
        if not words:
            return [""]
        lines: list[str] = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if font.size(candidate)[0] <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def _draw_interaction_hints(self) -> None:
        if self.show_interact_hint:
            nearby = self._nearby_npc()
            hint_text = "Press E to talk"
            if nearby is not None and nearby.npc_id == "circe":
                hint_text = "Press E to talk or P to pet"
            hint = self.small_font.render(hint_text, True, self.config.text)
            self.screen.blit(hint, (self.player.rect.centerx - hint.get_width() // 2, self.player.rect.top - 24))
        if self.active_door_hint:
            hint = self.small_font.render(self.active_door_hint, True, self.config.text)
            self.screen.blit(hint, (self.config.width // 2 - hint.get_width() // 2, self.config.height - 34))

    def _handle_mouse_click(self, pos: tuple[int, int]) -> None:
        if self.mode == GameMode.PETTING:
            self.mode = GameMode.EXPLORATION
            return

        if self.awaiting_loss_ack:
            if pygame.time.get_ticks() - self.loss_screen_started_ms >= 3000:
                self._return_to_lobby_from_chess()
            return

        if self.awaiting_return_to_lobby_confirm:
            for rect, option in self._popup_button_rects(self._return_to_lobby_options()):
                if rect.collidepoint(pos):
                    if option.option_id == "return_to_lobby_yes":
                        self.awaiting_return_to_lobby_confirm = False
                        self._return_to_lobby_from_chess()
                    else:
                        self.awaiting_return_to_lobby_confirm = False
                    return
            return

        if self.awaiting_shop_choice:
            if self._shop_popup_close_rect().collidepoint(pos):
                self.awaiting_shop_choice = False
                self.pending_shop_character_id = None
                self.shop_power_scroll = 0
                return
            for rect, option in self._shop_popup_button_rects(self._shop_options(self.pending_shop_character_id)):
                if rect.collidepoint(pos):
                    self.awaiting_shop_choice = False
                    if option.enabled:
                        self._buy_shop_item(option.option_id)
                    self.pending_shop_character_id = None
                    self.shop_power_scroll = 0
                    return
            return

        if self.awaiting_unlock_choice:
            for rect, option in self._popup_button_rects(self._unlock_options()):
                if rect.collidepoint(pos):
                    self.awaiting_unlock_choice = False
                    npc_id = self.pending_unlock_npc
                    self.pending_unlock_npc = None
                    if option.option_id == "unlock_yes" and npc_id is not None:
                        required = self.unlock_cost_by_npc[npc_id]
                        if self._can_afford_unlock(npc_id) and not self._is_npc_unlocked(npc_id):
                            self.save_state.points -= required
                            self._set_npc_unlocked(npc_id)
                            self._save_state()
                            script_id = f"{npc_id.replace('_locked', '')}_unlocked_now"
                            lines = self.dialogue_scripts.get(script_id, [DialogueLine("System", "Unlocked.")])
                            self.start_dialogue(lines)
                        else:
                            self.start_dialogue([DialogueLine("System", "You don't have enough points.")])
                    else:
                        self.start_dialogue([DialogueLine("???", "Maybe later.")])
                    return
            return

        if self.awaiting_practice_choice:
            for rect, option in self._popup_button_rects(self._practice_game_options()):
                if rect.collidepoint(pos):
                    self.awaiting_practice_choice = False
                    if option.option_id == "practice_yes":
                        self._enter_room(1, practice_mode=True)
                    else:
                        self.start_dialogue([DialogueLine("Circe", "Meow meow.")])
                    return
            return

        if self.awaiting_power_choice:
            for rect, option in self._popup_button_rects(self._power_popup_options()):
                if rect.collidepoint(pos):
                    self.awaiting_power_choice = False
                    definition = self.power_definitions[option.option_id]
                    if definition.target_kind != "none":
                        self.awaiting_power_target_power_id = option.option_id
                        self.chess_result_message = definition.target_prompt or "Select a target."
                    else:
                        self._grant_global_power(option.option_id)
                    self.selected_square = None
                    return
            return

        if self.mode == GameMode.CHESS and self.takeback_available > 0 and self._takeback_button_rect().collidepoint(pos):
            if self._use_takeback():
                self.chess_result_message = "Takeback used."
            return

        if self.mode == GameMode.CHESS and self._close_button_rect().collidepoint(pos):
            self.awaiting_return_to_lobby_confirm = True
            self.selected_square = None
            return

        if self.awaiting_pawn_exchange_side is not None:
            clicked = self.mouse_to_square(pos)
            if clicked is None:
                return
            piece = self.board.piece_at(clicked)
            if piece is None or piece.piece_type != chess.PAWN:
                return
            expected_color = self.player_color if self.awaiting_pawn_exchange_side == "player" else self.opponent_color
            if piece.color != expected_color:
                return
            self.board.remove_piece_at(clicked)
            self.empowered_pawns.pop(clicked, None)
            if self.awaiting_pawn_exchange_side == "player":
                opponent_pawns = self._opponent_piece_squares({chess.PAWN})
                if opponent_pawns:
                    self.awaiting_pawn_exchange_side = "opponent"
                    self.chess_result_message = "Pawn Exchange: select one enemy pawn to remove."
                else:
                    self.awaiting_pawn_exchange_side = None
                    self.chess_result_message = "Pawn Exchange resolved."
            else:
                self.awaiting_pawn_exchange_side = None
                self.chess_result_message = "Pawn Exchange resolved."
            self.selected_square = None
            return

        if self.awaiting_power_sacrifice_power_id is not None:
            clicked = self.mouse_to_square(pos)
            if clicked is None:
                return
            if clicked not in self._power_sacrifice_candidate_squares(
                self.awaiting_power_sacrifice_power_id,
                self.pending_power_target_square,
            ):
                return
            self.board.remove_piece_at(clicked)
            self.empowered_pawns.pop(clicked, None)
            if self.pending_power_target_square is not None:
                self._assign_power_to_piece(self.pending_power_target_square, self.awaiting_power_sacrifice_power_id)
            self.awaiting_power_sacrifice_power_id = None
            self.pending_power_target_square = None
            self.selected_square = None
            return

        if self.awaiting_power_target_power_id is not None:
            clicked = self.mouse_to_square(pos)
            if clicked is None:
                return
            piece = self.board.piece_at(clicked)
            power_id = self.awaiting_power_target_power_id
            if not self._power_target_is_valid(power_id, clicked):
                return
            self.awaiting_power_target_power_id = None
            if power_id in {"double", "paralyze", "death_foretold", "underpromote", "dodge", "summon_pawn"}:
                self._apply_targeted_power(power_id, clicked)
                self.selected_square = None
                return
            candidate_squares = self._power_sacrifice_candidate_squares(power_id, clicked)
            if candidate_squares:
                self.pending_power_target_square = clicked
                self.awaiting_power_sacrifice_power_id = power_id
                self.chess_result_message = self._power_sacrifice_prompt(power_id)
                self.selected_square = None
                return
            if power_id == "dragon_knights":
                self.chess_result_message = "Dragon Knights needs a pawn to sacrifice."
                self.selected_square = None
                return
            if power_id == "dragon_queen":
                self.chess_result_message = "Dragon Queen needs a minor or major piece to sacrifice."
                self.selected_square = None
                return
            self._assign_power_to_piece(clicked, power_id)
            self.selected_square = None
            return

        if self.mode != GameMode.CHESS:
            return
        if self.board.turn != self.player_color:
            return
        if self.match_is_finished:
            return
        clicked = self.mouse_to_square(pos)
        if clicked is None:
            self.selected_square = None
            return

        clicked_piece = self.board.piece_at(clicked)
        if self.selected_square is None:
            if clicked_piece is not None and clicked_piece.color == self.board.turn:
                self.selected_square = clicked
            return

        if clicked == self.selected_square:
            self.selected_square = None
            return

        attempted = self.build_move(self.selected_square, clicked)
        if self.can_apply_move(attempted):
            self._apply_move(attempted)
            self._consume_help_tile(attempted)
            self.selected_square = None
            self.player_turn_index += 1
            self.active_help_tiles = {}
            self.active_help_characters_this_turn = set()
            self.help_tiles_rolled_this_turn = True
            self.opponent_move_cooldown = 24
            self.active_global_powers.discard("gamer_god")
            self.gamer_god_visible_this_turn = False
            self.gamer_god_hint_moves = []
            if self.match_is_finished:
                return
            self._evaluate_match_end()
            return

        if clicked_piece is not None and clicked_piece.color == self.board.turn:
            self.selected_square = clicked
        else:
            self.selected_square = None

    def _handle_keydown(self, key: int) -> None:
        if self.mode == GameMode.PETTING:
            if key == pygame.K_ESCAPE:
                self.mode = GameMode.EXPLORATION
            return

        if self.awaiting_loss_ack:
            if pygame.time.get_ticks() - self.loss_screen_started_ms >= 3000:
                self._return_to_lobby_from_chess()
            return

        if self.awaiting_return_to_lobby_confirm:
            if key in (pygame.K_n, pygame.K_ESCAPE):
                self.awaiting_return_to_lobby_confirm = False
            elif key == pygame.K_y:
                self.awaiting_return_to_lobby_confirm = False
                self._return_to_lobby_from_chess()
            return

        if self.mode == GameMode.DIALOGUE:
            if key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_e):
                self.advance_dialogue()
            return

        if self.awaiting_unlock_choice:
            if key in (pygame.K_n, pygame.K_ESCAPE):
                self.awaiting_unlock_choice = False
                self.pending_unlock_npc = None
                self.start_dialogue([DialogueLine("???", "Maybe later.")])
            return

        if self.awaiting_practice_choice:
            if key in (pygame.K_n, pygame.K_ESCAPE):
                self.awaiting_practice_choice = False
                self.start_dialogue([DialogueLine("Circe", "Okay. Talk to me when you want a practice game.")])
            elif key == pygame.K_y:
                self.awaiting_practice_choice = False
                self._enter_room(1, practice_mode=True)
            return

        if self.awaiting_shop_choice:
            if key in (pygame.K_ESCAPE, pygame.K_x):
                self.awaiting_shop_choice = False
                self.pending_shop_character_id = None
                self.shop_power_scroll = 0
            elif key == pygame.K_UP:
                self.shop_power_scroll = max(0, self.shop_power_scroll - 24)
            elif key == pygame.K_DOWN:
                self.shop_power_scroll += 24
                self._clamp_shop_power_scroll()
            return

        if self.awaiting_power_choice:
            return

        if self.awaiting_power_target_power_id is not None or self.awaiting_power_sacrifice_power_id is not None or self.awaiting_pawn_exchange_side is not None:
            if key == pygame.K_ESCAPE:
                self._cancel_pending_power_selection()
                self.chess_result_message = "Power selection canceled."
            return

        if key == pygame.K_e:
            npc = self._nearby_npc()
            if npc is None:
                return
            lines = self._dialogue_for_npc(npc) or []
            if lines:
                self.start_dialogue(lines)
            return

        if key == pygame.K_p:
            npc = self._nearby_npc()
            if npc is None or npc.npc_id != "circe":
                return
            self.open_pet_scene_after_dialogue = True
            self.start_dialogue([DialogueLine("Circe", "Meow.")])
            return

        if key == pygame.K_r and self._current_room().room_type == RoomType.CHESS_BATTLE:
            self._start_chess_match()

        if key == pygame.K_u and self.mode == GameMode.CHESS:
            if self._use_takeback():
                self.chess_result_message = "Takeback used."
            return

        if key == pygame.K_ESCAPE and self.mode == GameMode.CHESS:
            self.awaiting_return_to_lobby_confirm = True

    def _update(self) -> None:
        room = self._current_room()
        self.show_interact_hint = False
        self.active_door_hint = None

        for npc in self._current_npcs():
            npc.update()

        if self.mode == GameMode.DIALOGUE:
            return

        if self.mode == GameMode.PETTING:
            return

        if self.mode == GameMode.EXPLORATION:
            keys = pygame.key.get_pressed()
            self.player.update(keys, room.walk_bounds)
            nearby = self._nearby_npc()
            self.show_interact_hint = nearby is not None
            self._handle_doorway_collisions()
            return

        if self.mode == GameMode.CHESS:
            if not self.pre_fight_dialogue_played:
                self.pre_fight_dialogue_played = True
                return
            nearby = self._nearby_npc()
            self.show_interact_hint = nearby is not None
            self._clear_expired_piece_powers()
            if self.board.turn == self.player_color:
                if self.player_skip_turns > 0:
                    self._push_state_snapshot()
                    self.player_skip_turns -= 1
                    self.board.push(chess.Move.null())
                    self.chess_result_message = "Double penalty triggered. Rhea skipped her turn."
                    self.help_tiles_rolled_this_turn = False
                    return
                if "gamer_god" in self.next_turn_global_powers and not self.gamer_god_visible_this_turn:
                    self.gamer_god_visible_this_turn = True
                    self.gamer_god_hint_moves = self._top_stockfish_moves(self.board, top_n=3)
                    self.next_turn_global_powers.discard("gamer_god")
                    self.active_global_powers.add("gamer_god")
                if (
                    not self.active_help_tiles
                    and not self.help_tiles_rolled_this_turn
                    and not self.awaiting_power_choice
                    and self.awaiting_power_target_power_id is None
                    and not self.open_power_choice_after_dialogue
                    and not self.awaiting_shop_choice
                    and not self.awaiting_return_to_lobby_confirm
                ):
                    self._schedule_help_tiles_for_turn()
            self._maybe_make_opponent_move()

    def _draw(self) -> None:
        self._draw_room_background()
        self._draw_doors()

        room = self._current_room()
        if room.room_type == RoomType.CHESS_BATTLE:
            self._draw_chess_board()
            self._draw_power_sidebar()
            self._draw_close_button()

        for npc in self._current_npcs():
            if npc.npc_id in self.unlock_cost_by_npc and not self._is_npc_unlocked(npc.npc_id):
                pygame.draw.rect(self.screen, (20, 20, 20), npc.rect, border_radius=10)
                pygame.draw.rect(self.screen, self.config.npc_outline, npc.rect, width=2, border_radius=10)
                label = self.small_font.render("?", True, (245, 245, 250))
                self.screen.blit(label, (npc.rect.centerx - label.get_width() // 2, npc.rect.centery - label.get_height() // 2))
                continue
            npc.draw(self.screen, self.config.npc_outline)

        self.player.draw(self.screen, self.config.player_color)
        self._draw_interaction_hints()
        games_text = self.small_font.render(
            f"Points: {self.save_state.points}",
            True,
            self.config.text,
        )
        self.screen.blit(games_text, (16, 12))
        attempts_text = self.small_font.render(
            f"Neil attempts: {self.save_state.neil_attempts}",
            True,
            self.config.text,
        )
        self.screen.blit(attempts_text, (16, 32))
        if room.room_type == RoomType.CHESS_BATTLE:
            status_text = self.chess_result_message
            if self.active_help_tiles:
                active_names = ", ".join(self._character_display_name(char_id) for char_id in sorted(set(self.active_help_tiles.values())))
                status_text = f"Active help tiles: {active_names}."
            elif self.awaiting_power_choice:
                status_text = "Choose 1 offered power."
            elif self.awaiting_power_target_power_id is not None:
                status_text = self.power_definitions[self.awaiting_power_target_power_id].target_prompt or self.chess_result_message
            status_surface = self.small_font.render(status_text, True, self.config.text)
            self.screen.blit(status_surface, (self.config.board_left, self.config.board_top - 28))

        if self.awaiting_loss_ack:
            self._draw_loss_overlay()

        if self.mode == GameMode.PETTING:
            self._draw_pet_scene()
        elif self.mode == GameMode.DIALOGUE and self.dialogue_queue:
            if self.dialogue_queue == self.dialogue_scripts.get("entry_post_win"):
                self._draw_birthday_banner()
            line = self.dialogue_queue[self.dialogue_index]
            portrait = self._portrait_surface(line.portrait_key or line.speaker)
            self.draw_dialogue_box(line.speaker, line.text, portrait)
        elif self.awaiting_power_choice:
            giver = self._character_display_name(self.pending_power_character_id or "pragya")
            self._draw_popup(f"{giver}'s Gift", "Choose 1 power", self._power_popup_options())
        elif self.awaiting_shop_choice:
            self._draw_shop_popup(self.pending_shop_character_id)
        elif self.awaiting_unlock_choice:
            self._draw_popup("???", "Spend points to unlock this character?", self._unlock_options())
        elif self.awaiting_practice_choice:
            self._draw_popup("Practice Game?", "Start a practice match with Circe?", self._practice_game_options())
        elif self.awaiting_return_to_lobby_confirm:
            self._draw_popup("Return to Lobby?", "Leave the current chess game?", self._return_to_lobby_options())

        pygame.display.flip()

    def run(self) -> None:
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    self._handle_keydown(event.key)
                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    if self.mode == GameMode.DIALOGUE:
                        if (
                            not self.awaiting_unlock_choice and
                            not self.awaiting_practice_choice
                            and not self.awaiting_shop_choice
                            and not self.awaiting_power_choice
                        ):
                            self.advance_dialogue()
                    else:
                        self._handle_mouse_click(event.pos)
                elif event.type == pygame.MOUSEWHEEL:
                    if self.awaiting_shop_choice:
                        self.shop_power_scroll = max(0, self.shop_power_scroll - event.y * 24)
                        self._clamp_shop_power_scroll()
                    elif self.mode == GameMode.CHESS:
                        self.power_sidebar_scroll = max(0, self.power_sidebar_scroll - event.y * 24)
                        self._clamp_power_sidebar_scroll()

            self._update()
            self._draw()
            self.clock.tick(self.config.fps)

        self._save_state()
        pygame.quit()


def run() -> None:
    game = ChessAdventureGame()
    game.run()


if __name__ == "__main__":
    run()
