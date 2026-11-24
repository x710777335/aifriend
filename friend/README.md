# AI 虚拟陪伴机器人 MVP

一个使用 Python 3.11 与 PySide6 实现的 Windows 桌面虚拟陪伴程序。左侧是随状态变化的 2D 头像，右侧是多轮文本对话。

## 目录结构

```text
friend/
├── main.py
├── requirements.txt
├── .env.example
├── config.example.toml
├── companion/
│   ├── config.py              # 环境、配置与日志
│   ├── interaction.py         # 统一交互状态机
│   ├── llm.py                 # 异步 OpenAI 兼容客户端 / Mock
│   ├── storage.py             # SQLite 聊天记录
│   ├── interfaces.py          # Vision / Audio / Memory 扩展点
│   └── ui/
│       ├── avatar.py
│       └── main_window.py
└── tests/
    └── test_interaction.py
```

## Windows 启动

1. 安装 Python 3.11，并在本项目目录打开 PowerShell。
2. 创建并启用虚拟环境：

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. 可选：复制 `.env.example` 为 `.env`。默认 `USE_MOCK_LLM=true`，无需 API Key。
4. 启动：

   ```powershell
   python main.py
   ```

输入“你好”后，头像会变为 Thinking，Mock 服务稍后给出回复并回到 Idle。窗口主线程不会等待网络请求。

## 使用 OpenAI 兼容接口

将 `.env` 设置为：

```ini
USE_MOCK_LLM=false
OPENAI_API_KEY=你的密钥
OPENAI_BASE_URL=https://your-provider.example/v1
OPENAI_MODEL=your-model
```

密钥只从 `OPENAI_API_KEY` 环境变量（或 `.env`）读取，程序不会写入配置或日志。`base_url`、`model` 与 Mock 开关也可用环境变量覆盖 `config.toml` 中的同名配置。

## 头像素材

如有素材，可在 `assets/avatars/` 中放入 `idle.png`、`greeting.png`、`listening.png`、`thinking.png`、`speaking.png`。缺少任一图片时，程序绘制对应状态的默认占位头像。

## 测试

```powershell
python -m unittest discover -s tests -v
```

SQLite 数据保存在运行目录的 `data/chat_history.sqlite3`，日志保存在 `logs/app.log`（两者均不会包含 API Key）。

## ESP32 WebSocket 服务（第一阶段）

`server_main.py` 是无 GUI 的 ESP32 服务入口。它实现 XiaoZhi WebSocket v1 的 `hello`、`listen`、`abort`、二进制 Opus 缓冲，以及服务端下发的 `stt`、`llm`、`tts` 控制消息。每个 `Device-Id` 使用独立的 SQLite `conversation_id`，不会串扰设备聊天记录。

```powershell
python -m pip install -r requirements.txt
python server_main.py
```

配置 ESP32 时，将 WebSocket URL 设为 `ws://<电脑局域网IP>:8765`。在生产网络中必须在 `.env` 设置 `FRIEND_DEVICE_TOKEN`，并在固件 WebSocket token 配置中填入同一值。第一阶段默认不会接受设备伪造的 `stt` JSON；将 `FRIEND_ALLOW_TEST_STT=true` 写入 `.env` 后，才可通过它做协议模拟测试。

服务端在收到 `listen: stop` 后处理该回合缓存的 Opus 音频：解码为 16k PCM、交给本地 SenseVoice、复用现有百炼 LLM，然后将 Edge TTS 的音频转换为 24k Opus 二进制帧并下发。`av`（PyAV）是该链路的必需依赖；首次启动前请确认 `python -c "import av"` 成功。

## 第二阶段：本地实时语音对话

语音链路为“麦克风 → VAD → SenseVoice ASR → 原有 LLM → Edge TTS → 扬声器”。它采用半双工模式：从检测到一句语音开始到 AI 播放完毕之间，麦克风会暂停，避免识别到自身的回复。每个语音会话带有 session id，关闭语音后不会被旧的后台回调重新开启。

### 安装

语音模式需要额外依赖，已列在 `requirements.txt`。务必使用**运行程序的同一个 Python 环境**执行：

```powershell
python -m pip install -r requirements.txt
```

`kaldi-native-fbank` is included as the FunASR feature-extraction backend. It avoids having to find a `torchaudio` wheel that exactly matches the installed Torch version.

首次实际语音识别会下载并缓存 Silero VAD 与 `iic/SenseVoiceSmall` 模型；需要网络、磁盘空间，且下载时间取决于网络。默认使用 CPU。Edge TTS 也需要联网。

将 `config.example.toml` 复制为 `config.toml` 后，可修改麦克风、VAD、ASR 与语音参数：

```powershell
Copy-Item config.example.toml config.toml
```

默认 VAD 策略会在检测到语音后等待连续静音 3 秒再将其作为一句提交；单句最长 30 秒，达到上限会自动提交，避免无限录音。

若 Windows 上 `soundfile` 无法读取 Edge TTS 输出的 MP3，请升级 `soundfile`（项目已要求 `>=0.12`）；该版本的 Windows wheel 通常带有 MP3 解码支持。仍无法播放时，请安装 FFmpeg 并确保它位于 `PATH`，以供系统音频工具转换/解码。

### 使用与验收

1. 启动 `python main.py`，点击 **Start voice**，选择允许访问的麦克风。
2. 正常说“你好”，界面依次显示 Listening、Processing ASR、Thinking、Synthesizing speech、Speaking。
3. 识别出的文本会显示在 Transcript，也会作为普通用户消息写入同一 SQLite 聊天历史。
4. AI 回复显示后由 TTS 播放，头像占位图按播放 RMS 能量张嘴；播放结束自动恢复 Listening。
5. 点击 **Stop voice** 可立即停止监听并使过期 ASR/TTS/播放回调失效。文本输入始终保留可用。

语音组件位于 `companion/audio/`：`microphone.py`、`vad.py`、`asr.py`、`tts.py`、`player.py` 和 `manager.py`。它们均不直接修改 Qt 控件；界面更新经 Qt 信号完成。
