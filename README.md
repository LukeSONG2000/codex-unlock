# codex-unlock

> 非官方 macOS Codex 本地补丁 Skill：从官方 `/Applications/Codex.app` 复制生成独立的 `/Applications/Codex Fast.app`，尝试在 API Key / custom provider 模式下解锁 Fast/Speed mode 与 Plugins 的 UI 门禁。

## 快速开始

### 方式一：命令安装

```bash
npx skills add LukeSONG2000/codex-unlock -g -a codex -y
```

安装后重启 Codex，然后对 Codex 说：

```text
[$codex-unlock] Rebuild /Applications/Codex Fast.app from the current official /Applications/Codex.app.
```

也可以直接运行脚本：

```bash
python3 ~/.codex/skills/codex-unlock/scripts/rebuild_codex_fast.py --yes --quit-target
open "/Applications/Codex Fast.app"
```

### 方式二：复制提示词安装

把下面这段话复制给 Codex：

```text
请安装这个 Codex skill：GitHub 仓库 LukeSONG2000/codex-unlock，skill 路径是 skills/codex-unlock。请把它安装到我的全局 Codex skills 目录，安装后告诉我需要重启 Codex。安装完成后，使用该 skill 从当前官方 /Applications/Codex.app 重建 /Applications/Codex Fast.app。
```

安装后重启 Codex，再执行：

```text
[$codex-unlock] Rebuild /Applications/Codex Fast.app from the current official /Applications/Codex.app.
```

## 使用范围

- 仅支持 macOS。
- 默认官方应用路径：`/Applications/Codex.app`。
- 默认生成的实验应用路径：`/Applications/Codex Fast.app`。
- 不支持 Windows / Linux。
- 不修改官方 `/Applications/Codex.app`，只复制并 patch 独立副本。

## 使用场景 / 用途

这个 Skill 适合这些场景：

- 你使用 Codex App 的 API Key / custom provider 模式，但希望尝试显示 Fast/Speed mode 入口。
- 你希望在 API Key 模式下尝试使用 Plugins 页面、插件安装流程和相关入口。
- 官方 Codex 更新后，想基于新的官方 `/Applications/Codex.app` 重新生成并覆盖旧的 `/Applications/Codex Fast.app`。
- 你想把实验版和官方版分开，避免本地 patch 影响现有正式工作。

生成后的结构：

```text
/Applications/Codex.app       # 官方版，保持原样
/Applications/Codex Fast.app  # 实验版，由本 Skill 重建并 patch
```

## 它做了什么

执行 `rebuild_codex_fast.py` 时会：

1. 检查 `/Applications/Codex.app`、`ditto`、`npx`、`codesign` 是否可用。
2. 如果 `/Applications/Codex Fast.app` 已存在，默认移动到时间戳备份。
3. 用当前官方版复制出新的 `/Applications/Codex Fast.app`。
4. 修改副本的显示名和 Bundle ID：`Codex Fast` / `com.openai.codex.fast`。
5. 解包副本的 `app.asar`。
6. Patch API Key 模式下的 Fast/Speed mode 与 Plugins 相关 UI gate。
7. 重新打包 `app.asar`，更新 `ElectronAsarIntegrity` hash。
8. 重新签名并验证 `/Applications/Codex Fast.app`。

## 常用命令

官方 Codex 更新后，覆盖旧 Fast 版并保留备份：

```bash
python3 ~/.codex/skills/codex-unlock/scripts/rebuild_codex_fast.py --yes --quit-target
```

覆盖旧 Fast 版但不保留备份：

```bash
python3 ~/.codex/skills/codex-unlock/scripts/rebuild_codex_fast.py --yes --quit-target --no-backup
```

指定路径：

```bash
python3 ~/.codex/skills/codex-unlock/scripts/rebuild_codex_fast.py \
  --source /Applications/Codex.app \
  --target "/Applications/Codex Fast.app" \
  --yes \
  --quit-target
```

打开实验版：

```bash
open "/Applications/Codex Fast.app"
```


## 避免每次重建后重新授权隐私权限

macOS 的隐私权限（辅助功能、屏幕录制、自动化等）会跟 App 的代码签名身份相关。早期版本使用 ad-hoc 签名，重建后可能被 macOS 当成“新 App”，从而要求重新授权。

现在脚本默认会创建并复用一个本地固定签名证书：

```text
Codex Unlock Local Code Signing
```

第一次从 ad-hoc 签名切换到这个证书时，可能仍需要最后重新授权一次；之后只要继续用同一个证书和同一个 `/Applications/Codex Fast.app` Bundle ID，后续重建通常不需要每次重新授权。

如果签名证书出问题，可以回退到 ad-hoc 签名：

```bash
python3 ~/.codex/skills/codex-unlock/scripts/rebuild_codex_fast.py --yes --quit-target --ad-hoc-sign
```

## 验证

打开 `/Applications/Codex Fast.app` 后检查：

- 能正常进入 Codex UI，而不是 Electron 默认页。
- API Key / custom provider 模式仍能使用。
- Fast/Speed mode 入口可见或可选。
- Plugins 页面 / 侧边栏可见。
- 插件安装时不再把所有 required apps/connectors 标为 unavailable。

## 风险说明

这是非官方本地 patch，不代表 OpenAI 官方支持：

- 它只修改本地 Codex App 副本的前端 / bundle gate。
- 它不保证你拥有官方 Fast credits、ChatGPT 订阅权益或任何服务端权限。
- Codex App 更新后，bundle 结构可能变化，patch pattern 可能失效。
- 如果脚本提示 `Required patch patterns were not found`，说明需要重新适配新版 Codex bundle。
- 请保留官方 `/Applications/Codex.app` 作为日常稳定版本。

## 卸载

删除实验版：

```bash
rm -rf "/Applications/Codex Fast.app"
```

删除 Skill：

```bash
npx skills remove codex-unlock -g -a codex -y
```
