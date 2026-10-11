# client

客户端测试。

## 代理连通实测

`.github/workflows/proxy-check.yml`，手动运行。在 GitHub 的 Windows、Ubuntu、macOS 机器上，经服务器对外的代理访问 Google 204、gstatic 204 和 ipify，记录成功次数、用时和出口（只显示前两段）。

服务器地址和账号不写进仓库，在 Settings → Secrets and variables → Actions 里设置：

- `PROXY_URLS`：每行一个，`socks5h://用户:密码@域名:端口` 或 `http://用户:密码@域名:端口`
- `SINGBOX_CONFIG`（可选）：sing-box 客户端配置 JSON，带一个 `127.0.0.1:2080` 的 socks 入站

两个都没设时任务直接结束。本仓库是公开的，运行日志和摘要所有人可见，脚本只输出打码后的地址，不输出账号密码。
