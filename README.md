# 生命科学科研调研工作台

当前仓库包含产品与技术方案、数据源实测记录、提示词验证、预算与安全规则，以及第一版零依赖网站骨架。

## 运行本地真实后端

在项目目录运行：

```bash
python3 server.py
```

然后打开 `http://127.0.0.1:4173`。服务会从本地 `.env` 读取 DeepSeek 密钥，真实调用 PubMed、Europe PMC、Crossref 和 DeepSeek；EPO 未获批时会明确降级，不会冒充已经检索专利。

## 本地检查

```bash
python3 tests/validate_web_skeleton.py
python3 tests/validate_security_retention.py
python3 tests/validate_edgeone_scaffold.py
PYTHONPATH=. python3 tests/test_server_core.py
shasum -a 256 -c 文件校验清单.sha256
```

## EdgeOne Makers

仓库根目录的 `edgeone.json` 将静态输出目录固定为 `web/`，并把 Node.js Cloud Functions 最长执行时间设为 120 秒。`cloud-functions/api/health.js` 是第一个上线探针：它只返回环境变量是否已配置，不返回任何密钥值，并使用强一致读取验证 Blob 可读写。

上线后检查 `/api/health`。只有返回 `ok: true` 且 `storage: "read_write"` 时，才继续迁移真实任务链。

## 密钥

把 `.env.example` 复制为 `.env` 后只在本机填写。不要把 `.env`、密钥、数据库、日志、用户输入或备份提交到 GitHub。生产密钥只配置在部署平台的服务端环境变量中。

## 当前边界

- 已完成：网站页面、本地真实论文／模型后端、五主题端到端验收、提示词验证、论文数据源选择、官方来源白名单、DeepSeek 预算规则、域名／备份／创建者鉴权规则。
- 待完成：EPO OPS 应用凭据与真实调用、创建者真实登录、EdgeOne 真实部署、部署后的权限／备份／移动端验收与公开发布决定。

详细状态以 `项目状态.json` 和 `移交说明.md` 为准。
