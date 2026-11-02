"""
答辩演示录屏一键启动脚本 (Presentation Demo Script Launcher)

用途：
- 无需在 UI 界面保留任何录制按钮（保持前端纯净优雅无干扰）；
- 运行本脚本后，5 秒倒计时留给操作者在 Recordly 录屏软件点击“开始录制”；
- 倒计时结束自动将 AstroQuery AI 窗口置顶，并发送 Alt+D 触发前端自动化演播。

快捷键备忘：
- 键盘直接触发：Alt + D 或 Ctrl + Shift + D
- 紧急中止：随时按 Esc 键
"""

import sys
import time
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

# 虚拟键码
VK_MENU = 0x12    # Alt 键
VK_D = 0x44       # D 键
KEYEVENTF_KEYUP = 0x0002

def find_astroquery_hwnd():
    """查找 AstroQuery AI 窗口句柄"""
    found_hwnd = []

    def enum_cb(hwnd, lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buff = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buff, length + 1)
                title = buff.value
                if "astroquery" in title.lower() or "ai-scientist" in title.lower():
                    found_hwnd.append(hwnd)
        return True

    CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows(CMPFUNC(enum_cb), 0)
    return found_hwnd[0] if found_hwnd else None

def activate_window(hwnd):
    """将目标窗口激活并置于前台"""
    if not hwnd:
        return
    # 解除可能存在的最小化
    SW_RESTORE = 9
    user32.ShowWindow(hwnd, SW_RESTORE)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.3)

def trigger_alt_d():
    """向当前前台窗口发送 Alt + D 快捷键"""
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_D, 0, 0, 0)
    time.sleep(0.06)
    user32.keybd_event(VK_D, 0, KEYEVENTF_KEYUP, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)

def main():
    print("=" * 64)
    print("🎬 AstroQuery AI 答辩演示录屏启动器 (Clean UI Mode)")
    print("=" * 64)
    print("说明：")
    print("1. 前端 UI 界面已完全去除录屏按钮，录屏画面纯净规范；")
    print("2. 即将开始 5 秒倒计时，请切换到 Recordly 录屏软件准备录制；")
    print("3. 演示过程中随时按键盘 Esc 键可立即安全终止。\n")

    hwnd = find_astroquery_hwnd()
    if hwnd:
        print("[Launcher] 已成功侦测到 AstroQuery AI 前端窗口。")
    else:
        print("[Launcher] 提示：请确保 AstroQuery AI 桌面客户端或网页已打开。")

    for i in range(5, 0, -1):
        print(f"⏳ 距离启动演示还剩: {i} 秒 (请在 Recordly 点开始录制)...", flush=True)
        time.sleep(1)

    print("\n🚀 正在唤起窗口并触发演示引擎...")
    if hwnd:
        activate_window(hwnd)
    trigger_alt_d()

    print("=" * 64)
    print("✅ 演播已启动！前端高亮演示光标正在按六幕剧本自动平滑演示：")
    print("   • 幕一：首页科研定位")
    print("   • 幕二：定位并选中「昴星团 M45（09-01 版）」卡片")
    print("   • 幕三：100x 回放执行，自动点击 [确认 (y)] 人工确认步骤")
    print("   • 幕四：数据结果、出处与证据抽屉、来源图证灯箱与质量雷达图")
    print("   • 幕五：工作流可视化、实时日志抽屉与返回按钮")
    print("   • 幕六：使用帮助新版截图展示与偏好设置收官")
    print("=" * 64)

if __name__ == '__main__':
    main()
