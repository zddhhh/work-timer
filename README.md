# 弹性下班计时器

透明桌面小窗：点一下录入今天 **8:30–9:30** 到岗时间，按 9.5 小时弹性算出下班时间，窗口只显示距离下班还有多久。

创建日期：2026-08-28

## 自己运行

```powershell
cd d:\workspace\64-work-timer
.\.venv\Scripts\Activate
python main.py
```

必须用 `.venv` 里的 python。

## 发给同事

```powershell
.\.venv\Scripts\python.exe scripts\build_release.py
```

产物：`release\WorkTimer.exe`（给 GitCode 上传）。`dist\` 不覆盖，留给本机旧版测 OTA。

## 操作

| 操作 | 效果 |
|---|---|
| 左键点一下 | 未计时：录入时间（上次用哪种还开哪种）；计时中：切换时分秒 / 分钟 / 秒 |
| 右键 → 设置上班时间 | 填 8:30–9:30 到岗，按 9.5 小时算下班 |
| 右键 → 设置下班时间 | 直接填今天下班几点，按这个点倒计时 |
| 左键拖 | 挪位置（会记住） |
| 右键 → 外观 | 淡影（默认，浅色墙纸也会缓变适配）/ 自适应 / 玻璃 / 霜白 / 霓虹 / 终端 / 极光 / 墨金；可「刷新在线外观」 |
| 右键 → 显示方式 | 时分秒 / 分钟 / 秒 |
| 右键 → Esc 隐藏窗口 | 开关，默认关；打开后 Esc 隐藏计时器，再按 Esc 显示 |
| 右键 → 关于 | 版本号、打开官方仓库、提交用户反馈 |
| 右键 → 检查更新 | GitCode OTA |
| 右键 → 退出 | 退出 |

每天第一次打开：弹性到岗会重置。选「我知道下班几点」时可勾选记住，第二天沿用；弹性打卡不受影响。

到岗格式：`8.45`、`8:45`、`0845`。超出 8:30–9:30 会夹到两端。下班时间任意，例如 `18:00`、`18.30`。

## 计算规则

- 8:30 到岗 → 18:00 下班
- 9:30 到岗 → 19:00 下班
- 中间按分钟线性映射（固定工时 9 小时 30 分）

## 自动更新

右键「检查更新」读 GitCode Release，下载 `WorkTimer.exe` 并由新版自己替换重启（不走 PowerShell）。

发版：改 `version.py` 的 `APP_VERSION` → 打包 → 上传 Release 附件，文件名保持 `WorkTimer.exe`。

Windows 误报见 [`docs/Windows安全说明.md`](docs/Windows安全说明.md)。

## 用户反馈

右键「关于」里提交，会直接发到仓库 Issue（标题带 `[反馈]`），用户不用登录 GitCode。本机拉下来分析：

```powershell
$env:GITCODE_TOKEN = Get-Content .gitcode_token -Raw
.\.venv\Scripts\python.exe scripts\pull_feedback.py
```

文件写在 `feedback/`（不进 git）。

给用户免登录提交：头像 → 个人设置 → 访问令牌，新建一个 **只勾选 Issue**（不要勾选代码推送/项目设置）的 PAT，复制成 `update_defaults.secret.json`：

```json
{ "feedback_token": "你的PAT" }
```

然后打包。这个文件不进 git。令牌仍可能从 exe 里被拆出来刷 Issue，所以权限一定要收窄，并设过期时间。

## 在线换皮（不用发新版本）

`1.0.7` 起皮肤读仓库根目录的 [`themes.json`](themes.json)。改颜色/加一套（最多 16 套）推到 `main` 后，用户启动或右键「刷新在线外观」就会换上。可用 `kind`：`ghost` / `glass` / `frost` / `neon` / `terminal` / `aurora` / `inkgold`。`adaptive` + `on_light` 可调自适应两套色；全新画法才需要发版。
