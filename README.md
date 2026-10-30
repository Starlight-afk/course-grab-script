# 教务抢课脚本（course-grab-script）

> ⚠️ **声明：本项目仅用于 Python 网络编程学习与研究。脚本基于本人账号模拟教务系统选课流程，仅为技术演示，不保证可用性。请勿在实际教务系统中使用，因使用本脚本导致的账号风险、学校纪律处分等一切后果由使用者自行承担。**

## 项目简介

基于 Python `requests` + `BeautifulSoup` 的教务系统公选课选课流程演示脚本：

- 模拟学生端登录流程（base64 加密参数）
- 自动拉取公选课列表，按学分优先级排序
- 目标学分自动判定：优先选 2 学分课程，抢不到则改选 1 学分课程，累计修满目标学分即停止
- 内置请求限速（1.5~5 秒随机间隔），避免高频请求
- 支持定时开抢、最长运行时长、调试模式
- 本地日志记录（`grab_log.txt`）

## 环境要求

- Python 3.8+
- 依赖：`requests`、`beautifulsoup4`、`lxml`

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

打开 `yinchuankejixueyuan.py`，修改顶部「配置区」：

| 配置项 | 说明 |
| --- | --- |
| `BASE_URL` | 教务系统地址（学生端） |
| `USERNAME` / `PASSWORD` | 本人教务系统账号。建议通过运行时输入读取，**切勿把真实账号密码提交到公开仓库** |
| `TARGET_CREDIT` | 目标总学分 |
| `PREFER_CREDITS` | 选课优先级（先 2 学分，后 1 学分） |
| `COURSE_2CREDIT` / `COURSE_1CREDIT` | 课程候选名单（辅助识别，非必需，脚本会按学分自动筛选） |
| `MIN_SLEEP` / `MAX_SLEEP` | 请求间隔范围（秒） |

### 3. 运行

```bash
python yinchuankejixueyuan.py                       # 立即开始
python yinchuankejixueyuan.py --start "12:00:00"    # 等到 12:00:00 整开始
python yinchuankejixueyuan.py --duration 60         # 最多运行 60 分钟后停止
python yinchuankejixueyuan.py --debug               # 调试模式（打印详细日志）
```

## 免责声明

- 脚本仅用于学习 `requests` / `BeautifulSoup` 等网络编程技术；
- 请使用本人账号，遵守学校教务系统使用规则；
- 禁止高并发、大规模自动化请求，由此产生的账号封禁等风险自行承担；
- 本项目不提供任何抢课成功率保证，选课结果以教务系统为准。

## 许可证

本项目使用 MIT License，详见 [LICENSE](LICENSE) 文件。

## 贡献

欢迎提交 Issue 交流技术问题。不接受用于增强自动化抢课能力的改动。
