/* 测试用的假主程序：尾部 4 字节是 BAD! 就不写启动确认。不随安装包发布。 */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>

static int boot_dir(wchar_t *out, size_t cap) {
    wchar_t env[1024];
    DWORD n = GetEnvironmentVariableW(L"WT_BOOT_DIR", env, 1024);
    if (n > 0 && n < 1024) {
        if (wcslen(env) >= cap)
            return 0;
        wcscpy(out, env);
        return 1;
    }
    n = GetEnvironmentVariableW(L"USERPROFILE", env, 1024);
    if (n == 0 || n >= 1024)
        return 0;
    return _snwprintf(out, cap, L"%s\\AppData\\Roaming\\WorkTimer", env) > 0;
}

static void write_beside(const wchar_t *self, const wchar_t *name) {
    wchar_t path[1024];
    char buf[2000];
    wchar_t *slash = wcsrchr(self, L'\\');
    const wchar_t *text = L"";
    HANDLE h;
    int n;
    DWORD w = 0;
    if (!slash)
        return;
    if (_snwprintf(path, 1024, L"%.*s\\%s", (int)(slash - self), self, name) <= 0)
        return;
    if (wcscmp(name, L"cmdline.txt") == 0)
        text = GetCommandLineW();
    n = WideCharToMultiByte(CP_UTF8, 0, text, -1, buf, (int)sizeof buf - 1, NULL, NULL);
    h = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return;
    if (n > 1)
        WriteFile(h, buf, (DWORD)(n - 1), &w, NULL);
    CloseHandle(h);
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmd, int show) {
    wchar_t self[1024];
    wchar_t token[64];
    wchar_t dir[1024];
    wchar_t marker[1100];
    const wchar_t *flag;
    char tail[4];
    DWORD n = 0;
    HANDLE h;
    int i;
    (void)inst;
    (void)prev;
    (void)cmd;
    (void)show;
    if (!GetModuleFileNameW(NULL, self, 1024))
        return 2;
    write_beside(self, L"cmdline.txt");
    h = CreateFileW(self, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, 0, NULL);
    if (h != INVALID_HANDLE_VALUE) {
        if (SetFilePointer(h, -4, NULL, FILE_END) != INVALID_SET_FILE_POINTER)
            ReadFile(h, tail, 4, &n, NULL);
        CloseHandle(h);
    }
    if (n == 4 && memcmp(tail, "BAD!", 4) == 0) {
        write_beside(self, L"bad-ran.txt");
        return 3;
    }
    flag = wcsstr(GetCommandLineW(), L"--boot-token ");
    if (!flag)
        return 2;
    flag += wcslen(L"--boot-token ");
    for (i = 0; i < 63 && flag[i] && flag[i] != L' '; i++)
        token[i] = flag[i];
    token[i] = 0;
    if (!boot_dir(dir, 1024))
        return 2;
    if (_snwprintf(marker, 1100, L"%s\\boot-%s.ok", dir, token) <= 0)
        return 2;
    h = CreateFileW(marker, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE)
        return 2;
    WriteFile(h, "ok", 2, &n, NULL);
    CloseHandle(h);
    write_beside(self, L"good-ran.txt");
    return 0;
}
