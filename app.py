"""
cpolar 隧道监控程序
功能：获取 cpolar 免费版的公网隧道地址，当检测到新隧道或地址变化时写入输出文件
用法：
    python app.py           # 单次运行
    python app.py -l        # 循环监控
    python app.py --loop    # 循环监控
"""

import random
import sys
import datetime
import argparse

import requests
from bs4 import BeautifulSoup
import json
import time
import os
import logging
import urllib3
from urllib.parse import urlparse

# 配置日志输出格式
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)

# 禁用 SSL 警告（cpolar dashboard 使用自签名证书）
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 全局变量
g_tunnels = {}  # 存储已知的隧道及其 URL
g_sleep = 1800  # 检查间隔（秒），默认 30 分钟
g_output_file = "output/urls.txt"  # 输出文件路径
g_schedule_time = None  # 定时推送时间，格式 "HH:MM"，如 "08:00"
g_ssh_config_file = None  # SSH config 文件路径，如 ~/.ssh/config
g_ssh_host_name = None  # 要修改的 Host 名字，如 SERVER


def remove_port_from_url(url):
    """
    从 URL 中移除端口号
    :param url: 原始 URL，如 https://example.cpolar.top:8080
    :return: 无端口的 URL，如 https://example.cpolar.top
    """
    parsed = urlparse(url)
    # 重新构造不带端口的 URL
    return f"{parsed.scheme}://{parsed.hostname}{parsed.path}"


def parse_tcp_url(url):
    """
    解析 tcp://host:port 格式的 URL
    :param url: 如 tcp://example.tcp.cpolar.cn:12345
    :return: (host, port) 如 ('example.tcp.cpolar.cn', '12345')
    """
    try:
        # 移除 tcp:// 前缀
        if url.startswith("tcp://"):
            url = url[6:]
        # 分割 host 和 port
        if ":" in url:
            host, port = url.rsplit(":", 1)
            return host, port
    except Exception as e:
        logging.error(f"Error parsing tcp url: {e}")
    return None, None


def update_ssh_config(host, port):
    """
    更新 SSH config 文件中指定 Host 的 HostName 和 Port
    :param host: 新的 HostName
    :param port: 新的 Port
    """
    if not g_ssh_config_file or not g_ssh_host_name:
        return

    # 展开 ~ 路径
    config_path = os.path.expanduser(g_ssh_config_file)

    if not os.path.isfile(config_path):
        logging.error(f"SSH config 文件不存在: {config_path}")
        return

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        new_lines = []
        in_target_host = False
        updated = False

        for line in lines:
            stripped = line.strip()

            # 检测 Host 行
            if stripped.startswith("Host "):
                host_names = stripped[5:].split()
                in_target_host = g_ssh_host_name in host_names
            elif in_target_host:
                # 在目标 Host 块内，替换 HostName 和 Port
                if stripped.startswith("HostName "):
                    line = f"  HostName {host}\n"
                    updated = True
                elif stripped.startswith("Port "):
                    line = f"  Port {port}\n"
                    updated = True

            new_lines.append(line)

        if updated:
            with open(config_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)
            logging.info(f"已更新 SSH config: {g_ssh_host_name} -> {host}:{port}")
        else:
            logging.warning(
                f"未在 SSH config 中找到 Host {g_ssh_host_name} 或未找到 HostName/Port 配置"
            )
    except Exception as e:
        logging.error(f"更新 SSH config 失败: {e}")


def write_to_output(tunnels):
    """
    将隧道地址写入输出文件
    :param tunnels: 隧道字典 {隧道名: [URL列表]}
    """
    try:
        # 确保输出目录存在
        output_dir = os.path.dirname(g_output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        with open(g_output_file, "w", encoding="utf-8") as f:
            f.write(
                f"# 更新时间: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            )
            for name, urls in tunnels.items():
                f.write(f"{name}:\n")
                for url in urls:
                    host, port = parse_tcp_url(url)
                    if host and port:
                        f.write(f"  HostName {host}\n")
                        f.write(f"  Port {port}\n")
                    else:
                        f.write(f"  {url}\n")
        logging.info(f"已写入输出文件: {g_output_file}")
    except Exception as e:
        logging.error(f"写入输出文件失败: {e}")


def read_config():
    """
    读取配置文件
    :return: cpolar 用户名和密码
    """
    global g_sleep, g_output_file, g_schedule_time, g_ssh_config_file, g_ssh_host_name

    # Docker 路径优先，本地路径备用
    config_path = "/app/config/config.json"
    if not os.path.isfile(config_path):
        config_path = "config/config.json"

    if os.path.isfile(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as file:
                config = json.load(file)
            username = config.get("username", "")
            password = config.get("password", "")
            g_sleep = config.get("sleep", 1800)
            g_output_file = config.get("output_file", "output/urls.txt")
            g_schedule_time = config.get("schedule_time", None)
            g_ssh_config_file = config.get("ssh_config_file", None)
            g_ssh_host_name = config.get("ssh_host_name", None)
        except Exception as e:
            logging.error(f"Error reading config file: {e}")
            sys.exit(1)
    else:
        logging.warning("Config file not found, please check!")
        sys.exit(1)

    return username, password


def dict_to_string(data):
    """
    将隧道字典转换为可读的字符串格式
    :param data: 隧道字典 {隧道名: [URL列表]}
    :return: 格式化的字符串
    """
    result = []
    for key, values in data.items():
        result.append(f"{key}:")
        for value in values:
            result.append(f"    {value}")
    return "\n".join(result)


def login(session, username, password):
    """
    登录 cpolar dashboard
    :param session: requests 会话对象
    :param username: cpolar 用户名
    :param password: cpolar 密码
    :return: 登录是否成功
    """
    try:
        # 获取登录页面
        login_page_url = "https://dashboard.cpolar.com/login"
        login_page_response = session.get(login_page_url, verify=False)
        login_page_soup = BeautifulSoup(login_page_response.text, "html.parser")

        # 解析登录表单
        login_form = login_page_soup.find("form")

        # 提取隐藏字段（如 CSRF token）
        hidden_inputs = login_form.find_all("input", type="hidden")
        form_data = {input.get("name"): input.get("value") for input in hidden_inputs}

        # 添加用户名和密码
        form_data["login"] = username
        form_data["password"] = password

        # 提交登录表单
        login_action_url = login_form.get("action")
        if not login_action_url.startswith("http"):
            login_action_url = "https://dashboard.cpolar.com" + login_action_url
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        response = session.post(
            login_action_url, data=form_data, headers=headers, verify=False
        )

        # 检查登录是否失败
        response_soup = BeautifulSoup(response.text, "html.parser")
        alert_error = response_soup.find("div", class_="alert alert-error")
        if alert_error:
            logging.error(f"Login failed: {alert_error.text.strip()}")
            return False

        return True
    except Exception as e:
        logging.error(f"Error during login: {e}")
        return False


def get_status_page(session):
    """
    获取 cpolar 隧道状态页面
    :param session: requests 会话对象
    :return: (页面HTML, 当前URL)
    """
    try:
        status_url = "https://dashboard.cpolar.com/status"
        response = session.get(status_url, verify=False)
        return response.text, response.url
    except Exception as e:
        logging.error(f"Error getting status page: {e}")
        return None, None


def parse_status_page(html):
    """
    解析状态页面，提取隧道名称为 ssh 的公网地址
    :param html: 页面 HTML
    :return: 隧道字典 {隧道名: [URL列表]}
    """
    tunnels = {}
    try:
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", {"class": "table table-sm"})

        if table:
            rows = table.find("tbody").find_all("tr")
            for row in rows:
                name_td = row.find("td")
                url_th = row.find("th")
                if name_td and url_th:
                    name = name_td.text.strip()
                    # 只提取隧道名为 ssh 的公网地址
                    if name != "ssh":
                        continue
                    a_tag = url_th.find("a")
                    if a_tag:
                        # URL 在 <a> 标签的文本中，如 tcp://example.tcp.cpolar.cn:12345
                        url = a_tag.text.strip()
                        if url:
                            if name in tunnels:
                                tunnels[name].append(url)
                            else:
                                tunnels[name] = [url]
    except Exception as e:
        logging.error(f"Error parsing status page: {e}")

    return tunnels


def is_schedule_time():
    """
    检查当前时间是否匹配定时推送时间
    :return: 是否到达定时推送时间
    """
    if not g_schedule_time:
        return False
    now = datetime.datetime.now().strftime("%H:%M")
    return now == g_schedule_time


def check_and_log_tunnels(session, username, password, last_schedule_log):
    """
    检查隧道状态并记录变化
    :param session: requests 会话对象
    :param username: cpolar 用户名
    :param password: cpolar 密码
    :param last_schedule_log: 上次定时记录日期
    :return: (是否成功, 更新后的 last_schedule_log)
    """
    global g_tunnels

    # 尝试获取状态页面
    status_page, current_url = get_status_page(session)
    if current_url and current_url.endswith("/status"):
        logging.info("Succeed to get status page")
    else:
        # 会话过期，需要重新登录
        logging.warning("Session expired, need to re-Login.")
        logged_in = login(session, username, password)
        if logged_in:
            logging.info("Login successful")
            status_page, current_url = get_status_page(session)
        else:
            logging.error("Login failed")
            return False, last_schedule_log

    if status_page:
        tunnels = parse_status_page(status_page)

        # 写入输出文件
        write_to_output(tunnels)

        for tunnel in tunnels:
            logging.info(f"隧道名称: {tunnel}, 公网地址: {tunnels[tunnel]}")
            # 检测新隧道
            if tunnel not in g_tunnels:
                g_tunnels[tunnel] = tunnels[tunnel]
                logging.info(f"检测到新的隧道: {tunnel}, 公网地址: {tunnels[tunnel]}")
                # 更新 SSH config
                for url in tunnels[tunnel]:
                    host, port = parse_tcp_url(url)
                    if host and port:
                        update_ssh_config(host, port)
            # 检测地址变化
            for url in tunnels[tunnel]:
                if url not in g_tunnels[tunnel]:
                    g_tunnels[tunnel] = tunnels[tunnel]
                    logging.info(f"隧道[{tunnel}]地址发生变化: {tunnels[tunnel]}")
                    # 更新 SSH config
                    host, port = parse_tcp_url(url)
                    if host and port:
                        update_ssh_config(host, port)
                    break

        # 定时记录：每天在指定时间记录所有隧道状态
        if g_schedule_time and is_schedule_time():
            today = datetime.datetime.now().strftime("%Y-%m-%d")
            if last_schedule_log != today:
                logging.info(f"定时记录隧道状态:\n{dict_to_string(g_tunnels)}")
                last_schedule_log = today
    else:
        logging.error("Failed to get status page")
        return False, last_schedule_log

    return True, last_schedule_log


def main():
    """
    主函数：获取隧道状态并记录变化
    默认单次运行，使用 -l 或 --loop 参数启用循环监控
    """
    global g_tunnels

    # 解析命令行参数
    parser = argparse.ArgumentParser(description="cpolar 隧道监控程序")
    parser.add_argument("-l", "--loop", action="store_true", help="启用循环监控模式")
    args = parser.parse_args()

    username, password = read_config()
    session = requests.Session()

    last_schedule_log = None  # 记录上次定时记录日期，避免重复

    logging.info(
        f"启动{'循环监控' if args.loop else '单次运行'}，检查间隔: {g_sleep}秒"
    )
    if g_schedule_time:
        logging.info(f"定时记录时间: {g_schedule_time}")
    logging.info(f"输出文件: {g_output_file}")

    if args.loop:
        # 循环监控模式
        while True:
            try:
                _, last_schedule_log = check_and_log_tunnels(
                    session, username, password, last_schedule_log
                )
                # 休眠一段时间后再次检查（添加随机抖动避免固定频率）
                time.sleep(g_sleep + random.randint(20, 120))
            except Exception as e:
                logging.error(f"Unexpected error: {e}")
                time.sleep(g_sleep + random.randint(20, 120))
    else:
        # 单次运行模式
        try:
            check_and_log_tunnels(session, username, password, last_schedule_log)
        except Exception as e:
            logging.error(f"Unexpected error: {e}")


if __name__ == "__main__":
    main()
