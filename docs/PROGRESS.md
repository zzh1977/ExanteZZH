# AI 编程助手安全设置：项目进展

> 主题：在 macOS 上安全使用 ChatGPT/Codex 与 Claude/Claude Code。
> 目标：AI 只读写指定文件夹、不乱删文件、不乱上网、不自己下载安装软件。
> 阅读版（Artifact）：见文末「相关链接」。本文件是唯一正本，Artifact 由它生成。

## 当前状态

- 已完成：两家产品的安全设置对比、各端（网页 / iPad / 桌面）运行位置与文件范围梳理、设置文件优先级、云端结果如何取回、Cowork 本地文件夹规则。
- 未做：在自己的 Mac 上实际落地配置并逐项测试（见「待办」）。
- 资料核对日期：2026-10-25。两家产品更新很快，落地前请再核对一次。

## 已定结论

### 1. 总体判断

- 两家在 Mac 上都用系统自带的 Seatbelt 沙箱，在系统层面限制文件和网络。
- **Codex**：默认更紧（只能写当前目录、命令断网），开箱接近要求；但默认能读全盘，细粒度控制较弱。
- **Claude Code**：默认沙箱关闭，必须自己配；配好后控制更细（限制读取、按域名放行、按命令拒绝、管理员锁定）。
- **共同短板**：在允许的文件夹里能改就能删，沙箱无法单独禁止删除。必须靠逐条审批 + git / Time Machine 备份兜底。

| 要求 | Codex | Claude Code |
|---|---|---|
| 只改指定文件夹 | ✅ 默认 | ✅ 需开沙箱 |
| 只读指定文件夹 | ⚠️ 默认读全盘 | ✅ 可挡住 |
| 不乱删 | ⚠️ 审批 + 规则 | ⚠️ 审批 + deny 规则 |
| 不乱上网 | ✅ 命令默认断网，搜索需手动关 | ⚠️ 需手动配置 |
| 不自装软件 | ✅ 断网即可 | ✅ 断网 + deny 规则 |
| 防 AI 改设置 | `/etc/codex/requirements.toml` | `/Library/Application Support/ClaudeCode/managed-settings.json` |

### 2. Codex 推荐配置

`~/.codex/config.toml`：

```toml
sandbox_mode    = "workspace-write"  # 只能写启动目录
approval_policy = "untrusted"        # 除安全只读命令外都要批准
web_search      = "disabled"         # 关掉联网搜索

[sandbox_workspace_write]
network_access = false
writable_roots = []
```

`~/.codex/rules/safety.rules`（预览功能）：

```python
prefix_rule(pattern=["rm"], decision="forbidden", justification="禁止删除，请让用户手动删")
prefix_rule(pattern=["rmdir"], decision="forbidden")
prefix_rule(pattern=["curl"], decision="forbidden")
prefix_rule(pattern=["wget"], decision="forbidden")
prefix_rule(pattern=["brew"], decision="forbidden")
prefix_rule(pattern=[["pip","pip3","npm","pnpm","yarn"], "install"], decision="forbidden")
```

注意：规则只管终端命令，Codex 自带的改文件工具仍可能删文件。想限制读取需用测试版的 `[permissions]` 权限配置文件。有用户反馈桌面 app 不一定读项目级权限配置。

### 3. Claude Code 推荐配置

`~/.claude/settings.json`（最好放进 managed-settings.json）：

```json
{
  "permissions": {
    "defaultMode": "default",
    "disableBypassPermissionsMode": "disable",
    "disableAutoMode": "disable",
    "blockReadsOutsideWorkingDirectories": true,
    "deny": [
      "WebFetch", "WebSearch",
      "Bash(rm *)", "Bash(rmdir *)", "Bash(unlink *)",
      "Bash(curl *)", "Bash(wget *)", "Bash(brew *)",
      "Bash(pip install *)", "Bash(pip3 install *)",
      "Bash(npm install *)", "Bash(npm i *)", "Bash(npx *)"
    ]
  },
  "sandbox": {
    "enabled": true,
    "failIfUnavailable": true,
    "allowUnsandboxedCommands": false,
    "autoAllowBashIfSandboxed": false,
    "network": { "allowedDomains": [], "strictAllowlist": true }
  }
}
```

要点：
- `sandbox.enabled` 不开，写文件和上网都不受系统层面限制。
- `autoAllowBashIfSandboxed: false` 让每条改东西的命令都要你点同意。
- `WebFetch` 必须禁止：它对部分文档网站默认免询问。
- `strictAllowlist` 需要 2.1.219+。
- `deny` 规则能被 `/bin/rm`、`bash -c` 绕过，真正可靠的是"沙箱 + 逐条审批"。
- 不要随便装 MCP 服务器 / 插件，它们不在沙箱里。

### 4. 各端运行位置与文件范围

| 入口 | 代码在哪跑 | 能碰的文件 |
|---|---|---|
| Codex 网页版 | OpenAI 云端容器 | 只有 clone 的 GitHub 仓库 |
| Codex iPad | 云任务 / 或遥控 Mac 上的桌面 app | 云端仓库 / Mac 桌面 app 被授权的范围 |
| Codex 桌面 app | 本地 Seatbelt 沙箱 | 打开的项目文件夹 |
| claude.ai 聊天 | Anthropic 沙箱容器 | 只有上传的文件 |
| claude.ai/code | Anthropic 云端 VM | 只有 clone 的 GitHub 仓库 |
| Claude iPad | 云端会话 / Remote Control / Cowork 云端 | 云端仓库 / Mac 上该会话工作目录 / 见第 6 条 |
| Claude 桌面 app | 本地或云端 | 本地：所选文件夹 |

- iPad 本身不运行代码，也读不到 iPad 里的文件（手动上传除外）。
- claude.ai 聊天：Settings → Capabilities → 可关 "Allow network egress"。
- claude.ai/code 网络四档：None / Trusted（默认）/ Full / Custom。即使 None 也能连 Anthropic API。
- Mac 上的 `~/.claude/settings.json` 和 managed-settings 对云端会话无效；云端要用仓库里的 `.claude/settings.json` 或环境变量。
- Remote Control：可用 `disableRemoteControl` 禁用，或开 Trusted Devices。

### 5. Claude Code 设置文件优先级

managed > 命令行 `--settings` > `.claude/settings.local.json` > `.claude/settings.json` > `~/.claude/settings.json`

- allow / deny 等列表是**合并**，不是覆盖。
- 只有 managed 能防 AI 改设置：其他三个文件 Claude Code 自己会写（点"不再询问"就写进 local）；managed 需 sudo。
- 少数安全键在低层级设"更严格"的值也生效，如 `blockReadsOutsideWorkingDirectories: true`。

### 6. Cowork 本地文件夹规则（2026-10-06 起，Pro/Max）

云端 Cowork 任务要读写 Mac 文件夹，须**同时满足**：
1. 任务在 Mac 桌面 app 里发起（或桌面建的定时任务）；
2. 任务/项目连接了该文件夹；
3. 运行期间桌面 app 一直开着在线。

- 读写方式：通过桌面 app 取单个文件副本到云端处理，文件内容会经过 Anthropic 服务器。
- 10/6 前开始的本地任务继续本地跑完。
- 带本地文件夹的项目只能在桌面 app 里用；在其中新建的任务在云端执行，但仍可读写连接的文件夹。
- iPad / 网页发起的任务永远碰不到本地文件夹。
- 想要文件不出电脑：用 Claude Code 本地会话。

### 7. 云端结果怎么取回

- **Claude Code 云端**：① commit + push / 开 PR（最稳）② 发布 Artifact ③ 发文件到对话 ④ 会话里的 Files 面板只能"看"不能下载。VM 回收后没 push 的就没了。
- **claude.ai 聊天 / Cowork**：对话里 Download；iPad 上用系统预览再"存储到文件"。
- **Codex 云任务**：网页看 diff、Create PR、预览下载生成文件；本地 `codex apply <任务ID>`。iPad 目前不能下载生成文件。

### 8. 云端会话与本地的关系

- iPad / 网页项目不在桌面上连接本地文件夹，就碰不到本地文件。
- 在 Mac 上打开、查看、指挥云端会话：不会本地化，不碰本地文件。
- 只有这些**主动动作**会落地到本地：`claude --teleport`（拉分支 + 复制会话，之后是独立的本地会话）、Cowork 连接文件夹、`codex apply`。
- 保守做法：云端任务里弹出"连接文件夹"时不点。

### 9. 进展记录方式

- 正本放仓库 `docs/PROGRESS.md`（本文件）；`CLAUDE.md` 要求每次任务后更新。
- Artifact 只是从本文件生成的阅读版，以本文件为准。
- 在本地电脑打开 Artifact 无安全影响：它是浏览器隔离框架里的静态网页，碰不到本地文件、不下载任何东西；唯一外部请求是 Google 字体（Google 可见 IP）。默认私有，分享需在 Share 菜单授权。

## 待办

- [ ] 在 Mac 上按第 2、3 节写入配置；Claude Code 部分放进 managed-settings.json（sudo）
- [ ] 逐项测试：让 AI 删文件、访问网站、装包、读项目外文件，确认都被拦住
- [ ] 工作文件夹 `git init` 并开启 Time Machine
- [ ] 核对 Codex 规则文件夹路径（`~/.codex/rules/`）与 `untrusted` 在当前版本的行为
- [ ] 决定是否关闭 Remote Control（`disableRemoteControl`）或开启 Trusted Devices

## 更新日志

- **2026-10-25**：补充结论：在本地电脑打开 Artifact 无安全影响。
- **2026-10-25**：建立本文件，汇总 Codex 与 Claude Code 安全设置对比、各端文件范围、设置文件优先级、Cowork 规则、云端结果取回方式；生成 Artifact 阅读版。

## 相关链接

- **Artifact 阅读版**：https://claude.ai/artifact/CDrgB7Nbf1dMBapS13WP61 （源文件 `docs/progress.html`，私有，需自己在页面 Share 菜单里分享）
- Claude Code：[沙箱](https://code.claude.com/docs/en/sandboxing) · [权限](https://code.claude.com/docs/en/permissions) · [设置优先级](https://code.claude.com/docs/en/settings) · [云端会话](https://code.claude.com/docs/en/claude-code-on-the-web) · [云端环境](https://code.claude.com/docs/en/cloud-environments) · [Remote Control](https://code.claude.com/docs/en/remote-control) · [管理员设置](https://code.claude.com/docs/en/managed-settings)
- Claude 帮助中心：[创建文件与网络设置](https://support.claude.com/en/articles/12111783-create-and-edit-files-with-claude) · [Cowork 各端](https://support.claude.com/en/articles/15520349-use-claude-cowork-on-web-desktop-and-mobile) · [Cowork 云端](https://support.claude.com/en/articles/15811196-what-to-expect-with-claude-cowork-in-the-cloud)
- Codex：[审批与安全](https://developers.openai.com/codex/agent-approvals-security) · [配置参考](https://developers.openai.com/codex/config-reference) · [远程连接](https://learn.chatgpt.com/docs/remote-connections) · [execpolicy 说明](https://github.com/openai/codex/blob/rust-v0.107.0/codex-rs/execpolicy/README.md)
