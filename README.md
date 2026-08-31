# 弹性下班计时器

透明桌面小窗：点一下录入今天 **8:30–9:30** 到岗时间，按 9.5 小时弹性算出 **18:00–19:00** 下班，显示距离下班还有多少分多少秒。

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
| 左键点一下 | 未计时：录入上班时间；计时中：切换时分秒 / 分钟 / 秒 |
| 左键拖 | 挪位置（会记住） |
| 右键 → 外观 | 淡影（默认）/ 深夜 / 霜白 / 霓虹 / 终端 |
| 右键 → 显示方式 | 时分秒 / 分钟 / 秒 |
| ESC | 切换成广告弹窗伪装；再按 ESC 或点广告关闭恢复 |
| 右键 → 伪装成广告 (Esc) | 同 Esc |
| 右键 → 检查更新 | GitCode OTA |
| 右键 → 退出 | 退出 |

每天第一次打开会重置，不会沿用昨天的到岗时间。同一天内改过的时间会记住，跨天才清空。

时间格式：`8.45`、`8:45`、`0845` 都可以。超出 8:30–9:30 会夹到两端。

## 计算规则

- 8:30 到岗 → 18:00 下班
- 9:30 到岗 → 19:00 下班
- 中间按分钟线性映射（固定工时 9 小时 30 分）

## 自动更新

右键「检查更新」读 GitCode Release，下载 `WorkTimer.exe` 并重启替换。

发版：改 `version.py` 的 `APP_VERSION` → 打包 → 上传 Release 附件，文件名保持 `WorkTimer.exe`。

Windows 误报见 [`docs/Windows安全说明.md`](docs/Windows安全说明.md)。
