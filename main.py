import requests
import yaml
from datetime import datetime, timedelta
import json
import os
import logging
import time

# ★★★ 新增：引入时区处理库 ★★★
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

# --- Basic Configuration ---
logging.basicConfig(
    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
    level=logging.INFO)

# --- 定义抢座目标时间 (东八区时间) ---
TARGET_HOUR = 14  # 目标小时 (24小时制)
TARGET_MINUTE = 56 # 目标分钟

class SeatAutoBooker:
    # ... 此 class 内的所有代码保持不变，无需修改 ...
    def __init__(self, booker_config):
        self.user_data = None
        logging.info('Creating SeatAutoBooker object')

        self.un = os.environ["SCHOOL_ID"].strip()
        self.pd = os.environ["PASSWORD"].strip()
        self.SCKey = os.environ.get("SCKEY", "")
        print(f"使用用户：{self.un}")

        if not self.SCKey:
            print("没有Server酱的key,将不会推送消息")

        chrome_options = Options()
        chrome_options.add_argument('--headless')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--disable-dev-shm-usage')
        self.driver = webdriver.Chrome(service=Service('/usr/local/bin/chromedriver'), options=chrome_options)
        self.wait = WebDriverWait(self.driver, 15, 1)
        self.cookie = None
        self.cfg = booker_config

    def login(self):
        logging.info('开始登陆...')
        pwd_path_selector = """//*[@id="react-root"]/div/div/div[1]/div[2]/div/div[1]/div[2]/div/div/div/div/div[1]/div[2]/div/div[3]/div/div[2]/input"""
        button_path_selector = """//*[@id="react-root"]/div/div/div[1]/div[2]/div/div[1]/div[2]/div/div/div/div/div[1]/div[3]"""

        try:
            self.driver.get("https://zisu.huitu.zhishulib.com/")
            logging.info('成功打开网站.')
            self.wait.until(EC.presence_of_element_located((By.NAME, "login_name")))
            self.wait.until(EC.presence_of_element_located((By.XPATH, pwd_path_selector)))
            self.wait.until(EC.element_to_be_clickable((By.XPATH, button_path_selector)))
            self.driver.find_element(By.NAME, 'login_name').send_keys(self.un)
            logging.info('输入用户名')
            self.driver.find_element(By.XPATH, pwd_path_selector).send_keys(self.pd)
            logging.info('输入密码')
            self.driver.find_element(By.XPATH, button_path_selector).click()
            logging.info('点击登录按钮')
            time.sleep(5)
            cookie_list = self.driver.get_cookies()
            self.cookie = ";".join([f"{item['name']}={item['value']}" for item in cookie_list])
            self.cfg["headers"]['Cookie'] = self.cookie
            logging.info("登录成功！")
            return 0
        except Exception as e:
            logging.error(f"登录失败：{e}")
            return -1

    def get_user_info(self):
        logging.info('获取用户信息...')
        headers = self.cfg["headers"]
        headers['Cookie'] = self.cookie
        try:
            resp = requests.get("https://zisu.huitu.zhishulib.com/Seat/Index/searchSeats?LAB_JSON=1", headers=headers)
            self.user_data = resp.json()['DATA']
            if 'uid' not in self.user_data:
                 raise KeyError("Response JSON does not contain 'uid'")
            logging.info("获取用户数据成功")
            return 0
        except Exception as e:
            logging.error(f"获取用户数据失败: {e}")
            logging.error(f"收到的响应: {resp.text if 'resp' in locals() else 'No response'}")
            return -1

    def book_seat(self, start_hour, duration_hours, user_config):
        logging.info(f'开始抢座: {start_hour}:00, 持续 {duration_hours} 小时')
        seat_to_book = user_config['自定义'][0]
        # 使用带时区的now()以确保日期正确
        book_date = datetime.now(ZoneInfo("Asia/Shanghai")) + timedelta(days=1)
        book_time_obj = book_date.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        delta = book_time_obj - self.cfg["start-time"]
        total_seconds = delta.days * 24 * 3600 + delta.seconds
        data = f"beginTime={total_seconds}&duration={3600 * duration_hours}&seats[0]={seat_to_book}&seatBookers[0]={self.user_data['uid']}"
        headers = self.cfg["headers"]
        headers['Cookie'] = self.cookie

        for i in range(self.cfg["max-retry"]):
            try:
                print(f"第 {i+1}/{self.cfg['max-retry']} 次尝试抢座: {start_hour}:00...")
                resp = requests.post(self.cfg["target"], data=data, headers=headers)
                resp_json = resp.json()
                print(f"收到响应: {resp_json}")
                if resp_json.get("CODE") == "ok":
                    message = f"成功抢到座位: {seat_to_book} at {start_hour}:00"
                    logging.info(message)
                    return True, message
                else:
                    time.sleep(0.5)
            except Exception as e:
                logging.error(f"请求时发生错误: {e}")
                time.sleep(1)

        final_message = f"抢座失败: {start_hour}:00 - {resp_json.get('MESSAGE', '未知错误')}"
        logging.warning(final_message)
        return False, final_message

    def wechatNotice(self, title, desp):
        logging.info('发送 Server酱 通知')
        if self.SCKey:
            url = f'https://sctapi.ftqq.com/{self.SCKey}.send'
            data = {'title': title, 'desp': desp}
            try:
                r = requests.post(url, data=data)
                result = r.json()
                if result.get("data", {}).get("error") == 'SUCCESS':
                    print("Server酱通知成功")
                else:
                    print(f"Server酱通知失败: {result}")
            except Exception as e:
                logging.error(f"推送服务配置错误: {e}")


if __name__ == "__main__":
    logging.info('====== 开始执行抢座脚本 ======')
    
    with open("user_config.yml", 'r', encoding='utf-8') as f_obj:
        user_config = yaml.safe_load(f_obj)
    with open("config/basic_config.yml", 'r', encoding='utf-8') as f_obj:
        basic_config = yaml.safe_load(f_obj)

    if not user_config.get('enabled', False):
        logging.info('抢座功能未在 user_config.yml 中启用，脚本退出。')
        exit(0)

    # --- 步骤一：提前登录并准备好信息 ---
    s = SeatAutoBooker(basic_config["SeatAutoBooker"])
    if s.login() != 0:
        s.wechatNotice("HDU抢座失败", "登录失败，请检查账号密码或网站更新。")
        s.driver.quit()
        exit(-1)
        
    if s.get_user_info() != 0:
        s.wechatNotice("HDU抢座失败", "获取用户信息失败，Cookie可能已过期。")
        s.driver.quit()
        exit(-1)

    # --- ★★★ 步骤二：进入基于东八区时间的精确等待循环 ★★★ ---
    tz_cst = ZoneInfo("Asia/Shanghai") # 定义东八区时区
    logging.info(f"登录成功，准备等待到北京时间 {TARGET_HOUR:02d}:{TARGET_MINUTE:02d} 进行抢座...")
    
    # 获取当前的东八区时间，并设置今天的目标时间点
    now_cst = datetime.now(tz_cst)
    target_time = now_cst.replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=0, microsecond=0)

    while True:
        # 实时获取东八区时间进行比较
        current_time_cst = datetime.now(tz_cst)
        if current_time_cst >= target_time:
            logging.info(f"北京时间 {current_time_cst.strftime('%H:%M:%S')} 已到，开始执行抢座！")
            break
        
        remaining_seconds = (target_time - current_time_cst).total_seconds()
        
        # 打印倒计时，避免日志刷屏
        if int(remaining_seconds) % 10 == 0 and int(remaining_seconds) > 0:
            logging.info(f"等待中... 距离目标时间还剩 {remaining_seconds:.0f} 秒")
            time.sleep(1) # 避免在同一秒内重复打印
        elif remaining_seconds < 10:
             time.sleep(0.05) # 最后10秒，高频检查
        else:
             time.sleep(1) # 平时每秒检查一次
    
    # --- 步骤三：执行抢座 ---
    # (此部分无变化)
    results = []
    success1, msg1 = s.book_seat(start_hour=8, duration_hours=6, user_config=user_config)
    results.append(msg1)
    time.sleep(1)
    success2, msg2 = s.book_seat(start_hour=14, duration_hours=6, user_config=user_config)
    results.append(msg2)

    # --- 步骤四：发送总结通知 ---
    # (此部分无变化)
    summary_title = "HDU抢座完成"
    summary_desp = f"早上场次: {msg1}\n\n下午场次: {msg2}"
    print("\n--- 抢座总结 ---")
    print(summary_desp)
    print("--------------------")
    s.wechatNotice(summary_title, summary_desp)

    s.driver.quit()
    logging.info('====== 脚本执行完毕 ======')
