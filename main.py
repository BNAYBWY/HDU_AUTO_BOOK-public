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
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementNotInteractableException

# --- 基本配置 ---
logging.basicConfig(
    format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
    datefmt='%H:%M:%S',
    level=logging.INFO)

# --- 定义抢座目标时间 (东八区时间) ---
TARGET_HOUR = 15
TARGET_MINUTE = 45

class SeatAutoBooker:
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
        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--window-size=1920,1080')
        # 添加更多选项以提高稳定性
        chrome_options.add_argument('--disable-blink-features=AutomationControlled')
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option('useAutomationExtension', False)
        
        self.driver = webdriver.Chrome(service=Service('/usr/local/bin/chromedriver'), options=chrome_options)
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        self.wait = WebDriverWait(self.driver, 20, 0.5)  # 增加等待时间
        self.cookie = None
        self.cfg = booker_config

    def login(self):
        logging.info('开始登陆...')
        try:
            self.driver.get("https://hdu.huitu.zhishulib.com/#!/Space/Category/list")
            logging.info('成功打开HDU统一认证登录页面.')
            
            # 等待页面完全加载
            time.sleep(3)
            
            # 使用更灵活的元素定位策略
            return self.enhanced_login_flow()
                
        except Exception as e:
            logging.error(f"登录流程失败：{e}")
            # 保存截图以便调试
            self.driver.save_screenshot("login_initial_error.png")
            return -1

    def enhanced_login_flow(self):
        """增强的登录流程，包含多种尝试策略"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                logging.info(f"尝试第 {attempt + 1}/{max_attempts} 种登录策略...")
                
                # 策略1: 使用JavaScript直接操作元素
                if self.login_with_javascript():
                    return 0
                    
                # 策略2: 使用传统方式但增加等待
                time.sleep(2)
                if self.login_with_enhanced_wait():
                    return 0
                    
                # 策略3: 刷新页面重试
                if attempt < max_attempts - 1:
                    logging.info("刷新页面重试...")
                    self.driver.refresh()
                    time.sleep(3)
                    
            except Exception as e:
                logging.error(f"第 {attempt + 1} 种策略失败: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(2)
        
        logging.error("所有登录策略都失败了")
        self.driver.save_screenshot("login_all_strategies_failed.png")
        return -1

    def login_with_javascript(self):
        """使用JavaScript直接操作元素的登录方式"""
        try:
            logging.info("尝试使用JavaScript登录...")
            
            # 使用JavaScript查找并操作元素
            username_script = """
            var inputs = document.querySelectorAll('input[type="text"], input[name="username"], input[id="username"]');
            for (var i = 0; i < inputs.length; i++) {
                if (inputs[i].offsetParent !== null) {
                    return inputs[i];
                }
            }
            return null;
            """
            
            password_script = """
            var inputs = document.querySelectorAll('input[type="password"], input[name="password"], input[id="password"]');
            for (var i = 0; i < inputs.length; i++) {
                if (inputs[i].offsetParent !== null) {
                    return inputs[i];
                }
            }
            return null;
            """
            
            submit_script = """
            var buttons = document.querySelectorAll('button[type="submit"], input[type="submit"], .btn-submit, .login-btn');
            for (var i = 0; i < buttons.length; i++) {
                if (buttons[i].offsetParent !== null && buttons[i].disabled === false) {
                    return buttons[i];
                }
            }
            return null;
            """
            
            # 查找用户名输入框
            username_element = self.driver.execute_script(username_script)
            if not username_element:
                logging.warning("JavaScript未找到用户名输入框")
                return False
                
            # 使用JavaScript设置用户名
            self.driver.execute_script("arguments[0].value = arguments[1];", username_element, self.un)
            logging.info('JavaScript设置用户名成功')
            
            # 查找密码输入框
            password_element = self.driver.execute_script(password_script)
            if not password_element:
                logging.warning("JavaScript未找到密码输入框")
                return False
                
            # 使用JavaScript设置密码
            self.driver.execute_script("arguments[0].value = arguments[1];", password_element, self.pd)
            logging.info('JavaScript设置密码成功')
            
            # 查找提交按钮
            submit_element = self.driver.execute_script(submit_script)
            if not submit_element:
                logging.warning("JavaScript未找到提交按钮")
                return False
                
            # 使用JavaScript点击提交按钮
            self.driver.execute_script("arguments[0].click();", submit_element)
            logging.info('JavaScript点击登录按钮成功')
            
            # 等待登录完成
            time.sleep(5)
            
            # 检查是否登录成功
            if self.check_login_success():
                return True
            else:
                logging.warning("JavaScript登录后未成功跳转")
                return False
                
        except Exception as e:
            logging.error(f"JavaScript登录失败: {e}")
            return False

    def login_with_enhanced_wait(self):
        """使用增强等待的传统登录方式"""
        try:
            logging.info("尝试使用增强等待登录...")
            
            # 定义多种可能的选择器
            username_selectors = [
                (By.ID, "username"),
                (By.NAME, "username"),
                (By.XPATH, "//input[@type='text']"),
                (By.XPATH, "//input[contains(@placeholder, '用户')]"),
                (By.XPATH, "//input[contains(@placeholder, '学工')]"),
                (By.CSS_SELECTOR, "input[type='text']")
            ]
            
            password_selectors = [
                (By.ID, "password"),
                (By.NAME, "password"), 
                (By.XPATH, "//input[@type='password']"),
                (By.CSS_SELECTOR, "input[type='password']")
            ]
            
            submit_selectors = [
                (By.CLASS_NAME, "btn-submit"),
                (By.XPATH, "//button[@type='submit']"),
                (By.XPATH, "//input[@type='submit']"),
                (By.XPATH, "//button[contains(text(), '登录')]"),
                (By.XPATH, "//input[contains(@value, '登录')]"),
                (By.CSS_SELECTOR, "button[type='submit']")
            ]
            
            # 查找并操作用户名输入框
            username_element = self.find_element_with_retry(username_selectors)
            if not username_element:
                raise Exception("未找到用户名输入框")
                
            # 清空并缓慢输入用户名
            username_element.clear()
            for char in self.un:
                username_element.send_keys(char)
                time.sleep(0.05)
            logging.info('输入用户名成功')
            
            # 查找并操作密码输入框
            password_element = self.find_element_with_retry(password_selectors)
            if not password_element:
                raise Exception("未找到密码输入框")
                
            # 清空并缓慢输入密码
            password_element.clear()
            for char in self.pd:
                password_element.send_keys(char)
                time.sleep(0.05)
            logging.info('输入密码成功')
            
            # 等待一下让界面响应
            time.sleep(1)
            
            # 查找并点击提交按钮
            submit_element = self.find_element_with_retry(submit_selectors)
            if not submit_element:
                raise Exception("未找到提交按钮")
                
            # 使用JavaScript点击避免状态问题
            self.driver.execute_script("arguments[0].click();", submit_element)
            logging.info('点击登录按钮成功')
            
            # 等待登录完成
            time.sleep(5)
            
            # 检查是否登录成功
            return self.check_login_success()
            
        except Exception as e:
            logging.error(f"增强等待登录失败: {e}")
            return False

    def find_element_with_retry(self, selectors, max_attempts=3):
        """使用多种选择器重试查找元素"""
        for attempt in range(max_attempts):
            for selector in selectors:
                try:
                    element = self.driver.find_element(*selector)
                    if element.is_displayed() and element.is_enabled():
                        logging.info(f"找到元素: {selector}")
                        return element
                except (NoSuchElementException, ElementNotInteractableException):
                    continue
            if attempt < max_attempts - 1:
                time.sleep(1)
        return None

    def check_login_success(self):
        """检查登录是否成功"""
        current_url = self.driver.current_url
        logging.info(f"当前URL: {current_url}")
        self.driver.get("https://hdu.huitu.zhishulib.com/#!/Space/Category/list")
        if "hdu.huitu.zhishulib.com" in current_url:
            logging.info("成功跳转到目标网站")
            
            # 获取Cookie
            cookie_list = self.driver.get_cookies()
            self.cookie = ";".join([f"{item['name']}={item['value']}" for item in cookie_list])
            self.cfg["headers"]['Cookie'] = self.cookie
            logging.info("登录成功！")
            logging.info(f"获取到的Cookie长度: {len(self.cookie)}")
            return True
        else:
            logging.warning(f"尚未跳转到目标网站，当前URL: {current_url}")
            return False

    def get_user_info(self):
        logging.info('获取用户信息...')
        headers = self.cfg["headers"]
        headers['Cookie'] = self.cookie
        try:
            resp = requests.get("https://hdu.huitu.zhishulib.com/Seat/Index/searchSeats?LAB_JSON=1", headers=headers)
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
        
        # 使用北京时间来计算预约时间
        tz_cst = ZoneInfo("Asia/Shanghai")
        cst_now = datetime.now(tz_cst)
        
        # 计算明天北京时间的预约时间点
        book_date_cst = cst_now + timedelta(days=1)
        book_time_cst = book_date_cst.replace(hour=start_hour, minute=0, second=0, microsecond=0)
        
        # 转换为UTC时间戳
        book_time_utc = book_time_cst.astimezone(ZoneInfo("UTC"))
        
        # 计算Unix时间戳
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
                        
    if not user_info_success:
        s.wechatNotice("HDU抢座失败", "获取用户信息失败，已尝试3次，Cookie可能已过期。")
        s.driver.quit()
        exit(-1)

    # 等待到目标时间
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
    success1, msg1 = s.book_seat(start_hour=9, duration_hours=13, user_config=user_config)
    
    logging.info('====== 脚本执行完毕 ======')
