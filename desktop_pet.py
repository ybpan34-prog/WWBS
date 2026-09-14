from __future__ import annotations

import math
import random
from pathlib import Path
from tkinter import Canvas, Menu, Toplevel
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
        "failed": 145,
        "waiting": 185,
        "running": 120,
        "review": 165,
    }
    ONE_SHOT_REPEATS = {"waving": 2, "jumping": 1, "failed": 1, "review": 1, "waiting": 1}
    CHATTER_ACTIONS = ("waving", "jumping", "review", "waiting")
    COMMAND_LABELS = (
        ("检测游戏窗口", "check_target"),
        ("周常拿满奖励", "run_rewards"),
        ("周常拿满星声", "run_astrite"),
        ("一键日常（2轮双倍）", "run_daily"),
        ("4C刷取（10次）", "run_4c_10"),
        ("4C刷取（30次）", "run_4c_30"),
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
        visible: bool = True,
        on_visibility_changed: Callable[[bool], None] | None = None,
    ):
        self.root = root
        self.frames_dir = Path(frames_dir)
        self.scale = scale
        self.commands = commands or {}
        self.pet_name = pet_name
        self.idle_line_factory = idle_line_factory or (lambda: "漂泊者，要稍微休息一下吗？")
        self.look_spritesheet = Path(look_spritesheet) if look_spritesheet else None
        self.on_visibility_changed = on_visibility_changed
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
        for label, command_key in self.COMMAND_LABELS:
            command = self.commands.get(command_key)
            if command is not None:
                self.menu.add_command(label=label, command=command)
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
            self._schedule_chatter(random.randint(24000, 40000))
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
        for state in self.STATE_DELAYS:
            paths = sorted((self.frames_dir / state).glob("*.png"))
            if not paths:
                raise FileNotFoundError(f"桌宠动画帧缺失：{self.frames_dir / state}")
            state_frames = []
            for path in paths:
                with Image.open(path) as source:
                    image = source.convert("RGBA")
                    target = (round(image.width * self.scale), round(image.height * self.scale))
                    if target != image.size:
                        image = image.resize(target, Image.Resampling.LANCZOS)
                    state_frames.append(ImageTk.PhotoImage(image, master=self.window))
            loaded[state] = state_frames
        return loaded

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
                if target != image.size:
                    image = image.resize(target, Image.Resampling.LANCZOS)
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
        if not self.look_frames or self.state != "idle" or self.dragging or self.working:
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
        self.canvas.itemconfigure(
            self.image_item,
            image=look_frame if look_frame is not None else sequence[self.frame_index],
        )
        self.frame_index += 1
        if self.frame_index >= len(sequence):
            self.frame_index = 0
            self.state_cycles += 1
            required_cycles = self.ONE_SHOT_REPEATS.get(self.state)
            if required_cycles is not None and self.state_cycles >= required_cycles and not self.dragging:
                self.state = "idle"
                self.state_cycles = 0
        self._animation_job = self.window.after(self.STATE_DELAYS[self.state], self._animate)

    def play(self, state: str):
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
        body_top = 9
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

        badge = self._rounded_rect_points(17, 1, 88, 28, 12)
        canvas.create_polygon(badge, smooth=True, splinesteps=20, fill=palette["badge"], outline=palette["badge_outline"], width=1)
        canvas.create_text(52, 14, text=self.pet_name, fill="#ffffff", font=("Microsoft YaHei UI", 9, "bold"))
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
        wait_ms = delay if delay is not None else random.randint(32000, 62000)
        self._chatter_job = self.window.after(wait_ms, self._chatter_tick)

    def _chatter_tick(self):
        self._chatter_job = None
        if self.visible and self.state == "idle" and not self.dragging and self._bubble_job is None:
            generated = self.idle_line_factory()
            text = str(getattr(generated, "text", generated))
            action = str(getattr(generated, "action", random.choice(self.CHATTER_ACTIONS)))
            if action in self.frames and action != "idle":
                self.play(action)
            self.say(text, 4600)
        self._schedule_chatter()

    def _start_drag(self, event):
        self.dragging = True
        self._drag_offset = (event.x_root - self.window.winfo_x(), event.y_root - self.window.winfo_y())
        self._cancel_move()

    def _drag(self, event):
        x = event.x_root - self._drag_offset[0]
        y = event.y_root - self._drag_offset[1]
        self.window.geometry(f"+{x}+{y}")
        self._position_bubble()
        self.play("running-right" if event.x_root >= self.window.winfo_x() + self.width // 2 else "running-left")

    def _stop_drag(self, _event):
        self.dragging = False
        self.play("idle")
        self._schedule_roam(3500)

    def _interact(self, _event=None):
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
            self._cancel_roam()
            self._cancel_move()
        elif self.visible and self.roaming and not self.dragging:
            self._schedule_roam(3500)

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
        self._schedule_chatter(random.randint(18000, 34000))
        self._notify_visibility_changed()

    def hide(self):
        if not self.visible:
            return
        self.visible = False
        self._cancel_roam()
        self._cancel_move()
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
        if self._chatter_job:
            try:
                self.window.after_cancel(self._chatter_job)
            except Exception:
                pass
        if self.bubble_window.winfo_exists():
            self.bubble_window.destroy()
        if self.window.winfo_exists():
            self.window.destroy()
