# ai-video-workflow

> **alpha 重要限制（务必先读）**
>
> - 本版本是**框架 + 模拟网页验证**的 alpha，不是开箱即用的全自动真实生产工具。
> - **即梦真实页面的选择器尚待核实**：仓库内 `browser.example.json` 是**空选择器模板**，必须复制为 `browser.local.json` 并按 `docs/browser-adapter.md` 配置后才可能生成。默认配置下无法生成。
> - **不宣传安装后即可全自动真实生成**；**真实扣积分链路尚未验证**。
> - **Codex 账号协议检查**已在本机通过测试；Hermes CLI 实际返回受限四步计划，适配器会拒绝不符合契约的回答。
> - 标记为 **UNVERIFIED** 的状态，既**不是失败也不是通过**。
> - 用户批准仅绑定**当前设计 hash + 素材 hash 顺序 + 参数 + 报价**；报价 **10 分钟**失效；**停止不撤销已扣的官网任务**。
> - 仓库**不包含**登录态、参考角色图、视频、模型、二进制或任何凭据；第三方许可见 `THIRD_PARTY_NOTICES.md`。
> - 请使用者自行遵守各平台条款。仅面向 **Windows 本地单用户**，**非多用户部署**，**不要对公网暴露**。

## 概述

`ai-video-workflow` 是一个本地运行的 AI 视频生成编排框架，目标是把“需求输入 → 设计 → 计划 → 受控网页操作 → 下载并分析媒体”串成可审计的流程。

- 版本：`v0.1.0-alpha`
- 许可证：MIT
- 平台：Windows 本地单用户，默认监听 `127.0.0.1:8765`（不要对公网暴露）
- 依赖：Python 3.12、Chrome、Codex CLI（使用订阅 ChatGPT 登录，**不使用 OpenAI API Key**）、Hermes + 自己的 DeepSeek 凭据、FFmpeg/ffprobe
- 可选语音：`install-speech.ps1 -Device cpu|cuda`。未安装时**显式 skip_speech**，不假装成功；CUDA 不做自动回退。

## 安装

1. 安装依赖：Python 3.12、Chrome、Codex CLI、Hermes（配置自己的 DeepSeek 凭据）、FFmpeg/ffprobe。
2. 运行安装脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

3. 可选语音安装（按需，不装则显式 skip_speech）：

```powershell
# CPU
powershell -ExecutionPolicy Bypass -File .\install-speech.ps1 -Device cpu
# CUDA（不自动回退到 CPU）
powershell -ExecutionPolicy Bypass -File .\install-speech.ps1 -Device cuda
```

4. 复制配置模板并填写本机值：

```
config.example.json  ->  config.local.json
```

5. 浏览器适配（真实页面必须）：复制 `browser.example.json` 为 `browser.local.json`，并按 `docs/browser-adapter.md` 填写选择器。**空选择器模板无法生成**。

## 启动

```cmd
start.cmd
```

默认地址：`http://127.0.0.1:8765`

## 使用流程（概要）

1. GUI 输入需求，并按顺序上传参考图。
2. Codex app-server 返回可修改的设计。
3. Hermes Flash **无工具**准备计划 → 宿主 Playwright 执行**受限**操作。
4. 默认使用 Seedance 2.5 样片，480P，1 条。
5. 真实报价需用户**批准一次**。
6. 批准后，在 SQLite 记录 `attempted` 之后才执行 Enter；**结果不明只查绝不重提**。
7. 下载后分别记录**技术验收与内容验收**。

> 批准有效期 10 分钟，且仅绑定当次设计 hash、素材 hash 顺序、参数与报价。暂停在当前阶段结束后生效，**不撤销**官网已扣任务。

## API 清单

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/session` | 会话信息 |
| GET | `/api/health` | 健康检查 |
| GET/POST | `/api/tasks` | 任务列表 / 创建 |
| GET | `/api/tasks/id` | 任务详情 |
| POST | `/api/tasks/{id}/materials` | 上传素材 |
| POST | `/api/tasks/{id}/start` | 开始 |
| POST | `/api/tasks/{id}/design` | 生成/提交设计 |
| POST | `/api/tasks/{id}/prepare` | 准备计划 |
| POST | `/api/tasks/{id}/approve` | 批准报价 |
| POST | `/api/tasks/{id}/pause` | 暂停 |
| POST | `/api/tasks/{id}/resume` | 恢复 |
| GET | `/api/tasks/{id}/events` | SSE 事件 |
| GET | `/api/tasks/{id}/files/path` | 获取文件 |
| POST | `/api/browser/login` | 浏览器登录 |

## 安全与边界

- **禁止 shell 泛化工具路由**：不提供任意命令执行通道。
- 个人运行场景，**不声称 OS 沙箱**；请自行限制访问范围，仅绑定 `127.0.0.1`。

## 目录结构

```
app/       应用与 API
workers/   任务执行（设计、计划、网页操作、下载等）
tests/     测试
docs/      文档
templates/ 模板
examples/  示例配置
```

## 测试

```
python -m pytest tests
```

计划中的真实测试**只能在报价后由用户批准一次**，未批准不得触发真实扣积分操作。

## 状态说明

- 本项目多处能力处于 **UNVERIFIED**：既非失败，也非通过。
- 不虚构安装器会下载现成的模型，也不虚构任何验证成功。
- 文档中不会写入“已通过”的未确认项。

## 许可

MIT。第三方组件与许可详见 `THIRD_PARTY_NOTICES.md`。
