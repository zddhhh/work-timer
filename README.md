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
| 左键点一下 | 未计时：录入时间（上次用哪种还开哪种）；计时中：切换时分秒 / 分钟 / 秒；霹雳狂潮皮下可连击触发多道劈雷沿边电涌 |
| 右键 → 设置下班时间… | 填 8:30–9:30 到岗按 9.5 小时算，或直接填今天下班几点 |
| 右键 → 日程列表… | 自建到点/时长日程、备忘；最多优先显示 3 项（节日项不占名额），可自动轮播 |
| 左键拖 | 挪位置（会记住） |
| 右键 → 外观 | 三个子菜单：经典（淡影 默认，浅色墙纸也会缓变适配 / 玻璃 / 霜白 / 霓虹 / 终端 / 极光 / 墨金 / 暖光）、特效（翻牌时钟 / 霓虹流光 / 墨水涟漪 / 霹雳狂潮）、节日（中秋 / 国庆，在季时标「· 限定」）；当前皮所在组名带勾；可「刷新在线外观」 |
| 右键 → 设置 → 显示方式 | 时分秒 / 分钟 / 秒 |
| 右键 → 设置 → 按键隐藏 | 开关，默认关；可设自定义按键（默认 `` ` ``），单击隐藏/再按显示 |
| 右键 → 设置 → 设置隐藏按键… | 改隐藏用的键位 |
| 右键 → 设置 → 开机自启动 | 开关；用「启动」文件夹快捷方式，不写注册表 |
| 右键 → 设置 → 卸载本程序… | 删除快捷方式、配置与 exe，不可恢复 |
| 右键 → 关于… | 版本号、打开官方仓库、提交用户反馈（需留联系方式） |
| 右键 → 检查更新 | GitCode OTA |
| 右键 → 退出 | 退出 |

每天第一次打开：弹性到岗会重置。选「我知道下班几点」时可勾选记住，第二天沿用；弹性打卡不受影响。

到岗格式：`8.45`、`8:45`、`0845`。超出 8:30–9:30 会夹到两端。下班时间任意，例如 `18:00`、`18.30`。

## 计算规则

- 8:30 到岗 → 18:00 下班
- 9:30 到岗 → 19:00 下班
- 中间按分钟线性映射（固定工时 9 小时 30 分）

## 自动更新

右键「检查更新」读 GitCode Release，下载 `WorkTimer.exe`，校验 PE 头与 Release 说明里的 `sha256:`，再由新版自己替换重启（不走 PowerShell）。

发版：改 `version.py` 的 `APP_VERSION` → `scripts\gitcode_release.py`（打包到 `release/`、创建 Release、把 sha256 写进说明、上传附件）。

测试：`.\.venv\Scripts\python.exe -m unittest discover -s tests -v`。待办见 [`docs/优化清单.md`](docs/优化清单.md)。

Windows 误报见 [`docs/Windows安全说明.md`](docs/Windows安全说明.md)。

## 用户反馈

右键「关于」里提交，会直接发到仓库 Issue（标题带 `[反馈]`，正文带 `- 联系：` 一行），用户不用登录 GitCode。联系方式必填并会记住。本机拉下来分析（`feedback/index.json` 里有 `contact` 字段）：

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

`1.0.7` 起皮肤读仓库根目录的 [`themes.json`](themes.json)。改颜色/加一套（最多 16 套）推到 `main` 后，用户启动或右键「刷新在线外观」就会换上。可用 `kind`：`ghost` / `glass` / `frost` / `neon` / `terminal` / `aurora` / `inkgold` / `warmglow` / `midautumn` / `nationalday` / `neonflow` / `inkpulse`。`adaptive` + `on_light` 可调自适应两套色；全新画法才需要发版。
