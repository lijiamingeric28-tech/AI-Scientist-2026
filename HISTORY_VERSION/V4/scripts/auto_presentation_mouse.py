"""
答辩演示物理鼠标辅助脚本 (Win32 OS-Level Presentation Mouse Automation)

适用场景：
如果您希望在 Recordly 录屏时录制真实的系统级物理鼠标光标，
可使用本脚本作为双保险工具。
无需安装 PyAutoGUI 等第三方库，直接使用 Python 核心库 ctypes 调用 Windows User32 API。

安全设计：
- 紧急制动 Fail-safe：将鼠标甩至屏幕左上角 (0, 0) 或按 Ctrl + C 即刻终止。
- 平滑缓动：采用三次缓动 (Cubic Ease In-Out) 模拟人手操作，杜绝机械僵硬感。
"""

import sys
import time
import math
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

# 鼠标事件标志
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

def get_cursor_pos():
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y

def set_cursor_pos(x, y):
    user32.SetCursorPos(int(x), int(y))

def check_failsafe():
    x, y = get_cursor_pos()
    if x <= 5 and y <= 5:
        print("\n[AutoMouse] 🚨 检测到鼠标移至屏幕左上角，触发紧急制动！")
        sys.exit(0)

def ease_in_out_cubic(t):
    return 4 * t * t * t if t < 0.5 else 1 - math.pow(-2 * t + 2, 3) / 2

def smooth_move_to(target_x, target_y, duration=0.8, steps=60):
    start_x, start_y = get_cursor_pos()
    start_time = time.time()
    
    for i in range(1, steps + 1):
        check_failsafe()
        elapsed = time.time() - start_time
        progress = min(1.0, elapsed / duration)
        eased = ease_in_out_cubic(progress)
        
        cur_x = start_x + (target_x - start_x) * eased
        cur_y = start_y + (target_y - start_y) * eased
        set_cursor_pos(cur_x, cur_y)
        
        if progress >= 1.0:
            break
        time.sleep(duration / steps)
    
    set_cursor_pos(target_x, target_y)

def mouse_click(duration_after=0.2):
    check_failsafe()
    user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.08)
    user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(duration_after)

def mouse_scroll(delta_wheel, duration_after=0.3):
    check_failsafe()
    user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, int(delta_wheel), 0)
    time.sleep(duration_after)

def countdown_banner(seconds=5):
    print("=" * 60)
    print("🎬 答辩录屏辅助：物理鼠标平滑演示引擎")
    print("=" * 60)
    print("说明：")
    print("1. 请确保前端已打开并处于全屏或前台窗口")
    print("2. 紧急停止：随时将鼠标甩到屏幕最左上角，或在控制台按 Ctrl+C")
    print(f"3. 录屏准备倒计时 {seconds} 秒：请切换至 Recordly 软件点击开始录制...")
    print("=" * 60)
    
    for remaining in range(seconds, 0, -1):
        print(f"⏳ 距离脚本接管鼠标还剩: {remaining} 秒")
        time.sleep(1)
    print("🚀 演示开始！")

def main():
    screen_w = user32.GetSystemMetrics(0)
    screen_h = user32.GetSystemMetrics(1)
    print(f"[AutoMouse] 侦测到主屏幕分辨率: {screen_w} x {screen_h}")

    countdown_banner(5)

    try:
        # 幕一：居中并展示首页
        smooth_move_to(int(screen_w * 0.5), int(screen_h * 0.45), duration=1.0)
        time.sleep(2.0)

        # 移动至左侧栏切换为演示样例
        smooth_move_to(int(screen_w * 0.08), int(screen_h * 0.09), duration=0.8)
        time.sleep(0.5)
        mouse_click(1.0)

        # 幕二：定位昂星团 M45
        smooth_move_to(int(screen_w * 0.4), int(screen_h * 0.35), duration=0.9)
        time.sleep(1.5)

        # 点击回放
        smooth_move_to(int(screen_w * 0.52), int(screen_h * 0.35), duration=0.6)
        mouse_click(1.5)

        # 幕三：回放进行中跟随
        print("[AutoMouse] 正在回放执行中...")
        time.sleep(55)

        # 幕四：数据结果
        smooth_move_to(int(screen_w * 0.48), int(screen_h * 0.62), duration=0.8)
        mouse_click(1.5)

        print("[AutoMouse] 演示流程执行完毕。")

    except KeyboardInterrupt:
        print("\n[AutoMouse] 用户手动按 Ctrl+C 中止演示。")

if __name__ == '__main__':
    main()
