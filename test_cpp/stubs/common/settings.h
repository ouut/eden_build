#pragma once
#include "common/common_types.h"

namespace Settings {

enum class Category : u32 { Overlay, Controls };

template <typename T>
struct Setting {
    T val{};
    Setting() = default;
    Setting(T v) : val(v) {}
    const T& GetValue() const { return val; }
    Setting& operator=(const T& v) { val = v; return *this; }
    operator bool() const { return static_cast<bool>(val); }
};

struct Values {
    Setting<bool> overlay_enabled{false};
    Setting<u16> overlay_port{26760};
};
extern Values values;

} // namespace Settings
