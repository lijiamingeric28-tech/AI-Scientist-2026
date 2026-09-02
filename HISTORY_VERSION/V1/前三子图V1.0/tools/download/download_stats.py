"""
下载统计模块

用于收集和展示下载过程的统计信息
"""

import time
from collections import defaultdict
from urllib.parse import urlparse
from typing import Optional


class DownloadStats:
    """下载统计类"""

    def __init__(self):
        self.total = 0
        self.success = 0
        self.failed = 0
        self.skipped = 0
        self.total_bytes = 0
        self.start_time = None
        self.end_time = None

        # 按来源统计
        self.success_by_source = defaultdict(int)

        # 按域名统计
        self.success_by_domain = defaultdict(int)
        self.failed_by_domain = defaultdict(int)

    def start(self):
        """开始计时"""
        self.start_time = time.time()

    def finish(self):
        """结束计时"""
        self.end_time = time.time()

    def record_success(self, source: str, url: Optional[str], file_size: int):
        """记录成功下载"""
        self.success += 1
        self.total_bytes += file_size
        self.success_by_source[source] += 1

        if url:
            try:
                domain = urlparse(url).netloc
                self.success_by_domain[domain] += 1
            except:
                pass

    def record_failure(self, url: Optional[str] = None):
        """记录失败下载"""
        self.failed += 1

        if url:
            try:
                domain = urlparse(url).netloc
                self.failed_by_domain[domain] += 1
            except:
                pass

    def record_skip(self):
        """记录跳过"""
        self.skipped += 1

    def get_elapsed_time(self) -> float:
        """获取耗时（秒）"""
        if self.start_time and self.end_time:
            return self.end_time - self.start_time
        return 0

    def print_summary(self):
        """打印统计摘要"""
        elapsed = self.get_elapsed_time()

        print("\n" + "="*80)
        print("下载统计报告")
        print("="*80)

        print(f"\n总计: {self.total} 篇")
        if self.total > 0:
            print(f"  成功: {self.success} 篇 ({self.success/self.total*100:.1f}%)")
            print(f"  跳过: {self.skipped} 篇 ({self.skipped/self.total*100:.1f}%)")
            print(f"  失败: {self.failed} 篇 ({self.failed/self.total*100:.1f}%)")

        print(f"\n总大小: {self.total_bytes / (1024*1024):.1f} MB")
        print(f"总耗时: {elapsed:.1f} 秒")

        if elapsed > 0:
            print(f"平均速度: {self.total/elapsed:.2f} 篇/秒")
            if self.success > 0:
                print(f"下载速度: {self.total_bytes / (1024*1024) / elapsed:.2f} MB/秒")

        if self.success_by_source:
            print(f"\n按来源统计:")
            for source, count in sorted(self.success_by_source.items(),
                                        key=lambda x: x[1], reverse=True):
                print(f"  {source:15s}: {count:3d} 篇")

        if self.success_by_domain:
            print(f"\nTop 5 成功域名:")
            for domain, count in sorted(self.success_by_domain.items(),
                                        key=lambda x: x[1], reverse=True)[:5]:
                print(f"  {domain:40s}: {count:3d} 篇")

        print("="*80)
