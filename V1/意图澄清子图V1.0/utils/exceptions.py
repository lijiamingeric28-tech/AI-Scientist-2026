"""
自定义异常类
"""


class PipelineException(Exception):
    """管道基础异常"""
    pass


class StateValidationError(PipelineException):
    """State校验失败"""
    pass


class ToolExecutionError(PipelineException):
    """工具执行失败"""
    pass


class LLMTimeoutError(ToolExecutionError):
    """LLM调用超时"""
    pass


class LLMFormatError(ToolExecutionError):
    """LLM返回格式错误"""
    pass
