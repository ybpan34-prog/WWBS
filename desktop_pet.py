from __future__ import annotations

import math
import random
from pathlib import Path
from tkinter import BooleanVar, Canvas, Menu, Toplevel
from typing import Callable

from PIL import Image, ImageTk

class DesktopPet:
    """Transparent, draggable desktop-pet window driven by PNG frame folders."""

    STATE_DELAYS = {
        "idle": 160,
        "running-right": 85,
        "running-left": 85,
        "waving": 260,
        "jumping": 105,
        "landing": 150,
        "failed": 145,
        "waiting": 185,
        "running": 120,
        "review": 165,
    }
    ONE_SHOT_REPEATS = {
        "waving": 2,
        "jumping": 1,
        "landing": 4,
        "failed": 1,
        "review": 1,
        "waiting": 1,
    }
    CHATTER_ACTIONS = ("waving", "jumping", "review", "waiting")
    COMMAND_LABELS = (
        ("周常拿满奖励", "run_rewards"),
        ("周常拿满星声", "run_astrite"),
        ("一键日常（2轮双倍）", "run_daily"),
        ("4C刷取（自定义次数）", "run_4c_custom"),
        ("停止当前任务", "stop_task"),
    )

    def __init__(
        self,
        root,
        frames_dir: Path,
        scale: float = 1.15,
        commands: dict[str, Callable[[], None]] | None = None,
        pet_name: str = "达妮娅",
        app_version: str = "1.3.9 beta",
        app_icon: Path | None = None,
        idle_line_factory: Callable[[], object] | None = None,
        bubble_palette: dict[str, str] | None = None,
        look_spritesheet: Path | None = None,
        alpha_cutoff: int | None = None,
        look_enabled: bool = True,
        auto_jump_enabled: bool | None = None,
        forward_jump_enabled: bool = False,
        visible: bool = True,
        on_visibility_changed: Callable[[bool], None] | None = None,
        on_look_enabled_changed: Callable[[bool], None] | None = None,
        on_auto_jump_enabled_changed: Callable[[bool], None] | None = None,
        speak_on_interact: bool = False,
        chatter_delay_range: tuple[int, int] | None = None,
        allow_generated_speech: Callable[[], bool] | None = None,
    ):
        self.root = root
        self.frames_dir = Path(frames_dir)
        self.scale = scale
        self.commands = commands or {}
        self.pet_name = pet_name
        self.idle_line_factory = idle_line_factory or (lambda: "漂泊者，要稍微休息一下吗？")
        self.allow_generated_speech = allow_generated_speech or (lambda: True)
        self.look_spritesheet = Path(look_spritesheet) if look_spritesheet else None
        self.alpha_cutoff = (
            max(0, min(254, int(alpha_cutoff))) if alpha_cutoff is not None else None
        )
        self.look_enabled = bool(look_enabled)
        self.auto_jump_enabled = (
            None if auto_jump_enabled is None else bool(auto_jump_enabled)
        )
        self.forward_jump_enabled = bool(forward_jump_enabled)
        self.on_visibility_changed = on_visibility_changed
        self.on_look_enabled_changed = on_look_enabled_changed
        self.on_auto_jump_enabled_changed = on_auto_jump_enabled_changed
        self.speak_on_interact = bool(speak_on_interact)
        self.chatter_delay_range = chatter_delay_range
        self.visible = bool(visible)
        self.bubble_palette = {
            "shadow": "#d9acc5",
            "body": "#fff8fc",
            "outline": "#e58ab8",
            "badge": "#e887b7",
            "badge_outline": "#d66ca2",
            "ornament": "#d7ad63",
            "ornament_outline": "#c48f3f",
            "text": "#5d3650",
            **(bubble_palette or {}),
        }
        self.window = Toplevel(root)
        self._configure_auxiliary_window(self.window, app_icon)
        self.window.title(f"{self.pet_name} · wwbs {app_version}")
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        if not self.visible:
            self.window.withdraw()
        self.transparent = "#010203"
        self.window.configure(bg=self.transparent)
        try:
            self.window.wm_attributes("-transparentcolor", self.transparent)
        except Exception:
            pass

        self.frames = self._load_frames()
        self.look_frames = self._load_look_frames()
        first = self.frames["idle"][0]
        self.width, self.height = first.width(), first.height()
        self.canvas = Canvas(
            self.window,
            width=self.width,
            height=self.height,
            bg=self.transparent,
            highlightthickness=0,
            bd=0,
        )
        self.canvas.pack()
        self.image_item = self.canvas.create_image(self.width // 2, self.height // 2, image=first)
        self.canvas.bind("<ButtonPress-1>", self._start_drag)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._stop_drag)
        self.canvas.bind("<Double-Button-1>", self._interact)
        self.canvas.bind("<Button-3>", self._popup_menu)

        self.menu = Menu(self.window, tearoff=False)
        diagnose = self.commands.get("diagnose")
        if diagnose is not None:
            self.menu.add_command(label=f"{self.pet_name}帮我诊断", command=diagnose)
        chat = self.commands.get("chat")
        if chat is not None:
            self.menu.add_command(label=f"和{self.pet_name}聊天", command=chat)
        if self.commands.get("chat_history") is not None:
            self.menu.add_command(label="查看聊天记录", command=self.commands["chat_history"])
        for label, command_key in self.COMMAND_LABELS:
            command = self.commands.get(command_key)
            if command is not None:
                self.menu.add_command(label=label, command=command)
        self.menu.add_separator()
        self.look_enabled_var = None
        self.auto_jump_enabled_var = None
        if self.auto_jump_enabled is not None:
            self.look_enabled_var = BooleanVar(master=self.window, value=self.look_enabled)
            self.auto_jump_enabled_var = BooleanVar(
                master=self.window,
                value=self.auto_jump_enabled,
            )
            self.menu.add_checkbutton(
                label="盯鼠标",
                variable=self.look_enabled_var,
                command=self._toggle_look_from_menu,
            )
            self.menu.add_checkbutton(
                label="定时跳跃（每45至90秒尝试一次）",
                variable=self.auto_jump_enabled_var,
                command=self._toggle_auto_jump_from_menu,
            )
            self.menu.add_separator()
        self.menu.add_command(label="开启/关闭漫游", command=self.toggle_roaming)
        size_menu = Menu(self.menu, tearoff=False)
        for percent in (70, 85, 100, 115, 130, 150):
            command = self.commands.get(f"pet_size_{percent}")
            if command is not None:
                size_menu.add_command(label=f"{percent}%", command=command)
        if size_menu.index("end") is not None:
            self.menu.add_cascade(label="调整大小", menu=size_menu)
        self.menu.add_command(label=f"隐藏{self.pet_name}", command=self.hide)

        self.bubble_window = Toplevel(self.window)
        self._configure_auxiliary_window(self.bubble_window, app_icon)
        self.bubble_window.overrideredirect(True)
        self.bubble_window.attributes("-topmost", True)
        self.bubble_window.configure(bg=self.transparent)
        try:
            self.bubble_window.wm_attributes("-transparentcolor", self.transparent)
        except Exception:
            pass
        self.bubble_canvas = Canvas(
            self.bubble_window,
            width=300,
            height=110,
            bg=self.transparent,
            highlightthickness=0,
            bd=0,
        )
        self.bubble_canvas.pack()
        self.bubble_size = (300, 110)
        self.bubble_text = ""
        self.bubble_window.withdraw()

        self.state = "idle"
        self.frame_index = 0
        self.state_cycles = 0
        self.dragging = False
        self.roaming = True
        self.working = False
        self._drag_offset = (0, 0)
        self._animation_job = None
        self._roam_job = None
        self._move_job = None
        self._bubble_job = None
        self._chatter_job = None
        self._auto_jump_job = None
        self._jump_motion_job = None
        self._jump_origin = (0, 0)
        self._jump_step = 0
        self._jump_total_steps = 18
        self._jump_height = 112
        self._airborne = False
        self._facing_direction = 1
        self._move_remaining = 0
        self._move_step = 0

        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(10, screen_w - self.width - 54)
        y = max(10, screen_h - self.height - 72)
        self.window.geometry(f"{self.width}x{self.height}+{x}+{y}")
        if self.visible:
            self._animate()
            self._schedule_roam(4200)
            self._schedule_chatter(self._next_chatter_delay(24000, 40000))
            self._schedule_auto_jump()
        else:
            self.window.withdraw()

    @staticmethod
    def _configure_auxiliary_window(window, app_icon: Path | None) -> None:
        """Keep pet windows out of the taskbar and inherit the wwbs icon."""
        if app_icon is not None and Path(app_icon).exists():
            try:
                window.iconbitmap(str(app_icon))
            except Exception:
                pass
        try:
            window.wm_attributes("-toolwindow", True)
        except Exception:
            pass

    def _load_frames(self):
        loaded = {}
        landing_image = None
        for state in self.STATE_DELAYS:
            if state == "landing":
                continue
            paths = sorted((self.frames_dir / state).glob("*.png"))
            if not paths:
                raise FileNotFoundError(f"桌宠动画帧缺失：{self.frames_dir / state}")
            state_frames = []
            for path in paths:
                with Image.open(path) as source:
                    target = (round(source.width * self.scale), round(source.height * self.scale))
                    image = self._scale_and_prepare_image(source, target)
                    state_frames.append(ImageTk.PhotoImage(image, master=self.window))
                    if state == "jumping" and landing_image is None:
                        landing_image = self._scale_and_prepare_landing_image(source, target)
            loaded[state] = state_frames
        if landing_image is not None:
            loaded["landing"] = [ImageTk.PhotoImage(landing_image, master=self.window)]
        return loaded

    def _prepare_image(self, source: Image.Image) -> Image.Image:
        """Prepare RGBA art for Tk's color-keyed transparent windows.

        Windows/Tk composites partially transparent pixels against the window's
        transparent color before applying ``-transparentcolor``. That creates
        dark, fuzzy fringes on detailed light-colored sprites. Character packs
        may opt into a binary alpha edge so their clean source RGB reaches the
        desktop without that intermediate matte.
        """
        image = source.convert("RGBA")
        if self.alpha_cutoff is None:
            return image
        alpha = image.getchannel("A").point(
            lambda value: 255 if value > self.alpha_cutoff else 0
        )
        image.putalpha(alpha)
        return image

    def _scale_and_prepare_image(
        self,
        source: Image.Image,
        target: tuple[int, int],
    ) -> Image.Image:
        """Resize first, then remove partial alpha introduced by resampling."""
        image = source.convert("RGBA")
        if target != image.size:
            image = image.resize(target, Image.Resampling.LANCZOS)
        return self._prepare_image(image)

    def _scale_and_prepare_landing_image(
        self,
        source: Image.Image,
        target: tuple[int, int],
        factor: float = 0.94,
    ) -> Image.Image:
        """Make a subtly compressed landing pose while keeping its feet grounded."""
        image = source.convert("RGBA")
        landing_size = (
            max(1, round(target[0] * factor)),
            max(1, round(target[1] * factor)),
        )
        image = image.resize(landing_size, Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", target, (0, 0, 0, 0))
        canvas.alpha_composite(
            image,
            ((target[0] - landing_size[0]) // 2, target[1] - landing_size[1]),
        )
        return self._prepare_image(canvas)

    def _load_look_frames(self):
        """Load the v2 atlas' 16 clockwise look directions (0 degrees is up)."""
        if self.look_spritesheet is None or not self.look_spritesheet.exists():
            return []
        loaded = []
        with Image.open(self.look_spritesheet) as source:
            atlas = source.convert("RGBA")
            if atlas.width % 8 or atlas.height % 11:
                return []
            cell_width = atlas.width // 8
            cell_height = atlas.height // 11
            for index in range(16):
                row = 9 + index // 8
                column = index % 8
                image = atlas.crop(
                    (
                        column * cell_width,
                        row * cell_height,
                        (column + 1) * cell_width,
                        (row + 1) * cell_height,
                    )
                )
                target = (round(cell_width * self.scale), round(cell_height * self.scale))
                image = self._scale_and_prepare_image(image, target)
                loaded.append(ImageTk.PhotoImage(image, master=self.window))
        return loaded

    @staticmethod
    def _look_direction_index(dx: float, dy: float, deadzone: float = 0.0) -> int | None:
        """Map a pointer offset to 16 clockwise directions, starting at up."""
        if math.hypot(dx, dy) <= deadzone:
            return None
        degrees = math.degrees(math.atan2(dx, -dy)) % 360.0
        return int((degrees + 11.25) // 22.5) % 16

    def _pointer_look_frame(self):
        if (
            not self.look_enabled
            or not self.look_frames
            or self.state != "idle"
            or self.dragging
            or self.working
        ):
            return None
        center_x = self.window.winfo_rootx() + self.width / 2
        head_y = self.window.winfo_rooty() + self.height * 0.36
        dx = self.window.winfo_pointerx() - center_x
        dy = self.window.winfo_pointery() - head_y
        deadzone = max(42.0, min(self.width, self.height) * 0.22)
        direction = self._look_direction_index(dx, dy, deadzone)
        return None if direction is None else self.look_frames[direction]

    def set_scale(self, scale: float) -> None:
        """Resize every animation frame while keeping the pet's feet in place."""
        new_scale = max(0.45, min(2.25, float(scale)))
        if abs(new_scale - self.scale) < 0.001:
            return

        self.window.update_idletasks()
        self._cancel_forward_jump(restore_ground=True)
        old_center_x = self.window.winfo_x() + self.width // 2
        old_bottom_y = self.window.winfo_y() + self.height
        self.scale = new_scale
        self.frames = self._load_frames()
        self.look_frames = self._load_look_frames()

        sequence = self.frames.get(self.state, self.frames["idle"])
        first = sequence[0]
        self.width, self.height = first.width(), first.height()
        self.canvas.configure(width=self.width, height=self.height)
        self.canvas.coords(self.image_item, self.width // 2, self.height // 2)
        self.canvas.itemconfigure(self.image_item, image=first)
        self.frame_index = 1 % len(sequence)
        self.state_cycles = 0

        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        x = max(0, min(screen_w - self.width, old_center_x - self.width // 2))
        y = max(0, min(screen_h - self.height, old_bottom_y - self.height))
        self.window.geometry(f"{self.width}x{self.height}+{x}+{y}")
        if self.bubble_window.winfo_viewable():
            self._position_bubble()

    def _animate(self):
        if not self.visible:
            return
        sequence = self.frames[self.state]
        look_frame = self._pointer_look_frame()
        airborne_frame = (
            sequence[len(sequence) // 2]
            if self.state == "jumping" and self._airborne
            else None
        )
        self.canvas.itemconfigure(
            self.image_item,
            image=(
                look_frame
                if look_frame is not None
                else airborne_frame if airborne_frame is not None else sequence[self.frame_index]
            ),
        )
        if airborne_frame is None:
            self.frame_index += 1
        if self.frame_index >= len(sequence):
            self.frame_index = 0
            self.state_cycles += 1
            required_cycles = self.ONE_SHOT_REPEATS.get(self.state)
            if required_cycles is not None and self.state_cycles >= required_cycles and not self.dragging:
                if not (self.state == "jumping" and self._airborne):
                    self.state = "idle"
                    self.state_cycles = 0
        self._animation_job = self.window.after(self.STATE_DELAYS[self.state], self._animate)

    def play(self, state: str):
        if state == "jumping" and self.forward_jump_enabled and not self._airborne:
            if self._begin_forward_jump():
                return
        if state not in self.frames:
            return
        if state == self.state:
            return
        self.state = state
        self.frame_index = 0
        self.state_cycles = 0

    def say(self, text: str, duration: int = 3200):
        if not self.visible:
            return
        if self._bubble_job:
            try:
                self.bubble_window.after_cancel(self._bubble_job)
            except Exception:
                pass
        self.bubble_text = text
        self._draw_bubble(text)
        self.bubble_window.deiconify()
        self.bubble_window.lift()
        self._position_bubble()
        self._bubble_job = self.bubble_window.after(duration, self._hide_bubble)

    @staticmethod
    def _rounded_rect_points(x1: int, y1: int, x2: int, y2: int, radius: int) -> list[int]:
        return [
            x1 + radius, y1, x2 - radius, y1,
            x2, y1, x2, y1 + radius,
            x2, y2 - radius, x2, y2,
            x2 - radius, y2, x1 + radius, y2,
            x1, y2, x1, y2 - radius,
            x1, y1 + radius, x1, y1,
        ]

    @staticmethod
    def _name_badge_width(name: str) -> int:
        """Leave enough room for four-character names without crowding the badge."""
        return max(76, min(160, 28 + len(name) * 16))

    def _draw_bubble(self, text: str):
        canvas = self.bubble_canvas
        palette = self.bubble_palette
        canvas.delete("all")
        probe = canvas.create_text(
            0,
            0,
            text=text,
            width=254,
            font=("Microsoft YaHei UI", 10, "bold"),
            anchor="nw",
        )
        canvas.update_idletasks()
        bbox = canvas.bbox(probe) or (0, 0, 254, 38)
        text_height = bbox[3] - bbox[1]
        canvas.delete(probe)

        width = 300
        body_top = 13
        body_bottom = body_top + max(78, text_height + 51)
        height = body_bottom + 24
        self.bubble_size = (width, height)
        canvas.configure(width=width, height=height)

        center = width // 2
        shadow = self._rounded_rect_points(8, body_top + 4, width - 4, body_bottom + 5, 18)
        canvas.create_polygon(shadow, smooth=True, splinesteps=24, fill=palette["shadow"], outline="")
        canvas.create_polygon(
            center - 11, body_bottom + 3,
            center + 15, body_bottom + 3,
            center + 2, body_bottom + 22,
            fill=palette["shadow"],
            outline="",
        )
        canvas.create_polygon(
            center - 12, body_bottom - 1,
            center + 12, body_bottom - 1,
            center, body_bottom + 19,
            fill=palette["body"],
            outline=palette["outline"],
            width=2,
        )
        body = self._rounded_rect_points(4, body_top, width - 8, body_bottom, 18)
        canvas.create_polygon(
            body,
            smooth=True,
            splinesteps=24,
            fill=palette["body"],
            outline=palette["outline"],
            width=2,
        )

        badge_width = self._name_badge_width(self.pet_name)
        badge_left = 17
        badge_right = badge_left + badge_width
        badge = self._rounded_rect_points(badge_left, 4, badge_right, 32, 12)
        canvas.create_polygon(badge, smooth=True, splinesteps=20, fill=palette["badge"], outline=palette["badge_outline"], width=1)
        canvas.create_text(
            (badge_left + badge_right) // 2,
            18,
            text=self.pet_name,
            fill="#ffffff",
            font=("Microsoft YaHei UI", 9, "bold"),
        )
        canvas.create_polygon(
            width - 25, 14,
            width - 19, 22,
            width - 25, 30,
            width - 31, 22,
            fill=palette["ornament"],
            outline=palette["ornament_outline"],
            width=1,
        )
        canvas.create_text(
            20,
            37,
            text=text,
            width=254,
            fill=palette["text"],
            font=("Microsoft YaHei UI", 10, "bold"),
            justify="left",
            anchor="nw",
        )

    def _position_bubble(self):
        if not self.visible:
            return
        self.bubble_window.update_idletasks()
        bubble_w, bubble_h = self.bubble_size
        screen_w = self.root.winfo_screenwidth()
        x = self.window.winfo_x() + ((self.width - bubble_w) // 2)
        x = max(6, min(screen_w - bubble_w - 6, x))
        y = self.window.winfo_y() - bubble_h + 14
        if y < 6:
            y = self.window.winfo_y() + 42
        self.bubble_window.geometry(f"{bubble_w}x{bubble_h}+{x}+{y}")

    def _hide_bubble(self):
        self._bubble_job = None
        if self.bubble_window.winfo_exists():
            self.bubble_window.withdraw()

    def _schedule_chatter(self, delay: int | None = None):
        if self._chatter_job:
            try:
                self.window.after_cancel(self._chatter_job)
            except Exception:
                pass
        wait_ms = delay if delay is not None else self._next_chatter_delay(32000, 62000)
        self._chatter_job = self.window.after(wait_ms, self._chatter_tick)

    def _next_chatter_delay(self, default_low: int, default_high: int) -> int:
        if self.chatter_delay_range is None:
            return random.randint(default_low, default_high)
        low, high = self.chatter_delay_range
        low = max(1000, int(low))
        high = max(low, int(high))
        return random.randint(low, high)

    def _chatter_tick(self):
        self._chatter_job = None
        if self.visible and self.state == "idle" and not self.dragging and self._bubble_job is None:
            self._speak_generated_line()
            self._schedule_chatter()
            return
        retry_delay = random.randint(4000, 8000) if self.chatter_delay_range else None
        self._schedule_chatter(retry_delay)

    def _speak_generated_line(self, play_action: bool = True) -> None:
        if not getattr(self, "allow_generated_speech", lambda: True)():
            return
        generated = self.idle_line_factory()
        text = str(getattr(generated, "text", generated))
        action = str(getattr(generated, "action", random.choice(self.CHATTER_ACTIONS)))
        if action == "jumping" and self.auto_jump_enabled is False:
            action = random.choice(("waving", "review", "waiting"))
        if play_action and action in self.frames and action != "idle":
            self.play(action)
        self.say(text, 4600)

    def _schedule_auto_jump(self, delay: int | None = None) -> None:
        self._cancel_auto_jump()
        if (
            self.auto_jump_enabled is True
            and self.visible
            and not self.working
        ):
            wait_ms = delay if delay is not None else random.randint(45000, 90000)
            self._auto_jump_job = self.window.after(wait_ms, self._auto_jump_tick)

    def _auto_jump_tick(self) -> None:
        self._auto_jump_job = None
        if (
            self.auto_jump_enabled is True
            and self.visible
            and not self.working
            and self.state == "idle"
            and not self.dragging
            and self._bubble_job is None
        ):
            self.play("jumping")
        self._schedule_auto_jump()

    def _begin_forward_jump(self) -> bool:
        if (
            not self.visible
            or self.working
            or self.dragging
            or self.state != "idle"
            or self._jump_motion_job is not None
        ):
            return False
        self._cancel_roam()
        self._cancel_move()
        screen_width = self.root.winfo_screenwidth()
        x = self.window.winfo_x()
        y = self.window.winfo_y()
        direction = self._facing_direction
        if x < 84:
            direction = 1
        elif x + self.width > screen_width - 84:
            direction = -1
        self._facing_direction = direction
        self._jump_origin = (x, y)
        self._jump_step = 0
        self._airborne = True
        self.state = "jumping"
        self.frame_index = 0
        self.state_cycles = 0
        self._show_airborne_pose()
        self._jump_motion_tick()
        return True

    def _show_airborne_pose(self) -> None:
        """Keep the jump pose visible for every moment before touchdown."""
        jump_frames = getattr(self, "frames", {}).get("jumping", [])
        if not jump_frames or not hasattr(self, "canvas"):
            return
        self.canvas.itemconfigure(
            self.image_item,
            image=jump_frames[len(jump_frames) // 2],
        )

    def _jump_motion_tick(self) -> None:
        self._jump_motion_job = None
        if not self._airborne or not self.visible or self.working or self.dragging:
            self._cancel_forward_jump(restore_ground=True)
            return
        self._jump_step += 1
        progress = min(1.0, self._jump_step / self._jump_total_steps)
        origin_x, origin_y = self._jump_origin
        screen_width = self.root.winfo_screenwidth()
        travel = round(84 * progress) * self._facing_direction
        lift = round(self._jump_height * 4 * progress * (1.0 - progress))
        x = max(0, min(screen_width - self.width, origin_x + travel))
        y = origin_y - lift
        self.window.geometry(f"+{x}+{y}")
        self._show_airborne_pose()
        self._position_bubble()
        if self._jump_step >= self._jump_total_steps:
            self._finish_forward_jump(x, origin_y)
            return
        self._jump_motion_job = self.window.after(40, self._jump_motion_tick)

    def _finish_forward_jump(self, x: int, ground_y: int) -> None:
        self._jump_motion_job = None
        self._airborne = False
        self.window.geometry(f"+{x}+{ground_y}")
        self.state = "landing" if "landing" in self.frames else "idle"
        self.frame_index = 0
        self.state_cycles = 0
        if self.roaming and not self.working:
            self._schedule_roam(1800)

    def _cancel_forward_jump(self, restore_ground: bool) -> None:
        if self._jump_motion_job:
            try:
                self.window.after_cancel(self._jump_motion_job)
            except Exception:
                pass
            self._jump_motion_job = None
        if self._airborne and restore_ground:
            origin_y = self._jump_origin[1]
            self.window.geometry(f"+{self.window.winfo_x()}+{origin_y}")
        if self._airborne:
            self._airborne = False
            self.state = "idle"
            self.frame_index = 0
            self.state_cycles = 0

    def _cancel_auto_jump(self) -> None:
        if self._auto_jump_job:
            try:
                self.window.after_cancel(self._auto_jump_job)
            except Exception:
                pass
            self._auto_jump_job = None

    def set_look_enabled(self, enabled: bool) -> None:
        self.look_enabled = bool(enabled)
        look_variable = getattr(self, "look_enabled_var", None)
        if look_variable is not None:
            look_variable.set(self.look_enabled)

    def set_auto_jump_enabled(self, enabled: bool) -> None:
        self.auto_jump_enabled = bool(enabled)
        jump_variable = getattr(self, "auto_jump_enabled_var", None)
        if jump_variable is not None:
            jump_variable.set(self.auto_jump_enabled)
        if self.auto_jump_enabled:
            self._schedule_auto_jump()
        else:
            self._cancel_auto_jump()

    def _toggle_look_from_menu(self) -> None:
        if getattr(self, "look_enabled_var", None) is None:
            return
        self.look_enabled = bool(self.look_enabled_var.get())
        if self.on_look_enabled_changed is not None:
            self.on_look_enabled_changed(self.look_enabled)

    def _toggle_auto_jump_from_menu(self) -> None:
        if getattr(self, "auto_jump_enabled_var", None) is None:
            return
        self.set_auto_jump_enabled(bool(self.auto_jump_enabled_var.get()))
        if self.on_auto_jump_enabled_changed is not None:
            self.on_auto_jump_enabled_changed(bool(self.auto_jump_enabled))

    def _start_drag(self, event):
        self._cancel_forward_jump(restore_ground=True)
        self.dragging = True
        self._drag_offset = (event.x_root - self.window.winfo_x(), event.y_root - self.window.winfo_y())
        self._cancel_move()

    def _drag(self, event):
        x = event.x_root - self._drag_offset[0]
        y = event.y_root - self._drag_offset[1]
        self.window.geometry(f"+{x}+{y}")
        self._position_bubble()
        self._facing_direction = 1 if event.x_root >= self.window.winfo_x() + self.width // 2 else -1
        self.play("running-right" if self._facing_direction > 0 else "running-left")

    def _stop_drag(self, _event):
        self.dragging = False
        self.play("idle")
        self._schedule_roam(3500)

    def _interact(self, _event=None):
        if self.forward_jump_enabled:
            if self.speak_on_interact:
                self._speak_generated_line(play_action=False)
                self._schedule_chatter()
            self.play("jumping")
            return
        if self.speak_on_interact:
            self._speak_generated_line()
            self._schedule_chatter()
            return
        self.play(random.choice(("waving", "jumping", "review")))

    def _popup_menu(self, event):
        try:
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()

    def toggle_roaming(self):
        self.roaming = not self.roaming
        if self.roaming and not self.working:
            self._schedule_roam(800)
        else:
            self._cancel_roam()
            self._cancel_move()
            if not self.working:
                self.play("idle")

    def set_working(self, working: bool) -> None:
        """Temporarily pause autonomous movement while an automation task runs."""
        if self.working == working:
            return
        self.working = working
        if working:
            self._cancel_forward_jump(restore_ground=True)
            self._cancel_roam()
            self._cancel_move()
            self._cancel_auto_jump()
        elif self.visible:
            if self.roaming and not self.dragging:
                self._schedule_roam(3500)
            self._schedule_auto_jump()

    def _schedule_roam(self, delay=5000):
        self._cancel_roam()
        if self.visible and self.roaming and not self.working and not self.dragging:
            self._roam_job = self.window.after(delay, self._begin_roam)

    def _begin_roam(self):
        self._roam_job = None
        if not (self.visible and self.roaming) or self.working or self.dragging:
            return
        direction = random.choice((-1, 1))
        screen_w = self.root.winfo_screenwidth()
        x = self.window.winfo_x()
        if x < 35:
            direction = 1
        elif x + self.width > screen_w - 35:
            direction = -1
        self._move_step = 4 * direction
        self._facing_direction = direction
        self._move_remaining = random.randint(22, 48)
        self.play("running-right" if direction > 0 else "running-left")
        self._move_tick()

    def _move_tick(self):
        if self._move_remaining <= 0 or self.dragging or self.working or not self.roaming:
            self._move_job = None
            self.play("idle")
            self._schedule_roam(random.randint(4200, 7200))
            return
        screen_w = self.root.winfo_screenwidth()
        x = max(0, min(screen_w - self.width, self.window.winfo_x() + self._move_step))
        self.window.geometry(f"+{x}+{self.window.winfo_y()}")
        self._position_bubble()
        self._move_remaining -= 1
        self._move_job = self.window.after(45, self._move_tick)

    def _cancel_move(self):
        if self._move_job:
            try:
                self.window.after_cancel(self._move_job)
            except Exception:
                pass
            self._move_job = None

    def _cancel_roam(self):
        if self._roam_job:
            try:
                self.window.after_cancel(self._roam_job)
            except Exception:
                pass
            self._roam_job = None

    def show(self):
        if self.visible:
            return
        self.visible = True
        self.window.deiconify()
        self.frame_index = 0
        self._animate()
        if not self.working:
            self._schedule_roam(2500)
        self._schedule_chatter(self._next_chatter_delay(18000, 34000))
        self._schedule_auto_jump()
        self._notify_visibility_changed()

    def hide(self):
        if not self.visible:
            return
        self.visible = False
        self._cancel_roam()
        self._cancel_move()
        self._cancel_auto_jump()
        self._cancel_forward_jump(restore_ground=True)
        self._hide_bubble()
        if self._chatter_job:
            try:
                self.window.after_cancel(self._chatter_job)
            except Exception:
                pass
            self._chatter_job = None
        if self._animation_job:
            try:
                self.window.after_cancel(self._animation_job)
            except Exception:
                pass
            self._animation_job = None
        self.window.withdraw()
        self._notify_visibility_changed()

    def _notify_visibility_changed(self) -> None:
        if self.on_visibility_changed is None:
            return
        self.on_visibility_changed(self.visible)

    def toggle_visible(self):
        self.hide() if self.visible else self.show()

    def close(self):
        self.visible = False
        self._cancel_roam()
        self._cancel_move()
        self._cancel_auto_jump()
        self._cancel_forward_jump(restore_ground=True)
        if self._chatter_job:
            try:
                self.window.after_cancel(self._chatter_job)
            except Exception:
                pass
        if self.bubble_window.winfo_exists():
            self.bubble_window.destroy()
        if self.window.winfo_exists():
            self.window.destroy()
