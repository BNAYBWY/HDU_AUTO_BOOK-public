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
TARGET_HOUR = 20
TARGET_MINUTE = 00

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

    def wait_for_redirect(self, target_domain, timeout=30):
        """等待页面重定向到目标域名"""
        logging.info(f"等待重定向到包含 '{target_domain}' 的页面，超时时间: {timeout}秒")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            current_url = self.driver.current_url
            logging.info(f"当前URL: {current_url}")
            
            if target_domain in current_url:
                logging.info(f"✓ 成功重定向到目标页面: {current_url}")
                return True
            
            # 检查页面是否包含目标网站的元素
            try:
                page_source = self.driver.page_source
                if target_domain in page_source:
                    logging.info(f"在页面源码中发现目标域名，可能已加载")
                    return True
            except Exception as e:
                logging.warning(f"检查页面源码时出错: {e}")
            
            # 检查是否有错误页面
            if "error" in current_url.lower() or "404" in page_source:
                logging.error("检测到错误页面，停止等待重定向")
                return False
                
            time.sleep(1)
        
        logging.warning(f"在{timeout}秒内未重定向到目标页面，当前URL: {self.driver.current_url}")
        return False

    def check_page_state(self):
        """检查页面状态"""
        try:
            # 检查页面标题或特定元素来确定是否在正确页面
            page_title = self.driver.title
            logging.info(f"页面标题: {page_title}")
            
            # 检查URL
            current_url = self.driver.current_url
            logging.info(f"当前URL: {current_url}")
            
            # 检查是否有登录表单
            login_forms = self.driver.find_elements(By.TAG_NAME, "form")
            logging.info(f"找到 {len(login_forms)} 个表单")
            
            # 检查页面内容关键词
            page_text = self.driver.page_source.lower()
            keywords = ['login', 'signin', '用户名', '密码', '统一身份认证', '图书馆', '座位']
            found_keywords = [kw for kw in keywords if kw in page_text]
            logging.info(f"页面包含关键词: {found_keywords}")
            
            return current_url, page_title, found_keywords
            
        except Exception as e:
            logging.error(f"检查页面状态失败: {e}")
            return None, None, []

    def save_debug_info(self, filename_prefix):
        """保存调试信息"""
        try:
            # 保存截图
            screenshot_path = f"{filename_prefix}_screenshot.png"
            self.driver.save_screenshot(screenshot_path)
            logging.info(f"截图已保存: {screenshot_path}")
            
            # 保存页面源代码
            source_path = f"{filename_prefix}_source.html"
            with open(source_path, "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            logging.info(f"页面源码已保存: {source_path}")
            
            # 保存当前URL
            logging.info(f"当前URL: {self.driver.current_url}")
            
        except Exception as e:
            logging.error(f"保存调试信息失败: {e}")

    def login(self):
        logging.info('开始登陆...')
        try:
            # 首先访问目标页面
            target_url = "https://hdu.huitu.zhishulib.com/#!/Space/Category/list"
            logging.info(f"访问目标URL: {target_url}")
            self.driver.get(target_url)
            
            # 立即检查页面状态
            current_url, page_title, keywords = self.check_page_state()
            logging.info(f"初始页面状态 - URL: {current_url}, 标题: {page_title}")
            
            # 保存初始页面信息
            self.save_debug_info("initial_page")
            
            # 等待页面加载
            time.sleep(5)
            
            # 再次检查页面状态
            current_url, page_title, keywords = self.check_page_state()
            logging.info(f"等待后页面状态 - URL: {current_url}, 标题: {page_title}")
            
            # 如果已经在目标网站，直接获取cookie
            if "hdu.huitu.zhishulib.com" in current_url:
                logging.info("已在目标网站，无需登录")
                cookie_list = self.driver.get_cookies()
                self.cookie = ";".join([f"{item['name']}={item['value']}" for item in cookie_list])
                self.cfg["headers"]['Cookie'] = self.cookie
                return 0
            
            return self.enhanced_login_flow()
                
        except Exception as e:
            logging.error(f"登录流程失败：{e}")
            self.save_debug_info("login_initial_error")
            return -1

    def enhanced_login_flow(self):
        """增强的登录流程，包含重定向等待"""
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                logging.info(f"尝试第 {attempt + 1}/{max_attempts} 种登录策略...")
                
                # 保存当前状态
                self.save_debug_info(f"login_attempt_{attempt+1}_before")
                
                # 策略1: 使用JavaScript直接操作元素
                if self.login_with_javascript():
                    # 等待重定向到目标网站
                    if self.wait_for_redirect("hdu.huitu.zhishulib.com", timeout=15):
                        self.save_debug_info(f"login_attempt_{attempt+1}_js_success")
                        return 0
                    else:
                        logging.warning("JavaScript登录成功但未重定向到目标网站")
                
                # 策略2: 使用传统方式但增加等待
                time.sleep(2)
                if self.login_with_enhanced_wait():
                    # 等待重定向到目标网站
                    if self.wait_for_redirect("hdu.huitu.zhishulib.com", timeout=15):
                        self.save_debug_info(f"login_attempt_{attempt+1}_enhanced_success")
                        return 0
                    else:
                        logging.warning("增强等待登录成功但未重定向到目标网站")
                
                # 策略3: 手动跳转到目标网站（最后一次尝试）
                if attempt == max_attempts - 1:
                    logging.info("尝试手动跳转到目标网站...")
                    self.driver.get("https://hdu.huitu.zhishulib.com/")
                    time.sleep(5)
                    
                    # 检查是否成功到达目标网站
                    current_url = self.driver.current_url
                    if "hdu.huitu.zhishulib.com" in current_url:
                        logging.info("手动跳转成功")
                        cookie_list = self.driver.get_cookies()
                        self.cookie = ";".join([f"{item['name']}={item['value']}" for item in cookie_list])
                        self.cfg["headers"]['Cookie'] = self.cookie
                        return 0
                    else:
                        logging.warning("手动跳转后仍未到达目标网站")
                        
            except Exception as e:
                logging.error(f"第 {attempt + 1} 种策略失败: {e}")
                self.save_debug_info(f"login_attempt_{attempt+1}_error")
                if attempt < max_attempts - 1:
                    logging.info(f"{3}秒后重试...")
                    time.sleep(3)
        
        logging.error("所有登录策略都失败了")
        self.save_debug_info("login_all_strategies_failed")
        return -1

    def login_with_javascript(self):
        """使用JavaScript直接操作元素的登录方式"""
        try:
            logging.info("尝试使用JavaScript登录...")
            
            # 首先检查页面状态
            current_url, page_title, keywords = self.check_page_state()
            
            # 使用JavaScript查找并操作元素
            username_script = """
            var inputs = document.querySelectorAll('input[type="text"], input[name="username"], input[id="username"], input[placeholder*="用户"], input[placeholder*="学工"], input[placeholder*="账号"]');
            for (var i = 0; i < inputs.length; i++) {
                if (inputs[i].offsetParent !== null) {
                    return inputs[i];
                }
            }
            return null;
            """
            
            password_script = """
            var inputs = document.querySelectorAll('input[type="password"], input[name="password"], input[id="password"], input[placeholder*="密码"]');
            for (var i = 0; i < inputs.length; i++) {
                if (inputs[i].offsetParent !== null) {
                    return inputs[i];
                }
            }
            return null;
            """
            
            submit_script = """
            var buttons = document.querySelectorAll('button[type="submit"], input[type="submit"], .btn-submit, .login-btn, button[onclick*="login"], input[value*="登录"]');
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
            
            return True
                
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
                (By.XPATH, "//input[contains(@placeholder, '账号')]"),
                (By.CSS_SELECTOR, "input[type='text']")
            ]
            
            password_selectors = [
                (By.ID, "password"),
                (By.NAME, "password"), 
                (By.XPATH, "//input[@type='password']"),
                (By.XPATH, "//input[contains(@placeholder, '密码')]"),
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
            
            return True
            
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
                logging.info(f"未找到元素，{1}秒后重试...")
                time.sleep(1)
        logging.warning(f"所有选择器都未找到元素: {selectors}")
        return None

    def check_login_success(self):
        """检查登录是否成功"""
        current_url = self.driver.current_url
        logging.info(f"当前URL: {current_url}")
        
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
        book_date_cst = cst_now + timedelta(days=2)
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
    success1, msg1 = s.book_seat(start_hour=8, duration_hours=13, user_config=user_config)
    
    logging.info('====== 脚本执行完毕 ======')
