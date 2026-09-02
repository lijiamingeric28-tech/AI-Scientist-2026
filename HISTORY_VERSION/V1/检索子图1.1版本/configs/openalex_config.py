"""
OpenAlex API密钥配置说明

注意：OpenAlex目前主要通过邮箱进行礼貌请求，不需要API密钥。
如果你有OpenAlex的API密钥，可以在这里配置。
"""

# OpenAlex API配置
# 方式1：使用邮箱（推荐，免费）
OPENALEX_EMAIL = "lijiamingeric28@gmail.com"

# 方式2：使用API密钥（如果有的话）
# 注意：M4nUEG1eVxi3ExIT6kwScT 这个看起来像API密钥
# 但OpenAlex官方文档显示主要使用邮箱，不需要密钥
# 如果需要使用密钥，请在API调用时添加到请求头
OPENALEX_API_KEY = "M4nUEG1eVxi3ExIT6kwScT"  # 可选
