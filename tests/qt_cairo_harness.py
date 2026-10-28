#!/usr/bin/env python3
"""
Lightweight Cairo-backed PyQt6 harness for testing and benchmarking the `if HAS_QT:`
GUI classes in `history/storage.py` and `Prismwake.py` when native PyQt6 is unavailable.
"""
from __future__ import annotations

import math
import sys
import time
import types
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
import cairo


class _SignalDescriptor:
    def __init__(self, *types_spec: Any) -> None:
        self.types_spec = types_spec
        self.attr_name = ""

    def __set_name__(self, owner: Any, name: str) -> None:
        self.attr_name = f"__sig_{name}"

    def __get__(self, instance: Any, owner: Any = None) -> Any:
        if instance is None:
            return self
        key = self.attr_name or f"__sig_{id(self)}"
        bound = getattr(instance, key, None)
        if bound is None:
            bound = _BoundSignal()
            setattr(instance, key, bound)
        return bound


class _BoundSignal:
    def __init__(self) -> None:
        self._slots: List[Callable[..., Any]] = []

    def connect(self, slot: Callable[..., Any]) -> None:
        if slot not in self._slots:
            self._slots.append(slot)

    def disconnect(self, slot: Optional[Callable[..., Any]] = None) -> None:
        if slot is None:
            self._slots.clear()
        elif slot in self._slots:
            self._slots.remove(slot)

    def emit(self, *args: Any) -> None:
        for s in list(self._slots):
            try:
                s(*args)
            except TypeError:
                s()


def pyqtSignal(*types_spec: Any) -> Any:
    return _SignalDescriptor(*types_spec)


class QPoint:
    def __init__(self, x: Any = 0, y: int = 0) -> None:
        if isinstance(x, (QPoint, QPointF)):
            self._x = int(round(x.x()))
            self._y = int(round(x.y()))
        else:
            self._x = int(round(x))
            self._y = int(round(y))

    def x(self) -> int: return self._x
    def y(self) -> int: return self._y
    def __add__(self, other: Any) -> "QPoint": return QPoint(self._x + other.x(), self._y + other.y())
    def __sub__(self, other: Any) -> "QPoint": return QPoint(self._x - other.x(), self._y - other.y())
    def __eq__(self, other: Any) -> bool: return isinstance(other, (QPoint, QPointF)) and self._x == int(other.x()) and self._y == int(other.y())


class QPointF:
    def __init__(self, x: Any = 0.0, y: float = 0.0) -> None:
        if isinstance(x, (QPoint, QPointF)):
            self._x = float(x.x())
            self._y = float(x.y())
        else:
            self._x = float(x)
            self._y = float(y)

    def x(self) -> float: return self._x
    def y(self) -> float: return self._y
    def toPoint(self) -> QPoint: return QPoint(int(round(self._x)), int(round(self._y)))
    def __add__(self, other: Any) -> "QPointF": return QPointF(self._x + other.x(), self._y + other.y())
    def __sub__(self, other: Any) -> "QPointF": return QPointF(self._x - other.x(), self._y - other.y())


class QSize:
    def __init__(self, w: Any = 0, h: int = 0) -> None:
        if isinstance(w, QSize):
            self._w, self._h = int(w.width()), int(w.height())
        else:
            self._w, self._h = int(w), int(h)

    def width(self) -> int: return self._w
    def height(self) -> int: return self._h
    def isEmpty(self) -> bool: return self._w <= 0 or self._h <= 0
    def __sub__(self, other: "QSize") -> "QSize": return QSize(self._w - other.width(), self._h - other.height())
    def __eq__(self, other: Any) -> bool:
        return isinstance(other, QSize) and self._w == other._w and self._h == other._h


class QRect:
    def __init__(self, *args: Any) -> None:
        if len(args) == 0:
            self._x, self._y, self._w, self._h = 0, 0, 0, 0
        elif len(args) == 1 and isinstance(args[0], (QRect, QRectF)):
            r = args[0]
            self._x, self._y, self._w, self._h = int(round(r.x())), int(round(r.y())), int(round(r.width())), int(round(r.height()))
        elif len(args) == 2 and isinstance(args[0], QPoint) and isinstance(args[1], QSize):
            self._x, self._y, self._w, self._h = args[0].x(), args[0].y(), args[1].width(), args[1].height()
        elif len(args) == 2 and isinstance(args[0], QPoint) and isinstance(args[1], QPoint):
            x0, y0 = args[0].x(), args[0].y()
            x1, y1 = args[1].x(), args[1].y()
            self._x, self._y = min(x0, x1), min(y0, y1)
            self._w, self._h = abs(x1 - x0), abs(y1 - y0)
        else:
            self._x, self._y, self._w, self._h = int(round(args[0])), int(round(args[1])), int(round(args[2])), int(round(args[3]))

    def x(self) -> int: return self._x
    def y(self) -> int: return self._y
    def left(self) -> int: return self._x
    def top(self) -> int: return self._y
    def right(self) -> int: return self._x + self._w
    def bottom(self) -> int: return self._y + self._h
    def width(self) -> int: return self._w
    def height(self) -> int: return self._h
    def size(self) -> QSize: return QSize(self._w, self._h)
    def topLeft(self) -> QPoint: return QPoint(self._x, self._y)
    def bottomLeft(self) -> QPoint: return QPoint(self._x, self._y + self._h)
    def topRight(self) -> QPoint: return QPoint(self._x + self._w, self._y)
    def bottomRight(self) -> QPoint: return QPoint(self._x + self._w, self._y + self._h)
    def center(self) -> QPoint: return QPoint(self._x + self._w // 2, self._y + self._h // 2)
    def isEmpty(self) -> bool: return self._w <= 0 or self._h <= 0
    def isValid(self) -> bool: return self._w > 0 and self._h > 0
    def adjusted(self, dx1: float, dy1: float, dx2: float, dy2: float) -> "QRect":
        return QRect(self._x + dx1, self._y + dy1, self._w - dx1 + dx2, self._h - dy1 + dy2)
    def translated(self, dx: float, dy: float = 0.0) -> "QRect":
        return QRect(self._x + dx, self._y + dy, self._w, self._h)
    def intersected(self, other: "QRect") -> "QRect":
        x0 = max(self.left(), other.left())
        y0 = max(self.top(), other.top())
        x1 = min(self.right(), other.right())
        y1 = min(self.bottom(), other.bottom())
        if x1 <= x0 or y1 <= y0:
            return QRect(0, 0, 0, 0)
        return QRect(x0, y0, x1 - x0, y1 - y0)
    def united(self, other: "QRect") -> "QRect":
        if self.isEmpty(): return QRect(other)
        if other.isEmpty(): return QRect(self)
        x0 = min(self.left(), other.left())
        y0 = min(self.top(), other.top())
        x1 = max(self.right(), other.right())
        y1 = max(self.bottom(), other.bottom())
        return QRect(x0, y0, x1 - x0, y1 - y0)
    def intersects(self, other: Any) -> bool:
        return not self.intersected(QRect(other)).isEmpty()
    def contains(self, *args: Any) -> bool:
        if len(args) == 1 and isinstance(args[0], (QPoint, QPointF)):
            px, py = args[0].x(), args[0].y()
        else:
            px, py = args[0], args[1]
        return self._x <= px <= self._x + self._w and self._y <= py <= self._y + self._h


class QRectF:
    def __init__(self, *args: Any) -> None:
        if len(args) == 0:
            self._x, self._y, self._w, self._h = 0.0, 0.0, 0.0, 0.0
        elif len(args) == 1 and isinstance(args[0], (QRect, QRectF)):
            r = args[0]
            self._x, self._y, self._w, self._h = float(r.x()), float(r.y()), float(r.width()), float(r.height())
        elif len(args) == 2 and isinstance(args[0], (QPoint, QPointF)) and isinstance(args[1], (QPoint, QPointF)):
            x0, y0 = float(args[0].x()), float(args[0].y())
            x1, y1 = float(args[1].x()), float(args[1].y())
            self._x, self._y = min(x0, x1), min(y0, y1)
            self._w, self._h = abs(x1 - x0), abs(y1 - y0)
        else:
            self._x, self._y, self._w, self._h = float(args[0]), float(args[1]), float(args[2]), float(args[3])

    def x(self) -> float: return self._x
    def y(self) -> float: return self._y
    def left(self) -> float: return self._x
    def top(self) -> float: return self._y
    def right(self) -> float: return self._x + self._w
    def bottom(self) -> float: return self._y + self._h
    def width(self) -> float: return self._w
    def height(self) -> float: return self._h
    def topLeft(self) -> QPointF: return QPointF(self._x, self._y)
    def bottomLeft(self) -> QPointF: return QPointF(self._x, self._y + self._h)
    def topRight(self) -> QPointF: return QPointF(self._x + self._w, self._y)
    def bottomRight(self) -> QPointF: return QPointF(self._x + self._w, self._y + self._h)
    def center(self) -> QPointF: return QPointF(self._x + self._w * 0.5, self._y + self._h * 0.5)
    def isEmpty(self) -> bool: return self._w <= 0.0 or self._h <= 0.0
    def isValid(self) -> bool: return self._w > 0.0 and self._h > 0.0
    def normalized(self) -> "QRectF":
        x = self._x if self._w >= 0 else self._x + self._w
        y = self._y if self._h >= 0 else self._y + self._h
        return QRectF(x, y, abs(self._w), abs(self._h))
    def adjusted(self, dx1: float, dy1: float, dx2: float, dy2: float) -> "QRectF":
        return QRectF(self._x + dx1, self._y + dy1, self._w - dx1 + dx2, self._h - dy1 + dy2)
    def translated(self, dx: float, dy: float = 0.0) -> "QRectF":
        return QRectF(self._x + dx, self._y + dy, self._w, self._h)
    def toRect(self) -> QRect:
        return QRect(int(round(self._x)), int(round(self._y)), int(round(self._w)), int(round(self._h)))
    def toAlignedRect(self) -> QRect:
        x0 = int(math.floor(self._x))
        y0 = int(math.floor(self._y))
        x1 = int(math.ceil(self._x + self._w))
        y1 = int(math.ceil(self._y + self._h))
        return QRect(x0, y0, max(0, x1 - x0), max(0, y1 - y0))
    def intersected(self, other: "QRectF") -> "QRectF":
        x0 = max(self.left(), other.left())
        y0 = max(self.top(), other.top())
        x1 = min(self.right(), other.right())
        y1 = min(self.bottom(), other.bottom())
        if x1 <= x0 or y1 <= y0:
            return QRectF(0, 0, 0, 0)
        return QRectF(x0, y0, x1 - x0, y1 - y0)
    def united(self, other: "QRectF") -> "QRectF":
        if self.isEmpty(): return QRectF(other)
        if other.isEmpty(): return QRectF(self)
        x0 = min(self.left(), other.left())
        y0 = min(self.top(), other.top())
        x1 = max(self.right(), other.right())
        y1 = max(self.bottom(), other.bottom())
        return QRectF(x0, y0, x1 - x0, y1 - y0)
    def intersects(self, other: Any) -> bool:
        return not self.intersected(QRectF(other)).isEmpty()
    def contains(self, *args: Any) -> bool:
        if len(args) == 1 and isinstance(args[0], (QPoint, QPointF)):
            px, py = float(args[0].x()), float(args[0].y())
        else:
            px, py = float(args[0]), float(args[1])
        return self._x <= px <= self._x + self._w and self._y <= py <= self._y + self._h


class _DynamicEnumMeta(type):
    def __getattr__(cls, name: str) -> int:
        val = abs(hash(name)) % 65535 + 1
        setattr(cls, name, val)
        return val

class Qt(metaclass=_DynamicEnumMeta):
    class AlignmentFlag(metaclass=_DynamicEnumMeta):
        AlignLeft = 1
        AlignRight = 2
        AlignHCenter = 4
        AlignTop = 8
        AlignBottom = 16
        AlignVCenter = 32
        AlignCenter = 36

    class AspectRatioMode(metaclass=_DynamicEnumMeta):
        IgnoreAspectRatio = 0
        KeepAspectRatio = 1
        KeepAspectRatioByExpanding = 2

    class TransformationMode(metaclass=_DynamicEnumMeta):
        FastTransformation = 0
        SmoothTransformation = 1

    class GlobalColor(metaclass=_DynamicEnumMeta):
        transparent = (0, 0, 0, 0)
        black = (0, 0, 0, 255)
        white = (255, 255, 255, 255)

    class PenStyle(metaclass=_DynamicEnumMeta):
        NoPen = 0
        SolidLine = 1
        DashLine = 2

    class PenCapStyle(metaclass=_DynamicEnumMeta):
        FlatCap = 0
        SquareCap = 1
        RoundCap = 2

    class PenJoinStyle(metaclass=_DynamicEnumMeta):
        MiterJoin = 0
        BevelJoin = 1
        RoundJoin = 2

    class BrushStyle(metaclass=_DynamicEnumMeta):
        NoBrush = 0
        SolidPattern = 1

    class MouseButton(metaclass=_DynamicEnumMeta):
        NoButton = 0
        LeftButton = 1
        RightButton = 2
        MiddleButton = 4

    class KeyboardModifier(metaclass=_DynamicEnumMeta):
        NoModifier = 0
        ShiftModifier = 1
        ControlModifier = 2
        AltModifier = 4

    class Key(metaclass=_DynamicEnumMeta):
        Key_Escape = 1
        Key_Return = 2
        Key_Enter = 3
        Key_Delete = 4
        Key_Backspace = 5
        Key_Space = 6

    class CursorShape(metaclass=_DynamicEnumMeta):
        ArrowCursor = 0
        CrossCursor = 1
        IBeamCursor = 2
        PointingHandCursor = 3
        SizeAllCursor = 4
        SizeFDiagCursor = 5
        SizeBDiagCursor = 6
        SizeHorCursor = 7
        SizeVerCursor = 8
        OpenHandCursor = 9
        ClosedHandCursor = 10

    class WindowType(metaclass=_DynamicEnumMeta):
        Widget = 0
        Window = 1
        Dialog = 2
        Popup = 4
        Tool = 8
        FramelessWindowHint = 16
        WindowStaysOnTopHint = 32
        WindowTitleHint = 64
        WindowSystemMenuHint = 128
        WindowMinMaxButtonsHint = 256
        WindowCloseButtonHint = 512
        BypassWindowManagerHint = 1024
        ToolTip = 2048

    class WidgetAttribute(metaclass=_DynamicEnumMeta):
        WA_TranslucentBackground = 1
        WA_NoSystemBackground = 2
        WA_ShowWithoutActivating = 4
        WA_DeleteOnClose = 8
        WA_TransparentForMouseEvents = 16
        WA_Hover = 32

    class Orientation(metaclass=_DynamicEnumMeta):
        Horizontal = 1
        Vertical = 2

    class ItemDataRole(metaclass=_DynamicEnumMeta):
        DisplayRole = 0
        DecorationRole = 1
        ToolTipRole = 3
        UserRole = 256

    class ContextMenuPolicy(metaclass=_DynamicEnumMeta):
        DefaultContextMenu = 1
        CustomContextMenu = 2

    class TextElideMode(metaclass=_DynamicEnumMeta):
        ElideLeft = 0
        ElideRight = 1
        ElideMiddle = 2

    class FocusPolicy(metaclass=_DynamicEnumMeta):
        NoFocus = 0
        StrongFocus = 1


class QColor:
    def __init__(self, *args: Any) -> None:
        if len(args) == 0:
            self._r, self._g, self._b, self._a = 0, 0, 0, 255
        elif len(args) == 1:
            v = args[0]
            if isinstance(v, QColor):
                self._r, self._g, self._b, self._a = v._r, v._g, v._b, v._a
            elif isinstance(v, tuple):
                self._r, self._g, self._b = int(v[0]), int(v[1]), int(v[2])
                self._a = int(v[3]) if len(v) > 3 else 255
            elif isinstance(v, str):
                s = v.lstrip("#")
                if len(s) == 6:
                    self._r, self._g, self._b, self._a = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), 255
                elif len(s) == 8:
                    self._r, self._g, self._b, self._a = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16)
                else:
                    self._r, self._g, self._b, self._a = 0, 180, 255, 255
            else:
                self._r, self._g, self._b, self._a = 0, 0, 0, 255
        elif len(args) == 3:
            self._r, self._g, self._b, self._a = int(args[0]), int(args[1]), int(args[2]), 255
        else:
            self._r, self._g, self._b, self._a = int(args[0]), int(args[1]), int(args[2]), int(args[3])
        self._r = max(0, min(255, self._r))
        self._g = max(0, min(255, self._g))
        self._b = max(0, min(255, self._b))
        self._a = max(0, min(255, self._a))

    def red(self) -> int: return self._r
    def green(self) -> int: return self._g
    def blue(self) -> int: return self._b
    def alpha(self) -> int: return self._a
    def setAlpha(self, a: int) -> None: self._a = max(0, min(255, int(a)))
    def name(self) -> str: return f"#{self._r:02x}{self._g:02x}{self._b:02x}"
    def darker(self, f: int = 200) -> "QColor":
        k = 100.0 / max(1.0, float(f))
        return QColor(int(self._r * k), int(self._g * k), int(self._b * k), self._a)
    def lighter(self, f: int = 150) -> "QColor":
        k = float(f) / 100.0
        return QColor(min(255, int(self._r * k)), min(255, int(self._g * k)), min(255, int(self._b * k)), self._a)


class QPen:
    def __init__(self, color: Any = None, width: float = 1.0, style: int = Qt.PenStyle.SolidLine, cap: int = Qt.PenCapStyle.RoundCap, join: int = Qt.PenJoinStyle.RoundJoin) -> None:
        if isinstance(color, int):
            self.style = color
            self.color = QColor(0, 0, 0, 0)
            self.width = 0.0
        elif isinstance(color, QPen):
            self.color = QColor(color.color)
            self.width = color.width
            self.style = color.style
        else:
            self.color = QColor(color) if color is not None else QColor(255, 255, 255, 255)
            self.width = float(width)
            self.style = style
        self.cap = cap
        self.join = join

    def setCapStyle(self, c: int) -> None: self.cap = c
    def setJoinStyle(self, j: int) -> None: self.join = j
    def setWidthF(self, w: float) -> None: self.width = float(w)
    def setStyle(self, s: int) -> None: self.style = s


class QBrush:
    def __init__(self, arg: Any = None) -> None:
        self.gradient = None
        self.color = QColor(0, 0, 0, 0)
        self.style = Qt.BrushStyle.SolidPattern
        if arg is None or arg == Qt.BrushStyle.NoBrush:
            self.style = Qt.BrushStyle.NoBrush
        elif isinstance(arg, QBrush):
            self.color = QColor(arg.color)
            self.gradient = arg.gradient
            self.style = arg.style
        elif isinstance(arg, (QLinearGradient, QRadialGradient)):
            self.gradient = arg
        else:
            self.color = QColor(arg)


class QLinearGradient:
    def __init__(self, *args: Any) -> None:
        self.stops: List[Tuple[float, QColor]] = []

    def setColorAt(self, pos: float, col: QColor) -> None:
        self.stops.append((float(pos), QColor(col)))


class QRadialGradient(QLinearGradient):
    pass


class QFont:
    class Weight:
        Normal = 400
        Medium = 500
        DemiBold = 600
        Bold = 700

    def __init__(self, family: str = "Segoe UI", size: int = 10, weight: int = 400) -> None:
        self.family = family
        self.size = size
        self.weight = weight

    def setBold(self, b: bool) -> None:
        self.weight = 700 if b else 400


class QFontMetrics:
    def __init__(self, font: QFont) -> None:
        self.font = font

    def horizontalAdvance(self, text: str) -> int:
        return max(8, len(str(text)) * 7)

    def height(self) -> int:
        return 16

    def elidedText(self, text: str, _mode: Any, width: int) -> str:
        s = str(text)
        max_chars = max(4, int(width // 7))
        return s if len(s) <= max_chars else (s[: max_chars - 1] + "…")


class QPainterPath:
    def __init__(self, start_pt: Optional[Any] = None) -> None:
        self.ops: List[Tuple[str, Any]] = []
        self._curr = QPointF(0.0, 0.0)
        if start_pt is not None:
            self.moveTo(start_pt)

    def clear(self) -> None:
        self.ops.clear()

    def moveTo(self, *args: Any) -> None:
        pt = QPointF(*args)
        self._curr = pt
        self.ops.append(("M", (pt.x(), pt.y())))

    def lineTo(self, *args: Any) -> None:
        pt = QPointF(*args)
        self._curr = pt
        self.ops.append(("L", (pt.x(), pt.y())))

    def quadTo(self, *args: Any) -> None:
        if len(args) == 2:
            c, p = QPointF(args[0]), QPointF(args[1])
        else:
            c, p = QPointF(args[0], args[1]), QPointF(args[2], args[3])
        self._curr = p
        self.ops.append(("Q", (c.x(), c.y(), p.x(), p.y())))

    def cubicTo(self, *args: Any) -> None:
        if len(args) == 3:
            c1, c2, p = QPointF(args[0]), QPointF(args[1]), QPointF(args[2])
        else:
            c1, c2, p = QPointF(args[0], args[1]), QPointF(args[2], args[3]), QPointF(args[4], args[5])
        self._curr = p
        self.ops.append(("C", (c1.x(), c1.y(), c2.x(), c2.y(), p.x(), p.y())))

    def closeSubpath(self) -> None:
        self.ops.append(("Z", ()))

    def addRoundedRect(self, rect: Any, rx: float, ry: float) -> None:
        r = QRectF(rect)
        self.ops.append(("RR", (r.x(), r.y(), r.width(), r.height(), float(rx), float(ry))))

    def addRect(self, rect: Any) -> None:
        r = QRectF(rect)
        self.ops.append(("R", (r.x(), r.y(), r.width(), r.height())))

    def addEllipse(self, *args: Any) -> None:
        if len(args) == 1:
            r = QRectF(args[0])
        elif len(args) == 3 and isinstance(args[0], (QPoint, QPointF)):
            c = args[0]
            rx, ry = float(args[1]), float(args[2])
            r = QRectF(c.x() - rx, c.y() - ry, rx * 2, ry * 2)
        else:
            r = QRectF(*args)
        self.ops.append(("E", (r.x(), r.y(), r.width(), r.height())))


class QPolygonF:
    def __init__(self, pts: Optional[Sequence[QPointF]] = None) -> None:
        self.points = list(pts or [])


class _BitsPtr:
    def __init__(self, buf: bytes) -> None:
        self._buf = bytearray(buf)
    def setsize(self, n: int) -> None:
        if len(self._buf) < n:
            self._buf.extend(b"\x00" * (n - len(self._buf)))
    def __buffer__(self, flags: int) -> memoryview:
        return memoryview(self._buf)
    def asstring(self, n: int = -1) -> bytes:
        return bytes(self._buf if n < 0 else self._buf[:n])

class QImage:
    class Format:
        Format_RGB888 = 1
        Format_RGBA8888 = 2
        Format_ARGB32 = 3
        Format_ARGB32_Premultiplied = 4

    def __init__(self, data: Any = None, width: int = 0, height: int = 0, bytes_per_line: int = 0, fmt: int = 2) -> None:
        if isinstance(data, QImage):
            self._w, self._h = data._w, data._h
            self._buf = bytes(data._buf) if data._buf else b""
        elif isinstance(data, int) and isinstance(width, int):
            self._w, self._h = int(data), int(width)
            self._buf = b"\x00" * (max(0, self._w * self._h * 4))
        else:
            self._w = int(width)
            self._h = int(height)
            if isinstance(data, (bytes, bytearray, memoryview)):
                self._buf = bytes(data)
            elif hasattr(data, "tobytes"):
                self._buf = data.tobytes()
            else:
                self._buf = b"\x00" * (max(0, self._w * self._h * 4))
        self._fmt = fmt

    def width(self) -> int: return self._w
    def height(self) -> int: return self._h
    def size(self) -> QSize: return QSize(self._w, self._h)
    def isNull(self) -> bool: return self._w <= 0 or self._h <= 0
    def bytesPerLine(self) -> int:
        bpp = 3 if self._fmt == QImage.Format.Format_RGB888 else 4
        return max(1, self._w * bpp)
    def bits(self) -> memoryview:
        class _MemPtr(bytearray):
            def setsize(self, _n: int) -> None: pass
        needed = self._h * self.bytesPerLine()
        raw = self._buf[:needed] if len(self._buf) >= needed else (self._buf + b"\x00" * (needed - len(self._buf)))
        return _MemPtr(raw)
    def scaled(self, *args: Any) -> "QImage":
        if isinstance(args[0], QSize):
            tw, th = args[0].width(), args[0].height()
        else:
            tw, th = int(args[0]), int(args[1])
        return QImage(b"\x20" * (max(1, tw) * max(1, th) * 4), max(1, tw), max(1, th), max(1, tw) * 4, self._fmt)
    def convertToFormat(self, fmt: int) -> "QImage":
        bpp = 3 if fmt == QImage.Format.Format_RGB888 else 4
        return QImage(b"\x20" * (max(1, self._w) * max(1, self._h) * bpp), self._w, self._h, self._w * bpp, fmt)
    def copy(self, *args: Any) -> "QImage":
        if not args:
            return QImage(self._buf, self._w, self._h, self._w * 4, self._fmt)
        r = QRect(*args)
        return QImage(b"\x00" * (max(1, r.width()) * max(1, r.height()) * 4), max(1, r.width()), max(1, r.height()))


class QPixmap:
    def __init__(self, *args: Any) -> None:
        if len(args) == 0:
            self._w, self._h = 0, 0
        elif len(args) == 1 and isinstance(args[0], QSize):
            self._w, self._h = max(0, args[0].width()), max(0, args[0].height())
        elif len(args) == 1 and isinstance(args[0], QPixmap):
            self._w, self._h = args[0]._w, args[0]._h
        else:
            self._w, self._h = max(0, int(args[0])), max(0, int(args[1]))
        self._surface: Optional[cairo.ImageSurface] = None
        if self._w > 0 and self._h > 0:
            self._surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, min(self._w, 320), min(self._h, 200))

    @classmethod
    def fromImage(cls, qimg: QImage) -> "QPixmap":
        return cls(qimg.width(), qimg.height())

    def width(self) -> int: return self._w
    def height(self) -> int: return self._h
    def size(self) -> QSize: return QSize(self._w, self._h)
    def rect(self) -> QRect: return QRect(0, 0, self._w, self._h)
    def isNull(self) -> bool: return self._w <= 0 or self._h <= 0
    def bytesPerLine(self) -> int:
        bpp = 3 if self._fmt == QImage.Format.Format_RGB888 else 4
        return max(1, self._w * bpp)
    def bits(self) -> memoryview:
        class _MemPtr(bytearray):
            def setsize(self, _n: int) -> None: pass
        needed = self._h * self.bytesPerLine()
        raw = self._buf[:needed] if len(self._buf) >= needed else (self._buf + b"\x00" * (needed - len(self._buf)))
        return _MemPtr(raw)
    def scaled(self, *args: Any) -> "QImage":
        if isinstance(args[0], QSize):
            tw, th = args[0].width(), args[0].height()
        else:
            tw, th = int(args[0]), int(args[1])
        return QImage(b"\x20" * (max(1, tw) * max(1, th) * 4), max(1, tw), max(1, th), max(1, tw) * 4, self._fmt)
    def convertToFormat(self, fmt: int) -> "QImage":
        bpp = 3 if fmt == QImage.Format.Format_RGB888 else 4
        return QImage(b"\x20" * (max(1, self._w) * max(1, self._h) * bpp), self._w, self._h, self._w * bpp, fmt)
    def setDevicePixelRatio(self, _dpr: float) -> None: pass
    def devicePixelRatio(self) -> float: return 1.0
    def fill(self, _color: Any = None) -> None:
        if self._surface is not None:
            ctx = cairo.Context(self._surface)
            ctx.set_operator(cairo.OPERATOR_CLEAR)
            ctx.paint()
    def copy(self, *args: Any) -> "QPixmap":
        if not args:
            return QPixmap(self._w, self._h)
        r = QRect(*args)
        return QPixmap(max(1, r.width()), max(1, r.height()))
    def scaled(self, *args: Any) -> "QPixmap":
        if isinstance(args[0], QSize):
            tw, th = args[0].width(), args[0].height()
            aspect_mode = args[1] if len(args) > 1 else Qt.AspectRatioMode.IgnoreAspectRatio
        else:
            tw, th = int(args[0]), int(args[1])
            aspect_mode = args[2] if len(args) > 2 else Qt.AspectRatioMode.IgnoreAspectRatio
        if self._w <= 0 or self._h <= 0 or tw <= 0 or th <= 0:
            return QPixmap(max(1, tw), max(1, th))
        if aspect_mode == Qt.AspectRatioMode.KeepAspectRatio:
            scale = min(float(tw) / float(self._w), float(th) / float(self._h))
            return QPixmap(max(1, int(round(self._w * scale))), max(1, int(round(self._h * scale))))
        return QPixmap(tw, th)
    def toImage(self) -> QImage:
        return QImage(b"\x00" * (max(1, self._w) * max(1, self._h) * 4), self._w, self._h)


class QIcon:
    def __init__(self, pm: Optional[QPixmap] = None) -> None:
        self.pixmap = pm


class QPainter:
    class RenderHint:
        Antialiasing = 1
        SmoothPixmapTransform = 2
        TextAntialiasing = 4

    class CompositionMode:
        CompositionMode_SourceOver = 0
        CompositionMode_Source = 1
        CompositionMode_Plus = 2

    def __init__(self, target: Any = None) -> None:
        self._ctx: Optional[cairo.Context] = None
        if target is not None:
            self.begin(target)

    def begin(self, target: Any) -> bool:
        surf = getattr(target, "_surface", None)
        if surf is None:
            w = max(1, int(getattr(target, "width", lambda: 64)()))
            h = max(1, int(getattr(target, "height", lambda: 64)()))
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, min(w, 320), min(h, 200))
            target._surface = surf
        self._ctx = cairo.Context(surf)
        return True

    def end(self) -> None:
        self._ctx = None

    def save(self) -> None:
        if self._ctx: self._ctx.save()

    def restore(self) -> None:
        if self._ctx: self._ctx.restore()

    def setRenderHint(self, _hint: int, _on: bool = True) -> None: pass
    def setCompositionMode(self, _mode: int) -> None: pass
    def setOpacity(self, _op: float) -> None: pass
    def setClipRect(self, *args: Any) -> None: pass
    def setClipPath(self, *args: Any) -> None: pass
    def setFont(self, _f: QFont) -> None: pass
    def fontMetrics(self) -> QFontMetrics: return QFontMetrics(QFont())
    def setPen(self, _p: Any) -> None: pass
    def setBrush(self, _b: Any) -> None: pass
    def translate(self, dx: float, dy: float) -> None: pass
    def scale(self, sx: float, sy: float) -> None: pass

    def fillRect(self, *args: Any) -> None:
        if self._ctx is None: return
        r = QRectF(args[0]) if len(args) == 2 else QRectF(args[0], args[1], args[2], args[3])
        self._ctx.rectangle(r.x(), r.y(), max(0.0, r.width()), max(0.0, r.height()))
        self._ctx.fill()

    def fillPath(self, path: QPainterPath, _brush: Any) -> None:
        self.drawPath(path)

    def strokePath(self, path: QPainterPath, _pen: Any) -> None:
        self.drawPath(path)

    def drawPath(self, path: QPainterPath) -> None:
        if self._ctx is None: return
        for op, vals in path.ops:
            if op == "M": self._ctx.move_to(vals[0], vals[1])
            elif op == "L": self._ctx.line_to(vals[0], vals[1])
            elif op == "Q": self._ctx.curve_to(vals[0], vals[1], vals[0], vals[1], vals[2], vals[3])
            elif op == "R" or op == "RR": self._ctx.rectangle(vals[0], vals[1], max(0.0, vals[2]), max(0.0, vals[3]))
        self._ctx.stroke()

    def drawRect(self, *args: Any) -> None:
        if self._ctx is None: return
        r = QRectF(args[0]) if len(args) == 1 else QRectF(*args)
        self._ctx.rectangle(r.x(), r.y(), max(0.0, r.width()), max(0.0, r.height()))
        self._ctx.stroke()

    def drawRoundedRect(self, rect: Any, _rx: float, _ry: float) -> None:
        self.drawRect(rect)

    def drawEllipse(self, *args: Any) -> None:
        if self._ctx is None: return
        if len(args) == 1:
            r = QRectF(args[0])
        elif len(args) == 3 and isinstance(args[0], (QPoint, QPointF)):
            c = args[0]
            r = QRectF(c.x() - args[1], c.y() - args[2], args[1] * 2, args[2] * 2)
        else:
            r = QRectF(*args)
        self._ctx.rectangle(r.x(), r.y(), max(0.0, r.width()), max(0.0, r.height()))
        self._ctx.stroke()

    def drawLine(self, *args: Any) -> None:
        if self._ctx is None: return
        if len(args) == 2:
            self._ctx.move_to(args[0].x(), args[0].y())
            self._ctx.line_to(args[1].x(), args[1].y())
        else:
            self._ctx.move_to(args[0], args[1])
            self._ctx.line_to(args[2], args[3])
        self._ctx.stroke()

    def drawPolygon(self, _poly: Any) -> None: pass
    def drawText(self, *args: Any) -> None: pass
    def drawImage(self, *args: Any) -> None: pass
    def drawPixmap(self, *args: Any) -> None:
        if self._ctx is None: return
        self._ctx.rectangle(0, 0, 4, 4)
        self._ctx.fill()


class QEvent:
    class Type:
        MouseButtonPress = 2
        MouseButtonRelease = 3
        MouseMove = 5
        Paint = 12
        UpdateRequest = 77

    def __init__(self, ev_type: int = 0) -> None:
        self._type = ev_type

    def type(self) -> int:
        return self._type


class QPaintEvent(QEvent):
    def __init__(self, rect: QRect) -> None:
        super().__init__(QEvent.Type.Paint)
        self._rect = QRect(rect)

    def rect(self) -> QRect:
        return self._rect


class QMouseEvent(QEvent):
    def __init__(self, ev_type: int, local_pos: QPointF, *args: Any) -> None:
        super().__init__(ev_type)
        self._pos = QPointF(local_pos)
        if len(args) >= 3:
            self._global = QPointF(args[0])
            self._button = args[1]
            self._buttons = args[2]
            self._mods = args[3] if len(args) > 3 else Qt.KeyboardModifier.NoModifier
        else:
            self._global = QPointF(local_pos)
            self._button = args[0] if len(args) > 0 else Qt.MouseButton.NoButton
            self._buttons = args[1] if len(args) > 1 else Qt.MouseButton.NoButton
            self._mods = args[2] if len(args) > 2 else Qt.KeyboardModifier.NoModifier

    def position(self) -> QPointF: return self._pos
    def pos(self) -> QPoint: return self._pos.toPoint()
    def globalPosition(self) -> QPointF: return self._global
    def button(self) -> int: return self._button
    def buttons(self) -> int: return self._buttons
    def modifiers(self) -> int: return self._mods
    def accept(self) -> None: pass


class QObject:
    def __init__(self, parent: Optional[Any] = None) -> None:
        self._parent = parent
        self._children: List[Any] = []
        self._signals_blocked = False
        if parent is not None and hasattr(parent, "_children"):
            parent._children.append(self)

    def parent(self) -> Optional[Any]: return self._parent
    def children(self) -> List[Any]: return list(self._children)
    def blockSignals(self, b: bool) -> bool:
        prev = self._signals_blocked
        self._signals_blocked = bool(b)
        return prev
    def signalsBlocked(self) -> bool: return self._signals_blocked
    def findChildren(self, cls: Any) -> List[Any]:
        out: List[Any] = []
        for ch in self._children:
            if isinstance(ch, cls):
                out.append(ch)
            if hasattr(ch, "findChildren"):
                out.extend(ch.findChildren(cls))
        return out
    def deleteLater(self) -> None: pass


class QTimer(QObject):
    _active_timers: List["QTimer"] = []

    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._interval = 0
        self._single_shot = False
        self._active = False
        self.timeout = _BoundSignal()

    def setInterval(self, ms: int) -> None: self._interval = int(ms)
    def setSingleShot(self, s: bool) -> None: self._single_shot = bool(s)
    def isActive(self) -> bool: return self._active
    def start(self, ms: Optional[int] = None) -> None:
        if ms is not None: self._interval = int(ms)
        self._active = True
        if self not in QTimer._active_timers:
            QTimer._active_timers.append(self)
    def stop(self) -> None:
        self._active = False
        if self in QTimer._active_timers:
            QTimer._active_timers.remove(self)

    @staticmethod
    def singleShot(_ms: int, cb: Callable[[], Any]) -> None:
        try:
            cb()
        except Exception:
            pass


class QElapsedTimer:
    def __init__(self) -> None:
        self._t0 = time.perf_counter()
    def isValid(self) -> bool: return True
    def start(self) -> None: self._t0 = time.perf_counter()
    def restart(self) -> int:
        now = time.perf_counter()
        dt = int((now - self._t0) * 1000)
        self._t0 = now
        return dt
    def elapsed(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)
    def nsecsElapsed(self) -> int:
        return int((time.perf_counter() - self._t0) * 1_000_000_000)


class QEasingCurve:
    class Type:
        Linear = 0
        InOutSine = 1
        OutCubic = 2
        OutBack = 3


class QVariantAnimation(QObject):
    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self.valueChanged = _BoundSignal()
        self.finished = _BoundSignal()
        self._start = 0.0
        self._end = 1.0
    def setDuration(self, _d: int) -> None: pass
    def setStartValue(self, v: Any) -> None: self._start = v
    def setEndValue(self, v: Any) -> None: self._end = v
    def setEasingCurve(self, _c: Any) -> None: pass
    def start(self) -> None:
        self.valueChanged.emit(self._end)
        self.finished.emit()
    def stop(self) -> None: pass


class QRunnable:
    def __init__(self) -> None: pass


class QThreadPool:
    _inst: Optional["QThreadPool"] = None
    @classmethod
    def globalInstance(cls) -> "QThreadPool":
        if cls._inst is None:
            cls._inst = cls()
        return cls._inst
    def start(self, runnable: Any) -> None:
        if hasattr(runnable, "run"):
            runnable.run()


class QCursor:
    def __init__(self, *_args: Any) -> None: pass
    @staticmethod
    def pos() -> QPoint: return QPoint(200, 200)


class _Clipboard:
    def __init__(self) -> None:
        self._text = ""
        self._pm: Optional[QPixmap] = None
    def text(self) -> str: return self._text
    def setText(self, t: str) -> None: self._text = str(t)
    def pixmap(self) -> Optional[QPixmap]: return self._pm
    def setPixmap(self, pm: QPixmap) -> None: self._pm = pm


class _Screen:
    def name(self) -> str: return "Primary"
    def geometry(self) -> QRect: return QRect(0, 0, 1920, 1080)
    def availableGeometry(self) -> QRect: return QRect(0, 0, 1920, 1040)
    def devicePixelRatio(self) -> float: return 1.0


class QApplication(QObject):
    _instance: Optional["QApplication"] = None
    _clipboard = _Clipboard()
    _dirty_widgets: Dict[int, Tuple["QWidget", QRect]] = {}

    def __init__(self, _argv: Any = None) -> None:
        super().__init__(None)
        QApplication._instance = self

    @classmethod
    def instance(cls) -> Optional["QApplication"]:
        return cls._instance

    @classmethod
    def clipboard(cls) -> _Clipboard:
        return cls._clipboard

    @classmethod
    def primaryScreen(cls) -> _Screen:
        return _Screen()

    @classmethod
    def screens(cls) -> List[_Screen]:
        return [_Screen()]

    @classmethod
    def screenAt(cls, _pt: Any) -> _Screen:
        return _Screen()

    def setQuitOnLastWindowClosed(self, _b: bool) -> None: pass

    @classmethod
    def processEvents(cls) -> None:
        for t in list(QTimer._active_timers):
            if t.isActive():
                t.timeout.emit()
        cls.sendPostedEvents(None, QEvent.Type.UpdateRequest)

    @classmethod
    def sendPostedEvents(cls, target: Optional[Any] = None, _ev_type: int = 0) -> None:
        if target is not None:
            entry = cls._dirty_widgets.pop(id(target), None)
            if entry is not None:
                w, rc = entry
                if hasattr(w, "paintEvent"):
                    w.paintEvent(QPaintEvent(rc))
        else:
            items = list(cls._dirty_widgets.values())
            cls._dirty_widgets.clear()
            for w, rc in items:
                if hasattr(w, "paintEvent"):
                    w.paintEvent(QPaintEvent(rc))


class QGuiApplication(QApplication):
    pass


class QWidget(QObject):
    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._rect = QRect(0, 0, 640, 480)
        self._min_size = QSize(0, 0)
        self._visible = False
        self._enabled = True
        self._style = ""
        self._tooltip = ""

    def winId(self) -> int: return id(self)
    def windowHandle(self) -> Any: return None
    def devicePixelRatioF(self) -> float: return 1.0
    def devicePixelRatio(self) -> float: return 1.0
    def layout(self) -> Any: return getattr(self, "_layout", None)
    def setLayout(self, l: Any) -> None: self._layout = l
    def font(self) -> QFont: return getattr(self, "_font", QFont())
    def setFont(self, f: QFont) -> None: self._font = f
    def fontMetrics(self) -> QFontMetrics: return QFontMetrics(self.font())
    def sizeHint(self) -> QSize: return QSize(max(60, self._rect.width()), max(30, self._rect.height()))
    def adjustSize(self) -> None: pass
    def updateGeometry(self) -> None: pass
    def setObjectName(self, n: str) -> None: self._obj_name = str(n)
    def objectName(self) -> str: return getattr(self, "_obj_name", "")
    def x(self) -> int: return self._rect.x()
    def y(self) -> int: return self._rect.y()
    def pos(self) -> QPoint: return QPoint(self._rect.x(), self._rect.y())
    def width(self) -> int: return self._rect.width()
    def height(self) -> int: return self._rect.height()
    def size(self) -> QSize: return self._rect.size()
    def rect(self) -> QRect: return QRect(0, 0, self._rect.width(), self._rect.height())
    def geometry(self) -> QRect: return QRect(self._rect)
    def setGeometry(self, *args: Any) -> None:
        self._rect = QRect(*args)
        if hasattr(self, "resizeEvent"):
            try:
                self.resizeEvent(QEvent())
            except Exception:
                pass
    def resize(self, *args: Any) -> None:
        if len(args) == 1 and isinstance(args[0], QSize):
            w, h = args[0].width(), args[0].height()
        else:
            w, h = int(args[0]), int(args[1])
        self._rect = QRect(self._rect.x(), self._rect.y(), w, h)
    def move(self, *args: Any) -> None:
        if len(args) == 1:
            x, y = args[0].x(), args[0].y()
        else:
            x, y = int(args[0]), int(args[1])
        self._rect = QRect(x, y, self._rect.width(), self._rect.height())
    def setMinimumSize(self, *args: Any) -> None:
        if len(args) == 1 and isinstance(args[0], QSize):
            self._min_size = QSize(args[0])
        else:
            self._min_size = QSize(int(args[0]), int(args[1]))
        if self._rect.width() < self._min_size.width() or self._rect.height() < self._min_size.height():
            self._rect = QRect(self._rect.x(), self._rect.y(), max(self._rect.width(), self._min_size.width()), max(self._rect.height(), self._min_size.height()))
    def setMinimumWidth(self, w: int) -> None: self.setMinimumSize(w, self._min_size.height())
    def setMinimumHeight(self, h: int) -> None: self.setMinimumSize(self._min_size.width(), h)
    def setFixedWidth(self, w: int) -> None: self.resize(w, self.height())
    def setFixedHeight(self, h: int) -> None: self.resize(self.width(), h)
    def setFixedSize(self, *args: Any) -> None: self.resize(*args)
    def setWindowTitle(self, _t: str) -> None: pass
    def setWindowFlags(self, _f: Any) -> None: pass
    def windowFlags(self) -> int: return 0
    def setAttribute(self, _a: Any, _on: bool = True) -> None: pass
    def setMouseTracking(self, _b: bool) -> None: pass
    def setCursor(self, _c: Any) -> None: pass
    def unsetCursor(self) -> None: pass
    def setToolTip(self, t: str) -> None: self._tooltip = str(t)
    def toolTip(self) -> str: return self._tooltip
    def setStyleSheet(self, s: str) -> None: self._style = str(s)
    def styleSheet(self) -> str: return self._style
    def setFocusPolicy(self, _p: Any) -> None: pass
    def setFocus(self) -> None: pass
    def setSizePolicy(self, *_args: Any) -> None: pass
    def setContentsMargins(self, *_args: Any) -> None: pass
    def setGraphicsEffect(self, _e: Any) -> None: pass
    def setContextMenuPolicy(self, _p: Any) -> None: pass
    def mapToGlobal(self, pt: QPoint) -> QPoint: return pt
    def isVisible(self) -> bool: return self._visible
    def isMinimized(self) -> bool: return False
    def setVisible(self, v: bool) -> None: self._visible = bool(v)
    def isEnabled(self) -> bool: return self._enabled
    def setEnabled(self, e: bool) -> None: self._enabled = bool(e)
    def show(self) -> None:
        self._visible = True
        if hasattr(self, "showEvent") and type(self).showEvent is not QWidget.showEvent:
            self.showEvent(QEvent())
    def hide(self) -> None:
        self._visible = False
        if hasattr(self, "hideEvent") and type(self).hideEvent is not QWidget.hideEvent:
            self.hideEvent(QEvent())
    def close(self) -> None:
        self._visible = False
        if hasattr(self, "closeEvent") and type(self).closeEvent is not QWidget.closeEvent:
            self.closeEvent(QEvent())
    def raise_(self) -> None: pass
    def activateWindow(self) -> None: pass
    def showEvent(self, _ev: Any) -> None: pass
    def hideEvent(self, _ev: Any) -> None: pass
    def closeEvent(self, _ev: Any) -> None: pass
    def resizeEvent(self, _ev: Any) -> None: pass
    def paintEvent(self, _ev: Any) -> None: pass
    def mousePressEvent(self, _ev: Any) -> None: pass
    def mouseMoveEvent(self, _ev: Any) -> None: pass
    def mouseReleaseEvent(self, _ev: Any) -> None: pass
    def leaveEvent(self, _ev: Any) -> None: pass
    def update(self, *args: Any) -> None:
        if not args:
            rc = self.rect()
        elif len(args) == 1 and isinstance(args[0], (QRect, QRectF)):
            rc = QRect(args[0])
        else:
            rc = QRect(*args)
        prev = QApplication._dirty_widgets.get(id(self))
        if prev is not None:
            QApplication._dirty_widgets[id(self)] = (self, prev[1].united(rc))
        else:
            QApplication._dirty_widgets[id(self)] = (self, rc)
    def repaint(self, *args: Any) -> None:
        self.update(*args)
        QApplication.sendPostedEvents(self, QEvent.Type.UpdateRequest)


class QDialog(QWidget):
    def exec(self) -> int: return 1
    def accept(self) -> None: self.close()
    def reject(self) -> None: self.close()


class QFrame(QWidget):
    class Shape:
        NoFrame = 0
        StyledPanel = 1
    def setFrameShape(self, _s: Any) -> None: pass


class QLabel(QWidget):
    def __init__(self, text_or_parent: Any = "", parent: Optional[Any] = None) -> None:
        if isinstance(text_or_parent, QWidget):
            super().__init__(text_or_parent)
            self._text = ""
        else:
            super().__init__(parent)
            self._text = str(text_or_parent or "")
        self._pixmap: Optional[QPixmap] = None

    def text(self) -> str: return self._text
    def setText(self, t: str) -> None:
        self._text = str(t)
        self._pixmap = None
    def pixmap(self) -> Optional[QPixmap]: return self._pixmap
    def setPixmap(self, pm: QPixmap) -> None:
        self._pixmap = pm
    def clear(self) -> None:
        self._text = ""
        self._pixmap = None
    def setWordWrap(self, _b: bool) -> None: pass
    def setAlignment(self, a: Any) -> None: self._align = int(a)
    def alignment(self) -> int: return getattr(self, "_align", Qt.AlignmentFlag.AlignCenter)


class QPushButton(QWidget):
    def __init__(self, text_or_parent: Any = "", parent: Optional[Any] = None) -> None:
        if isinstance(text_or_parent, QWidget):
            super().__init__(text_or_parent)
            self._text = ""
        else:
            super().__init__(parent)
            self._text = str(text_or_parent or "")
        self._checkable = False
        self._checked = False
        self.clicked = _BoundSignal()
        self.toggled = _BoundSignal()

    def text(self) -> str: return self._text
    def setText(self, t: str) -> None: self._text = str(t)
    def setCheckable(self, b: bool) -> None: self._checkable = bool(b)
    def isCheckable(self) -> bool: return self._checkable
    def isChecked(self) -> bool: return self._checked
    def setChecked(self, b: bool) -> None:
        changed = (bool(b) != self._checked)
        self._checked = bool(b)
        if changed and not self.signalsBlocked():
            self.toggled.emit(self._checked)
    def click(self) -> None:
        if self._checkable:
            self.setChecked(not self._checked)
        if not self.signalsBlocked():
            self.clicked.emit(self._checked)


class QCheckBox(QPushButton):
    def __init__(self, text_or_parent: Any = "", parent: Optional[Any] = None) -> None:
        super().__init__(text_or_parent, parent)
        self._checkable = True
        self.stateChanged = _BoundSignal()


class QLineEdit(QWidget):
    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._text = ""
        self.textChanged = _BoundSignal()
    def text(self) -> str: return self._text
    def setText(self, t: str) -> None:
        self._text = str(t)
        if not self.signalsBlocked():
            self.textChanged.emit(self._text)
    def setPlaceholderText(self, _p: str) -> None: pass


class QPlainTextEdit(QWidget):
    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._text = ""
    def toPlainText(self) -> str: return self._text
    def setPlainText(self, t: str) -> None: self._text = str(t)
    def setReadOnly(self, _b: bool) -> None: pass
    def setPlaceholderText(self, _p: str) -> None: pass


class QTextEdit(QPlainTextEdit):
    pass


class QComboBox(QWidget):
    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._items: List[Tuple[str, Any]] = []
        self._idx = 0
        self.currentIndexChanged = _BoundSignal()
    def addItem(self, label: str, user_data: Any = None) -> None:
        self._items.append((str(label), user_data))
    def addItems(self, labels: Sequence[str]) -> None:
        for l in labels: self.addItem(l, l)
    def currentIndex(self) -> int: return self._idx
    def setCurrentIndex(self, i: int) -> None:
        self._idx = max(0, min(len(self._items) - 1, int(i))) if self._items else 0
        if not self.signalsBlocked():
            self.currentIndexChanged.emit(self._idx)
    def currentText(self) -> str:
        return self._items[self._idx][0] if self._items else ""
    def setCurrentText(self, t: str) -> None:
        for idx, (lbl, _) in enumerate(self._items):
            if lbl == t:
                self.setCurrentIndex(idx)
                return
    def currentData(self) -> Any:
        return self._items[self._idx][1] if self._items else None
    def findData(self, d: Any) -> int:
        for idx, (_, ud) in enumerate(self._items):
            if ud == d: return idx
        return -1


class QListWidgetItem:
    def __init__(self, text: str = "") -> None:
        self._text = str(text)
        self._roles: Dict[int, Any] = {Qt.ItemDataRole.DisplayRole: self._text}
        self._selected = False
        self._size_hint = QSize(218, 182)
        self._icon: Optional[QIcon] = None
    def text(self) -> str: return self._text
    def setText(self, t: str) -> None:
        self._text = str(t)
        self._roles[Qt.ItemDataRole.DisplayRole] = self._text
    def data(self, role: int) -> Any: return self._roles.get(role)
    def setData(self, role: int, val: Any) -> None: self._roles[role] = val
    def setIcon(self, ic: QIcon) -> None: self._icon = ic
    def setSizeHint(self, sz: QSize) -> None: self._size_hint = sz
    def isSelected(self) -> bool: return self._selected
    def setSelected(self, b: bool) -> None: self._selected = bool(b)


class _ScrollBar(QObject):
    def __init__(self) -> None:
        super().__init__(None)
        self._val = 0
        self._max = 100
        self.valueChanged = _BoundSignal()
    def value(self) -> int: return self._val
    def setValue(self, v: int) -> None:
        changed = (int(v) != self._val)
        self._val = int(v)
        if changed and not self.signalsBlocked():
            self.valueChanged.emit(self._val)
    def maximum(self) -> int: return self._max


class _ModelIndex:
    def __init__(self, row: int, item: Optional[QListWidgetItem]) -> None:
        self._row = row
        self._item = item
    def row(self) -> int: return self._row
    def isValid(self) -> bool: return self._item is not None and self._row >= 0
    def data(self, role: int = Qt.ItemDataRole.DisplayRole) -> Any:
        return self._item.data(role) if self._item is not None else None


class QAbstractItemView(QWidget):
    class SelectionMode:
        SingleSelection = 1
        ExtendedSelection = 2


class QListWidget(QAbstractItemView):
    class ViewMode:
        ListMode = 0
        IconMode = 1
    class ResizeMode:
        Fixed = 0
        Adjust = 1
    class Movement:
        Static = 0

    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._items: List[QListWidgetItem] = []
        self._current_row = -1
        self._viewport = QWidget(self)
        self._viewport.resize(560, 620)
        self._sb = _ScrollBar()
        self._delegate: Optional[Any] = None
        self.itemSelectionChanged = _BoundSignal()
        self.itemDoubleClicked = _BoundSignal()
        self.currentRowChanged = _BoundSignal()
        self.customContextMenuRequested = _BoundSignal()

    def viewport(self) -> QWidget: return self._viewport
    def verticalScrollBar(self) -> _ScrollBar: return self._sb
    def setItemDelegate(self, d: Any) -> None: self._delegate = d
    def itemDelegate(self) -> Any: return self._delegate
    def setViewMode(self, _m: int) -> None: pass
    def setIconSize(self, _s: QSize) -> None: pass
    def setGridSize(self, _s: QSize) -> None: pass
    def setResizeMode(self, _m: int) -> None: pass
    def setMovement(self, _m: int) -> None: pass
    def setSelectionMode(self, _m: int) -> None: pass
    def setUniformItemSizes(self, _b: bool) -> None: pass
    def setWordWrap(self, _b: bool) -> None: pass
    def count(self) -> int: return len(self._items)
    def clear(self) -> None:
        self._items.clear()
        self._current_row = -1
    def addItem(self, it: Any) -> None:
        if isinstance(it, str):
            it = QListWidgetItem(it)
        self._items.append(it)
    def item(self, row: int) -> Optional[QListWidgetItem]:
        return self._items[row] if 0 <= row < len(self._items) else None
    def currentRow(self) -> int: return self._current_row
    def currentItem(self) -> Optional[QListWidgetItem]:
        return self.item(self._current_row)
    def setCurrentRow(self, row: int) -> None:
        for idx, it in enumerate(self._items):
            it.setSelected(idx == row)
        self._current_row = int(row)
        if not self.signalsBlocked():
            self.currentRowChanged.emit(self._current_row)
            self.itemSelectionChanged.emit()
    def clearSelection(self) -> None:
        for it in self._items:
            it.setSelected(False)
        if not self.signalsBlocked():
            self.itemSelectionChanged.emit()
    def selectedItems(self) -> List[QListWidgetItem]:
        return [it for it in self._items if it.isSelected()]
    def indexAt(self, _pos: QPoint) -> _ModelIndex:
        return _ModelIndex(0, self.item(0))
    def visualItemRect(self, it: QListWidgetItem) -> QRect:
        try:
            idx = self._items.index(it)
        except ValueError:
            return QRect(0, 0, 0, 0)
        col = idx % 2
        row = idx // 2
        return QRect(col * 224, row * 188, 218, 182)


class QStyledItemDelegate(QObject):
    def __init__(self, parent: Optional[Any] = None) -> None:
        super().__init__(parent)


class QSplitter(QWidget):
    def __init__(self, _orient: Any = None, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
    def setHandleWidth(self, _w: int) -> None: pass
    def setChildrenCollapsible(self, _b: bool) -> None: pass
    def addWidget(self, _w: QWidget) -> None: pass
    def setSizes(self, _s: Sequence[int]) -> None: pass


class _BoxLayout:
    def __init__(self, parent: Optional[Any] = None) -> None:
        if parent is not None: parent._layout = self
    def activate(self) -> None: pass
    def invalidate(self) -> None: pass
    def setContentsMargins(self, *_args: Any) -> None: pass
    def setSpacing(self, _s: int) -> None: pass
    def addWidget(self, *_args: Any) -> None: pass
    def addLayout(self, *_args: Any) -> None: pass
    def addSpacing(self, _s: int) -> None: pass
    def addStretch(self, _s: int = 0) -> None: pass


class QVBoxLayout(_BoxLayout): pass
class QHBoxLayout(_BoxLayout): pass
class QGridLayout(_BoxLayout): pass
class QFormLayout(_BoxLayout):
    def addRow(self, *_args: Any) -> None: pass


class QStyle:
    class StateFlag:
        State_Selected = 1
        State_MouseOver = 2


class QStyleOptionViewItem:
    def __init__(self, rect: Optional[QRect] = None, state: int = 0) -> None:
        self.rect = rect or QRect(0, 0, 218, 182)
        self.state = state


class QStyleOptionSlider: pass
class QGraphicsDropShadowEffect(QObject):
    def setBlurRadius(self, _r: float) -> None: pass
    def setColor(self, _c: QColor) -> None: pass
    def setOffset(self, *_args: Any) -> None: pass


class QSlider(QWidget):
    class TickPosition(metaclass=_DynamicEnumMeta):
        NoTicks = 0
    def __init__(self, *_args: Any) -> None:
        super().__init__(None)
        self._val = 0
        self._min = 0
        self._max = 100
        self.valueChanged = _BoundSignal()
        self.sliderReleased = _BoundSignal()
        self.sliderPressed = _BoundSignal()
        self.sliderMoved = _BoundSignal()
    def minimum(self) -> int: return self._min
    def maximum(self) -> int: return self._max
    def setPageStep(self, _s: int) -> None: pass
    def setSingleStep(self, _s: Any) -> None: pass
    def setRange(self, _a: int, _b: int) -> None: pass
    def setMinimum(self, _a: int) -> None: pass
    def setMaximum(self, _b: int) -> None: pass
    def setValue(self, v: int) -> None:
        changed = (int(v) != self._val)
        self._val = int(v)
        if changed and not self.signalsBlocked():
            self.valueChanged.emit(self._val)
    def value(self) -> int: return self._val
    def setTickPosition(self, _p: Any) -> None: pass


class QSpinBox(QSlider):
    def setSuffix(self, _s: str) -> None: pass
class QDoubleSpinBox(QSpinBox):
    def setSingleStep(self, _s: float) -> None: pass
    def setDecimals(self, _d: int) -> None: pass
class QProgressBar(QWidget): pass
class QScrollArea(QWidget):
    def setWidgetResizable(self, _b: bool) -> None: pass
    def setWidget(self, _w: QWidget) -> None: pass
class QSizePolicy:
    class Policy:
        Fixed = 0
        Expanding = 1
        Preferred = 2
class QKeySequence:
    def __init__(self, s: Any = "") -> None: self.seq = str(s)
class QKeySequenceEdit(QWidget): pass
class QShortcut(QObject):
    def __init__(self, _seq: Any, parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self.activated = _BoundSignal()
class QAction(QObject):
    def __init__(self, text: str = "", parent: Optional[Any] = None) -> None:
        super().__init__(parent)
        self._text = text
        self.triggered = _BoundSignal()
class QMenu(QWidget):
    def addAction(self, text: str, cb: Optional[Callable[[], Any]] = None) -> QAction:
        act = QAction(text, self)
        if cb is not None: act.triggered.connect(cb)
        return act
    def addSeparator(self) -> None: pass
    def exec(self, *_args: Any) -> None: pass
class QMessageBox:
    class StandardButton:
        Yes = 1
        No = 2
        Ok = 4
    @staticmethod
    def warning(*_args: Any) -> int: return 4
    @staticmethod
    def information(*_args: Any) -> int: return 4
    @staticmethod
    def critical(*_args: Any) -> int: return 4
    @staticmethod
    def question(*_args: Any) -> int: return 1
class QFileDialog:
    @staticmethod
    def getSaveFileName(*_args: Any) -> Tuple[str, str]: return ("", "")
class QInputDialog:
    @staticmethod
    def getText(*_args: Any, **kwargs: Any) -> Tuple[str, bool]: return (str(kwargs.get("text", "")), True)
class QColorDialog:
    @staticmethod
    def getColor(*_args: Any) -> QColor: return QColor(0, 220, 255)
class QSystemTrayIcon(QObject):
    class ActivationReason:
        Trigger = 1
    def __init__(self, *_args: Any) -> None:
        super().__init__(None)
        self.activated = _BoundSignal()
    def setIcon(self, _ic: Any) -> None: pass
    def setToolTip(self, _t: str) -> None: pass
    def setContextMenu(self, _m: Any) -> None: pass
    def show(self) -> None: pass
    def hide(self) -> None: pass


def install_qt_cairo_harness() -> None:
    qt_mod = types.ModuleType("PyQt6")
    core_mod = types.ModuleType("PyQt6.QtCore")
    gui_mod = types.ModuleType("PyQt6.QtGui")
    widgets_mod = types.ModuleType("PyQt6.QtWidgets")

    for name, obj in {
        "QEasingCurve": QEasingCurve,
        "QElapsedTimer": QElapsedTimer,
        "QEvent": QEvent,
        "QObject": QObject,
        "QPoint": QPoint,
        "QPointF": QPointF,
        "QRect": QRect,
        "QRectF": QRectF,
        "QRunnable": QRunnable,
        "QSize": QSize,
        "Qt": Qt,
        "QThreadPool": QThreadPool,
        "QTimer": QTimer,
        "QVariantAnimation": QVariantAnimation,
        "pyqtSignal": pyqtSignal,
        "_ModelIndex": _ModelIndex,
    }.items():
        setattr(core_mod, name, obj)

    for name, obj in {
        "QAction": QAction,
        "QBrush": QBrush,
        "QColor": QColor,
        "QCursor": QCursor,
        "QFont": QFont,
        "QFontMetrics": QFontMetrics,
        "QGuiApplication": QGuiApplication,
        "QIcon": QIcon,
        "QImage": QImage,
        "QKeySequence": QKeySequence,
        "QLinearGradient": QLinearGradient,
        "QMouseEvent": QMouseEvent,
        "QPaintEvent": QPaintEvent,
        "QPainter": QPainter,
        "QPainterPath": QPainterPath,
        "QPen": QPen,
        "QPixmap": QPixmap,
        "QPolygonF": QPolygonF,
        "QRadialGradient": QRadialGradient,
        "QShortcut": QShortcut,
    }.items():
        setattr(gui_mod, name, obj)

    for name, obj in {
        "QAbstractItemView": QAbstractItemView,
        "QApplication": QApplication,
        "QCheckBox": QCheckBox,
        "QColorDialog": QColorDialog,
        "QComboBox": QComboBox,
        "QDialog": QDialog,
        "QDoubleSpinBox": QDoubleSpinBox,
        "QFileDialog": QFileDialog,
        "QFormLayout": QFormLayout,
        "QFrame": QFrame,
        "QGridLayout": QGridLayout,
        "QGraphicsDropShadowEffect": QGraphicsDropShadowEffect,
        "QHBoxLayout": QHBoxLayout,
        "QInputDialog": QInputDialog,
        "QKeySequenceEdit": QKeySequenceEdit,
        "QLabel": QLabel,
        "QLineEdit": QLineEdit,
        "QListWidget": QListWidget,
        "QListWidgetItem": QListWidgetItem,
        "QMenu": QMenu,
        "QMessageBox": QMessageBox,
        "QPlainTextEdit": QPlainTextEdit,
        "QProgressBar": QProgressBar,
        "QPushButton": QPushButton,
        "QScrollArea": QScrollArea,
        "QSizePolicy": QSizePolicy,
        "QSlider": QSlider,
        "QSpinBox": QSpinBox,
        "QSplitter": QSplitter,
        "QStyle": QStyle,
        "QStyledItemDelegate": QStyledItemDelegate,
        "QStyleOptionSlider": QStyleOptionSlider,
        "QStyleOptionViewItem": QStyleOptionViewItem,
        "QSystemTrayIcon": QSystemTrayIcon,
        "QTextEdit": QTextEdit,
        "QVBoxLayout": QVBoxLayout,
        "QWidget": QWidget,
    }.items():
        setattr(widgets_mod, name, obj)

    qt_mod.QtCore = core_mod
    qt_mod.QtGui = gui_mod
    qt_mod.QtWidgets = widgets_mod

    sys.modules["PyQt6"] = qt_mod
    sys.modules["PyQt6.QtCore"] = core_mod
    sys.modules["PyQt6.QtGui"] = gui_mod
    sys.modules["PyQt6.QtWidgets"] = widgets_mod
