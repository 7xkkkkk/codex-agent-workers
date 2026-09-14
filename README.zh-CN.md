# codex-agent-workers

[English](README.md) | [简体中文](README.zh-CN.md)

一个在本机执行有明确范围的编程任务、返回可审查 Git diff 的 MCP 服务。
由你的编程助手指定任务、文件和测试，配置的执行模型提出修改方案；本地执行器在独立的 Git worktree 中应用修改，运行指定测试，并返回实际结果。

API 地址、密钥和模型名称均通过配置提供，支持兼容 OpenAI 的 Chat Completions 和 Responses 接口，不绑定特定 API 供应商。本项目并非 OpenAI 官方产品。

## 环境要求

- Python 3.12 和 Git，服务进程需要能访问它们。
- Linux 或 WSL，这是目前已验证的执行环境。
- 支持上述两种协议之一的 API，以及能按要求返回 JSON 修改方案的模型。
- 目标项目必须是至少有一次提交、工作区干净的 Git 仓库。

Git 可以完全在本机使用，目标项目不需要上传 GitHub。

## 安装与配置

克隆或下载本仓库后，执行：

```bash
cd codex-agent-workers
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
```

根据供应商提供的信息填写 `.env`：

```dotenv
WORKER_BASE_URL=https://api.example.com/v1
WORKER_API_KEY=your-api-key
WORKER_MODEL_FAST=your-fast-model
WORKER_MODEL_HARD=your-reasoning-model
WORKER_API_MODE=chat_completions
```

`api.example.com` 只是占位地址。请使用供应商文档给出的 API 基础地址，包括其要求的 `/v1` 等路径。
如果使用兼容 Responses 的接口，将 `WORKER_API_MODE` 改为 `responses`。
两个模型变量可以填写同一个模型名称。

程序读取 `server.py` 同目录下的 `.env`，不受客户端启动目录影响；进程中已有的环境变量优先。
真实密钥只保存在本机配置中，不要提交到 Git。仓库中的 `.env.example` 仅包含占位值。

## 连接 MCP 客户端

默认通过 stdio 运行：

```bash
.venv/bin/python server.py
```

在客户端中指定虚拟环境 Python 的路径，以及 `server.py` 的绝对路径。
对于使用 `mcpServers` JSON 配置格式的客户端，示例如下：

```json
{
  "mcpServers": {
    "codex-agent-workers": {
      "command": "/absolute/path/codex-agent-workers/.venv/bin/python",
      "args": ["/absolute/path/codex-agent-workers/server.py"]
    }
  }
}
```

如果客户端运行在 Windows、服务运行在 WSL，也可以选择本地 HTTP 方式：

```bash
.venv/bin/python server.py --http --port 8765
```

客户端连接 `http://127.0.0.1:8765/mcp`。保持服务终端运行；服务重启后，客户端需要重新连接以建立新会话。
HTTP 仅监听本机回环地址，没有身份验证，用于本机访问。

## 委派任务

调用 `delegate_task` 时明确指定输入：

```json
{
  "task": "让 status() 返回 ready。",
  "repo_path": "/absolute/path/target-repo",
  "files": ["main.py", "test_main.py"],
  "context": "保持现有函数签名不变。",
  "acceptance_criteria": ["现有 status 测试通过。"],
  "difficulty": "fast",
  "test_commands": [["python", "-m", "unittest", "-q"]],
  "test_timeout_seconds": 120
}
```

`difficulty` 为 `fast` 或 `hard`，分别使用 `WORKER_MODEL_FAST` 和 `WORKER_MODEL_HARD`。
`files` 使用相对仓库根目录的路径，分隔符为 `/`。
在采用标准磁盘挂载方式的 WSL 中，`C:\projects\target-repo` 会转换为 `/mnt/c/projects/target-repo`。
使用自定义挂载位置时，请直接传入 Linux 路径；目前不会转换 UNC 路径。

返回内容包括 `worker`、`status`、`changed_files`、`tests_run`、`git_diff`、`worktree_path`、`needs_escalation` 和 `escalation_reason`。
状态可能是 `completed`、`incomplete` 或 `blocked`。
`tests_run` 为空表示没有执行测试；任务完成也不代表修改已被审查或合并。

当前审查约定返回 `review_required: true` 和 `review_role: sol`。
调用方负责规划、编排及安排审查，服务本身不会自动调用审查模型。
修改保留在返回的 worktree 中，供调用方检查：

```bash
git -C /returned/worktree/path diff
# 审查并保存所需结果后，删除临时 worktree：
git -C /absolute/path/target-repo worktree remove --force /returned/worktree/path
```

worktree 默认保存在 `~/.local/share/codex-agent-workers/worktrees`。
可通过 `CODEX_WORKER_WORKTREE_ROOT` 修改保存位置。

## 执行范围与限制

指定文件的内容、任务说明、上下文和验收条件会发送给配置的 API。
工具不会自动对目标文件进行去敏感化，请选择适合发送给该供应商的文件。
`.gitignore` 控制 Git 跟踪范围，不会过滤显式传入的 `files`。

修改使用精确的 `create` / `replace` 操作。执行器拒绝路径越界、匹配不唯一的替换，以及工作区不干净的仓库。
测试命令以参数数组运行，不经过 shell。
允许的测试入口包括 pytest、Python unittest/pytest、npm test、pnpm test、yarn test、cargo test 和 go test；每条命令的超时上限为 600 秒。
目标项目所需的测试依赖需要安装在服务可用的环境中。

Git worktree 提供文件修改隔离，**不提供操作系统权限隔离**。
测试代码仍以服务进程的用户权限运行，应使用可信仓库。
OpenAI 客户端库的重试行为保持默认，执行器没有额外的自动恢复循环或重试框架。

## 常见问题

- **Not a Git repository：** 在预期的源码目录初始化 Git，选择需要跟踪的文件，并创建首次提交；先排除凭证和运行数据。
- **Repository must be clean：** 在服务所在环境执行 `git status`，处理尚未提交的改动后再委派任务。
- **Directory does not exist：** 目标路径必须能被服务进程访问。
- **Model or key not configured：** 对照 `.env.example` 补全本机 `.env`。
- **供应商错误或无效 JSON：** 检查 API 地址、接口模式、模型支持情况和供应商响应；不同供应商的协议兼容程度可能不同。

## 测试

```bash
.venv/bin/python -m unittest discover -s tests -v
```

自动测试使用临时本地 Git 仓库和模拟 API 响应，不需要密钥，也不会产生付费 API 调用。
真实供应商调用与这套回归测试分开验证。
项目采用 MIT 许可证，见 [LICENSE](LICENSE)。
