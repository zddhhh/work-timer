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

产物（给 GitCode 上传）：

| 安装包 | 适用系统 | 打包环境 |
|---|---|---|
| `release\WorkTimer-Setup.exe` | Windows 8.1 / 10 / 11（64 位） | `.venv`，Python 3.12 |
| `release\WorkTimer-Win7-Setup.exe` | Windows 7 SP1（64 位） | `.venv38`，Python 3.8 |

默认装到 `%LOCALAPPDATA%\Programs\WorkTimer`，安装向导可以改文件夹。不要管理员权限，控制面板里能卸载。检查更新会装回上次选的位置。`dist\` 不覆盖，留给本机旧版测 OTA。

打包前提（一次性）：

- Inno Setup 6：`winget install JRSoftware.InnoSetup`
- 自编译 PyInstaller bootloader（官方预编译的 bootloader 被大量恶意样本复用，杀软误报多）：装 MinGW（`winget install BrechtSanders.WinLibs.POSIX.MSVCRT`）后跑 `python scripts\build_bootloader.py .venv` 和 `.venv38` 各一次。升级 PyInstaller 后要重跑，否则 `build_release.py` 会拒绝打包。
- Win7 环境：Python 3.8.10 建 `.venv38`，装 `Pillow<11`、`pyinstaller<7`、`pyinstaller-hooks-contrib`、`tkinterdnd2==0.6.2`。本机开了系统代理时，3.8 的 pip 要先设 `$env:HTTPS_PROXY="http://127.0.0.1:端口"`。

## 操作

| 操作 | 效果 |
|---|---|
| 左键点一下 | 未计时：录入时间（上次用哪种还开哪种）；计时中：切换时分秒 / 分钟 / 秒；霹雳狂潮皮下可连击触发多道劈雷沿边电涌；喵喵仪仗队皮下小猫踢一段正步 |
| 右键 → 设置下班时间… | 填 8:30–9:30 到岗按 9.5 小时算，或直接填今天下班几点 |
| 右键 → 日程列表… | 自建到点/时长日程、备忘；最多优先显示 3 项（节日项不占名额），可自动轮播 |
| 右键 → 工时账本… | 按周看来了/走了/待了多久/比该走；本周与本月合计。可手改、导出本月 CSV。可选记下今天敲了多少下、点了多少次、鼠标大约滑了多远（只在本机，按每英寸 1600 计数估算）。次数图默认折线，可换成柱状；今天按小时、这周按天。距离跟次数画在同一张图里，单独按米缩放。鼠标停在某一小时上，底部数字一直显示，移开才收。卡片上开着次数时，手停满 3 分钟会写「手停了几分钟」，一碰就收。来是当天第一次凑满「30 秒里 3 个不同的秒」的起点，走是最后一次。碰一下不算。中间空档留在这段里，看次数图。每天都记，含周末 |
| 右键 → 小游戏… | 扫雷（初级 9×9 / 中级 16×16 / 高级 16×30，左键翻开，右键插旗）；高尔夫（只点，牌面差 1 接上）；台球（按住白球往后拉，松开就打）。没玩完的一局关掉还能接着 |
| 右键 → 设置 → 光标尾巴 | 默认关。打开后，设了下班时间时鼠标后面跟一条尾巴，系统箭头不变。越长离下班越远，快到点收成一个小光点。点击直接穿过去。右键菜单开着时尾巴照样跟着走。隐藏键不收尾巴。没开始计时、锁屏或关屏时不画 |
| 左键拖 | 挪位置（会记住） |
| 右键 → 外观 | 三个子菜单：经典（淡影 默认，浅色墙纸也会缓变适配 / 玻璃 / 霜白 / 霓虹 / 终端 / 极光 / 墨金 / 暖光）、特效（翻牌时钟 / 霓虹流光 / 墨水涟漪 / 霹雳狂潮 / 喵喵仪仗队）、节日（中秋 / 国庆，在季时标「· 限定」）；当前皮所在组名带勾；可「刷新在线外观」 |
| 右键 → 设置 → 显示方式 | 时分秒 / 分钟 / 秒 |
| 右键 → 设置 → 按键隐藏 | 开关，默认关；可设自定义按键（默认 `` ` ``），单击把卡片、右键菜单和弹窗一起收起，再按显示。光标尾巴不跟着收 |
| 右键 → 设置 → 设置隐藏按键… | 改隐藏用的键位 |
| 右键 → 设置 → 喝水久坐提醒 | 开关，默认关；到点卡片写「该喝水了」，不抢下班倒计时 |
| 右键 → 设置 → 设置喝水久坐提醒… | 30 / 45 / 60 / 90 分钟，默认 45；离开座位、隐藏窗口、过了下班点不催。可另开加强：到点同时写「起来站一会」，喝一杯并离开座位 |
| 右键 → 设置 → 开机自启动 | 开关；用「启动」文件夹快捷方式，不写注册表 |
| 右键 → 设置 → 卸载本程序… | 删除快捷方式与配置，再调系统卸载程序删程序文件，不可恢复；也可在控制面板卸载 |
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

右键「检查更新」读 GitCode Release，按当前系统下载对应安装包（Win7 版下 `WorkTimer-Win7-Setup.exe`，其余下 `WorkTimer-Setup.exe`），校验 PE 头与 Release 说明里的 `sha256(<附件名>):`，然后退出并静默运行安装包覆盖安装，装完由安装包拉起新版。

1.3.34 及更早的单文件版只认 `WorkTimer.exe`，找不到时取第一个 `.exe` 附件、校验第一行 `sha256:`，并把它当新 exe 带 `--ota-replace` 参数拉起。所以：主安装包必须先上传、文件名排序在前，说明里要保留一行主包的 `sha256:`；安装包认出这种拉起方式后会转成静默安装，新版启动后删掉老 exe 和 `%LOCALAPPDATA%\WorkTimer` 里的旧副本。

发版：改 `version.py` 的 `APP_VERSION` → `scripts\gitcode_release.py`（打包两个安装包到 `release/`、创建 Release、把两个包的 sha256 写进说明、按顺序上传）。本地已打包测过的用 `--no-build` 直接发。

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
