import requests
import yaml
from datetime import datetime, timedelta
import json
import os
import logging
import time

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

# --- ★★★ 新增：定义抢座目标时间 ★★★ ---
TARGET_HOUR = 14  # 目标小时 (24小时制)
TARGET_MINUTE = 50 # 目标分钟

class SeatAutoBooker:
    def __init__(self, booker_config):
        self.user_data = None
        logging.info('Creating SeatAutoBooker object')

        # --- User Credentials from GitHub Secrets ---
        self.un = os.environ["SCHOOL_ID"].strip()
        self.pd = os.environ["PASSWORD"].strip()
        self.SCKey = os.environ.get("SCKEY", "")
        print(f"使用用户：{self.un}")

        if not self.SCKey:
            print("没有Server酱的key,将不会推送消息")

        # --- Selenium WebDriver Setup ---
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
        book_date = datetime.now() + timedelta(days=1)
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

    # --- ★★★ 步骤二：进入精确时间等待循环 ★★★ ---
    logging.info(f"登录成功，准备等待到 {TARGET_HOUR:02d}:{TARGET_MINUTE:02d} 进行抢座...")
    target_time = datetime.now().replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=0, microsecond=0)
    
    while True:
        current_time = datetime.now()
        if current_time >= target_time:
            logging.info("目标时间已到，开始执行抢座！")
            break
        
        remaining_seconds = (target_time - current_time).total_seconds()
        # 打印倒计时，避免日志刷屏
        if int(remaining_seconds) % 10 == 0:
            logging.info(f"等待中... 距离目标时间还剩 {remaining_seconds:.2f} 秒")
        
        # 循环最后10秒时，提高检查频率
        if remaining_seconds < 10:
             time.sleep(0.05) # 50毫秒检查一次
        else:
             time.sleep(1) # 1秒检查一次
    
    # --- 步骤三：执行抢座 ---
    results = []
    # Slot 1: 8:00 AM for 6 hours
    success1, msg1 = s.book_seat(start_hour=8, duration_hours=6, user_config=user_config)
    results.append(msg1)
    
    time.sleep(1) # 抢完第一个后稍微停顿一下

    # Slot 2: 2:00 PM (14:00) for 6 hours
    success2, msg2 = s.book_seat(start_hour=14, duration_hours=6, user_config=user_config)
    results.append(msg2)

    # --- 步骤四：发送总结通知 ---
    summary_title = "HDU抢座完成"
    summary_desp = f"早上场次: {msg1}\n\n下午场次: {msg2}"
    print("\n--- 抢座总结 ---")
    print(summary_desp)
    print("--------------------")
    s.wechatNotice(summary_title, summary_desp)

    s.driver.quit()
    logging.info('====== 脚本执行完毕 ======')
