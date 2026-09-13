#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>

typedef struct wide_buffer {
    WCHAR *data;
    SIZE_T length;
    SIZE_T capacity;
} wide_buffer;

static WCHAR g_message[1024];

static SIZE_T wide_length(const WCHAR *text)
{
    SIZE_T length = 0;
    while (text[length]) {
        ++length;
    }
    return length;
}

static WCHAR *wide_last_character(WCHAR *text, WCHAR character)
{
    WCHAR *last = NULL;
    while (*text) {
        if (*text == character) {
            last = text;
        }
        ++text;
    }
    return last;
}

static void wide_copy(WCHAR *destination, const WCHAR *source, SIZE_T count)
{
    SIZE_T i;
    for (i = 0; i < count; ++i) {
        destination[i] = source[i];
    }
}

static void zero_memory(void *memory, SIZE_T count)
{
    volatile BYTE *bytes = (volatile BYTE *)memory;
    while (count) {
        *bytes++ = 0;
        --count;
    }
}

static void fixed_append(WCHAR *buffer, SIZE_T capacity, SIZE_T *length,
                         const WCHAR *text)
{
    while (*text && *length + 1 < capacity) {
        buffer[(*length)++] = *text++;
    }
    if (capacity) {
        buffer[*length] = L'\0';
    }
}

static void fixed_append_character(WCHAR *buffer, SIZE_T capacity,
                                   SIZE_T *length, WCHAR character)
{
    if (*length + 1 < capacity) {
        buffer[(*length)++] = character;
    }
    if (capacity) {
        buffer[*length] = L'\0';
    }
}

static void fixed_append_number(WCHAR *buffer, SIZE_T capacity, SIZE_T *length,
                                DWORD number)
{
    DWORD divisor = 1;
    while (number / divisor >= 10 && divisor <= 100000000) {
        divisor *= 10;
    }
    for (;;) {
        fixed_append_character(buffer, capacity, length,
                               (WCHAR)(L'0' + number / divisor));
        number %= divisor;
        if (divisor == 1) {
            break;
        }
        divisor /= 10;
    }
}

static BOOL buffer_reserve(wide_buffer *buffer, SIZE_T extra)
{
    SIZE_T needed;
    SIZE_T capacity;
    WCHAR *grown;

    if (extra > (SIZE_T)-1 - buffer->length - 1) {
        return FALSE;
    }
    needed = buffer->length + extra + 1;
    if (needed <= buffer->capacity) {
        return TRUE;
    }

    capacity = buffer->capacity ? buffer->capacity : 128;
    while (capacity < needed) {
        if (capacity > (SIZE_T)-1 / 2) {
            capacity = needed;
            break;
        }
        capacity *= 2;
    }
    if (capacity > (SIZE_T)-1 / sizeof(WCHAR)) {
        return FALSE;
    }

    if (buffer->data) {
        grown = (WCHAR *)HeapReAlloc(GetProcessHeap(), 0, buffer->data,
                                     capacity * sizeof(WCHAR));
    } else {
        grown = (WCHAR *)HeapAlloc(GetProcessHeap(), 0,
                                   capacity * sizeof(WCHAR));
    }
    if (!grown) {
        return FALSE;
    }

    buffer->data = grown;
    buffer->capacity = capacity;
    return TRUE;
}

static BOOL buffer_append_char(wide_buffer *buffer, WCHAR character)
{
    if (!buffer_reserve(buffer, 1)) {
        return FALSE;
    }
    buffer->data[buffer->length++] = character;
    buffer->data[buffer->length] = L'\0';
    return TRUE;
}

static BOOL buffer_append_repeat(wide_buffer *buffer, WCHAR character,
                                 SIZE_T count)
{
    SIZE_T i;

    if (!buffer_reserve(buffer, count)) {
        return FALSE;
    }
    for (i = 0; i < count; ++i) {
        buffer->data[buffer->length++] = character;
    }
    buffer->data[buffer->length] = L'\0';
    return TRUE;
}

static BOOL buffer_append_quoted(wide_buffer *buffer, const WCHAR *argument)
{
    SIZE_T slashes = 0;
    const WCHAR *cursor = argument;

    if (!buffer_append_char(buffer, L'"')) {
        return FALSE;
    }

    while (*cursor) {
        if (*cursor == L'\\') {
            ++slashes;
            ++cursor;
            continue;
        }

        if (*cursor == L'"') {
            if (!buffer_append_repeat(buffer, L'\\', slashes * 2 + 1) ||
                !buffer_append_char(buffer, L'"')) {
                return FALSE;
            }
        } else {
            if (!buffer_append_repeat(buffer, L'\\', slashes) ||
                !buffer_append_char(buffer, *cursor)) {
                return FALSE;
            }
        }
        slashes = 0;
        ++cursor;
    }

    if (!buffer_append_repeat(buffer, L'\\', slashes * 2) ||
        !buffer_append_char(buffer, L'"')) {
        return FALSE;
    }
    return TRUE;
}

static WCHAR *get_module_path(void)
{
    DWORD capacity = 512;

    while (capacity <= 32768) {
        WCHAR *path = (WCHAR *)HeapAlloc(GetProcessHeap(), 0,
                                          (SIZE_T)capacity * sizeof(WCHAR));
        DWORD length;

        if (!path) {
            return NULL;
        }
        SetLastError(ERROR_SUCCESS);
        length = GetModuleFileNameW(NULL, path, capacity);
        if (!length) {
            HeapFree(GetProcessHeap(), 0, path);
            return NULL;
        }
        if (length < capacity) {
            path[length] = L'\0';
            return path;
        }
        HeapFree(GetProcessHeap(), 0, path);
        if (capacity == 32768) {
            break;
        }
        capacity *= 2;
        if (capacity > 32768) {
            capacity = 32768;
        }
    }

    SetLastError(ERROR_FILENAME_EXCED_RANGE);
    return NULL;
}

static WCHAR *get_application_root(WCHAR *module_path)
{
    WCHAR *backslash = wide_last_character(module_path, L'\\');
    WCHAR *slash = wide_last_character(module_path, L'/');
    WCHAR *last = backslash;

    if (!last || (slash && slash > last)) {
        last = slash;
    }
    if (!last) {
        return NULL;
    }

    if (last == module_path + 2 && module_path[1] == L':') {
        last[1] = L'\0';
    } else {
        *last = L'\0';
    }
    return module_path;
}

static WCHAR *join_path(const WCHAR *root, const WCHAR *relative)
{
    SIZE_T root_length = wide_length(root);
    SIZE_T relative_length = wide_length(relative);
    BOOL needs_separator = root_length > 0 &&
        root[root_length - 1] != L'\\' && root[root_length - 1] != L'/';
    SIZE_T total = root_length + (needs_separator ? 1 : 0) + relative_length + 1;
    WCHAR *joined;

    if (total < root_length || total > (SIZE_T)-1 / sizeof(WCHAR)) {
        return NULL;
    }
    joined = (WCHAR *)HeapAlloc(GetProcessHeap(), 0, total * sizeof(WCHAR));
    if (!joined) {
        return NULL;
    }

    wide_copy(joined, root, root_length);
    if (needs_separator) {
        joined[root_length++] = L'\\';
    }
    wide_copy(joined + root_length, relative, relative_length + 1);
    return joined;
}

static BOOL file_exists(const WCHAR *path)
{
    DWORD attributes = GetFileAttributesW(path);
    return attributes != INVALID_FILE_ATTRIBUTES &&
           !(attributes & FILE_ATTRIBUTE_DIRECTORY);
}

static void show_error(const WCHAR *message)
{
    MessageBoxW(NULL, message, L"Parappa Access", MB_OK | MB_ICONERROR |
                MB_SETFOREGROUND);
}

static void show_missing_file(const WCHAR *description, const WCHAR *path)
{
    SIZE_T length = 0;
    fixed_append(g_message, sizeof(g_message) / sizeof(g_message[0]), &length,
                 description);
    fixed_append(g_message, sizeof(g_message) / sizeof(g_message[0]), &length,
                 L" was not found:\n\n");
    fixed_append(g_message, sizeof(g_message) / sizeof(g_message[0]), &length,
                 path);
    fixed_append(g_message, sizeof(g_message) / sizeof(g_message[0]), &length,
                 L"\n\nExtract the complete Parappa Access folder and try again.");
    show_error(g_message);
}

static BOOL append_command_argument(wide_buffer *command, const WCHAR *argument)
{
    if (command->length && !buffer_append_char(command, L' ')) {
        return FALSE;
    }
    return buffer_append_quoted(command, argument);
}

static BOOL launch_menu(const WCHAR *root, const WCHAR *python,
                        const WCHAR *script)
{
    wide_buffer command = {0};
    LPWSTR *arguments = NULL;
    int argument_count = 0;
    int i;
    STARTUPINFOW startup;
    PROCESS_INFORMATION process;
    DWORD error;
    BOOL started = FALSE;

    arguments = CommandLineToArgvW(GetCommandLineW(), &argument_count);
    if (!arguments) {
        SIZE_T length = 0;
        DWORD command_error = GetLastError();
        fixed_append(g_message, sizeof(g_message) / sizeof(g_message[0]), &length,
                     L"Could not read the launcher command line (Windows error ");
        fixed_append_number(g_message, sizeof(g_message) / sizeof(g_message[0]),
                            &length, command_error);
        fixed_append(g_message, sizeof(g_message) / sizeof(g_message[0]), &length,
                     L").");
        show_error(g_message);
        return FALSE;
    }

    if (!append_command_argument(&command, python) ||
        !append_command_argument(&command, script)) {
        goto allocation_error;
    }
    for (i = 1; i < argument_count; ++i) {
        if (!append_command_argument(&command, arguments[i])) {
            goto allocation_error;
        }
    }

    if (command.length > 32760) {
        show_error(L"The launcher arguments exceed the Windows command-line limit.");
        goto cleanup;
    }

    zero_memory(&startup, sizeof(startup));
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESHOWWINDOW;
    startup.wShowWindow = SW_SHOWNORMAL;
    zero_memory(&process, sizeof(process));

    if (CreateProcessW(python, command.data, NULL, NULL, FALSE, 0, NULL,
                       root, &startup, &process)) {
        CloseHandle(process.hThread);
        CloseHandle(process.hProcess);
        started = TRUE;
        goto cleanup;
    }

    error = GetLastError();
    {
        LPWSTR detail = NULL;
        DWORD characters = FormatMessageW(
            FORMAT_MESSAGE_ALLOCATE_BUFFER | FORMAT_MESSAGE_FROM_SYSTEM |
            FORMAT_MESSAGE_IGNORE_INSERTS,
            NULL, error, 0, (LPWSTR)&detail, 0, NULL);
        if (characters && detail) {
            while (characters && (detail[characters - 1] == L'\r' ||
                                  detail[characters - 1] == L'\n')) {
                detail[--characters] = L'\0';
            }
            SIZE_T length = 0;
            fixed_append(g_message, sizeof(g_message) / sizeof(g_message[0]), &length,
                         L"Could not start Parappa Access (Windows error ");
            fixed_append_number(g_message, sizeof(g_message) / sizeof(g_message[0]),
                                &length, error);
            fixed_append(g_message, sizeof(g_message) / sizeof(g_message[0]), &length,
                         L"):\n\n");
            fixed_append(g_message, sizeof(g_message) / sizeof(g_message[0]), &length,
                         detail);
        } else {
            SIZE_T length = 0;
            fixed_append(g_message, sizeof(g_message) / sizeof(g_message[0]), &length,
                         L"Could not start Parappa Access (Windows error ");
            fixed_append_number(g_message, sizeof(g_message) / sizeof(g_message[0]),
                                &length, error);
            fixed_append(g_message, sizeof(g_message) / sizeof(g_message[0]), &length,
                         L").");
        }
        if (detail) {
            LocalFree(detail);
        }
        show_error(g_message);
    }
    goto cleanup;

allocation_error:
    show_error(L"Not enough memory to start Parappa Access.");

cleanup:
    if (arguments) {
        LocalFree(arguments);
    }
    if (command.data) {
        HeapFree(GetProcessHeap(), 0, command.data);
    }
    return started;
}

static int run_launcher(void)
{
    WCHAR *module_path = get_module_path();
    WCHAR *root;
    WCHAR *python = NULL;
    WCHAR *script = NULL;
    BOOL launched = FALSE;

    if (!module_path) {
        show_error(L"Could not find the Parappa Access application folder.");
        return 1;
    }

    root = get_application_root(module_path);
    if (!root) {
        show_error(L"Could not find the Parappa Access application folder.");
        HeapFree(GetProcessHeap(), 0, module_path);
        return 1;
    }

    python = join_path(root, L"runtime\\pythonw.exe");
    script = join_path(root, L"scripts\\launcher_boot.py");
    if (!python || !script) {
        show_error(L"Not enough memory to locate the Parappa Access files.");
        goto done;
    }
    if (!file_exists(python)) {
        show_missing_file(L"The portable Python runtime", python);
        goto done;
    }
    if (!file_exists(script)) {
        show_missing_file(L"The Parappa Access menu", script);
        goto done;
    }

    launched = launch_menu(root, python, script);

done:
    if (script) {
        HeapFree(GetProcessHeap(), 0, script);
    }
    if (python) {
        HeapFree(GetProcessHeap(), 0, python);
    }
    HeapFree(GetProcessHeap(), 0, module_path);
    return launched ? 0 : 1;
}

void WINAPI launcher_entry(void)
{
    ExitProcess((UINT)run_launcher());
}
