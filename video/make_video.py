#!/usr/bin/env python3
"""台本（YAML）から動画を作る。

    python3 video/make_video.py video/sample/台本.yaml
    python3 video/make_video.py 台本.yaml -o workspace/動画.mp4
    python3 video/make_video.py 台本.yaml --preview   # 各シーンの静止画だけ並べて確認

画像・音声のパスは、台本ファイルの置き場所からの相対パスで書く。
書き方は video/README.md を参照。
"""

import argparse
import math
import shutil
import subprocess
import sys
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parents[1]

SIZES = {"横": (1920, 1080), "縦": (1080, 1920), "正方形": (1080, 1080)}

# 上から順に探して、最初に見つかったフォントを使う（設定の「フォント」が優先）
FONT_CANDIDATES = [
    "/System/Library/Fonts/ヒラギノ角ゴシック W8.ttc",
    "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/meiryob.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
]

POSITIONS = {
    "左上": (0, 0), "上": (0.5, 0), "右上": (1, 0),
    "左": (0, 0.5), "中央": (0.5, 0.5), "右": (1, 0.5),
    "左下": (0, 1), "下": (0.5, 1), "右下": (1, 1),
}
TEXT_SIZES = {"特大": 0.13, "大": 0.10, "中": 0.07, "小": 0.05}

# 行頭に来ないようにする文字
NO_HEAD = set("、。，．・：；？！ー）」』】〉》〕ぁぃぅぇぉっゃゅょゎァィゥェォッャュョヮヵヶ…!?,.)")

POP_SEC = 0.2       # 文字が「ポン」と出る時間
FADE_SEC = 0.3      # フェードで出る時間
CHUNK_FADE = 0.12   # 「／」で区切った続きが出る時間
MOUTH_SEC = 0.12    # 口パクの開け閉めの間隔
TRANSITION_SEC = {"ワイプ": 0.5, "フェード": 0.4}


class DaihonError(Exception):
    """台本の書き方の間違い。そのまま利用者に見せる日本語メッセージを持つ。"""


def check_keys(d, allowed, where):
    if not isinstance(d, dict):
        raise DaihonError(f"{where} の書き方が違います。「項目: 値」の形で書いてください")
    unknown = [k for k in d if k not in allowed]
    if unknown:
        raise DaihonError(
            f"{where} に知らない項目があります: {'、'.join(map(str, unknown))}"
            f"（使える項目: {'、'.join(allowed)}）")


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def rgb(hex_color):
    s = str(hex_color).lstrip("#")
    if len(s) != 6:
        raise DaihonError(f"色の指定が読めません: {hex_color}（#E8452C のように書いてください）")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def ease_out_back(p):
    c = 1.70158
    return 1 + (c + 1) * (p - 1) ** 3 + c * (p - 1) ** 2


def with_alpha(img, alpha):
    img = img.copy()
    img.putalpha(img.getchannel("A").point(lambda v: int(v * alpha)))
    return img


def audio_seconds(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        raise DaihonError(f"音声ファイルの長さが読めません: {path}")


class Ctx:
    """台本全体の設定と、画像・フォントの読み込み。"""

    SETTING_KEYS = ["サイズ", "FPS", "フォント", "BGM", "BGM音量",
                    "文字色", "強調色", "縁色", "切り替え色", "出力"]

    def __init__(self, cfg, base_dir):
        check_keys(cfg, self.SETTING_KEYS, "設定")
        self.base_dir = base_dir
        size = cfg.get("サイズ", "横")
        if isinstance(size, str):
            if size not in SIZES:
                raise DaihonError(f"サイズは {'、'.join(SIZES)} か [幅, 高さ] で書いてください")
            size = SIZES[size]
        self.W, self.H = int(size[0]), int(size[1])
        self.fps = int(cfg.get("FPS", 30))
        self.text_color = rgb(cfg.get("文字色", "#1E2A4A"))
        self.accent = rgb(cfg.get("強調色", "#E8452C"))
        self.outline = rgb(cfg.get("縁色", "#FFFFFF"))
        self.wipe_color = rgb(cfg.get("切り替え色", "#E04E36"))
        self.bgm = self.path(cfg["BGM"], "設定のBGM") if cfg.get("BGM") else None
        self.bgm_volume = float(cfg.get("BGM音量", 0.15))
        self.output = cfg.get("出力")
        if cfg.get("フォント"):
            self.font_path = str(self.path(cfg["フォント"], "設定のフォント"))
        else:
            found = [p for p in FONT_CANDIDATES if Path(p).exists()]
            if not found:
                raise DaihonError("日本語フォントが見つかりません。設定の「フォント」にフォントファイルを書いてください")
            self.font_path = found[0]
        self._fonts, self._images, self._fitted = {}, {}, {}

    def path(self, p, where):
        full = (self.base_dir / str(p)).resolve()
        if not full.exists():
            raise DaihonError(f"{where} のファイルが見つかりません: {p}")
        return full

    def font(self, size):
        if size not in self._fonts:
            self._fonts[size] = ImageFont.truetype(self.font_path, size)
        return self._fonts[size]

    def image(self, path):
        if path not in self._images:
            self._images[path] = Image.open(path).convert("RGBA")
        return self._images[path]

    def fitted(self, path):
        """画面いっぱいに収まるよう、はみ出す部分を切り落とした絵。"""
        if path not in self._fitted:
            img = self.image(path).convert("RGB")
            scale = max(self.W / img.width, self.H / img.height)
            img = img.resize((math.ceil(img.width * scale), math.ceil(img.height * scale)),
                             Image.Resampling.LANCZOS)
            x0, y0 = (img.width - self.W) // 2, (img.height - self.H) // 2
            self._fitted[path] = img.crop((x0, y0, x0 + self.W, y0 + self.H))
        return self._fitted[path]


# ---- 文字の描画 -----------------------------------------------------------

def parse_rich(text, color, accent):
    """【】で囲んだ部分を強調色に、「／」で区切った塊に番号をつけて (文字, 色, 塊番号) の列にする。"""
    out, chunk, cur = [], 0, color
    for ch in str(text).rstrip("\n"):
        if ch == "【":
            cur = accent
        elif ch == "】":
            cur = color
        elif ch == "／":
            chunk += 1
        else:
            out.append((ch, cur, chunk))
    return out, chunk + 1


def wrap(chars, font, max_w):
    lines, w = [[]], 0
    for c in chars:
        if c[0] == "\n":
            lines.append([])
            w = 0
            continue
        cw = font.getlength(c[0])
        if w + cw > max_w and lines[-1] and c[0] not in NO_HEAD:
            lines.append([])
            w = 0
        lines[-1].append(c)
        w += cw
    return lines


def draw_lines(ctx, lines, size, upto, outline=None, align="left", color=None):
    """折り返し済みの行を描く。upto 番目までの塊だけ描き、大きさは全部出たときと同じにする。"""
    font = ctx.font(size)
    asc, desc = font.getmetrics()
    lh = int((asc + desc) * 1.12)
    ow = max(2, size // 9) if outline else 0
    bold = max(1, size // 40)
    widths = [sum(font.getlength(c[0]) for c in ln) for ln in lines]
    pad = ow + bold + 2
    img = Image.new("RGBA", (int(max(widths, default=0)) + pad * 2, lh * len(lines) + pad * 2))
    d = ImageDraw.Draw(img)
    passes = ([(outline, ow)] if outline else []) + [(None, bold)]
    for fixed, sw in passes:
        y = pad
        for ln, lw in zip(lines, widths):
            x = pad + (img.width - 2 * pad - lw) / 2 if align == "center" else pad
            for ch, c, chunk in ln:
                if chunk <= upto:
                    fill = fixed or color or c
                    d.text((x, y), ch, font=font, fill=fill, stroke_width=sw, stroke_fill=fill)
                x += font.getlength(ch)
            y += lh
    return img


# ---- 画面に出すもの（テロップ・セリフ・画像） -------------------------------

class Element:
    COMMON_KEYS = ["から", "まで", "位置", "動き", "間", "音声", "口パク"]

    def __init__(self, ctx, item, where, scene_dur, keys):
        check_keys(item, keys + self.COMMON_KEYS, where)
        self.ctx, self.where = ctx, where
        self.start = float(item.get("から", 0))
        self.end = float(item.get("まで", scene_dur))
        self.gap = float(item.get("間", 0.6))
        self.anim = item.get("動き", "ポン")
        if self.anim not in ("ポン", "フェード", "なし"):
            raise DaihonError(f"{where} の動きは ポン・フェード・なし のどれかで書いてください")
        self.audio = ctx.path(item["音声"], where) if item.get("音声") else None
        self.lip = bool(item.get("口パク", False))
        self.n = 1
        self.chunk_chars = [0]
        self._sprites = {}
        self.pos = item.get("位置", "中央")

    def place(self, w, h):
        W, H = self.ctx.W, self.ctx.H
        if isinstance(self.pos, list):
            return int(W * self.pos[0] / 100), int(H * self.pos[1] / 100)
        if self.pos not in POSITIONS:
            raise DaihonError(f"{self.where} の位置は {'・'.join(POSITIONS)} か [横%, 縦%] で書いてください")
        ax, ay = POSITIONS[self.pos]
        mx, my = W * 0.03, H * 0.05
        return int(mx + ax * (W - 2 * mx - w)), int(my + ay * (H - 2 * my - h))

    def set_text(self, text):
        self.chars, self.n = parse_rich(text, self.ctx.text_color, self.ctx.accent)
        self.chunk_chars = [sum(1 for c in self.chars if c[2] == i) for i in range(self.n)]

    def talk_end(self):
        if self.audio:
            return self.start + audio_seconds(self.audio)
        return self.start + (self.n - 1) * self.gap + self.chunk_chars[-1] * 0.09 + 0.2

    def talking(self, t):
        if not hasattr(self, "_talk_end"):
            self._talk_end = self.talk_end()
        return self.lip and self.start <= t < min(self._talk_end, self.end)

    def sprite(self, upto):
        if upto not in self._sprites:
            self._sprites[upto] = self.build(upto)
        return self._sprites[upto]

    def draw(self, frame, t):
        if not (self.start <= t < self.end):
            return
        age = t - self.start
        upto = min(self.n - 1, int(age / self.gap))
        spr = self.sprite(upto)
        since = age - upto * self.gap
        if upto > 0 and since < CHUNK_FADE:
            spr = Image.blend(self.sprite(upto - 1), spr, since / CHUNK_FADE)
        if not hasattr(self, "xy"):
            self.xy = self.place(*spr.size)
        x, y = self.xy
        if self.anim == "ポン" and age < POP_SEC:
            p = age / POP_SEC
            s = max(0.05, 0.6 + 0.4 * ease_out_back(p))
            w, h = spr.size
            spr = with_alpha(spr.resize((max(1, int(w * s)), max(1, int(h * s)))), min(1, p * 2))
            x, y = x + (w - spr.width) // 2, y + (h - spr.height) // 2
        elif self.anim == "フェード" and age < FADE_SEC:
            spr = with_alpha(spr, age / FADE_SEC)
        frame.paste(spr, (x, y), spr)


class Telop(Element):
    KEYS = ["文字", "大きさ", "種類", "色"]

    def __init__(self, ctx, item, where, scene_dur):
        super().__init__(ctx, item, where, scene_dur, self.KEYS)
        if "文字" not in item:
            raise DaihonError(f"{where} に「文字」がありません")
        size = item.get("大きさ", "中")
        if size not in TEXT_SIZES:
            raise DaihonError(f"{where} の大きさは {'・'.join(TEXT_SIZES)} のどれかで書いてください")
        self.size = int(min(ctx.W, ctx.H * 16 / 9) * TEXT_SIZES[size] * 9 / 16)
        self.kind = item.get("種類", "ふつう")
        if self.kind not in ("ふつう", "タグ"):
            raise DaihonError(f"{where} の種類は ふつう・タグ のどちらかで書いてください")
        self.color = rgb(item["色"]) if item.get("色") else None
        self.set_text(item["文字"])
        self.lines = wrap(self.chars, ctx.font(self.size), ctx.W * 0.9)

    def build(self, upto):
        if self.kind == "タグ":
            txt = draw_lines(self.ctx, self.lines, self.size, upto, color=(255, 255, 255))
            px, py = int(self.size * 0.35), int(self.size * 0.12)
            img = Image.new("RGBA", (txt.width + px * 2, txt.height + py * 2))
            ImageDraw.Draw(img).rounded_rectangle(
                (0, 0, img.width - 1, img.height - 1), radius=int(self.size * 0.2),
                fill=self.color or self.ctx.text_color)
            img.paste(txt, (px, py), txt)
            return img
        align = "center" if self.pos in ("上", "中央", "下") else "left"
        return draw_lines(self.ctx, self.lines, self.size, upto, outline=self.ctx.outline,
                          align=align, color=self.color)


class Serif(Element):
    KEYS = ["名前", "文字", "大きさ", "色", "しっぽ"]

    def __init__(self, ctx, item, where, scene_dur):
        item = dict(item)
        item.setdefault("口パク", True)
        item.setdefault("位置", "左上")
        super().__init__(ctx, item, where, scene_dur, self.KEYS)
        if "文字" not in item:
            raise DaihonError(f"{where} に「文字」がありません")
        size = item.get("大きさ", "小")
        if size not in TEXT_SIZES:
            raise DaihonError(f"{where} の大きさは {'・'.join(TEXT_SIZES)} のどれかで書いてください")
        self.size = int(min(ctx.W, ctx.H * 16 / 9) * TEXT_SIZES[size] * 9 / 16)
        self.name = item.get("名前")
        self.border = rgb(item.get("色", "#4B3A8C"))
        self.tail = item.get("しっぽ", "右下")
        if self.tail not in ("右下", "左下", "なし"):
            raise DaihonError(f"{where} のしっぽは 右下・左下・なし のどれかで書いてください")
        self.set_text(item["文字"])
        self.lines = wrap(self.chars, ctx.font(self.size), ctx.W * 0.4)

    def build(self, upto):
        s = self.size
        txt = draw_lines(self.ctx, self.lines, s, upto)
        pad, bw = int(s * 0.55), max(3, s // 10)
        tag_font = self.ctx.font(int(s * 0.5))
        tag_h = int(s * 0.75) if self.name else 0
        tail_h = int(s * 0.9) if self.tail != "なし" else 0
        box_w = max(txt.width + pad * 2, int(s * 4))
        box_h = txt.height + pad * 2
        top = tag_h // 2
        img = Image.new("RGBA", (box_w + bw, top + box_h + tail_h + bw))
        d = ImageDraw.Draw(img)
        fill = (255, 253, 247)
        bottom = top + box_h
        if self.tail != "なし":
            if self.tail == "右下":
                b0, b1, tip = box_w * 0.68, box_w * 0.82, box_w * 0.93
            else:
                b0, b1, tip = box_w * 0.18, box_w * 0.32, box_w * 0.07
            d.polygon([(b0, bottom - bw), (b1, bottom - bw), (tip, bottom + tail_h)],
                      fill=fill, outline=self.border, width=bw)
        d.rounded_rectangle((0, top, box_w - 1, bottom), radius=int(s * 0.35),
                            fill=fill, outline=self.border, width=bw)
        if self.tail != "なし":
            # 吹き出しとしっぽの境目の線を消す
            d.polygon([(b0 + bw * 1.5, bottom - bw * 2), (b1 - bw * 1.5, bottom - bw * 2),
                       (tip + (b0 + b1 - 2 * tip) * 0.12, bottom + tail_h - bw * 2.5)], fill=fill)
        img.paste(txt, (pad, top + pad), txt)
        if self.name:
            tw = int(tag_font.getlength(self.name))
            x0 = int(pad * 0.6)
            d.rectangle((x0, 0, x0 + tw + int(s * 0.5), tag_h), fill=self.border)
            d.text((x0 + int(s * 0.25), tag_h / 2), self.name, font=tag_font,
                   fill=(255, 255, 255), anchor="lm")
        return img


class Picture(Element):
    KEYS = ["ファイル", "幅", "枠"]

    def __init__(self, ctx, item, where, scene_dur):
        item = dict(item)
        item.setdefault("動き", "フェード")
        super().__init__(ctx, item, where, scene_dur, self.KEYS)
        if "ファイル" not in item:
            raise DaihonError(f"{where} に「ファイル」がありません")
        self.file = ctx.path(item["ファイル"], where)
        self.width = float(item.get("幅", 50))
        self.frame = bool(item.get("枠", True))

    def build(self, upto):
        img = self.ctx.image(self.file)
        w = int(self.ctx.W * self.width / 100)
        img = img.resize((w, int(img.height * w / img.width)), Image.Resampling.LANCZOS)
        if not self.frame:
            return img
        b = max(4, w // 60)
        out = Image.new("RGBA", (img.width + b * 2, img.height + b * 2), (255, 255, 255, 255))
        ImageDraw.Draw(out).rectangle((0, 0, out.width - 1, out.height - 1), outline=(200, 200, 200), width=2)
        out.paste(img, (b, b), img)
        return out


# ---- シーン ---------------------------------------------------------------

class Scene:
    KEYS = ["秒", "絵", "口パク", "ズーム", "切り替え", "音声", "テロップ", "セリフ", "画像", "メモ"]

    def __init__(self, ctx, item, num):
        where = f"{num}番目のシーン"
        check_keys(item, self.KEYS, where)
        self.ctx, self.num = ctx, num
        self.audio = ctx.path(item["音声"], f"{where}の音声") if item.get("音声") else None
        if "秒" in item:
            self.dur = float(item["秒"])
        elif self.audio:
            self.dur = audio_seconds(self.audio) + 0.4
        else:
            raise DaihonError(f"{where} に「秒」がありません（音声があれば省略できます）")

        # 絵: 1枚なら「絵: a.png」、途中で表情を変えるなら「絵:」の下に から/絵/口パク を並べる
        pics = item.get("絵")
        if pics is None:
            raise DaihonError(f"{where} に「絵」がありません")
        if not isinstance(pics, list):
            pics = [{"から": 0, "絵": pics, "口パク": item.get("口パク")}]
        self.pics = []
        for j, p in enumerate(pics, 1):
            check_keys(p, ["から", "絵", "口パク"], f"{where}の絵{j}")
            self.pics.append((float(p.get("から", 0)), ctx.path(p["絵"], f"{where}の絵{j}"),
                              ctx.path(p["口パク"], f"{where}の口パク{j}") if p.get("口パク") else None))
        self.pics.sort(key=lambda p: p[0])

        self.zoom = bool(item.get("ズーム", False))
        self.transition = item.get("切り替え", "なし")
        if self.transition not in ("ワイプ", "フェード", "なし"):
            raise DaihonError(f"{where} の切り替えは ワイプ・フェード・なし のどれかで書いてください")
        self.elements = (
            [Picture(ctx, x, f"{where}の画像{j}", self.dur) for j, x in enumerate(as_list(item.get("画像")), 1)]
            + [Telop(ctx, x, f"{where}のテロップ{j}", self.dur) for j, x in enumerate(as_list(item.get("テロップ")), 1)]
            + [Serif(ctx, x, f"{where}のセリフ{j}", self.dur) for j, x in enumerate(as_list(item.get("セリフ")), 1)])

    def background(self, t):
        shown = [p for p in self.pics if p[0] <= t] or self.pics[:1]
        _, pic, mouth = shown[-1]
        if mouth and any(e.talking(t) for e in self.elements) and int(t / MOUTH_SEC) % 2 == 0:
            pic = mouth
        img = self.ctx.fitted(pic)
        if self.zoom:
            W, H = self.ctx.W, self.ctx.H
            s = 1 + 0.06 * t / self.dur
            w, h = W / s, H / s
            img = img.resize((W, H), Image.Resampling.BILINEAR,
                             box=((W - w) / 2, (H - h) / 2, (W + w) / 2, (H + h) / 2))
        else:
            img = img.copy()
        return img

    def frame(self, t):
        img = self.background(t)
        for e in self.elements:
            e.draw(img, t)
        return img


def wipe(ctx, prev, cur, p):
    """矢印の形の帯が左から右へ通り抜けて、前のシーンから次のシーンへ切り替える。"""
    W, H = ctx.W, ctx.H
    a = H * 0.35
    q = p * 2 if p < 0.5 else (p - 0.5) * 2
    q = 1 - (1 - q) ** 2
    if p < 0.5:
        img, left, right = prev.copy(), -a - 20, -a + q * (W + a)
    else:
        img, left, right = cur.copy(), -a + q * (W + a), W + a
    pts = [(left, 0), (right, 0), (right + a, H / 2), (right, H), (left, H), (left + a, H / 2)]
    d = ImageDraw.Draw(img)
    d.polygon(pts, fill=ctx.wipe_color)
    d.line(pts[1:4], fill=(255, 255, 255), width=max(4, W // 200))
    return img


# ---- 書き出し --------------------------------------------------------------

def load(path):
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise DaihonError(f"台本の書き方に間違いがあります（行と列の番号を見てください）:\n{e}")
    check_keys(data, ["設定", "シーン"], "台本")
    ctx = Ctx(data.get("設定") or {}, path.parent)
    scenes = [Scene(ctx, s, i) for i, s in enumerate(as_list(data.get("シーン")), 1)]
    if not scenes:
        raise DaihonError("「シーン」が1つもありません")
    return ctx, scenes


def collect_audio(scenes):
    clips, t0 = [], 0.0
    for sc in scenes:
        if sc.audio:
            clips.append((sc.audio, t0))
        clips += [(e.audio, t0 + e.start) for e in sc.elements if e.audio]
        t0 += sc.dur
    return clips


def render(ctx, scenes, out):
    fps = ctx.fps
    total = sum(round(sc.dur * fps) for sc in scenes) / fps
    clips = collect_audio(scenes)
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{ctx.W}x{ctx.H}", "-r", str(fps), "-i", "-"]
    for path, _ in clips:
        cmd += ["-i", str(path)]
    if ctx.bgm:
        cmd += ["-stream_loop", "-1", "-i", str(ctx.bgm)]
    fmt = "aresample=44100,aformat=channel_layouts=stereo"
    graph = [f"anullsrc=r=44100:cl=stereo,atrim=0:{total}[base]"]
    labels = ["[base]"]
    for i, (_, start) in enumerate(clips, 1):
        ms = int(start * 1000)
        graph.append(f"[{i}:a]{fmt},adelay={ms}|{ms}[a{i}]")
        labels.append(f"[a{i}]")
    if ctx.bgm:
        graph.append(f"[{len(clips) + 1}:a]{fmt},volume={ctx.bgm_volume},atrim=0:{total}[bgm]")
        labels.append("[bgm]")
    graph.append(f"{''.join(labels)}amix=inputs={len(labels)}:duration=first:normalize=0[aout]")
    cmd += ["-filter_complex", ";".join(graph), "-map", "0:v", "-map", "[aout]",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "medium",
            "-c:a", "aac", "-b:a", "160k", "-t", f"{total}", "-movflags", "+faststart", str(out)]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    prev = None
    done = 0.0
    try:
        for sc in scenes:
            n = round(sc.dur * fps)
            tsec = TRANSITION_SEC.get(sc.transition, 0)
            for f in range(n):
                t = f / fps
                img = sc.frame(t)
                if prev is not None and t < tsec:
                    p = t / tsec
                    img = wipe(ctx, prev, img, p) if sc.transition == "ワイプ" else Image.blend(prev, img, p)
                proc.stdin.write(img.tobytes())
            prev = img
            done += sc.dur
            print(f"  シーン{sc.num} 完了（{done:.1f} / {total:.1f} 秒）", flush=True)
        proc.stdin.close()
    except BrokenPipeError:
        pass
    if proc.wait() != 0:
        raise DaihonError("ffmpeg で動画の書き出しに失敗しました（上のエラーを見てください）")


def preview(ctx, scenes, out):
    """各シーンの終わり近くの1コマを並べた画像を作る。動画を書き出す前の確認用。"""
    cols = min(3, len(scenes))
    tw = 640
    th = int(tw * ctx.H / ctx.W)
    rows = math.ceil(len(scenes) / cols)
    sheet = Image.new("RGB", (cols * tw, rows * (th + 36)), (30, 30, 30))
    d = ImageDraw.Draw(sheet)
    for i, sc in enumerate(scenes):
        t = max(0.0, min(sc.dur - 0.05, sc.dur * 0.9))
        x, y = (i % cols) * tw, (i // cols) * (th + 36)
        sheet.paste(sc.frame(t).resize((tw, th), Image.Resampling.LANCZOS), (x, y + 36))
        d.text((x + 8, y + 18), f"シーン{sc.num}（{sc.dur:.1f}秒）", font=ctx.font(22),
               fill=(255, 255, 255), anchor="lm")
    sheet.save(out)


def main():
    ap = argparse.ArgumentParser(description="台本（YAML）から動画を作る")
    ap.add_argument("daihon", type=Path, help="台本ファイル（.yaml）")
    ap.add_argument("-o", "--output", type=Path, help="書き出し先（省略時は workspace/台本名.mp4）")
    ap.add_argument("--preview", action="store_true", help="動画にせず、各シーンの静止画を並べた画像だけ作る")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg が見つかりません。先にインストールしてください（video/README.md 参照）")
    try:
        ctx, scenes = load(args.daihon.resolve())
        out = args.output or (Path(ctx.output) if ctx.output else REPO / "workspace" / f"{args.daihon.stem}.mp4")
        out.parent.mkdir(parents=True, exist_ok=True)
        if args.preview:
            out = out.with_name(out.stem + "_下見.png")
            preview(ctx, scenes, out)
        else:
            render(ctx, scenes, out)
    except DaihonError as e:
        sys.exit(f"台本エラー: {e}")
    print(f"できました: {out}")


if __name__ == "__main__":
    main()
