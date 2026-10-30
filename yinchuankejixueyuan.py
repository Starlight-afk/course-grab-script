# -*- coding: utf-8 -*-
"""
银川科技学院 · 强智教务系统 · 公选课自动抢课脚本
================================================
目标：选课期内自动抢公共选修课，优先选 2 学分课程，抢不到则改选 1 学分课程，
      累计修满 2 学分即停止（可选 1 门 2 分课，或 2 门 1 分课）。

适用：2026-2027-1 学期线上公共选修课（选课时间 10月30日12:00 - 11月02日12:00）

依赖：python3 + requests + beautifulsoup4 + lxml
安装：pip install requests beautifulsoup4 lxml

用法：
    python yinchuankejixueyuan.py                     # 立即开始抢
    python yinchuankejixueyuan.py --start "12:00:00"  # 等到 12:00:00 整开始抢
    python yinchuankejixueyuan.py --duration 60       # 最多抢 60 分钟后停止
    python yinchuankejixueyuan.py --debug             # 打印详细调试信息

注意：
    1. 选课前请在浏览器里确认教务系统能正常登录（初始密码为学号）。
    2. 脚本使用本人账号，仅用于本人选课，请勿高并发轰炸服务器。
    3. 选课一旦提交成功不能退选、不能改选，请确认课程后再抢。
"""

import base64
import json
import random
import re
import sys
import time
import datetime
import argparse

import requests
from bs4 import BeautifulSoup

# ================= 配置区（按需修改） =================

BASE_URL = 'http://jw.ycust.com/yckjxy_jsxsd'   # 教务系统地址（学生端）
USERNAME = '输入学号'  # 学号（必填）
PASSWORD = '输入密码'    # 密码（必填，初始密码为学号，请用修改后的密码）

TARGET_CREDIT = 2.0          # 目标总学分（本学期最多 2 学分）
PREFER_CREDITS = [2.0, 1.0]  # 选课优先级：先 2 学分，后 1 学分
MIN_SLEEP = 1.5              # 每轮最小间隔（秒），避免请求过快
MAX_SLEEP = 5.0              # 每轮最大间隔（秒）

# 2 分课 / 1 分课候选名单（来自"2026-2027-1学期线上课程开课列表"，用于辅助识别；
# 脚本也会直接从系统课程列表按学分自动筛选，名单非必需）
COURSE_2CREDIT = ['数学与科技进步', '现代办公软件高级实用技能', '心理健康与情商修炼']
COURSE_1CREDIT = [
    '大话机器人', '探秘身边的材料——材料与社会', '固体废物处理与处置',
    '有趣的Photoshop从入门到精通', '人工智能与创新设计', '人工智能与科学之美',
    '人工智能前沿与产业趋势', '人人学点营销学', '西方经济学的奇妙世界',
    '《易经》的政治智慧', '逻辑思维与写作', '孙子兵法鉴赏', '中华传统文化集萃',
    '吃货的营养学修养', '带你听懂中国传统音乐', '健康与健康能力',
    '山水画鉴赏与实践', '视觉传达设计思维与方法', '审美分析',
    '一画一课：红色美术经典赏析之革命历史篇', '创意、视觉、营销、传播—理解广告',
    '大学生职业素养提升', '职场菜鸟礼仪指南',
]

# ================= 以下一般无需修改 =================

UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')


def log(msg, debug=False):
    ts = datetime.datetime.now().strftime('%H:%M:%S')
    line = '[%s] %s' % (ts, msg)
    print(line, flush=True)
    try:
        with open('grab_log.txt', 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def make_session():
    s = requests.Session()
    s.headers.update({'User-Agent': UA})
    return s


def login(session):
    """登录教务系统。返回 True 表示成功。"""
    # 1. 打开登录页，获取 JSESSIONID
    try:
        r = session.get(BASE_URL + '/', timeout=20)
    except Exception as e:
        log('连接教务系统失败: %s' % e)
        return False

    # 2. 构造 encoded = base64(账号)%%%base64(密码)
    account_b64 = base64.b64encode(USERNAME.encode('utf-8')).decode('ascii')
    pwd_b64 = base64.b64encode(PASSWORD.encode('utf-8')).decode('ascii')
    encoded = account_b64 + '%%%' + pwd_b64

    data = {
        'userAccount': USERNAME,
        'userPassword': PASSWORD,
        'encoded': encoded,
        'jzmmid': '1',
    }
    try:
        r = session.post(BASE_URL + '/xk/LoginToXk', data=data, timeout=20)
    except Exception as e:
        log('登录请求失败: %s' % e)
        return False

    # 3. 登录成功会 302 到学生个人中心主框架页
    if '用户名或密码错误' in r.text:
        log('登录失败：用户名或密码错误，请检查学号/密码')
        return False
    if '学生个人中心' in r.text or 'xsMain.jsp' in (r.url or ''):
        log('登录成功：%s' % USERNAME)
        return True

    # 兜底：访问主框架页判断
    try:
        r2 = session.get(BASE_URL + '/framework/xsMain.jsp', timeout=20)
        text = r2.text
    except Exception as e:
        log('登录后校验失败: %s' % e)
        return False
    if '学生个人中心' in text or ('menu' in text.lower() and '<frame' in text.lower()):
        log('登录成功：%s' % USERNAME)
        return True
    log('登录可能失败：主页面内容异常（长度 %d），请检查账号密码或网络' % len(text))
    return False


def get_select_rounds(session):
    """获取选课中心轮次列表，返回 [(名称, 链接, jx0502zbid), ...]"""
    rounds = []
    try:
        r = session.get(BASE_URL + '/xsxk/xklc_list', timeout=20)
        soup = BeautifulSoup(r.text, 'lxml')
    except Exception as e:
        log('获取选课中心失败: %s' % e)
        return rounds
    for a in soup.find_all('a', href=True):
        href = a['href']
        name = a.get_text(strip=True)
        m = re.search(r'jx0502zbid=([0-9A-Za-z]+)', href)
        if m and name:
            rounds.append((name, href, m.group(1)))
    # 若链接文本为空，尝试从所在行的单元格取名称
    if not rounds:
        for tr in soup.find_all('tr'):
            cells = [td.get_text(strip=True) for td in tr.find_all('td')]
            a = tr.find('a', href=True)
            if a and cells:
                m = re.search(r'jx0502zbid=([0-9A-Za-z]+)', a['href'])
                if m:
                    name = next((c for c in cells if c and len(c) > 1), '选课轮次')
                    rounds.append((name, a['href'], m.group(1)))
    return rounds


def enter_select_round(session, zbid, debug=False):
    """进入指定选课轮次，建立选课上下文。"""
    url = BASE_URL + '/xsxk/xsxk_index?jx0502zbid=' + zbid
    try:
        r = session.get(url, timeout=20)
        if debug:
            log('进入轮次页面长度: %d' % len(r.text))
        return True
    except Exception as e:
        log('进入选课轮次失败: %s' % e)
        return False


def fetch_courses(session, debug=False):
    """
    从公选课 DataTable 接口拉取当前可选课程列表。
    返回 [{name, credit, remain, course_id, raw}, ...]
    """
    # 先进一次公选课入口，建立选课上下文（轮次开放后有效）
    try:
        session.get(BASE_URL + '/xsxkkc/comeInGgxxkxk', timeout=20)
    except Exception:
        pass

    url = BASE_URL + '/xsxkkc/xsxkGgxxkxk'
    data = {
        'kcxx': '', 'skls': '', 'skxq': '', 'skjc': '',
        'sfym': 'false', 'sfct': 'false', 'szjylb': '',
        'sEcho': '1', 'iColumns': '13', 'sColumns': '',
        'iDisplayStart': '0', 'iDisplayLength': '500',
        'mDataProp_0': 'kch', 'mDataProp_1': 'kcmc', 'mDataProp_2': 'newszkcflmc',
        'mDataProp_3': 'xf', 'mDataProp_4': 'skls', 'mDataProp_5': 'sksj',
        'mDataProp_6': 'skdd', 'mDataProp_7': 'ktmc', 'mDataProp_8': 'xkrs',
        'mDataProp_9': 'syrs', 'mDataProp_10': 'ctsm', 'mDataProp_11': 'szkcflmc',
        'mDataProp_12': 'czOper',
    }
    try:
        r = session.post(url, data=data, timeout=20)
    except Exception as e:
        log('获取课程列表失败: %s' % e)
        return []

    try:
        payload = r.json()
    except Exception:
        if debug:
            log('课程列表返回非 JSON，前 300 字符：%s' % r.text[:300])
        return []

    aa = payload.get('aaData') or []
    courses = []
    for row in aa:
        if isinstance(row, dict):
            name = row.get('kcmc') or row.get('kcm') or ''
            credit = row.get('xf') or 0
            remain = row.get('syrs')
            cid = row.get('jx0404id') or row.get('jxb_id') or ''
            # 操作列里通常含 jx0404id
            if not cid:
                oper = row.get('czOper') or ''
                m = re.search(r'jx0404id=([0-9A-Za-z]+)', str(oper))
                if m:
                    cid = m.group(1)
        else:
            # 数组型行：按 mDataProp 顺序 0=kch 1=kcmc 2=... 3=xf 9=syrs 12=czOper
            def get(i):
                return row[i] if i < len(row) else None
            name = str(get(1) or '')
            credit = get(3) or 0
            remain = get(9)
            oper = str(get(12) or '')
            m = re.search(r'jx0404id=([0-9A-Za-z]+)', oper)
            cid = m.group(1) if m else ''
        try:
            credit = float(credit)
        except Exception:
            credit = 0.0
        if name:
            courses.append({'name': name, 'credit': credit, 'remain': remain,
                            'course_id': cid, 'raw': row})
    return courses


def select_course(session, course, debug=False):
    """提交选课。返回 (成功, 信息)"""
    cid = course.get('course_id')
    if not cid:
        return False, '无课程ID'
    url = BASE_URL + '/xsxkkc/ggxxkxkOper'
    params = {'xkzy': '', 'trjf': '', 'jx0404id': cid}
    try:
        r = session.get(url, params=params, timeout=20)
        txt = r.text.strip()
    except Exception as e:
        return False, '请求异常: %s' % e

    try:
        res = r.json()
        ok = bool(res.get('success'))
        msg = res.get('message') or res.get('msg') or json.dumps(res, ensure_ascii=False)
        return ok, msg
    except Exception:
        # 非 JSON：可能是 HTML 页（成功跳转）或错误页
        if '<' not in txt[:50]:
            return True, '返回: %s' % txt[:200]
        return False, '返回异常页面: %s' % txt[:200]


def parse_args():
    p = argparse.ArgumentParser(description='银川科技学院公选课抢课脚本')
    p.add_argument('--start', default='', help='开始抢课时间，如 12:00:00 或 2026-10-30 12:00:00')
    p.add_argument('--duration', type=int, default=0, help='最长抢课分钟数，0=不限')
    p.add_argument('--debug', action='store_true', help='调试模式')
    return p.parse_args()


def wait_until(start_str):
    """等待到指定时间。"""
    now = datetime.datetime.now()
    target = None
    for fmt in ('%Y-%m-%d %H:%M:%S', '%H:%M:%S'):
        try:
            target = datetime.datetime.strptime(start_str, fmt)
            if fmt == '%H:%M:%S':
                target = target.replace(year=now.year, month=now.month, day=now.day)
                if target < now:
                    target += datetime.timedelta(days=1)
            break
        except ValueError:
            continue
    if target is None:
        log('无法解析开始时间：%s' % start_str)
        return
    secs = (target - now).total_seconds()
    if secs > 0:
        log('等待 %.0f 秒，将于 %s 开始抢课...' % (secs, target.strftime('%Y-%m-%d %H:%M:%S')))
        time.sleep(secs)


def main():
    args = parse_args()
    global USERNAME, PASSWORD

    if not USERNAME:
        USERNAME = input('请输入学号: ').strip()
    if not PASSWORD:
        import getpass
        PASSWORD = getpass.getpass('请输入密码（输入时不会显示）: ').strip()
    if not USERNAME or not PASSWORD:
        log('学号或密码不能为空')
        sys.exit(1)

    if args.start:
        wait_until(args.start)

    session = make_session()
    if not login(session):
        log('登录失败，程序退出。请检查账号密码后重试。')
        sys.exit(1)

    # 先看看选课中心有哪些轮次（供参考）
    rounds = get_select_rounds(session)
    if rounds:
        log('选课中心轮次：' + '；'.join('%s' % n for n, _, _ in rounds))

    done_credits = 0.0       # 已成功选到的学分
    attempted = set()        # 已尝试过的课程名
    fail_reasons = {}        # 课程名 -> 失败原因
    start_time = time.time()
    current_zbid = None      # 当前选课轮次ID

    log('开始抢课：目标 %.1f 学分，优先 %s' % (TARGET_CREDIT, '、'.join('%g' % c for c in PREFER_CREDITS)))
    log('如需中途停止，请按 Ctrl+C。')

    while done_credits < TARGET_CREDIT - 0.001:
        if args.duration and (time.time() - start_time) / 60 >= args.duration:
            log('已达最长抢课时间 %d 分钟，停止。已选学分 %.1f' % (args.duration, done_credits))
            break

        # 若无轮次上下文，先获取并进入选课轮次（选课开放后 xklc_list 才有数据）
        if not current_zbid:
            rounds = get_select_rounds(session)
            if not rounds:
                log('选课轮次尚未出现（12:00 开放前为空），%.0f 秒后重试...' % MAX_SLEEP)
                time.sleep(MAX_SLEEP)
                if not login(session):
                    log('重新登录失败，程序退出')
                    break
                continue
            # 优先选名称含"公选/公共选修/线上/选修"的轮次
            chosen = None
            for name, href, zbid in rounds:
                if any(k in name for k in ('公选', '公共选修', '线上', '选修')):
                    chosen = (name, href, zbid)
                    break
            if chosen is None:
                chosen = rounds[0]
            log('使用选课轮次：%s' % chosen[0])
            if enter_select_round(session, chosen[2], debug=args.debug):
                current_zbid = chosen[2]
            else:
                time.sleep(MIN_SLEEP)
                continue

        courses = fetch_courses(session, debug=args.debug)
        if not courses:
            log('本轮未获取到课程列表（可能尚未开放或会话失效），%.0f 秒后重试...' % MAX_SLEEP)
            time.sleep(MAX_SLEEP)
            # 会话可能失效，重新登录
            if not login(session):
                log('重新登录失败，程序退出')
                break
            continue

        # 按优先级排序：2 分课在前、1 分课在后，同分按剩余名额少（更抢手）排前
        def sort_key(c):
            try:
                prefer = PREFER_CREDITS.index(c['credit']) if c['credit'] in PREFER_CREDITS else 99
            except Exception:
                prefer = 99
            remain = c['remain']
            try:
                remain = int(remain)
            except Exception:
                remain = 9999
            return (prefer, remain if remain >= 0 else 0)
        courses.sort(key=sort_key)

        got_one = False
        for c in courses:
            if done_credits >= TARGET_CREDIT - 0.001:
                break
            need = TARGET_CREDIT - done_credits
            if c['credit'] > need + 0.001:
                continue  # 学分超出剩余需求，不选（例如只差1分时不选2分课）
            if c['name'] in attempted:
                continue
            # 剩余名额判断（remain 字段可能为 None）
            remain = c['remain']
            try:
                remain_i = int(remain)
            except Exception:
                remain_i = 9999
            if remain_i == 0:
                attempted.add(c['name'])
                fail_reasons[c['name']] = '已满'
                continue

            ok, msg = select_course(session, c, debug=args.debug)
            attempted.add(c['name'])
            if ok:
                done_credits += c['credit']
                log('抢课成功！%s（%.1f 学分，累计 %.1f/%s）' % (
                    c['name'], c['credit'], done_credits, TARGET_CREDIT))
                got_one = True
                # 登录可能被挤掉，重新建会话
                session = make_session()
                login(session)
                break
            else:
                fail_reasons[c['name']] = msg
                log('抢课失败：%s -> %s' % (c['name'], msg))

        if done_credits >= TARGET_CREDIT - 0.001:
            log('已修满 %.1f 学分，任务完成！' % TARGET_CREDIT)
            break

        if not got_one:
            log('本轮无成功课程，%.1f~%.1f 秒后继续...' % (MIN_SLEEP, MAX_SLEEP))
        time.sleep(MIN_SLEEP + (MAX_SLEEP - MIN_SLEEP) * random.random())

    log('程序结束。最终已选学分：%.1f' % done_credits)
    if fail_reasons:
        log('失败记录：' + '；'.join('%s：%s' % (k, v) for k, v in list(fail_reasons.items())[:20]))


if __name__ == '__main__':
    main()