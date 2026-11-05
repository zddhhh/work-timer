"""应用版本号：每次发 GitCode Release 时同步改这里并重新打包。"""

import sys

APP_NAME = "WorkTimer"
APP_VERSION = "1.4.34"
# Python 3.9+ 不支持 Win7，Win7 包单独用 3.8 打；运行时按解释器版本认领自己那份安装包。
# Win7 包名要排在主包后面：1.3.34 及更早的客户端找不到 WorkTimer.exe 时会取第一个 .exe 附件。
WIN7_BUILD = sys.version_info < (3, 9)
MAIN_SETUP = "WorkTimer-Setup.exe"
WIN7_SETUP = "WorkTimer-Win7-Setup.exe"
ASSET_NAME = WIN7_SETUP if WIN7_BUILD else MAIN_SETUP
