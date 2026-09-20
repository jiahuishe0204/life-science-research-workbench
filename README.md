# 生命科学科研调研工作台

当前仓库包含产品与技术方案、数据源实测记录、提示词验证、预算与安全规则，以及第一版零依赖网站骨架。

## 预览网站骨架

在项目目录运行：

```bash
python3 -m http.server 4173 --directory web
```

然后打开 `http://localhost:4173`。当前页面会明确提示“未连接检索”，不会用演示数据冒充真实调研结果。

## 本地检查

```bash
python3 tests/validate_web_skeleton.py
python3 tests/validate_security_retention.py
shasum -a 256 -c 文件校验清单.sha256
```

## 密钥

把 `.env.example` 复制为 `.env` 后只在本机填写。不要把 `.env`、密钥、数据库、日志、用户输入或备份提交到 GitHub。生产密钥只配置在部署平台的服务端环境变量中。

## 当前边界

- 已完成：静态页面骨架、提示词验证、论文数据源选择、官方来源白名单、DeepSeek 预算规则、域名／备份／创建者鉴权规则。
- 待完成：EPO OPS 应用凭据与真实调用、网站后端与真实数据链、EdgeOne 真实部署、端到端内容与权限验收。

详细状态以 `项目状态.json` 和 `移交说明.md` 为准。
