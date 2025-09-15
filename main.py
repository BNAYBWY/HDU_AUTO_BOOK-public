import requests
import yaml
from datetime import datetime, timedelta
import json
import os
import logging
import time

# 引入时区处理库
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

# --- 基本配置 ---
logging.basicConfig(
    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
    level=logging.INFO)

# --- 定义抢座目标时间 (东八区时间) ---
TARGET_HOUR = 22
TARGET_MINUTE = 30

class SeatAutoBooker:
    # ... class内部直到 book_seat 方法前都无任何变化 ...
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
        
        # ★★★ 核心修正 ★★★
        # 使用北京时间来计算预约时间，确保 start_hour 对应的是北京时间
        
        # 1. 获取北京时间
        tz_cst = ZoneInfo("Asia/Shanghai")
        cst_now = datetime.now(tz_cst)
        
        # 2. 计算明天北京时间的预约时间点
        book_date_cst = cst_now + timedelta(days=1)
        book_time_cst = book_date_cst.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        
        # 3. 转换为UTC时间戳（API通常期望UTC时间戳）
        book_time_utc = book_time_cst.astimezone(ZoneInfo("UTC"))
        
        # 4. 计算Unix时间戳
        api_epoch_utc = datetime(1970, 1, 1, tzinfo=ZoneInfo("UTC"))
        delta = book_time_utc - api_epoch_utc
        total_seconds = int(delta.total_seconds())
        
        logging.info(f"预约时间: 北京时间 {book_time_cst.strftime('%Y-%m-%d %H:%M:%S')} -> UTC时间戳 {total_seconds}")
        
        data = f"beginTime={total_seconds}&duration={3600 * duration_hours}&seats[0]={seat_to_book}&seatBookers[0]={self.user_data['uid']}"
        headers = self.cfg["headers"]
        headers['Cookie'] = self.cookie
        logging.info(data)
        for i in range(3):
            try:
                logging.info(f"第 {i+1}/{3} 次尝试抢座: {start_hour}:00...")
                resp = requests.post(self.cfg["target"], data=data, headers=headers)
                # resp_json = {}
                resp_json = resp.json()
                logging.info(f"收到响应: {resp_json}")
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
    # (主程序中的时区等待逻辑保持不变，确保准时触发)
    logging.info('====== 开始执行抢座脚本 ======')
    
    with open("user_config.yml", 'r', encoding='utf-8') as f_obj:
        user_config = yaml.safe_load(f_obj)
    with open("config/basic_config.yml", 'r', encoding='utf-8') as f_obj:
        basic_config = yaml.safe_load(f_obj)

    if not user_config.get('enabled', False):
        logging.info('抢座功能未在 user_config.yml 中启用，脚本退出。')
        exit(0)

    s = SeatAutoBooker(basic_config["SeatAutoBooker"])
    login_success = False
    for attempt in range(3):  # 最多尝试3次
        logging.info(f"第 {attempt + 1}/3 次尝试登录...")
        if s.login() == 0:
            login_success = True
            break
        else:
            if attempt < 2:  # 如果不是最后一次尝试
                logging.warning(f"登录失败，{5}秒后重试...")
                time.sleep(5)
            
    if not login_success:
        s.wechatNotice("HDU抢座失败", "登录失败，已尝试3次，请检查账号密码或网站更新。")
        s.driver.quit()
        exit(-1)
    
    # 获取用户信息重试逻辑
    user_info_success = False
    for attempt in range(3):  # 最多尝试3次
        logging.info(f"第 {attempt + 1}/3 次尝试获取用户信息...")
        if s.get_user_info() == 0:
            user_info_success = True
            break
        else:
            if attempt < 2:  # 如果不是最后一次尝试
                logging.warning(f"获取用户信息失败，{3}秒后重试...")
                time.sleep(3)
                # 如果获取用户信息失败，可能需要重新登录
                if attempt == 1:  # 第二次失败时尝试重新登录
                    logging.info("尝试重新登录...")
                    if s.login() != 0:
                        logging.error("重新登录也失败了")
                        
    if not user_info_success:
        s.wechatNotice("HDU抢座失败", "获取用户信息失败，已尝试3次，Cookie可能已过期。")
        s.driver.quit()
        exit(-1)


    # 此处的时区逻辑仅用于精确等待，是正确的
    tz_cst = ZoneInfo("Asia/Shanghai")
    logging.info(f"登录成功，准备等待到北京时间 {TARGET_HOUR:02d}:{TARGET_MINUTE:02d} 进行抢座...")
    
    now_cst = datetime.now(tz_cst)
    target_time = now_cst.replace(hour=TARGET_HOUR, minute=TARGET_MINUTE, second=0, microsecond=0)

    while True:
        current_time_cst = datetime.now(tz_cst)
        if current_time_cst >= target_time:
            logging.info(f"北京时间 {current_time_cst.strftime('%H:%M:%S')} 已到，开始执行抢座！")
            break
        
        remaining_seconds = (target_time - current_time_cst).total_seconds()
        
        if int(remaining_seconds) % 10 == 0 and int(remaining_seconds) > 0:
            logging.info(f"等待中... 距离目标时间还剩 {remaining_seconds:.0f} 秒")
            time.sleep(1)
        elif remaining_seconds < 10:
             time.sleep(0.05)
        else:
             time.sleep(1)
    
    results = []
    success1, msg1 = s.book_seat(start_hour=8, duration_hours=5, user_config=user_config)
    success2, msg2 = s.book_seat(start_hour=13, duration_hours=5, user_config=user_config)
    success3, msg3 = s.book_seat(start_hour=18, duration_hours=4, user_config=user_config)
    results.append(msg1)
    results.append(msg2)
    results.append(msg3)
    summary_title = "HDU抢座完成"
    summary_desp = f"早上场次: {msg1}\n\n下午场次: {msg2}"
    print("\n--- 抢座总结 ---")
    print(summary_desp)
    print("--------------------")
    s.wechatNotice(summary_title, summary_desp)

    s.driver.quit()
    logging.info('====== 脚本执行完毕 ======')
