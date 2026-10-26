/* WorkTimer.exe
 * 不链接 VC 运行库。快捷方式始终指向这个文件。
 * 真正的程序是同目录的 WorkTimer.bin.exe，运行库在 _internal。
 * 安装包只把新版本放进 _pending。这里确认它进了主界面，才丢掉上一版；
 * 没确认就把 _prev 换回来。已经打不开的安装不会被换掉。
 *
 * 运行库是否齐全，和 installer/WorkTimer.iss、scripts/build_release.py 三处要一起改。
 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdarg.h>
#include <stdio.h>

static wchar_t g_dir[1024];
static HANDLE g_log = INVALID_HANDLE_VALUE;

static void log_line(const wchar_t *s) {
    char buf[1200];
    DWORD n, w;
    if (g_log == INVALID_HANDLE_VALUE)
        return;
    n = (DWORD)WideCharToMultiByte(CP_UTF8, 0, s, -1, buf, (int)sizeof buf - 1, NULL, NULL);
    if (n < 2)
        return;
    WriteFile(g_log, buf, n - 1, &w, NULL);
    WriteFile(g_log, "\r\n", 2, &w, NULL);
    FlushFileBuffers(g_log);
}

static void note(const wchar_t *fmt, ...) {
    wchar_t buf[900];
    va_list ap;
    va_start(ap, fmt);
    _vsnwprintf(buf, 899, fmt, ap);
    buf[899] = 0;
    va_end(ap);
    log_line(buf);
}

static void log_open(void) {
    wchar_t path[MAX_PATH + 32];
    DWORD n = GetTempPathW(MAX_PATH, path);
    if (n == 0 || n >= MAX_PATH)
        return;
    if (wcslen(path) + 22 >= sizeof path / sizeof path[0])
        return;
    wcscat(path, L"WorkTimer-launch.log");
    g_log = CreateFileW(path, FILE_APPEND_DATA, FILE_SHARE_READ, NULL, OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    log_line(L"----");
}

static int join2(wchar_t *out, size_t cap, const wchar_t *a, const wchar_t *b) {
    int n = _snwprintf(out, cap, L"%s\\%s", a, b);
    return n > 0 && (size_t)n < cap;
}

static int under_app(const wchar_t *path) {
    size_t n = wcslen(g_dir);
    if (n == 0 || _wcsnicmp(path, g_dir, n) != 0)
        return 0;
    return path[n] == L'\\' && path[n + 1] != 0;
}

static int file_exists(const wchar_t *path) {
    DWORD a = GetFileAttributesW(path);
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY) == 0;
}

static int dir_exists(const wchar_t *path) {
    DWORD a = GetFileAttributesW(path);
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY) != 0;
}

static int move_item(const wchar_t *src, const wchar_t *dst) {
    int i;
    for (i = 0; i < 8; i++) {
        if (MoveFileW(src, dst))
            return 1;
        if (GetLastError() == ERROR_FILE_NOT_FOUND || GetLastError() == ERROR_PATH_NOT_FOUND)
            return 0;
        Sleep(250);
    }
    note(L"move failed %lu: %s -> %s", GetLastError(), src, dst);
    return 0;
}

static int delete_tree(const wchar_t *dir);

static int delete_children(const wchar_t *dir) {
    wchar_t pattern[1024];
    WIN32_FIND_DATAW fd;
    HANDLE h;
    if (_snwprintf(pattern, 1024, L"%s\\*", dir) <= 0)
        return 0;
    h = FindFirstFileW(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE)
        return 1;
    do {
        wchar_t child[1024];
        if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0)
            continue;
        if (!join2(child, 1024, dir, fd.cFileName)) {
            FindClose(h);
            return 0;
        }
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            if (!delete_tree(child)) {
                FindClose(h);
                return 0;
            }
        } else {
            SetFileAttributesW(child, FILE_ATTRIBUTE_NORMAL);
            if (!DeleteFileW(child) && GetLastError() != ERROR_FILE_NOT_FOUND) {
                FindClose(h);
                return 0;
            }
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return 1;
}

static int delete_tree(const wchar_t *dir) {
    int i;
    if (!under_app(dir)) {
        note(L"refuse delete outside app: %s", dir);
        return 0;
    }
    for (i = 0; i < 5; i++) {
        DWORD a = GetFileAttributesW(dir);
        if (a == INVALID_FILE_ATTRIBUTES)
            return 1;
        if ((a & FILE_ATTRIBUTE_DIRECTORY) == 0) {
            SetFileAttributesW(dir, FILE_ATTRIBUTE_NORMAL);
            if (DeleteFileW(dir))
                return 1;
        } else if (delete_children(dir)) {
            SetFileAttributesW(dir, FILE_ATTRIBUTE_NORMAL);
            if (RemoveDirectoryW(dir))
                return 1;
        }
        Sleep(200);
    }
    note(L"delete failed %lu: %s", GetLastError(), dir);
    return 0;
}

static int runtime_ok(const wchar_t *dir) {
    wchar_t p[1024];
    int has312;
    int has38;
    if (!join2(p, 1024, dir, L"python312.dll"))
        return 0;
    has312 = file_exists(p);
    if (!join2(p, 1024, dir, L"python38.dll"))
        return 0;
    has38 = file_exists(p);
    if (!has312 && !has38)
        return 0;
    if (!join2(p, 1024, dir, L"vcruntime140.dll") || !file_exists(p))
        return 0;
    /* 3.12 还依赖 vcruntime140_1。Win7 的 3.8 包里没有这份，不能当成缺文件。 */
    if (has312 && (!join2(p, 1024, dir, L"vcruntime140_1.dll") || !file_exists(p)))
        return 0;
    return 1;
}

static int boot_dir(wchar_t *out, size_t cap) {
    wchar_t env[1024];
    DWORD n = GetEnvironmentVariableW(L"WT_BOOT_DIR", env, 1024);
    if (n > 0 && n < 1024) {
        if (wcslen(env) >= cap)
            return 0;
        wcscpy(out, env);
        CreateDirectoryW(out, NULL);
        return 1;
    }
    n = GetEnvironmentVariableW(L"USERPROFILE", env, 1024);
    if (n == 0 || n >= 1024)
        return 0;
    if (_snwprintf(out, cap, L"%s\\AppData\\Roaming\\WorkTimer", env) <= 0)
        return 0;
    CreateDirectoryW(out, NULL);
    return 1;
}

static void make_token(wchar_t *out, size_t cap) {
    _snwprintf(out, cap, L"%08lx%08lx", GetCurrentProcessId(), GetTickCount());
}

static int boot_marker(wchar_t *out, size_t cap, const wchar_t *token) {
    wchar_t dir[1024];
    if (!boot_dir(dir, 1024))
        return 0;
    return _snwprintf(out, cap, L"%s\\boot-%s.ok", dir, token) > 0;
}

static void forward_args(wchar_t *cmd, size_t cap) {
    /* 安装包带给启动器的参数（老单文件版的 --legacy-cleanup）原样交给真正的程序。 */
    const wchar_t *rest = GetCommandLineW();
    size_t n;
    if (*rest == L'"') {
        rest++;
        while (*rest && *rest != L'"')
            rest++;
        if (*rest == L'"')
            rest++;
    } else {
        while (*rest && *rest != L' ')
            rest++;
    }
    while (*rest == L' ')
        rest++;
    if (!*rest)
        return;
    n = wcslen(cmd);
    if (n + 1 + wcslen(rest) >= cap)
        return;
    cmd[n] = L' ';
    wcscpy(cmd + n + 1, rest);
}

static int spawn_and_wait(const wchar_t *exe, const wchar_t *token) {
    wchar_t cmd[2048];
    wchar_t marker[1100];
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    if (!boot_marker(marker, 1100, token)) {
        log_line(L"no boot dir, skip confirm");
        return 0;
    }
    DeleteFileW(marker);
    if (_snwprintf(cmd, 2048, L"\"%s\" --boot-token %s", exe, token) <= 0)
        return 0;
    forward_args(cmd, 2048);
    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    ZeroMemory(&pi, sizeof pi);
    if (!CreateProcessW(exe, cmd, NULL, NULL, FALSE, 0, NULL, g_dir, &si, &pi)) {
        note(L"CreateProcess failed %lu", GetLastError());
        return 0;
    }
    for (;;) {
        if (file_exists(marker)) {
            CloseHandle(pi.hThread);
            CloseHandle(pi.hProcess);
            DeleteFileW(marker);
            log_line(L"boot confirmed");
            return 1;
        }
        if (WaitForSingleObject(pi.hProcess, 200) == WAIT_OBJECT_0) {
            int ok = file_exists(marker);
            CloseHandle(pi.hThread);
            CloseHandle(pi.hProcess);
            if (ok)
                DeleteFileW(marker);
            note(L"process exit, boot=%d", ok);
            return ok;
        }
    }
}

static int prev_ok(void) {
    wchar_t internal[1024], bin[1024];
    if (!join2(internal, 1024, g_dir, L"_prev\\_internal"))
        return 0;
    if (!join2(bin, 1024, g_dir, L"_prev\\WorkTimer.bin.exe"))
        return 0;
    return runtime_ok(internal) && file_exists(bin);
}

static int commit_exists(void) {
    wchar_t p[1024];
    if (!join2(p, 1024, g_dir, L"_prev\\COMMIT"))
        return 0;
    return file_exists(p);
}

static int restore_prev(void) {
    wchar_t live_i[1024], live_b[1024], prev[1024], prev_i[1024], prev_b[1024];
    if (!prev_ok())
        return 0;
    if (!join2(live_i, 1024, g_dir, L"_internal") || !join2(live_b, 1024, g_dir, L"WorkTimer.bin.exe"))
        return 0;
    if (!join2(prev, 1024, g_dir, L"_prev") || !join2(prev_i, 1024, g_dir, L"_prev\\_internal"))
        return 0;
    if (!join2(prev_b, 1024, g_dir, L"_prev\\WorkTimer.bin.exe"))
        return 0;
    log_line(L"restore previous version");
    {
        /* 先整个挪开，挪不动说明有文件被占用，什么都不删。 */
        wchar_t aside_i[1024], aside_b[1024];
        if (!join2(aside_i, 1024, g_dir, L"_broken_internal") || !join2(aside_b, 1024, g_dir, L"_broken.bin.exe"))
            return 0;
        if (dir_exists(aside_i) && !delete_tree(aside_i))
            return 0;
        if (file_exists(aside_b) && !DeleteFileW(aside_b))
            return 0;
        if (dir_exists(live_i) && !move_item(live_i, aside_i))
            return 0;
        if (file_exists(live_b) && !move_item(live_b, aside_b)) {
            move_item(aside_i, live_i);
            return 0;
        }
        if (!move_item(prev_i, live_i)) {
            move_item(aside_i, live_i);
            move_item(aside_b, live_b);
            return 0;
        }
        if (!move_item(prev_b, live_b)) {
            move_item(live_i, prev_i);
            move_item(aside_i, live_i);
            move_item(aside_b, live_b);
            return 0;
        }
        delete_tree(aside_i);
        if (file_exists(aside_b))
            DeleteFileW(aside_b);
    }
    delete_tree(prev);
    return runtime_ok(live_i) && file_exists(live_b);
}

static int app_running(void) {
    /* 名字和 single_instance.py 一致。WT_MUTEX_NAME 只给测试用。 */
    wchar_t name[256];
    HANDLE h;
    DWORD n = GetEnvironmentVariableW(L"WT_MUTEX_NAME", name, 256);
    if (n == 0 || n >= 256)
        wcscpy(name, L"Local\\WorkTimer.SingleInstance");
    h = OpenMutexW(SYNCHRONIZE, FALSE, name);
    if (!h)
        return 0;
    CloseHandle(h);
    return 1;
}

/* 已经开着一份：不换文件，交给它自己唤起窗口。 */
static void hand_to_running(void) {
    wchar_t bin[1024], cmd[1100];
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    if (!join2(bin, 1024, g_dir, L"WorkTimer.bin.exe") || !file_exists(bin))
        return;
    if (_snwprintf(cmd, 1100, L"\"%s\"", bin) <= 0)
        return;
    ZeroMemory(&si, sizeof si);
    si.cb = sizeof si;
    if (CreateProcessW(bin, cmd, NULL, NULL, FALSE, 0, NULL, g_dir, &si, &pi)) {
        CloseHandle(pi.hThread);
        CloseHandle(pi.hProcess);
    }
}

static void heal_internal_old(void) {
    wchar_t live[1024], old[1024];
    if (!join2(live, 1024, g_dir, L"_internal") || !join2(old, 1024, g_dir, L"_internal.old"))
        return;
    if (!runtime_ok(live) && runtime_ok(old)) {
        log_line(L"restore _internal.old");
        if (dir_exists(live))
            delete_tree(live);
        move_item(old, live);
    } else if (runtime_ok(live) && dir_exists(old)) {
        delete_tree(old);
    }
}

static void heal_launch_name(void) {
    wchar_t live[1024], tmp[1024];
    if (!join2(live, 1024, g_dir, L"WorkTimer.exe") || !join2(tmp, 1024, g_dir, L"WorkTimer.launch.exe"))
        return;
    if (!file_exists(live) && file_exists(tmp))
        move_item(tmp, live);
}

static int pending_paths(wchar_t *ready, wchar_t *pbin, wchar_t *pinternal) {
    return join2(ready, 1024, g_dir, L"_pending\\READY")
        && join2(pbin, 1024, g_dir, L"_pending\\WorkTimer.bin.exe")
        && join2(pinternal, 1024, g_dir, L"_pending\\_internal");
}

static void discard_bad_pending(void) {
    wchar_t pending[1024], ready[1024], pbin[1024], pinternal[1024];
    if (!join2(pending, 1024, g_dir, L"_pending") || !pending_paths(ready, pbin, pinternal))
        return;
    if (!file_exists(ready))
        return;
    if (file_exists(pbin) && runtime_ok(pinternal))
        return;
    log_line(L"discard incomplete pending");
    delete_tree(pending);
}

/* 返回 1 表示已经换成 _pending 里的新版本。attempted 表示这次处理过一份待换的包。 */
static int apply_pending(int *attempted) {
    wchar_t pending[1024], ready[1024], pbin[1024], pinternal[1024];
    wchar_t live_i[1024], live_b[1024], prev[1024], prev_i[1024], prev_b[1024], commit[1024];
    int parked = 0;
    int aside = 0;
    HANDLE h;
    *attempted = 0;
    if (!join2(pending, 1024, g_dir, L"_pending") || !pending_paths(ready, pbin, pinternal))
        return 0;
    if (!file_exists(ready) || !file_exists(pbin) || !runtime_ok(pinternal))
        return 0;
    if (!join2(live_i, 1024, g_dir, L"_internal") || !join2(live_b, 1024, g_dir, L"WorkTimer.bin.exe"))
        return 0;
    if (!join2(prev, 1024, g_dir, L"_prev") || !join2(prev_i, 1024, g_dir, L"_prev\\_internal"))
        return 0;
    if (!join2(prev_b, 1024, g_dir, L"_prev\\WorkTimer.bin.exe") || !join2(commit, 1024, g_dir, L"_prev\\COMMIT"))
        return 0;
    if (commit_exists()) {
        log_line(L"unconfirmed backup still present, skip apply");
        return 0;
    }
    *attempted = 1;
    log_line(L"apply pending");
    if (runtime_ok(live_i) && file_exists(live_b)) {
        if (dir_exists(prev) && !delete_tree(prev))
            return 0;
        if (!CreateDirectoryW(prev, NULL))
            return 0;
        if (!move_item(live_b, prev_b) || !move_item(live_i, prev_i)) {
            move_item(prev_b, live_b);
            move_item(prev_i, live_i);
            delete_tree(prev);
            delete_tree(pending);
            *attempted = 1;
            return 0;
        }
        h = CreateFileW(commit, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
        if (h == INVALID_HANDLE_VALUE) {
            move_item(prev_i, live_i);
            move_item(prev_b, live_b);
            delete_tree(prev);
            delete_tree(pending);
            return 0;
        }
        CloseHandle(h);
        parked = 1;
    } else {
        /* 现在这份本来就打不开：先挪到旁边，新文件就位再删，失败就挪回来。 */
        wchar_t aside_i[1024], aside_b[1024];
        if (!join2(aside_i, 1024, g_dir, L"_broken_internal") || !join2(aside_b, 1024, g_dir, L"_broken.bin.exe"))
            return 0;
        if (dir_exists(aside_i))
            delete_tree(aside_i);
        if (file_exists(aside_b))
            DeleteFileW(aside_b);
        if (dir_exists(live_i) && !move_item(live_i, aside_i))
            return 0;
        if (file_exists(live_b) && !move_item(live_b, aside_b)) {
            move_item(aside_i, live_i);
            return 0;
        }
        aside = 1;
        (void)aside_i;
        (void)aside_b;
    }
    if (!move_item(pinternal, live_i) || !move_item(pbin, live_b) || !runtime_ok(live_i)) {
        wchar_t aside_i[1024], aside_b[1024];
        log_line(L"pending swap failed");
        join2(aside_i, 1024, g_dir, L"_broken_internal");
        join2(aside_b, 1024, g_dir, L"_broken.bin.exe");
        if (parked)
            restore_prev();
        else {
            if (dir_exists(live_i))
                delete_tree(live_i);
            if (file_exists(live_b))
                DeleteFileW(live_b);
            if (aside) {
                move_item(aside_i, live_i);
                move_item(aside_b, live_b);
            } else {
                move_item(live_i, pinternal);
                move_item(live_b, pbin);
            }
        }
        if (runtime_ok(live_i) && file_exists(live_b))
            delete_tree(pending);
        return 0;
    }
    if (!parked) {
        wchar_t aside_i[1024], aside_b[1024];
        if (join2(aside_i, 1024, g_dir, L"_broken_internal"))
            delete_tree(aside_i);
        if (join2(aside_b, 1024, g_dir, L"_broken.bin.exe") && file_exists(aside_b))
            DeleteFileW(aside_b);
    }
    DeleteFileW(ready);
    log_line(L"pending is now live");
    return 1;
}

static void start_or_recover(void) {
    wchar_t bin[1024], prev[1024], pending[1024], token[40];
    wchar_t live_i[1024];
    int attempted = 0;
    int swapped;
    int ok;
    if (!join2(bin, 1024, g_dir, L"WorkTimer.bin.exe") || !join2(live_i, 1024, g_dir, L"_internal"))
        return;
    if (!join2(prev, 1024, g_dir, L"_prev") || !join2(pending, 1024, g_dir, L"_pending"))
        return;
    if (commit_exists() || (!runtime_ok(live_i) && prev_ok())) {
        log_line(L"unconfirmed or broken install");
        restore_prev();
    }
    discard_bad_pending();
    swapped = apply_pending(&attempted);
    (void)attempted;
    if ((!runtime_ok(live_i) || !file_exists(bin)) && prev_ok())
        restore_prev();
    if (runtime_ok(live_i) && file_exists(bin)) {
        make_token(token, 40);
        ok = spawn_and_wait(bin, token);
        if (ok) {
            delete_tree(prev);
            if (swapped)
                delete_tree(pending);
            ExitProcess(0);
        }
        log_line(L"boot not confirmed");
        if (swapped || commit_exists()) {
            delete_tree(pending);
            if (restore_prev()) {
                make_token(token, 40);
                if (spawn_and_wait(bin, token))
                    ExitProcess(0);
            }
        }
        if (runtime_ok(live_i) && file_exists(bin))
            ExitProcess(1);
    }
    MessageBoxW(NULL,
                L"更新没有完成，上一版也没能打开。请再安装一次。",
                L"下班倒计时",
                MB_OK | MB_ICONERROR | MB_SETFOREGROUND);
    ExitProcess(2);
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmd, int show) {
    wchar_t self[1024];
    wchar_t *slash;
    (void)inst;
    (void)prev;
    (void)cmd;
    (void)show;
    if (!GetModuleFileNameW(NULL, self, 1024))
        return 2;
    slash = wcsrchr(self, L'\\');
    if (!slash)
        return 2;
    *slash = 0;
    if (wcslen(self) >= 1024)
        return 2;
    wcscpy(g_dir, self);
    log_open();
    if (app_running()) {
        log_line(L"already running");
        hand_to_running();
        return 0;
    }
    heal_launch_name();
    heal_internal_old();
    start_or_recover();
    return 0;
}
