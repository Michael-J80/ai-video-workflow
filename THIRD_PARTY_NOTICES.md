# 第三方组件

MIT 仅覆盖本仓库自有源码、文档与模板。外部组件独立安装，各自许可证不因本仓库 MIT 而改变；官网服务、订阅及模型权重也不属于本项目授权范围。

| 组件 | 上游及许可证 |
| --- | --- |
| FastAPI / Starlette / Uvicorn / HTTPX / pytest | 对应 PyPI 发行版，BSD/MIT 许可证，详见安装分发中的 LICENSE |
| Playwright | [microsoft/playwright](https://github.com/microsoft/playwright)，Apache-2.0 |
| Codex CLI | [openai/codex](https://github.com/openai/codex)，Apache-2.0；账户服务另受服务条款约束 |
| Hermes Agent | [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)，MIT；本项目不再分发其代码或登录数据 |
| PySceneDetect | [Breakthrough/PySceneDetect](https://github.com/Breakthrough/PySceneDetect)，BSD-3-Clause |
| WhisperX | [m-bain/whisperX](https://github.com/m-bain/whisperX)，BSD-2-Clause；模型及其他依赖分别授权 |
| OpenCV | [opencv/opencv](https://github.com/opencv/opencv)，Apache-2.0；Python wheels 内含第三方声明 |
| NumPy | [numpy/numpy](https://github.com/numpy/numpy)，BSD-3-Clause |
| Pillow | [python-pillow/Pillow](https://github.com/python-pillow/Pillow)，HPND |
| FFmpeg / FFprobe | [ffmpeg.org/legal.html](https://ffmpeg.org/legal.html)，构建可能适用 LGPL 或 GPL；本项目仅调用用户安装版本，不分发二进制 |
| Chrome / Chromium | 用户另行安装；浏览器及其第三方组件受各自许可约束 |

`workers/scene_worker.py`、`speech_worker.py`、`subtitle_utils.py` 是从本项目所有者既有本地工作流迁入的自有编排代码，调用而不复制上述第三方算法库源码。仓库未包含第三方角色参考图、历史样片、模型权重或私有工具包。

精确的基础 Python 依赖记录在 `requirements.lock.txt`。可选语音环境由 `install-speech.ps1` 单独安装，重型运行库和模型不进入 Git。
