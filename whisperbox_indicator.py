#!/usr/bin/env python3
"""
Whisperbox recording indicator — built from scratch on native Cocoa.

Why this is different from every previous attempt: it uses a Cocoa
**non-activating NSPanel** (not Tkinter). A non-activating panel is the macOS
mechanism for a floating overlay that CANNOT become key/main and CANNOT take
keyboard focus — so it physically cannot interfere with what you're typing into.
No Tk, no shared code with the engine, no audio hooks.

It's a standalone, read-only process: it watches the engine's log
(/tmp/whisperbox.log) to know when you're recording and shows a small animated
indicator. If it dies or misbehaves, the engine is completely unaffected.
"""
import math
import os

import objc
from Foundation import NSObject, NSMakeRect
from AppKit import (
    NSApplication, NSPanel, NSView, NSColor, NSBezierPath, NSTimer, NSScreen,
    NSBackingStoreBuffered, NSStatusWindowLevel,
    NSWindowStyleMaskBorderless, NSWindowStyleMaskNonactivatingPanel,
    NSApplicationActivationPolicyAccessory,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorStationary,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
)

LOG = "/tmp/whisperbox.log"
W, H = 300.0, 62.0

STATE = {"mode": "idle", "phase": 0.0, "pos": 0, "visible": False}


def _rgba(r, g, b, a=1.0):
    return NSColor.colorWithCalibratedRed_green_blue_alpha_(r, g, b, a)


class IndicatorView(NSView):
    def drawRect_(self, dirty):
        b = self.bounds()
        w, h = b.size.width, b.size.height
        cy = h / 2.0

        # rounded dark pill background
        _rgba(0.08, 0.086, 0.11, 0.96).setFill()
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(b, 26.0, 26.0).fill()

        recording = STATE["mode"] == "recording"
        (_rgba(1.0, 0.29, 0.29) if recording else _rgba(1.0, 0.69, 0.13)).setFill()

        # status dot
        NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(18, cy - 5, 10, 10)).fill()

        # smooth flowing bars (time-based, not tied to audio)
        n, x0, x1 = 22, 46.0, w - 22.0
        gap = (x1 - x0) / n
        ph = STATE["phase"]
        for i in range(n):
            wave = (math.sin(ph + i * 0.5) + 1) / 2.0
            amp = (0.25 + wave * 0.65) if recording else (wave * 0.55)
            bh = max(3.0, amp * (h * 0.6))
            x = x0 + i * gap + gap / 2.0
            NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                NSMakeRect(x - 1.5, cy - bh / 2, 3.0, bh), 1.5, 1.5).fill()


class Ticker(NSObject):
    def initWithPanel_view_(self, panel, view):
        self = objc.super(Ticker, self).init()
        if self is None:
            return None
        self.panel = panel
        self.view = view
        return self

    def _read_log(self):
        try:
            size = os.path.getsize(LOG)
        except OSError:
            return
        if size < STATE["pos"]:
            STATE["pos"] = 0
        try:
            with open(LOG) as f:
                f.seek(STATE["pos"])
                chunk = f.read()
                STATE["pos"] = f.tell()
        except OSError:
            return
        for line in chunk.splitlines():
            if "RECORDING" in line:
                STATE["mode"] = "recording"
            elif "captured dur" in line:
                STATE["mode"] = "transcribing"
            elif any(k in line for k in ("transcript:", "no speech",
                                         "delivered", "error", "quitting")):
                STATE["mode"] = "idle"

    def tick_(self, timer):
        self._read_log()
        STATE["phase"] += 0.3
        if STATE["mode"] in ("recording", "transcribing"):
            if not STATE["visible"]:
                self.panel.orderFrontRegardless()   # show WITHOUT activating
                STATE["visible"] = True
            self.view.setNeedsDisplay_(True)
        elif STATE["visible"]:
            self.panel.orderOut_(None)
            STATE["visible"] = False


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

    screen = NSScreen.mainScreen().frame()
    x = (screen.size.width - W) / 2.0
    y = 130.0
    mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
    panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(x, y, W, H), mask, NSBackingStoreBuffered, False)
    panel.setLevel_(NSStatusWindowLevel)   # above fullscreen windows
    panel.setOpaque_(False)
    panel.setBackgroundColor_(NSColor.clearColor())
    panel.setHasShadow_(True)
    panel.setIgnoresMouseEvents_(True)
    panel.setCollectionBehavior_(
        NSWindowCollectionBehaviorCanJoinAllSpaces
        | NSWindowCollectionBehaviorStationary
        # fullscreen apps are their own Space; without this flag macOS
        # shows the pill on the last regular desktop instead
        | NSWindowCollectionBehaviorFullScreenAuxiliary)

    view = IndicatorView.alloc().initWithFrame_(NSMakeRect(0, 0, W, H))
    panel.setContentView_(view)

    try:
        STATE["pos"] = os.path.getsize(LOG)   # start from end; ignore old lines
    except OSError:
        STATE["pos"] = 0

    ticker = Ticker.alloc().initWithPanel_view_(panel, view)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        0.04, ticker, "tick:", None, True)

    print("[indicator] running (non-activating Cocoa panel)", flush=True)
    app.run()


if __name__ == "__main__":
    main()
