#define UNICODE
#define _UNICODE
#define CINTERFACE
#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <objbase.h>
#include <shlguid.h>
#include <shlobj.h>
#include <shlwapi.h>
#include <shellapi.h>
#include <commctrl.h>
#include <stdio.h>

#pragma comment(lib, "shell32")
#pragma comment(lib, "shlwapi")
#pragma comment(lib, "ole32")
#pragma comment(lib, "comctl32")
#pragma comment(lib, "uuid")

enum { PAGE_WELCOME = 0, PAGE_DEST = 1, PAGE_PROGRESS = 2, PAGE_FINISH = 3 };

static HWND g_main, g_next, g_back, g_install, g_finish, g_cancel;
static HWND g_welcome, g_dest, g_progress, g_done;
static HWND g_dest_edit, g_log, g_bar;
static HWND g_launch_check;
static int g_page = 0;
static wchar_t g_root[MAX_PATH];
static wchar_t g_payload[MAX_PATH];
static int g_ok = 0;

static void append_log(const wchar_t *line) {
    int len = GetWindowTextLengthW(g_log);
    SendMessageW(g_log, EM_SETSEL, len, len);
    SendMessageW(g_log, EM_REPLACESEL, FALSE, (LPARAM)line);
    SendMessageW(g_log, EM_REPLACESEL, FALSE, (LPARAM)L"\r\n");
}

static void show_page(int page) {
    g_page = page;
    ShowWindow(g_welcome, page == PAGE_WELCOME ? SW_SHOW : SW_HIDE);
    ShowWindow(g_dest, page == PAGE_DEST ? SW_SHOW : SW_HIDE);
    ShowWindow(g_progress, page == PAGE_PROGRESS ? SW_SHOW : SW_HIDE);
    ShowWindow(g_done, page == PAGE_FINISH ? SW_SHOW : SW_HIDE);
    EnableWindow(g_back, page == PAGE_DEST);
    EnableWindow(g_next, page == PAGE_WELCOME);
    EnableWindow(g_install, page == PAGE_DEST);
    EnableWindow(g_finish, page == PAGE_FINISH);
}

static int exists(const wchar_t *path) {
    return GetFileAttributesW(path) != INVALID_FILE_ATTRIBUTES;
}

static void join(wchar_t *out, const wchar_t *a, const wchar_t *b) {
    lstrcpynW(out, a, MAX_PATH);
    PathAppendW(out, b);
}

static BOOL run_hidden(const wchar_t *exe, wchar_t *cmdline, const wchar_t *cwd) {
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;
    if (!CreateProcessW(exe, cmdline, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, cwd, &si, &pi)) {
        return FALSE;
    }
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return code == 0;
}

static BOOL create_shortcut(const wchar_t *link, const wchar_t *target, const wchar_t *workdir, const wchar_t *icon) {
    HRESULT hr;
    IShellLinkW *sl = NULL;
    IPersistFile *pf = NULL;
    CoInitialize(NULL);
    hr = CoCreateInstance(&CLSID_ShellLink, NULL, CLSCTX_INPROC_SERVER, &IID_IShellLinkW, (void **)&sl);
    if (FAILED(hr)) return FALSE;
    sl->lpVtbl->SetPath(sl, target);
    sl->lpVtbl->SetWorkingDirectory(sl, workdir);
    sl->lpVtbl->SetDescription(sl, L"Jonathan Ai");
    if (icon && icon[0]) sl->lpVtbl->SetIconLocation(sl, icon, 0);
    hr = sl->lpVtbl->QueryInterface(sl, &IID_IPersistFile, (void **)&pf);
    if (SUCCEEDED(hr)) {
        pf->lpVtbl->Save(pf, link, TRUE);
        pf->lpVtbl->Release(pf);
    }
    sl->lpVtbl->Release(sl);
    return TRUE;
}

static void make_shortcuts(const wchar_t *exe, const wchar_t *icon) {
    wchar_t desk[MAX_PATH], start[MAX_PATH], desk_lnk[MAX_PATH], start_lnk[MAX_PATH], work[MAX_PATH];
    SHGetFolderPathW(NULL, CSIDL_DESKTOPDIRECTORY, NULL, 0, desk);
    SHGetFolderPathW(NULL, CSIDL_PROGRAMS, NULL, 0, start);
    join(desk_lnk, desk, L"Jonathan Ai.lnk");
    join(start_lnk, start, L"Jonathan Ai.lnk");
    lstrcpynW(work, exe, MAX_PATH);
    PathRemoveFileSpecW(work);
    create_shortcut(desk_lnk, exe, work, icon);
    create_shortcut(start_lnk, exe, work, icon);
}

static DWORD WINAPI install_thread(LPVOID param) {
    wchar_t dest[MAX_PATH], cmd[2048], python[MAX_PATH], launcher[MAX_PATH], icon[MAX_PATH], srccli[MAX_PATH];
    (void)param;
    GetWindowTextW(g_dest_edit, dest, MAX_PATH);
    append_log(L"Creating install folder…");
    SHCreateDirectoryExW(NULL, dest, NULL);

    join(srccli, g_payload, L"src\\cli.py");
    if (exists(srccli)) {
        append_log(L"Copying this checkout into the Jonathan folder…");
        wsprintfW(cmd, L"cmd.exe /C xcopy /E /I /Y /Q \"%s\" \"%s\"", g_payload, dest);
        run_hidden(L"C:\\Windows\\System32\\cmd.exe", cmd, g_payload);
    } else {
        append_log(L"Cloning https://github.com/GoDeskio/Clawd-Code …");
        wsprintfW(cmd, L"git clone --origin origin https://github.com/GoDeskio/Clawd-Code.git \"%s\"", dest);
        if (!run_hidden(L"C:\\Windows\\System32\\cmd.exe", cmd, NULL)) {
            append_log(L"ERROR: git clone failed. Install Git or run from a checkout.");
            PostMessageW(g_main, WM_APP + 2, 0, 0);
            return 1;
        }
    }

    append_log(L"Locating Python 3.10+…");
    if (GetEnvironmentVariableW(L"CLAWD_PYTHON", python, MAX_PATH) == 0) {
        lstrcpynW(python, L"python", MAX_PATH);
    }
    append_log(L"Installing Jonathan Ai (venv, dependencies, verify)…");
    wsprintfW(
        cmd,
        L"\"%s\" -m src.install --source-dir \"%s\" --from-local \"%s\" --yes",
        python, dest, dest
    );
    if (!run_hidden(python, cmd, dest)) {
        /* Retry with py launcher. */
        wsprintfW(cmd, L"py -3 -m src.install --source-dir \"%s\" --from-local \"%s\" --yes", dest, dest);
        if (!run_hidden(L"py", cmd, dest)) {
            append_log(L"ERROR: Python install step failed.");
            PostMessageW(g_main, WM_APP + 2, 0, 0);
            return 1;
        }
    }

    join(launcher, dest, L"JonathanAi.exe");
    if (!exists(launcher)) {
        wchar_t bundled[MAX_PATH];
        join(bundled, g_root, L"JonathanAi.exe");
        if (exists(bundled)) CopyFileW(bundled, launcher, FALSE);
    }
    join(icon, dest, L"src\\desktop\\web\\favicon.ico");
    if (!exists(icon)) join(icon, g_root, L"jonathan-ai.ico");
    append_log(L"Creating Desktop and Start Menu shortcuts…");
    make_shortcuts(launcher, icon);
    append_log(L"Done.");
    g_ok = 1;
    PostMessageW(g_main, WM_APP + 1, 0, 0);
    return 0;
}

static void launch_app(void) {
    wchar_t dest[MAX_PATH], exe[MAX_PATH];
    GetWindowTextW(g_dest_edit, dest, MAX_PATH);
    join(exe, dest, L"JonathanAi.exe");
    ShellExecuteW(NULL, L"open", exe, NULL, dest, SW_SHOWNORMAL);
}

static LRESULT CALLBACK WndProc(HWND hwnd, UINT msg, WPARAM w, LPARAM l) {
    switch (msg) {
    case WM_CREATE: {
        INITCOMMONCONTROLSEX icc = { sizeof(icc), ICC_PROGRESS_CLASS };
        InitCommonControlsEx(&icc);
        CreateWindowW(L"STATIC", L"Jonathan Ai", WS_CHILD | WS_VISIBLE,
            24, 16, 400, 28, hwnd, NULL, NULL, NULL);
        CreateWindowW(L"STATIC", L"Windows desktop installer", WS_CHILD | WS_VISIBLE,
            24, 44, 400, 20, hwnd, NULL, NULL, NULL);

        g_welcome = CreateWindowW(L"STATIC",
            L"This wizard installs Jonathan Ai.\r\n\r\n"
            L"On Finish the app window opens and a Jonathan Ai icon is placed on the Desktop and Start Menu.\r\n\r\n"
            L"Source and updates: https://github.com/GoDeskio/Clawd-Code\r\n"
            L"Tokens stay on this computer. They are never written into the installer.",
            WS_CHILD | WS_VISIBLE, 24, 80, 560, 180, hwnd, NULL, NULL, NULL);

        g_dest = CreateWindowW(L"STATIC", L"Install folder", WS_CHILD, 24, 80, 200, 20, hwnd, NULL, NULL, NULL);
        g_dest_edit = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"",
            WS_CHILD | ES_AUTOHSCROLL, 24, 108, 560, 28, hwnd, NULL, NULL, NULL);
        {
            wchar_t home[MAX_PATH], dest[MAX_PATH];
            if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_PROFILE, NULL, 0, home))) {
                join(dest, home, L"Jonathan\\Jonathan-Ai");
                SetWindowTextW(g_dest_edit, dest);
            }
        }

        g_progress = CreateWindowW(L"STATIC", L"", WS_CHILD, 24, 80, 10, 10, hwnd, NULL, NULL, NULL);
        g_bar = CreateWindowW(PROGRESS_CLASSW, NULL, WS_CHILD | PBS_MARQUEE, 24, 88, 560, 20, hwnd, NULL, NULL, NULL);
        g_log = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"",
            WS_CHILD | ES_MULTILINE | ES_AUTOVSCROLL | ES_READONLY | WS_VSCROLL,
            24, 120, 560, 180, hwnd, NULL, NULL, NULL);

        g_done = CreateWindowW(L"STATIC",
            L"Installation finished.\r\nShortcuts named Jonathan Ai are on the Desktop and Start Menu.",
            WS_CHILD, 24, 80, 560, 80, hwnd, NULL, NULL, NULL);
        g_launch_check = CreateWindowW(L"BUTTON", L"Launch Jonathan Ai now",
            WS_CHILD | BS_AUTOCHECKBOX, 24, 170, 300, 24, hwnd, NULL, NULL, NULL);
        SendMessageW(g_launch_check, BM_SETCHECK, BST_CHECKED, 0);

        g_cancel = CreateWindowW(L"BUTTON", L"Cancel", WS_CHILD | WS_VISIBLE, 24, 380, 90, 30, hwnd, (HMENU)1, NULL, NULL);
        g_back = CreateWindowW(L"BUTTON", L"Back", WS_CHILD | WS_VISIBLE, 280, 380, 90, 30, hwnd, (HMENU)2, NULL, NULL);
        g_next = CreateWindowW(L"BUTTON", L"Next", WS_CHILD | WS_VISIBLE, 380, 380, 90, 30, hwnd, (HMENU)3, NULL, NULL);
        g_install = CreateWindowW(L"BUTTON", L"Install", WS_CHILD | WS_VISIBLE, 380, 380, 90, 30, hwnd, (HMENU)4, NULL, NULL);
        g_finish = CreateWindowW(L"BUTTON", L"Finish", WS_CHILD | WS_VISIBLE, 480, 380, 90, 30, hwnd, (HMENU)5, NULL, NULL);
        show_page(PAGE_WELCOME);
        return 0;
    }
    case WM_COMMAND:
        if (LOWORD(w) == 1) PostQuitMessage(0);
        if (LOWORD(w) == 2) show_page(PAGE_WELCOME);
        if (LOWORD(w) == 3) show_page(PAGE_DEST);
        if (LOWORD(w) == 4) {
            show_page(PAGE_PROGRESS);
            ShowWindow(g_bar, SW_SHOW);
            ShowWindow(g_log, SW_SHOW);
            SendMessageW(g_bar, PBM_SETMARQUEE, TRUE, 50);
            CreateThread(NULL, 0, install_thread, NULL, 0, NULL);
        }
        if (LOWORD(w) == 5) {
            if (SendMessageW(g_launch_check, BM_GETCHECK, 0, 0) == BST_CHECKED) {
                launch_app();
            }
            PostQuitMessage(0);
        }
        return 0;
    case WM_APP + 1:
        SendMessageW(g_bar, PBM_SETMARQUEE, FALSE, 0);
        show_page(PAGE_FINISH);
        ShowWindow(g_launch_check, SW_SHOW);
        return 0;
    case WM_APP + 2:
        SendMessageW(g_bar, PBM_SETMARQUEE, FALSE, 0);
        MessageBoxW(hwnd, L"Install failed. See the log.", L"Jonathan Ai", MB_OK | MB_ICONERROR);
        show_page(PAGE_DEST);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, w, l);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, PWSTR cmd, int show) {
    WNDCLASSW wc;
    MSG msg;
    wchar_t exe[MAX_PATH];
    (void)prev; (void)cmd;
    GetModuleFileNameW(NULL, exe, MAX_PATH);
    lstrcpynW(g_root, exe, MAX_PATH);
    PathRemoveFileSpecW(g_root);
    lstrcpynW(g_payload, g_root, MAX_PATH);
    /* If Setup lives in packaging\\windows\\bin, payload is the repo root. */
    if (wcsstr(g_root, L"packaging\\windows")) {
        lstrcpynW(g_payload, g_root, MAX_PATH);
        PathRemoveFileSpecW(g_payload);
        PathRemoveFileSpecW(g_payload);
        PathRemoveFileSpecW(g_payload);
    }

    ZeroMemory(&wc, sizeof(wc));
    wc.lpfnWndProc = WndProc;
    wc.hInstance = inst;
    wc.lpszClassName = L"JonathanAiSetup";
    wc.hbrBackground = CreateSolidBrush(RGB(18, 18, 20));
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hIcon = LoadIconW(inst, MAKEINTRESOURCEW(1));
    if (!wc.hIcon) wc.hIcon = LoadIcon(NULL, IDI_APPLICATION);
    RegisterClassW(&wc);
    g_main = CreateWindowW(L"JonathanAiSetup", L"Install Jonathan Ai",
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
        CW_USEDEFAULT, CW_USEDEFAULT, 640, 460, NULL, NULL, inst, NULL);
    ShowWindow(g_main, show);
    UpdateWindow(g_main);
    while (GetMessageW(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
    return 0;
}
