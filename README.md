# cpolar_url_checker

监控 cpolar 免费版隧道地址变化，自动更新 SSH config 文件。

## 功能

- 自动登录 cpolar dashboard 获取隧道状态
- 提取指定隧道（如 ssh）的公网地址
- 检测隧道地址变化并记录
- 自动更新 SSH config 文件中的 HostName 和 Port
- 支持定时记录和循环监控

## 安装依赖

```bash
pip install lxml requests bs4 charset_normalizer
```

## 使用方法

**单次运行：**
```bash
python app.py
```

**循环监控：**
```bash
python app.py -l
# 或
python app.py --loop
```

**Docker：**
```bash
# 构建镜像
docker build -t cpolar-checker .

# 单次运行
docker run -v $(pwd)/config:/app/config cpolar-checker

# 循环监控
docker run -v $(pwd)/config:/app/config cpolar-checker -l
```

## 配置

配置文件位于 `config/config.json`：

```json
{
    "username": "your_cpolar_username",
    "password": "your_cpolar_password",
    "sleep": 1800,
    "output_file": "output/urls.txt",
    "schedule_time": null,
    "ssh_config_file": null,
    "ssh_host_name": null
}
```

### 配置说明

| 字段              | 必填 | 说明                                                           |
| ----------------- | ---- | -------------------------------------------------------------- |
| `username`        | 是   | cpolar 账号                                                    |
| `password`        | 是   | cpolar 密码                                                    |
| `sleep`           | 否   | 检查间隔（秒），默认 1800，仅在 `-l`/`--loop` 模式下生效       |
| `output_file`     | 否   | 隧道地址输出文件路径，默认 `output/urls.txt`，设为 `null` 禁用 |
| `schedule_time`   | 否   | 定时记录时间，格式 `"HH:MM"`，如 `"08:00"`，设为 `null` 禁用   |
| `ssh_config_file` | 否   | SSH config 文件路径，如 `~/.ssh/config`，设为 `null` 禁用      |
| `ssh_host_name`   | 否   | 要修改的 Host 名字，如 `SERVER`，需配合 `ssh_config_file` 使用 |

### SSH Config 自动更新

配置：
```json
{
    "ssh_config_file": "~/.ssh/config",
    "ssh_host_name": "SERVER"
}
```

当检测到隧道地址变化时，会自动更新 SSH config 中对应 Host 的 `HostName` 和 `Port`。

## 致谢

本项目源代码借鉴自 [zcc0077/cpolar_url_checker](https://github.com/zcc0077/cpolar_url_checker.git)。

## License

MIT
