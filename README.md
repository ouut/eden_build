# Eden DSU Build

基于 [Eden-CI/Workflow](https://github.com/Eden-CI/Workflow) 的 CI 构建仓库，增加 DSU（Cemuhook）协议完整手柄支持。

## DSU 协议支持

在官方构建流程中增加一个 patch 步骤：将 `enable_udp_controller` 默认值从 `false` 改为 `true`。

改动位于 `.github/workflows/build.yml` 的 clone job，在拉取 Eden 源码后、构建前执行：

```
git clone Eden → sed 改 settings.h → 全平台构建
```

## 构建

手动触发：

1. 进入 [Actions](../../actions) 页面
2. 选择 **"DSU Build"**
3. 点击 **Run workflow**
4. 等待三平台（macOS / Windows / Linux）构建完成
5. 构建产物自动发布到 [Releases](../../releases) 页面

## DSU 使用方式

1. 在手机安装 DSU Server（支持 Cemuhook 协议，UDP 26760 端口）
2. 模拟器控制器设置中选择 "UDP Controller" 作为输入设备
3. 填入 DSU Server IP 和端口（默认 26760）
4. 按键、摇杆、体感同时生效

## 协议参考

- [cemuhook-protocol](https://github.com/v1993/cemuhook-protocol)

## 许可

GPLv3。基于 [Eden-CI/Workflow](https://github.com/Eden-CI/Workflow)。
