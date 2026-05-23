"""Project-wide shared constants."""

# 受支持的代码托管平台 OAuth provider 标识(对应 social_django UserSocialAuth.provider).
# 该集合用于:
# - 用户首次 OAuth 登录时识别代码托管账号并触发待领取积分领取
# - 积分分配/领取逻辑中过滤用户绑定的代码托管社交账号
CODE_HOSTING_PROVIDERS = frozenset({"github", "gitee", "gitlab", "gitea", "atomgit"})
