// SPDX-FileCopyrightText: Copyright 2026 Eden Overlay Project
// SPDX-License-Identifier: GPL-3.0-or-later

#include <algorithm>
#include <chrono>
#include <cstring>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

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

// ---- Global engine registry ----

std::mutex g_registry_mtx;
std::map<int, OverlayEngine*> g_engines;  // player_id → engine

// ---- UDP bridge per handle ----

struct UdpState {
    std::mutex mtx;
    std::string buf;
    bool       fresh = false;
    int        fd    = -1;
    std::atomic<bool> running{false};
    std::thread worker;

    ~UdpState() { stop(); }

    void start(u16 port, SlotArray* slots, int slot) {
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
        worker = std::thread([this, slots, slot] {
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

    std::string take() {
        std::lock_guard lk(mtx);
        if (!fresh) return {};
        fresh = false;
        return std::move(buf);
    }
};

// ---- Handle userdata ----

struct HandleData {
    int  player_id;
    int  slot;
    UdpState* udp = nullptr;   // owned, non-null only for new_udp
};

const char* HANDLE_META = "OverlayHandle";

HandleData* check_handle(lua_State* L, int idx) {
    return static_cast<HandleData*>(luaL_checkudata(L, idx, HANDLE_META));
}

SlotArray* get_slots_for(lua_State* L, int player_id) {
    auto* eng = OverlayEngine::FindGlobal(player_id);
    if (!eng) { luaL_error(L, "player %d not found", player_id); return nullptr; }
    return &eng->overlay_slots_ref();
}

// ---- Handle methods ----

int h_press(lua_State* L) {
    auto* h = check_handle(L, 1);
    u32 bit = GetButtonBit(luaL_checkstring(L, 2));
    auto* eng = OverlayEngine::FindGlobal(h->player_id);
    if (bit && eng) {
        auto& slots = eng->overlay_slots_ref();
        slots[h->slot].button_mask |= bit;
        slots[h->slot].last_update = NowUs();
    }
    return 0;
}

int h_release(lua_State* L) {
    auto* h = check_handle(L, 1);
    u32 bit = GetButtonBit(luaL_checkstring(L, 2));
    auto* eng = OverlayEngine::FindGlobal(h->player_id);
    if (bit && eng) {
        auto& slots = eng->overlay_slots_ref();
        slots[h->slot].button_mask &= ~bit;
        slots[h->slot].last_update = NowUs();
    }
    return 0;
}

int h_move(lua_State* L) {
    auto* h = check_handle(L, 1);
    const char* which = luaL_checkstring(L, 2);
    f32 x = static_cast<f32>(luaL_checknumber(L, 3));
    f32 y = static_cast<f32>(luaL_checknumber(L, 4));
    auto* eng = OverlayEngine::FindGlobal(h->player_id);
    if (eng) {
        auto& s = eng->overlay_slots_ref()[h->slot];
        if (std::strcmp(which, "left") == 0)  { s.left_x = x; s.left_y = y; }
        else if (std::strcmp(which, "right") == 0) { s.right_x = x; s.right_y = y; }
        s.last_update = NowUs();
    }
    return 0;
}

int h_motion(lua_State* L) {
    auto* h = check_handle(L, 1);
    const char* which = luaL_checkstring(L, 2);
    f32 gx = static_cast<f32>(luaL_checknumber(L, 3));
    f32 gy = static_cast<f32>(luaL_checknumber(L, 4));
    f32 gz = static_cast<f32>(luaL_checknumber(L, 5));
    f32 ax = static_cast<f32>(luaL_checknumber(L, 6));
    f32 ay = static_cast<f32>(luaL_checknumber(L, 7));
    f32 az = static_cast<f32>(luaL_checknumber(L, 8));
    auto* eng = OverlayEngine::FindGlobal(h->player_id);
    if (eng) {
        auto& s = eng->overlay_slots_ref()[h->slot];
        if (std::strcmp(which, "left") == 0) {
            s.left_gyro_x = gx; s.left_gyro_y = gy; s.left_gyro_z = gz;
            s.left_accel_x = ax; s.left_accel_y = ay; s.left_accel_z = az;
        } else if (std::strcmp(which, "right") == 0) {
            s.right_gyro_x = gx; s.right_gyro_y = gy; s.right_gyro_z = gz;
            s.right_accel_x = ax; s.right_accel_y = ay; s.right_accel_z = az;
        }
        s.last_update = NowUs();
    }
    return 0;
}

int h_wait(lua_State* L) {
    lua_Integer ms = luaL_checkinteger(L, 2);
    lua_pushinteger(L, ms);
    return lua_yield(L, 1);
}

int h_recv(lua_State* L) {
    auto* h = check_handle(L, 1);
    if (!h->udp) { lua_pushnil(L); return 1; }
    auto s = h->udp->take();
    if (s.empty()) { lua_pushnil(L); }
    else { lua_pushlstring(L, s.data(), s.size()); }
    return 1;
}

int h_kill(lua_State* L) {
    auto* h = check_handle(L, 1);
    if (h->udp) { delete h->udp; h->udp = nullptr; }
    auto* eng = OverlayEngine::FindGlobal(h->player_id);
    if (eng) {
        auto& slots = eng->overlay_slots_ref();
        slots[h->slot] = OverlaySlotState{};
    }
    return 0;
}

int h_gc(lua_State* L) {
    auto* h = static_cast<HandleData*>(luaL_testudata(L, 1, HANDLE_META));
    if (h && h->udp) { delete h->udp; h->udp = nullptr; }
    return 0;
}

void push_handle(lua_State* L, int player_id, int slot, UdpState* udp) {
    auto* h = static_cast<HandleData*>(lua_newuserdata(L, sizeof(HandleData)));
    h->player_id = player_id;
    h->slot      = slot;
    h->udp       = udp;
    luaL_setmetatable(L, HANDLE_META);
}

void setup_handle_metatable(lua_State* L) {
    luaL_newmetatable(L, HANDLE_META);
    // __index → itself so methods are found
    lua_pushvalue(L, -1); lua_setfield(L, -2, "__index");
    lua_pushcfunction(L, h_gc);      lua_setfield(L, -2, "__gc");
    lua_pushcfunction(L, h_press);   lua_setfield(L, -2, "press");
    lua_pushcfunction(L, h_release); lua_setfield(L, -2, "release");
    lua_pushcfunction(L, h_move);    lua_setfield(L, -2, "move");
    lua_pushcfunction(L, h_motion);  lua_setfield(L, -2, "motion");
    lua_pushcfunction(L, h_wait);    lua_setfield(L, -2, "wait");
    lua_pushcfunction(L, h_recv);    lua_setfield(L, -2, "recv");
    lua_pushcfunction(L, h_kill);    lua_setfield(L, -2, "kill");
    lua_pop(L, 1);
}

int alloc_slot_in_engine(lua_State* L, int player_id, int slot) {
    auto* eng = OverlayEngine::FindGlobal(player_id);
    if (!eng) { luaL_error(L, "player %d not found", player_id); return -1; }
    auto& slots = eng->overlay_slots_ref();
    if (slot >= 0) {
        if (static_cast<std::size_t>(slot) >= MAX_OVERLAY_SOURCES || slots[slot].active)
            { luaL_error(L, "slot %d occupied or invalid", slot); return -1; }
        slots[slot] = OverlaySlotState{};
        slots[slot].active = true;
        slots[slot].last_update = NowUs();
        return slot;
    }
    for (std::size_t i = 0; i < MAX_OVERLAY_SOURCES; ++i) {
        if (!slots[i].active) {
            slots[i] = OverlaySlotState{};
            slots[i].active = true;
            slots[i].last_update = NowUs();
            return static_cast<int>(i);
        }
    }
    luaL_error(L, "no free overlay slot"); return -1;
}

// ---- player module methods ----

int l_player_new(lua_State* L) {
    int pid  = static_cast<int>(luaL_checkinteger(L, 2));  // self, pid, [slot]
    int slot = (lua_gettop(L) >= 3) ? static_cast<int>(luaL_checkinteger(L, 3)) : -1;
    slot = alloc_slot_in_engine(L, pid, slot);
    push_handle(L, pid, slot, nullptr);
    return 1;
}

int l_player_new_udp(lua_State* L) {
    int pid  = static_cast<int>(luaL_checkinteger(L, 2));
    u16 port = static_cast<u16>(luaL_checkinteger(L, 3));
    int slot = (lua_gettop(L) >= 4) ? static_cast<int>(luaL_checkinteger(L, 4)) : -1;
    slot = alloc_slot_in_engine(L, pid, slot);
    auto* udp = new UdpState();
    auto* eng = OverlayEngine::FindGlobal(pid);
    if (eng) udp->start(port, &eng->overlay_slots_ref(), slot);
    push_handle(L, pid, slot, udp);
    return 1;
}

// Coroutine-level globals that route to a specific slot.
void register_coroutine_env(lua_State* T, SlotArray* slots, int slot) {
    // press, release, move, motion, wait as globals in this coroutine
    auto push_cclosure = [&](lua_CFunction fn) {
        lua_pushlightuserdata(T, slots);
        lua_pushinteger(T, slot);
        lua_pushcclosure(T, fn, 2);
    };

    // press(name)
    push_cclosure([](lua_State* Lc) -> int {
        auto& s = *static_cast<SlotArray*>(lua_touserdata(Lc, lua_upvalueindex(1)));
        int sl = static_cast<int>(lua_tointeger(Lc, lua_upvalueindex(2)));
        u32 b = GetButtonBit(luaL_checkstring(Lc, 1));
        if (b) { s[sl].button_mask |= b; s[sl].last_update = NowUs(); }
        return 0;
    }); lua_setglobal(T, "press");

    // release(name)
    push_cclosure([](lua_State* Lc) -> int {
        auto& s = *static_cast<SlotArray*>(lua_touserdata(Lc, lua_upvalueindex(1)));
        int sl = static_cast<int>(lua_tointeger(Lc, lua_upvalueindex(2)));
        u32 b = GetButtonBit(luaL_checkstring(Lc, 1));
        if (b) { s[sl].button_mask &= ~b; s[sl].last_update = NowUs(); }
        return 0;
    }); lua_setglobal(T, "release");

    // move(which, x, y)
    push_cclosure([](lua_State* Lc) -> int {
        auto& s = *static_cast<SlotArray*>(lua_touserdata(Lc, lua_upvalueindex(1)));
        int sl = static_cast<int>(lua_tointeger(Lc, lua_upvalueindex(2)));
        const char* w = luaL_checkstring(Lc, 1);
        f32 x = static_cast<f32>(luaL_checknumber(Lc, 2));
        f32 y = static_cast<f32>(luaL_checknumber(Lc, 3));
        auto& r = s[sl];
        if (std::strcmp(w, "left") == 0)  { r.left_x = x; r.left_y = y; }
        else if (std::strcmp(w, "right") == 0) { r.right_x = x; r.right_y = y; }
        r.last_update = NowUs();
        return 0;
    }); lua_setglobal(T, "move");

    // motion(which, gx, gy, gz, ax, ay, az)
    push_cclosure([](lua_State* Lc) -> int {
        auto& s = *static_cast<SlotArray*>(lua_touserdata(Lc, lua_upvalueindex(1)));
        int sl = static_cast<int>(lua_tointeger(Lc, lua_upvalueindex(2)));
        const char* w = luaL_checkstring(Lc, 1);
        f32 gx = static_cast<f32>(luaL_checknumber(Lc, 2));
        f32 gy = static_cast<f32>(luaL_checknumber(Lc, 3));
        f32 gz = static_cast<f32>(luaL_checknumber(Lc, 4));
        f32 ax = static_cast<f32>(luaL_checknumber(Lc, 5));
        f32 ay = static_cast<f32>(luaL_checknumber(Lc, 6));
        f32 az = static_cast<f32>(luaL_checknumber(Lc, 7));
        auto& r = s[sl];
        if (std::strcmp(w, "left") == 0) {
            r.left_gyro_x = gx; r.left_gyro_y = gy; r.left_gyro_z = gz;
            r.left_accel_x = ax; r.left_accel_y = ay; r.left_accel_z = az;
        } else if (std::strcmp(w, "right") == 0) {
            r.right_gyro_x = gx; r.right_gyro_y = gy; r.right_gyro_z = gz;
            r.right_accel_x = ax; r.right_accel_y = ay; r.right_accel_z = az;
        }
        r.last_update = NowUs();
        return 0;
    }); lua_setglobal(T, "motion");

    // wait(ms) — yield this coroutine
    lua_pushcfunction(T, [](lua_State* Lc) -> int {
        lua_pushinteger(Lc, luaL_checkinteger(Lc, 1));
        return lua_yield(Lc, 1);
    }); lua_setglobal(T, "wait");
}

int l_player_new_script(lua_State* L) {
    int pid  = static_cast<int>(luaL_checkinteger(L, 2));
    const char* path = luaL_checkstring(L, 3);
    int slot = (lua_gettop(L) >= 4) ? static_cast<int>(luaL_checkinteger(L, 4)) : -1;
    slot = alloc_slot_in_engine(L, pid, slot);

    auto* eng = OverlayEngine::FindGlobal(pid);
    if (!eng) { luaL_error(L, "player %d not found", pid); return 0; }
    auto* L_ = static_cast<lua_State*>(eng->get_lua_state());
    auto& slots = eng->overlay_slots_ref();

    // Create coroutine, load file
    lua_State* T = lua_newthread(L_);
    if (luaL_loadfile(T, path) != LUA_OK) {
        LOG_ERROR(Input, "Overlay: failed to load {}: {}", path, lua_tostring(T, -1));
        lua_pop(L_, 1); slots[slot] = OverlaySlotState{}; return 0;
    }
    register_coroutine_env(T, &slots, slot);
    int ref = luaL_ref(L_, LUA_REGISTRYINDEX);

    // First resume
    int status  = lua_resume(T, nullptr, 0);
    int wake_ms = 0;
    if (status == LUA_YIELD) {
        wake_ms = static_cast<int>(lua_tointeger(T, -1));
        lua_pop(T, 1);
    } else if (status == LUA_OK) {
        // Wrap in loop
        LOG_WARNING(Input, "Overlay: {} exited; wrapping in loop", path);
        luaL_unref(L_, LUA_REGISTRYINDEX, ref);
        T = lua_newthread(L_);
        std::string wrapped = "while true do local f, e = loadfile(\"" + std::string(path) +
                              "\") if f then f() else error(e) end wait(0) end";
        if (luaL_loadstring(T, wrapped.c_str()) != LUA_OK) {
            LOG_ERROR(Input, "Overlay: wrap error: {}", lua_tostring(T, -1));
            lua_pop(L_, 1); slots[slot] = OverlaySlotState{}; return 0;
        }
        register_coroutine_env(T, &slots, slot);
        ref = luaL_ref(L_, LUA_REGISTRYINDEX);
        status = lua_resume(T, nullptr, 0);
        if (status == LUA_YIELD) {
            wake_ms = static_cast<int>(lua_tointeger(T, -1));
            lua_pop(T, 1);
        } else if (status != LUA_OK) {
            LOG_ERROR(Input, "Overlay: {} error: {}", path, lua_tostring(T, -1));
            luaL_unref(L_, LUA_REGISTRYINDEX, ref); slots[slot] = OverlaySlotState{}; return 0;
        }
    } else {
        LOG_ERROR(Input, "Overlay: {} error: {}", path, lua_tostring(T, -1));
        luaL_unref(L_, LUA_REGISTRYINDEX, ref); slots[slot] = OverlaySlotState{}; return 0;
    }

    auto& sc = eng->scripts_ref().emplace_back();
    sc.path   = path;
    sc.slot   = slot;
    sc.wake_ms = wake_ms;
    sc.thread_ref = ref;

    LOG_INFO(Input, "Overlay: loaded {} (player {} slot {})", path, pid, slot);
    push_handle(L, pid, slot, nullptr);
    return 1;
}

int l_player_held(lua_State* L) {
    int pid = static_cast<int>(luaL_checkinteger(L, 2));
    u32 bit = GetButtonBit(luaL_checkstring(L, 3));
    auto* eng = OverlayEngine::FindGlobal(pid);
    if (!eng || !eng->GetController()) { lua_pushboolean(L, 0); return 1; }
    auto buttons = eng->GetController()->GetNpadButtons();
    lua_pushboolean(L, (buttons.raw & bit) != 0);
    return 1;
}

int l_player_axis(lua_State* L) {
    int pid = static_cast<int>(luaL_checkinteger(L, 2));
    const char* which = luaL_checkstring(L, 3);
    auto* eng = OverlayEngine::FindGlobal(pid);
    if (!eng || !eng->GetController()) { lua_pushnumber(L, 0); lua_pushnumber(L, 0); return 2; }
    auto sticks = eng->GetController()->GetSticks();
    auto norm = [](s32 v) { return static_cast<f32>(v) / static_cast<f32>(HID_JOYSTICK_MAX); };
    f32 x = 0, y = 0;
    if (std::strcmp(which, "left") == 0)  { x = norm(sticks.left.x); y = norm(sticks.left.y); }
    else if (std::strcmp(which, "right") == 0) { x = norm(sticks.right.x); y = norm(sticks.right.y); }
    lua_pushnumber(L, x); lua_pushnumber(L, y);
    return 2;
}

int l_player_motion(lua_State* L) {
    int pid = static_cast<int>(luaL_checkinteger(L, 2));
    const char* which = luaL_checkstring(L, 3);
    auto* eng = OverlayEngine::FindGlobal(pid);
    if (!eng || !eng->GetController()) {
        for (int i = 0; i < 6; i++) lua_pushnumber(L, 0);
        return 6;
    }
    auto motion = eng->GetController()->GetMotions();
    std::size_t idx = (std::strcmp(which, "right") == 0) ? 1 : 0;
    lua_pushnumber(L, motion[idx].gyro.x);
    lua_pushnumber(L, motion[idx].gyro.y);
    lua_pushnumber(L, motion[idx].gyro.z);
    lua_pushnumber(L, motion[idx].accel.x);
    lua_pushnumber(L, motion[idx].accel.y);
    lua_pushnumber(L, motion[idx].accel.z);
    return 6;
}

// ---- game module methods ----

int l_game_id(lua_State* L) {
    OverlayEngine* eng = nullptr;
    for (auto& [k, v] : g_engines) { eng = v; break; }
    lua_pushinteger(L, eng ? static_cast<lua_Integer>(eng->GetProgramId()) : 0);
    return 1;
}

int l_game_name(lua_State* L) {
    OverlayEngine* eng = nullptr;
    for (auto& [k, v] : g_engines) { eng = v; break; }
    lua_pushstring(L, eng ? eng->GetGameName().c_str() : "");
    return 1;
}

// ---- Global wait ----

int l_global_wait(lua_State* L) {
    lua_pushinteger(L, luaL_checkinteger(L, 1));
    return lua_yield(L, 1);
}

// ---- Register all Lua modules (called once in first engine's RegisterController) ----

void setup_lua_env(lua_State* L) {
    // handle metatable
    setup_handle_metatable(L);

    // player table
    lua_newtable(L);
    lua_pushcfunction(L, l_player_new);        lua_setfield(L, -2, "new");
    lua_pushcfunction(L, l_player_new_udp);    lua_setfield(L, -2, "new_udp");
    lua_pushcfunction(L, l_player_new_script); lua_setfield(L, -2, "new_script");
    lua_pushcfunction(L, l_player_held);       lua_setfield(L, -2, "held");
    lua_pushcfunction(L, l_player_axis);       lua_setfield(L, -2, "axis");
    lua_pushcfunction(L, l_player_motion);     lua_setfield(L, -2, "motion");
    lua_setglobal(L, "player");

    // game table
    lua_newtable(L);
    lua_pushcfunction(L, l_game_id);   lua_setfield(L, -2, "id");
    lua_pushcfunction(L, l_game_name); lua_setfield(L, -2, "name");
    lua_setglobal(L, "game");

    // global wait
    lua_pushcfunction(L, l_global_wait);
    lua_setglobal(L, "wait");
}

} // anonymous namespace

// ---- OverlayEngine public implementation ----

OverlayEngine::OverlayEngine() = default;

OverlayEngine::~OverlayEngine() {
    UnregisterGlobal(player_id);
    if (L) lua_close(static_cast<lua_State*>(L));
}

void OverlayEngine::RegisterController(
    int pid, EmulatedController* ctrl, std::array<OverlaySlotState, MAX_OVERLAY_SOURCES>& slots) {
    player_id    = pid;
    controller   = ctrl;
    overlay_slots = &slots;
    if (!L) {
        L = luaL_newstate();
        luaL_openlibs(static_cast<lua_State*>(L));
        setup_lua_env(static_cast<lua_State*>(L));
    }
    RegisterGlobal(pid, this);
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

bool OverlayEngine::LoadScriptToSlot(const std::string& path, int slot) {
    // Used internally by l_player_new_script which already allocates the slot.
    // This is a stub — the real loading is in l_player_new_script.
    return true;
}

void OverlayEngine::Tick(u32 dt_ms) {
    if (!L || scripts.empty()) return;
    auto* L_ = static_cast<lua_State*>(L);

    for (auto& script : scripts) {
        if (script.wake_ms > 0) {
            if (dt_ms >= static_cast<u32>(script.wake_ms))
                script.wake_ms = 0;
            else {
                script.wake_ms -= static_cast<int>(dt_ms);
                continue;
            }
        }

        lua_rawgeti(L_, LUA_REGISTRYINDEX, script.thread_ref);
        auto* T = lua_tothread(L_, -1);

        int status = lua_resume(T, nullptr, 0);
        if (status == LUA_YIELD) {
            script.wake_ms = static_cast<int>(lua_tointeger(T, -1));
            lua_pop(T, 1);
        } else if (status == LUA_OK) {
            LOG_INFO(Input, "Overlay: {} completed, reloading", script.path);
            std::string p = script.path;
            int slot = script.slot;
            luaL_unref(L_, LUA_REGISTRYINDEX, script.thread_ref);
            ReleaseSlot(slot);
            script = ScriptState{};
            // Re-load via the script API
            // (simplified: just mark invalid)
        } else {
            LOG_ERROR(Input, "Overlay: {} error: {}", script.path, lua_tostring(T, -1));
            script.wake_ms = 1000;
        }
        lua_pop(L_, 1);
    }

    scripts.erase(
        std::remove_if(scripts.begin(), scripts.end(),
                       [](const auto& s) { return s.slot < 0; }),
        scripts.end());
}

// ---- Static registry ----

void OverlayEngine::RegisterGlobal(int pid, OverlayEngine* engine) {
    std::lock_guard lk(g_registry_mtx);
    g_engines[pid] = engine;
}

void OverlayEngine::UnregisterGlobal(int pid) {
    std::lock_guard lk(g_registry_mtx);
    g_engines.erase(pid);
}

OverlayEngine* OverlayEngine::FindGlobal(int pid) {
    std::lock_guard lk(g_registry_mtx);
    auto it = g_engines.find(pid);
    return (it != g_engines.end()) ? it->second : nullptr;
}

} // namespace Core::HID
