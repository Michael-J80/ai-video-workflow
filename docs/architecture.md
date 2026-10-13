# 架构说明

## 定位

`ai-video-workflow` 是 Windows 本地单用户、绑定 `127.0.0.1:8765` 的编排框架，`v0.1.0-alpha`。当前定位是**框架 + 模拟网页验证**，真实网页链路尚需按 `docs/browser-adapter.md` 配置并核实。

## 组件

- GUI / HTTP 服务（`app/`）：接收需求与素材，暴露 API 与 SSE 事件。
- 设计层（Codex CLI）：使用**订阅 ChatGPT 登录**，不使用 OpenAI API Key；app-server 返回可修改的设计。
- 计划层（Hermes + 自备 DeepSeek 凭据）：**无工具**准备计划（Flash）。
- 执行层（workers/ + 宿主 Playwright）：按计划执行**受限**网页操作，禁止泛化 shell 路由。
- 媒体层：FFmpeg/ffprobe 处理下载，进行**技术/内容分离**。
- 数据层：SQLite 记录状态与 `attempted` 标记；配置文件 `config.local.json`。

## 请求流程（概要）

1. 用户通过 GUI 输入需求，按序上传参考图（`POST /materials`）。
2. `POST /start` 启动任务；`POST /design` 获取 Codex 设计。
3. `POST /prepare` 由 Hermes 生成无工具计划，交宿主 Playwright 受限执行。
4. 默认样例：Seedance 2.5，480P，1 条。
5. 真实报价返回后需 `POST /approve` **批准一次**。
6. 批准后，**先在 SQLite 记录 `attempted`，再执行 Enter**；若结果不明，**只查不重提**。
7. 下载媒体后交由 FFmpeg 做技术/内容分离，`GET /api/tasks/{id}/files/path` 取回。

## 批准与绑定

- 批准仅绑定**当前设计 hash + 素材 hash 顺序 + 参数 + 报价**。
- 报价 **10 分钟**失效。
- 停止/暂停**不撤销**官网已扣任务。

## 状态模型

- 关键状态：`UNVERIFIED` 表示未知，**既非失败也非通过**。
- 语音功能未安装时显式 `skip_speech`；CUDA 不自动回退。

## 边界与不做

- 非多用户，不对公网暴露。
- 禁止 shell 泛化工具路由；个人运行不声称 OS 沙箱。
- 仓库不含登录态、参考角色图、视频、模型、二进制或凭据。

## 已知未验证项

- 即梦真实页面选择器**待核实**（`browser.example.json` 为空模板，需 `browser.local.json`）。
- **真实扣积分链路尚未验证**。
- Codex 账号协议检查本机已通过；Hermes CLI 已实际返回受限四步计划。
