// SPDX-FileCopyrightText: Copyright 2026 Eden Overlay Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include <algorithm>
#include <chrono>
#include <cstring>
#include <mutex>
#include <string>
#include <thread>

#ifdef _WIN32
#include <winsock2.h>
#pragma comment(lib, "ws2_32.lib")
using socklen_t = int;
#else
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#define closesocket close
#endif

#include "common/logging.h"
#include "hid_core/frontend/emulated_controller.h"
#include "hid_core/frontend/overlay_engine.h"

extern "C" {
#include <lua.h>
#include <lualib.h>
#include <lauxlib.h>
}

namespace Core::HID {

namespace {

using steady_clock = std::chrono::steady_clock;

u64 NowUs() {
    return std::chrono::duration_cast<std::chrono::microseconds>(
        steady_clock::now().time_since_epoch()).count();
}

u32 GetButtonBit(const std::string& name) {
    using B = NpadButton;
    if (name == "A")       return static_cast<u32>(B::A);
    if (name == "B")       return static_cast<u32>(B::B);
    if (name == "X")       return static_cast<u32>(B::X);
    if (name == "Y")       return static_cast<u32>(B::Y);
    if (name == "L")       return static_cast<u32>(B::L);
    if (name == "R")       return static_cast<u32>(B::R);
    if (name == "ZL")      return static_cast<u32>(B::ZL);
    if (name == "ZR")      return static_cast<u32>(B::ZR);
    if (name == "Plus")    return static_cast<u32>(B::Plus);
    if (name == "Minus")   return static_cast<u32>(B::Minus);
    if (name == "DUp")     return static_cast<u32>(B::Up);
    if (name == "DDown")   return static_cast<u32>(B::Down);
    if (name == "DLeft")   return static_cast<u32>(B::Left);
    if (name == "DRight")  return static_cast<u32>(B::Right);
    if (name == "LStick")  return static_cast<u32>(B::StickL);
    if (name == "RStick")  return static_cast<u32>(B::StickR);
    if (name == "SLLeft")  return static_cast<u32>(B::LeftSL);
    if (name == "SLRight") return static_cast<u32>(B::RightSL);
    if (name == "SRLeft")  return static_cast<u32>(B::LeftSR);
    if (name == "SRRight") return static_cast<u32>(B::RightSR);
    return 0;
}

using SlotArray = std::array<OverlaySlotState, MAX_OVERLAY_SOURCES>;
OverlayEngine* g_engine = nullptr;

// ---- UDP bridge ----
// Global buffer + listener thread. Lua calls udp_bind(port) then
// udp_poll() each frame.  No external dependencies required.
struct UdpBridge {
    std::mutex mtx;
    std::string buf;          // latest received payload
    bool       fresh = false; // true = new data since last poll
    int        fd  = -1;
    std::atomic<bool> running{false};
    std::thread worker;

    void start(u16 port) {
        if (running.load()) return;
#ifdef _WIN32
        WSADATA wsa;
        if (WSAStartup(MAKEWORD(2,2), &wsa) != 0) return;
#endif
        fd = static_cast<int>(::socket(AF_INET, SOCK_DGRAM, 0));
        if (fd < 0) return;
#ifdef _WIN32
        u_long mode = 1; ioctlsocket(fd, FIONBIO, &mode);
#else
        int flags = fcntl(fd, F_GETFL, 0);
        fcntl(fd, F_SETFL, flags | O_NONBLOCK);
#endif
        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_addr.s_addr = INADDR_ANY;
        addr.sin_port = htons(port);
        if (bind(fd, (sockaddr*)&addr, sizeof(addr)) < 0) {
            closesocket(fd); fd = -1; return;
        }
        running.store(true);
        worker = std::thread([this] {
            char tmp[4096];
            while (running.load()) {
                int n = static_cast<int>(
                    recvfrom(fd, tmp, sizeof(tmp), 0, nullptr, nullptr));
                if (n > 0) {
                    std::lock_guard lk(mtx);
                    buf.assign(tmp, static_cast<std::size_t>(n));
                    fresh = true;
                } else {
                    std::this_thread::sleep_for(std::chrono::milliseconds(1));
                }
            }
        });
    }

    void stop() {
        running.store(false);
        if (worker.joinable()) worker.join();
        if (fd >= 0) { closesocket(fd); fd = -1; }
#ifdef _WIN32
        WSACleanup();
#endif
    }

    // Move latest data out. Returns empty string if nothing new.
    std::string take() {
        std::lock_guard lk(mtx);
        if (!fresh) return {};
        fresh = false;
        return std::move(buf);
    }
};
static UdpBridge g_udp;

// ---- Lua C callbacks ----

int l_press(lua_State* L) {
    auto& slots = *static_cast<SlotArray*>(lua_touserdata(L, lua_upvalueindex(1)));
    int slot = static_cast<int>(lua_tointeger(L, lua_upvalueindex(2)));
    u32 bit = GetButtonBit(luaL_checkstring(L, 1));
    if (bit) { slots[slot].button_mask |= bit; slots[slot].last_update = NowUs(); }
    return 0;
}

int l_release(lua_State* L) {
    auto& slots = *static_cast<SlotArray*>(lua_touserdata(L, lua_upvalueindex(1)));
    int slot = static_cast<int>(lua_tointeger(L, lua_upvalueindex(2)));
    u32 bit = GetButtonBit(luaL_checkstring(L, 1));
    if (bit) { slots[slot].button_mask &= ~bit; slots[slot].last_update = NowUs(); }
    return 0;
}

int l_set_stick(lua_State* L) {
    auto& slots = *static_cast<SlotArray*>(lua_touserdata(L, lua_upvalueindex(1)));
    int slot = static_cast<int>(lua_tointeger(L, lua_upvalueindex(2)));
    const char* which = luaL_checkstring(L, 1);
    f32 x = static_cast<f32>(luaL_checknumber(L, 2));
    f32 y = static_cast<f32>(luaL_checknumber(L, 3));
    auto now = NowUs();
    if (std::strcmp(which, "left") == 0)
        { slots[slot].left_x = x; slots[slot].left_y = y; }
    else if (std::strcmp(which, "right") == 0)
        { slots[slot].right_x = x; slots[slot].right_y = y; }
    slots[slot].last_update = now;
    return 0;
}

int l_sleep(lua_State* L) {
    lua_pushinteger(L, luaL_checkinteger(L, 1));
    return lua_yield(L, 1);
}

int l_get_button(lua_State* L) {
    if (!g_engine || !g_engine->GetController()) { lua_pushboolean(L, 0); return 1; }
    u32 bit = GetButtonBit(luaL_checkstring(L, 1));
    auto buttons = g_engine->GetController()->GetNpadButtons();
    lua_pushboolean(L, (buttons.raw & bit) != 0);
    return 1;
}

int l_get_stick(lua_State* L) {
    if (!g_engine || !g_engine->GetController()) {
        lua_pushnumber(L, 0); lua_pushnumber(L, 0); return 2;
    }
    const char* which = luaL_checkstring(L, 1);
    auto sticks = g_engine->GetController()->GetSticks();
    f32 x = 0, y = 0;
    auto norm = [](s32 v) { return static_cast<f32>(v) / static_cast<f32>(HID_JOYSTICK_MAX); };
    if (std::strcmp(which, "left") == 0)
        { x = norm(sticks.left.x); y = norm(sticks.left.y); }
    else if (std::strcmp(which, "right") == 0)
        { x = norm(sticks.right.x); y = norm(sticks.right.y); }
    lua_pushnumber(L, x); lua_pushnumber(L, y);
    return 2;
}

int l_udp_bind(lua_State* L) {
    u16 port = static_cast<u16>(luaL_checkinteger(L, 1));
    g_udp.stop(); // close previous if any
    g_udp.start(port);
    lua_pushboolean(L, g_udp.running.load());
    return 1;
}

int l_udp_poll(lua_State* L) {
    auto data = g_udp.take();
    if (data.empty()) { lua_pushnil(L); return 1; }
    lua_pushlstring(L, data.data(), data.size());
    return 1;
}

int l_spawn(lua_State* L) {
    if (!g_engine) { lua_pushboolean(L, 0); return 1; }
    auto path = luaL_checkstring(L, 1);
    lua_pushboolean(L, g_engine->LoadScript(path));
    return 1;
}

int l_get_title_id(lua_State* L) {
    if (!g_engine) { lua_pushinteger(L, 0); return 1; }
    lua_pushinteger(L, static_cast<lua_Integer>(g_engine->GetProgramId()));
    return 1;
}

int l_get_game_name(lua_State* L) {
    if (!g_engine) { lua_pushstring(L, ""); return 1; }
    lua_pushstring(L, g_engine->GetGameName().c_str());
    return 1;
}

void register_bindings(lua_State* T, SlotArray* slots, int slot) {
    auto push_cclosure = [&](lua_CFunction fn) {
        lua_pushlightuserdata(T, slots);
        lua_pushinteger(T, slot);
        lua_pushcclosure(T, fn, 2);
    };
    push_cclosure(l_press);      lua_setglobal(T, "press");
    push_cclosure(l_release);    lua_setglobal(T, "release");
    push_cclosure(l_set_stick);  lua_setglobal(T, "set_stick");
    lua_pushcfunction(T, l_sleep);       lua_setglobal(T, "sleep");
    lua_pushcfunction(T, l_get_button);  lua_setglobal(T, "get_button");
    lua_pushcfunction(T, l_get_stick);   lua_setglobal(T, "get_stick");
    lua_pushcfunction(T, l_udp_bind);      lua_setglobal(T, "udp_bind");
    lua_pushcfunction(T, l_udp_poll);      lua_setglobal(T, "udp_poll");
    lua_pushcfunction(T, l_spawn);         lua_setglobal(T, "spawn");
    lua_pushcfunction(T, l_get_title_id);  lua_setglobal(T, "get_title_id");
    lua_pushcfunction(T, l_get_game_name); lua_setglobal(T, "get_game_name");
}

} // anonymous namespace

// ---- OverlayEngine --------------------------------------------------

OverlayEngine::OverlayEngine()  { g_engine = this; }
OverlayEngine::~OverlayEngine() {
    g_udp.stop();
    if (L) lua_close(static_cast<lua_State*>(L));
    g_engine = nullptr;
}

void OverlayEngine::RegisterController(
    EmulatedController* ctrl,
    std::array<OverlaySlotState, MAX_OVERLAY_SOURCES>& slots) {
    controller     = ctrl;
    overlay_slots  = &slots;
    if (!L) {
        L = luaL_newstate();
        luaL_openlibs(static_cast<lua_State*>(L));
    }
}

int OverlayEngine::AllocateSlot() {
    for (std::size_t i = 0; i < MAX_OVERLAY_SOURCES; ++i) {
        if (!(*overlay_slots)[i].active) {
            (*overlay_slots)[i] = OverlaySlotState{};
            (*overlay_slots)[i].active = true;
            (*overlay_slots)[i].last_update = NowUs();
            return static_cast<int>(i);
        }
    }
    return -1;
}

void OverlayEngine::ReleaseSlot(int slot) {
    if (slot >= 0 && static_cast<std::size_t>(slot) < MAX_OVERLAY_SOURCES)
        (*overlay_slots)[slot] = OverlaySlotState{};
}

bool OverlayEngine::LoadScript(const std::string& path) {
    if (!L || !overlay_slots) return false;
    auto* L_ = static_cast<lua_State*>(L);

    int slot = AllocateSlot();
    if (slot < 0) { LOG_ERROR(Input, "Overlay: no free slot for {}", path); return false; }

    // Create Lua thread (coroutine), load script file
    lua_State* T = lua_newthread(L_);
    if (luaL_loadfile(T, path.c_str()) != LUA_OK) {
        LOG_ERROR(Input, "Overlay: failed to load {}: {}", path, lua_tostring(T, -1));
        lua_pop(L_, 1); ReleaseSlot(slot); return false;
    }

    register_bindings(T, overlay_slots, slot);
    int thread_ref = luaL_ref(L_, LUA_REGISTRYINDEX);  // pops thread from main stack

    // First resume to start the script
    int status  = lua_resume(T, nullptr, 0);
    int wake_ms = 0;

    if (status == LUA_YIELD) {
        wake_ms = static_cast<int>(lua_tointeger(T, -1));
        lua_pop(T, 1);
    } else if (status == LUA_OK) {
        // Script returned without looping — wrap it
        LOG_WARNING(Input, "Overlay: {} exited; wrapping in loop", path);
        luaL_unref(L_, LUA_REGISTRYINDEX, thread_ref);
        ReleaseSlot(slot);

        T = lua_newthread(L_);
        std::string wrapped = "while true do local f, e = loadfile(\"" + path +
                              "\") if f then f() else error(e) end sleep(0) end";
        if (luaL_loadstring(T, wrapped.c_str()) != LUA_OK) {
            LOG_ERROR(Input, "Overlay: wrap error: {}", lua_tostring(T, -1));
            lua_pop(L_, 1); ReleaseSlot(slot); return false;
        }
        register_bindings(T, overlay_slots, slot);
        thread_ref = luaL_ref(L_, LUA_REGISTRYINDEX);
        status = lua_resume(T, nullptr, 0);
        if (status == LUA_YIELD) {
            wake_ms = static_cast<int>(lua_tointeger(T, -1));
            lua_pop(T, 1);
        } else if (status != LUA_OK) {
            LOG_ERROR(Input, "Overlay: {} error: {}", path, lua_tostring(T, -1));
            luaL_unref(L_, LUA_REGISTRYINDEX, thread_ref); ReleaseSlot(slot); return false;
        }
    } else {
        LOG_ERROR(Input, "Overlay: {} error: {}", path, lua_tostring(T, -1));
        luaL_unref(L_, LUA_REGISTRYINDEX, thread_ref); ReleaseSlot(slot); return false;
    }

    auto& s  = scripts.emplace_back();
    s.path   = path;
    s.slot   = slot;
    s.wake_ms = wake_ms;
    s.thread_ref = thread_ref;

    LOG_INFO(Input, "Overlay: loaded {} (slot {})", path, slot);
    return true;
}

void OverlayEngine::UnloadScript(const std::string& path) {
    auto* L_ = static_cast<lua_State*>(L);
    for (auto it = scripts.begin(); it != scripts.end(); ++it) {
        if (it->path == path) {
            luaL_unref(L_, LUA_REGISTRYINDEX, it->thread_ref);
            ReleaseSlot(it->slot);
            scripts.erase(it);
            LOG_INFO(Input, "Overlay: unloaded {}", path);
            return;
        }
    }
}

void OverlayEngine::ReloadAll() {
    std::vector<std::string> paths;
    for (auto& s : scripts) paths.push_back(s.path);
    for (auto& s : scripts) ReleaseSlot(s.slot);
    scripts.clear();
    for (auto& p : paths) LoadScript(p);
}

void OverlayEngine::ScanAndLoad(const std::filesystem::path& dir) {
    if (!std::filesystem::is_directory(dir)) {
        std::error_code ec;
        std::filesystem::create_directories(dir, ec);
        if (ec) {
            LOG_ERROR(Input, "Overlay: cannot create dir {}: {}", dir.string(), ec.message());
            return;
        }
        LOG_INFO(Input, "Overlay: created scripts directory: {}", dir.string());
    }
    // Collect .lua files, sorted for deterministic slot order
    std::vector<std::string> files;
    for (auto& entry : std::filesystem::directory_iterator(dir)) {
        if (entry.is_regular_file() && entry.path().extension() == ".lua")
            files.push_back(entry.path().string());
    }
    std::sort(files.begin(), files.end());
    for (auto& f : files)
        LoadScript(f);
}

void OverlayEngine::Tick(u32 dt_ms) {
    if (!L || scripts.empty()) return;
    auto* L_ = static_cast<lua_State*>(L);

    for (auto& script : scripts) {
        // Count down sleep
        if (script.wake_ms > 0) {
            if (dt_ms >= static_cast<u32>(script.wake_ms)) {
                script.wake_ms = 0;
            } else {
                script.wake_ms -= static_cast<int>(dt_ms);
                continue;
            }
        }

        // Get the Lua thread from registry and resume
        lua_rawgeti(L_, LUA_REGISTRYINDEX, script.thread_ref);
        auto* T = lua_tothread(L_, -1);

        int status = lua_resume(T, nullptr, 0);
        if (status == LUA_YIELD) {
            script.wake_ms = static_cast<int>(lua_tointeger(T, -1));
            lua_pop(T, 1);
        } else if (status == LUA_OK) {
            // Script completed — reload it
            LOG_INFO(Input, "Overlay: {} completed, reloading", script.path);
            std::string p = script.path;
            luaL_unref(L_, LUA_REGISTRYINDEX, script.thread_ref);
            ReleaseSlot(script.slot);
            script = ScriptState{}; // invalidate
            LoadScript(p);
        } else {
            LOG_ERROR(Input, "Overlay: {} error: {}", script.path, lua_tostring(T, -1));
            script.wake_ms = 1000; // back off
        }
        lua_pop(L_, 1); // pop thread from stack
    }

    // Remove invalidated entries
    scripts.erase(
        std::remove_if(scripts.begin(), scripts.end(),
                       [](const auto& s) { return s.slot < 0; }),
        scripts.end());
}

} // namespace Core::HID
