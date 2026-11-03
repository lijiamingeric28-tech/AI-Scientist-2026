import { clsx } from "clsx"
import { twMerge } from "tailwind-merge"

/**
 * 合并 Tailwind class 字符串，自动处理冲突类名
 * shadcn/ui 标准 cn 工具函数
 */
export function cn(...inputs) {
  return twMerge(clsx(inputs))
}
